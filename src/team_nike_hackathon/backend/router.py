"""MatchCare API routes.

All routes mount under the ``/api`` prefix configured in ``_metadata.py``.

Sections:

* App-level: version + current user
* Search: deterministic Lakebase shortlist + LLM agentic re-rank
* Catalog: specialty facet values for the filter UI
* Submissions: provider self-attest + fieldwork surveyor intake
* Persistence: shortlists / notes / overrides / decisions \u2014 mounted
  from ``routes/persistence.py`` (Delta-backed, closes the spec
  "save or revise" gap without depending on Lakebase).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from databricks.sdk.service.iam import User as UserOut
from fastapi import HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlmodel import col, select

from .agents.evidence_agent import score_evidence_with_llm
from .agents.graph import run_referral_pipeline
from .agents.llm_client import set_workspace, reset_workspace, set_endpoint, reset_endpoint
from .agents.query_parser import parse_query
from .core import Dependencies, create_router, logger
from .core._config import AppConfig
from .db import DeltaQueryError, delta_query
from .geocode import geocode
from .models import (
    AgentTraceStep,
    Evidence,
    Facility,
    FacilityOut,
    FacilitySubmission,
    ParsedQueryOut,
    SearchIn,
    SearchOrigin,
    SearchResultItem,
    SearchResults,
    SubmissionIn,
    SubmissionOut,
    SubmissionStatus,
    VersionOut,
)
from .routes.persistence import router as persistence_router

router = create_router()
router.include_router(persistence_router)

# ---------------------------------------------------------------------------
# App-level
# ---------------------------------------------------------------------------


@router.get("/version", response_model=VersionOut, operation_id="version")
async def version() -> VersionOut:
    return VersionOut.from_metadata()


@router.get("/current-user", response_model=UserOut, operation_id="currentUser")
def me(user_ws: Dependencies.UserClient):
    return user_ws.current_user.me()


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@router.get(
    "/facilities/specialties",
    response_model=list[str],
    operation_id="listSpecialties",
)
def list_specialties(
    session: Dependencies.Session,
    ws: Dependencies.Client,
    config: Dependencies.Config,
) -> list[str]:
    """Return the distinct specialty values across all facilities.

    Tries Unity Catalog Delta first (where production data lives),
    falling back to Lakebase. Returns an empty list (not a 500) when
    nothing is configured so the UI can boot before the partner's
    ingest job has run.
    """
    warehouse_id = (config.delta_warehouse_id or "").strip()
    table = (config.delta_facilities_table or "").strip()
    if warehouse_id and table:
        try:
            rows = delta_query(
                ws,
                warehouse_id=warehouse_id,
                statement=(
                    f"SELECT DISTINCT lower(item) AS s "
                    f"FROM {table} "
                    f"LATERAL VIEW explode(from_json(specialties, 'array<string>')) AS item "
                    f"WHERE specialties IS NOT NULL AND specialties != '[]' "
                    f"ORDER BY s"
                ),
                wait_timeout="30s",
            )
            return [r["s"] for r in rows if r.get("s")]
        except DeltaQueryError as exc:
            logger.warning("list_specialties delta lookup failed: %s", exc)

    if session is None:
        return []
    try:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT lower(elem) AS s
                FROM facilities,
                     LATERAL jsonb_array_elements_text(
                         COALESCE(specialties, '[]'::jsonb)
                     ) AS elem
                ORDER BY s
                """
            )
        ).all()
    except ProgrammingError as exc:
        logger.warning("list_specialties: %s", exc)
        return []
    return [r[0] for r in rows if r[0]]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


# Text-scoring strategy:
#
# Postgres trigram similarity (``pg_trgm``) gives us typo tolerance with no
# extra dependencies. ``similarity(a, b)`` returns 0..1; values above ~0.3
# usually indicate a meaningful match. We blend three signals so an exact
# substring still outranks a far-off fuzzy candidate:
#
#   1. Substring (ILIKE) on name / raw_description / structured lists.
#      Score: 0 or 1.0 per field, capped.
#   2. Best trigram similarity over the same fields.
#      Score: max(similarity) * weight per field.
#   3. The two sum to ``text_score`` so a name match (weight 3) outranks
#      a description match (weight 1).
#
# Names: substring weight 3.0, similarity weight 3.0.
# Descriptions: substring weight 1.0, similarity weight 1.0.
# Structured lists (specialties/services/procedures/equipment): weight 2.5
# for similarity, plus a small bonus for substring matches.
#
# Threshold of 0.25 keeps the fuzzy floor reasonable; below that the match
# is too noisy to be useful (e.g. "delhi" ≈ "deli" similarity ~0.2).
_FUZZY_FLOOR = 0.25
_SEARCH_SQL = text(
    """
    WITH params AS (
        SELECT
            CAST(:q AS text)                   AS q,
            lower(CAST(:q AS text))            AS ql,
            CAST(:lat AS float)                AS qlat,
            CAST(:lng AS float)                AS qlng,
            CAST(:radius_km AS float)          AS radius_km,
            CAST(:min_conf AS float)           AS min_conf,
            CAST(:specialties_filter AS jsonb) AS specialties_filter,
            CAST(:fuzzy_floor AS float)        AS fuzzy_floor,
            CAST(:limit AS int)                AS lim
    ),
    scored AS (
        SELECT
            f.*,
            CASE
                WHEN p.qlat IS NULL OR p.qlng IS NULL
                    OR f.latitude IS NULL OR f.longitude IS NULL
                THEN NULL
                ELSE 6371.0 * acos(LEAST(1.0, GREATEST(-1.0,
                    sin(radians(p.qlat)) * sin(radians(f.latitude)) +
                    cos(radians(p.qlat)) * cos(radians(f.latitude)) *
                    cos(radians(f.longitude - p.qlng))
                )))
            END AS distance_km,
            COALESCE((
                SELECT AVG((v)::float)
                FROM jsonb_each_text(COALESCE(f.confidence, '{}'::jsonb)) AS x(k, v)
                WHERE v ~ '^-?[0-9]+(\\.[0-9]+)?$'
            ), 0.5) AS confidence_avg,
            CASE
                WHEN p.q IS NULL OR p.q = '' THEN 0.0
                ELSE
                    -- Exact-substring contributions (untouched legacy weighting).
                    (CASE WHEN f.name ILIKE '%' || p.q || '%' THEN 3.0 ELSE 0.0 END) +
                    (CASE WHEN f.raw_description ILIKE '%' || p.q || '%' THEN 1.0 ELSE 0.0 END) +
                    LEAST(2.0, (
                        SELECT COUNT(*)::float * 0.5
                        FROM jsonb_array_elements_text(
                            COALESCE(f.specialties, '[]'::jsonb) ||
                            COALESCE(f.services, '[]'::jsonb) ||
                            COALESCE(f.procedures, '[]'::jsonb) ||
                            COALESCE(f.equipment, '[]'::jsonb)
                        ) AS e
                        WHERE e ILIKE '%' || p.q || '%'
                    )) +
                    -- Fuzzy (trigram) contributions. ``GREATEST(0, sim - floor)``
                    -- so noise below the floor adds nothing.
                    GREATEST(0.0,
                        similarity(lower(COALESCE(f.name, '')), p.ql) - p.fuzzy_floor
                    ) * 3.0 +
                    GREATEST(0.0,
                        similarity(lower(COALESCE(f.raw_description, '')), p.ql) - p.fuzzy_floor
                    ) * 1.0 +
                    GREATEST(0.0,
                        COALESCE((
                            SELECT MAX(similarity(lower(e), p.ql))
                            FROM jsonb_array_elements_text(
                                COALESCE(f.specialties, '[]'::jsonb) ||
                                COALESCE(f.services, '[]'::jsonb) ||
                                COALESCE(f.procedures, '[]'::jsonb) ||
                                COALESCE(f.equipment, '[]'::jsonb)
                            ) AS e
                        ), 0.0) - p.fuzzy_floor
                    ) * 2.5
            END AS text_score
        FROM facilities f
        CROSS JOIN params p
        WHERE
            (
                p.specialties_filter IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(
                        COALESCE(f.specialties, '[]'::jsonb)
                    ) AS e
                    -- Fuzzy specialty filter: an exact match OR ``e`` shares
                    -- a similarity > floor with one of the requested values.
                    WHERE EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements_text(p.specialties_filter) AS s
                        WHERE lower(e) = lower(s)
                           OR similarity(lower(e), lower(s)) > p.fuzzy_floor
                    )
                )
            )
    )
    SELECT
        s.id, s.external_id, s.name, s.type, s.address, s.city, s.state,
        s.pincode, s.country, s.latitude, s.longitude,
        s.specialties, s.services, s.equipment, s.procedures,
        s.raw_description, s.confidence, s.source,
        s.distance_km,
        s.confidence_avg,
        s.text_score,
        (
            s.text_score
            + COALESCE(GREATEST(0.0, 1.0 - s.distance_km / NULLIF(p.radius_km, 0)), 0.0) * 2.0
            + s.confidence_avg * 1.5
        ) AS match_score
    FROM scored s CROSS JOIN params p
    WHERE s.confidence_avg >= p.min_conf
      AND (p.radius_km IS NULL OR s.distance_km IS NULL OR s.distance_km <= p.radius_km)
      AND (p.q IS NULL OR p.q = '' OR s.text_score > 0)
    ORDER BY
        match_score DESC NULLS LAST,
        CASE WHEN s.distance_km IS NULL THEN 1 ELSE 0 END,
        s.distance_km ASC,
        s.confidence_avg DESC
    LIMIT (SELECT lim FROM params)
    """
)

# Same SQL but with all ``similarity()`` calls stripped — used as a fallback
# when ``pg_trgm`` is not available on the database. We compile this lazily
# the first time we need it so the trigram path stays the hot path.
_SEARCH_SQL_FALLBACK = text(
    """
    WITH params AS (
        SELECT
            CAST(:q AS text)                   AS q,
            CAST(:lat AS float)                AS qlat,
            CAST(:lng AS float)                AS qlng,
            CAST(:radius_km AS float)          AS radius_km,
            CAST(:min_conf AS float)           AS min_conf,
            CAST(:specialties_filter AS jsonb) AS specialties_filter,
            CAST(:limit AS int)                AS lim
    ),
    scored AS (
        SELECT
            f.*,
            CASE
                WHEN p.qlat IS NULL OR p.qlng IS NULL
                    OR f.latitude IS NULL OR f.longitude IS NULL
                THEN NULL
                ELSE 6371.0 * acos(LEAST(1.0, GREATEST(-1.0,
                    sin(radians(p.qlat)) * sin(radians(f.latitude)) +
                    cos(radians(p.qlat)) * cos(radians(f.latitude)) *
                    cos(radians(f.longitude - p.qlng))
                )))
            END AS distance_km,
            COALESCE((
                SELECT AVG((v)::float)
                FROM jsonb_each_text(COALESCE(f.confidence, '{}'::jsonb)) AS x(k, v)
                WHERE v ~ '^-?[0-9]+(\\.[0-9]+)?$'
            ), 0.5) AS confidence_avg,
            CASE
                WHEN p.q IS NULL OR p.q = '' THEN 0.0
                ELSE
                    (CASE WHEN f.name ILIKE '%' || p.q || '%' THEN 3.0 ELSE 0.0 END) +
                    (CASE WHEN f.raw_description ILIKE '%' || p.q || '%' THEN 1.0 ELSE 0.0 END) +
                    LEAST(2.0, (
                        SELECT COUNT(*)::float * 0.5
                        FROM jsonb_array_elements_text(
                            COALESCE(f.specialties, '[]'::jsonb) ||
                            COALESCE(f.services, '[]'::jsonb) ||
                            COALESCE(f.procedures, '[]'::jsonb) ||
                            COALESCE(f.equipment, '[]'::jsonb)
                        ) AS e
                        WHERE e ILIKE '%' || p.q || '%'
                    ))
            END AS text_score
        FROM facilities f
        CROSS JOIN params p
        WHERE
            (
                p.specialties_filter IS NULL
                OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(
                        COALESCE(f.specialties, '[]'::jsonb)
                    ) AS e
                    WHERE lower(e) = ANY(
                        SELECT lower(s)
                        FROM jsonb_array_elements_text(p.specialties_filter) AS s
                    )
                )
            )
    )
    SELECT
        s.id, s.external_id, s.name, s.type, s.address, s.city, s.state,
        s.pincode, s.country, s.latitude, s.longitude,
        s.specialties, s.services, s.equipment, s.procedures,
        s.raw_description, s.confidence, s.source,
        s.distance_km,
        s.confidence_avg,
        s.text_score,
        (
            s.text_score
            + COALESCE(GREATEST(0.0, 1.0 - s.distance_km / NULLIF(p.radius_km, 0)), 0.0) * 2.0
            + s.confidence_avg * 1.5
        ) AS match_score
    FROM scored s CROSS JOIN params p
    WHERE s.confidence_avg >= p.min_conf
      AND (p.radius_km IS NULL OR s.distance_km IS NULL OR s.distance_km <= p.radius_km)
    ORDER BY
        match_score DESC NULLS LAST,
        CASE WHEN s.distance_km IS NULL THEN 1 ELSE 0 END,
        s.distance_km ASC,
        s.confidence_avg DESC
    LIMIT (SELECT lim FROM params)
    """
)


def _resolve_origin(body: SearchIn) -> SearchOrigin:
    """Resolve the request's location to a (lat, lng, label) origin."""
    if body.location and body.location.lat is not None and body.location.lng is not None:
        return SearchOrigin(
            lat=body.location.lat,
            lng=body.location.lng,
            label=body.location.label,
        )
    text_in = body.location_text or (body.location.label if body.location else None)
    if text_in:
        place = geocode(text_in)
        if place is not None:
            return SearchOrigin(lat=place.lat, lng=place.lng, label=place.label)
        return SearchOrigin(label=text_in)
    return SearchOrigin()


def _best_fuzzy_token(query: str, haystack: str) -> tuple[str, float] | None:
    """Find the word in ``haystack`` most similar to ``query``.

    Returns the matched token plus a 0..1 similarity ratio, or ``None`` if no
    word clears the floor. Used to highlight the *actual* word that matched a
    misspelled query (e.g. user typed "dialisis" → we highlight "dialysis").
    """
    from difflib import SequenceMatcher

    if not query or not haystack:
        return None
    q = query.strip().lower()
    if not q:
        return None
    best: tuple[str, float] | None = None
    seen: set[str] = set()
    for word in haystack.split():
        token = word.strip(".,;:()/-").lower()
        if len(token) < 3 or token in seen:
            continue
        seen.add(token)
        ratio = SequenceMatcher(None, q, token).ratio()
        if best is None or ratio > best[1]:
            best = (word.strip(".,;:()-"), ratio)
    if best is None or best[1] < 0.6:
        return None
    return best


def _pick_evidence(row: dict[str, Any], query: str | None) -> Evidence | None:
    """Pick the single best evidence snippet to surface in the result row.

    Looks first for an exact substring match (highest signal), then falls
    back to fuzzy / trigram-style matching so a typo'd query like
    "dialisis" still surfaces the "dialysis" specialty as evidence. Without
    this fallback the SQL would correctly rank the row but the UI would
    show no highlighted snippet, making it look like a mistaken match.
    """
    if not query:
        return None
    q = query.strip().lower()
    if not q:
        return None

    confidence = row.get("confidence") or {}
    if isinstance(confidence, str):
        try:
            confidence = json.loads(confidence)
        except Exception:
            confidence = {}

    def conf_for(field: str) -> float:
        v = confidence.get(field) if isinstance(confidence, dict) else None
        if isinstance(v, (int, float)):
            return float(v)
        return float(row.get("confidence_avg") or 0.5)

    # ---- Pass 1: exact-substring match ----
    for field in ("specialties", "services", "procedures", "equipment"):
        items = row.get(field) or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        for item in items:
            if isinstance(item, str) and q in item.lower():
                return Evidence(field=field, snippet=item, confidence=conf_for(field))

    name = row.get("name") or ""
    if q in name.lower():
        return Evidence(field="name", snippet=name, confidence=conf_for("name"))

    raw = row.get("raw_description") or ""
    lower = raw.lower()
    idx = lower.find(q)
    if idx >= 0:
        start = max(0, idx - 60)
        end = min(len(raw), idx + len(q) + 80)
        snippet = ("…" if start > 0 else "") + raw[start:end] + ("…" if end < len(raw) else "")
        return Evidence(
            field="raw_description",
            snippet=snippet,
            confidence=conf_for("raw_description"),
        )

    # ---- Pass 2: fuzzy match (typo tolerance) ----
    best_field: str | None = None
    best_snippet: str | None = None
    best_ratio = 0.0
    for field in ("specialties", "services", "procedures", "equipment"):
        items = row.get(field) or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = []
        for item in items:
            if not isinstance(item, str):
                continue
            from difflib import SequenceMatcher
            r = SequenceMatcher(None, q, item.lower()).ratio()
            if r > best_ratio:
                best_ratio = r
                best_field = field
                best_snippet = item

    if name:
        from difflib import SequenceMatcher
        r = SequenceMatcher(None, q, name.lower()).ratio()
        if r > best_ratio:
            best_ratio = r
            best_field = "name"
            best_snippet = name

    if raw:
        token = _best_fuzzy_token(q, raw)
        if token is not None and token[1] > best_ratio:
            best_ratio = token[1]
            best_field = "raw_description"
            best_snippet = f"…matched on “{token[0]}”…"

    if best_field and best_snippet and best_ratio >= 0.6:
        # Slight confidence haircut so fuzzy matches read as less certain.
        base = conf_for(best_field)
        return Evidence(
            field=best_field,
            snippet=best_snippet,
            confidence=base * best_ratio,
        )

    return None


def _row_to_facility(row: dict[str, Any]) -> FacilityOut:
    """Coerce a SQL row dict into a FacilityOut, parsing JSONB strings."""
    def _as_list(v: Any) -> list[str] | None:
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else None
            except Exception:
                return None
        return None

    def _as_dict(v: Any) -> dict[str, float] | None:
        if v is None:
            return None
        if isinstance(v, dict):
            return {k: float(val) for k, val in v.items() if isinstance(val, (int, float))}
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return {k: float(val) for k, val in parsed.items() if isinstance(val, (int, float))}
            except Exception:
                return None
        return None

    return FacilityOut(
        id=row["id"],
        external_id=row.get("external_id"),
        name=row["name"],
        type=row.get("type"),
        address=row.get("address"),
        city=row.get("city"),
        state=row.get("state"),
        pincode=row.get("pincode"),
        country=row.get("country") or "IN",
        latitude=row.get("latitude"),
        longitude=row.get("longitude"),
        specialties=_as_list(row.get("specialties")),
        services=_as_list(row.get("services")),
        equipment=_as_list(row.get("equipment")),
        procedures=_as_list(row.get("procedures")),
        raw_description=row.get("raw_description"),
        confidence=_as_dict(row.get("confidence")),
        source=row.get("source"),
    )


# ---------------------------------------------------------------------------
# Delta-backed search (Unity Catalog ``facilities_gold``)
# ---------------------------------------------------------------------------
#
# The deterministic Postgres SQL above stays available for when the ETL
# eventually lands data in Lakebase, but production search currently
# reads from the partner's Delta table directly. We score with a simple
# lower+LIKE pass over the JSON-string columns — Spark SQL has no
# ``pg_trgm`` so fuzzy matching is best-effort and runs in Python on the
# result set (typo rescue handled by the ``_pick_evidence`` pass).
def _delta_search_sql(table: str, limit: int) -> str:
    # ``limit`` is interpolated into the SQL because Spark requires the
    # ``LIMIT`` clause to be a literal ``INT`` (and the SDK parameter
    # binding emits a ``BIGINT``). It's safe because callers always pass
    # a validated, capped int — never user-supplied text.
    return f"""
    WITH params AS (
        SELECT
            :q   AS q,
            lower(COALESCE(:q, '')) AS ql,
            CAST(:lat       AS DOUBLE) AS qlat,
            CAST(:lng       AS DOUBLE) AS qlng,
            CAST(:radius_km AS DOUBLE) AS radius_km
    ),
    scored AS (
        SELECT
            f.unique_id, f.name, f.facilityTypeId, f.organization_type,
            f.address_line1, f.address_city, f.address_stateOrRegion,
            f.pincode, f.state, f.district,
            f.latitude, f.longitude,
            f.specialties, f.capability, f.procedure, f.equipment,
            f.description, f.source, f.source_types, f.source_urls,
            f.distinct_source_count, f.base_trust_signal, f.trust_rank,
            f.mentions_pmjay, f.mentions_cghs, f.mentions_esi,
            f.mentions_nabh, f.mentions_jci,
            f.is_24x7, f.has_ambulance, f.has_telemedicine, f.has_blood_bank,
            f.mentions_icu, f.mentions_nicu, f.mentions_emergency,
            f.is_government_mentioned, f.is_private_mentioned,
            f.is_nonprofit_mentioned, f.offers_charity_care,
            CASE
                WHEN p.qlat IS NULL OR p.qlng IS NULL
                  OR f.latitude IS NULL OR f.longitude IS NULL
                THEN NULL
                ELSE 6371.0 * acos(LEAST(1.0, GREATEST(-1.0,
                    sin(radians(p.qlat)) * sin(radians(f.latitude)) +
                    cos(radians(p.qlat)) * cos(radians(f.latitude)) *
                    cos(radians(f.longitude - p.qlng))
                )))
            END AS distance_km,
            CASE
                WHEN p.q IS NULL OR p.q = '' THEN 0.0
                ELSE
                    (CASE WHEN lower(COALESCE(f.name, '')) LIKE concat('%', p.ql, '%') THEN 3.0 ELSE 0.0 END) +
                    (CASE WHEN lower(COALESCE(f.description, '')) LIKE concat('%', p.ql, '%') THEN 1.0 ELSE 0.0 END) +
                    (CASE WHEN lower(COALESCE(f.specialties, '')) LIKE concat('%', p.ql, '%') THEN 2.5 ELSE 0.0 END) +
                    (CASE WHEN lower(COALESCE(f.capability, '')) LIKE concat('%', p.ql, '%') THEN 1.5 ELSE 0.0 END) +
                    (CASE WHEN lower(COALESCE(f.procedure, '')) LIKE concat('%', p.ql, '%') THEN 1.5 ELSE 0.0 END) +
                    (CASE WHEN lower(COALESCE(f.equipment, '')) LIKE concat('%', p.ql, '%') THEN 1.0 ELSE 0.0 END)
            END AS text_score
        FROM {table} f
        CROSS JOIN params p
        WHERE f.latitude IS NOT NULL
          AND f.longitude IS NOT NULL
    )
    SELECT s.*
    FROM scored s
    CROSS JOIN params p
    WHERE (p.q IS NULL OR p.q = '' OR s.text_score > 0)
      AND (p.radius_km IS NULL OR s.distance_km IS NULL OR s.distance_km <= p.radius_km)
    ORDER BY
        (s.text_score
         + COALESCE(GREATEST(0.0, 1.0 - s.distance_km / NULLIF(p.radius_km, 0)), 0.0) * 2.0
         + COALESCE(s.trust_rank, 0) * 0.3
        ) DESC NULLS LAST,
        s.distance_km ASC NULLS LAST,
        s.trust_rank DESC NULLS LAST
    LIMIT {int(limit)}
    """


def _parse_json_list(value: Any) -> list[str]:
    """Decode a JSON-string list column. Returns ``[]`` on any failure."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        v = value.strip()
        if not v or v == "[]":
            return []
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item is not None]
        except Exception:
            return [v]
    return []


def _delta_row_to_facility(row: dict[str, Any]) -> FacilityOut:
    """Map a ``facilities_gold`` row into the wire ``FacilityOut`` shape.

    The synthesised ``confidence`` dict mirrors the components used in
    :func:`_delta_row_quality` so the UI can show per-signal breakdowns
    in the evidence drawer instead of two near-duplicate numbers.
    """
    import math

    confidence: dict[str, float] = {}
    trust_rank = row.get("trust_rank")
    if isinstance(trust_rank, (int, float)):
        confidence["trust_rank"] = max(0.0, min(1.0, float(trust_rank) / 5.0))
    src_count = row.get("distinct_source_count")
    if isinstance(src_count, (int, float)) and src_count > 0:
        confidence["source_count"] = min(
            1.0, math.log1p(float(src_count)) / math.log1p(5.0)
        )

    accred = 0.0
    if _truthy(row.get("mentions_nabh")):
        accred += 0.45
    if _truthy(row.get("mentions_jci")):
        accred += 0.45
    for key in ("mentions_pmjay", "mentions_cghs", "mentions_esi"):
        if _truthy(row.get(key)):
            accred += 0.10
    if accred > 0:
        confidence["accreditation"] = min(1.0, accred)

    populated = sum(
        1
        for field in _COMPLETENESS_FIELDS
        if _is_populated(row.get(field))
    )
    if populated:
        confidence["completeness"] = populated / float(len(_COMPLETENESS_FIELDS))

    text_score = row.get("text_score")
    if isinstance(text_score, (int, float)) and text_score > 0:
        confidence["match_breadth"] = min(1.0, float(text_score) / 6.0)

    return FacilityOut(
        id=str(row.get("unique_id") or ""),
        external_id=row.get("unique_id"),
        name=str(row.get("name") or "Unknown"),
        type=row.get("facilityTypeId") or row.get("organization_type"),
        address=row.get("address_line1"),
        city=row.get("address_city"),
        state=row.get("state") or row.get("address_stateOrRegion"),
        pincode=row.get("pincode"),
        country="IN",
        latitude=_safe_float(row.get("latitude")),
        longitude=_safe_float(row.get("longitude")),
        specialties=_parse_json_list(row.get("specialties")) or None,
        services=_parse_json_list(row.get("capability")) or None,
        equipment=_parse_json_list(row.get("equipment")) or None,
        procedures=_parse_json_list(row.get("procedure")) or None,
        raw_description=row.get("description"),
        confidence=confidence or None,
        source=row.get("source"),
    )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _run_delta_search(
    ws,
    config: AppConfig,
    body: SearchIn,
    origin: SearchOrigin,
) -> list[SearchResultItem] | None:
    """Run the SQL search against ``facilities_gold`` in Unity Catalog.

    Returns ``None`` (not ``[]``) when Delta search is not configured;
    callers can then fall through to the Lakebase path. Returns an empty
    list when Delta *was* tried but returned no rows.
    """
    warehouse_id = (config.delta_warehouse_id or "").strip()
    table = (config.delta_facilities_table or "").strip()
    if not warehouse_id or not table:
        return None

    q = (body.query or "").strip() or None
    limit = max(1, min(body.limit, 200))
    params: dict[str, Any] = {
        "q": q,
        "lat": origin.lat,
        "lng": origin.lng,
        "radius_km": body.radius_km if body.radius_km else None,
    }

    try:
        rows = delta_query(
            ws,
            warehouse_id=warehouse_id,
            statement=_delta_search_sql(table, limit),
            parameters=params,
            wait_timeout="30s",
        )
    except DeltaQueryError as exc:
        logger.warning("delta search failed (%s); falling back", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("delta search crashed: %s", exc)
        return None

    # Optional specialty filter (Spark JSON parsing is expensive in-line;
    # easier to do it post-query in Python).
    wanted = {s.strip().lower() for s in (body.specialties or []) if s.strip()}
    min_conf = body.min_confidence or 0.0

    results: list[SearchResultItem] = []
    for row in rows:
        facility = _delta_row_to_facility(row)
        if wanted:
            specs = {s.lower() for s in (facility.specialties or [])}
            if not (wanted & specs):
                continue
        if min_conf > 0 and facility.confidence:
            conf_vals = [v for v in facility.confidence.values() if isinstance(v, (int, float))]
            if conf_vals and (sum(conf_vals) / len(conf_vals)) < min_conf:
                continue
        results.append(
            SearchResultItem(
                facility=facility,
                distance_km=_safe_float(row.get("distance_km")),
                match_score=float(row.get("text_score") or 0.0),
                top_evidence=_pick_evidence_from_delta(row, body.query),
            )
        )
    return results


_COMPLETENESS_FIELDS: tuple[str, ...] = (
    "specialties",
    "capability",
    "procedure",
    "equipment",
    "description",
    "address_line1",
    "pincode",
    "facilityTypeId",
)


def _delta_row_quality(row: dict[str, Any]) -> float:
    """Per-row quality score in ``[0, 1]`` from gold-table trust signals.

    Blends five components so identical ``trust_rank`` values still
    produce visibly different confidences — real-world data clusters
    tightly on any single signal, so we have to average across several:

    * ``trust_norm`` — ETL trust rank (0-5) divided by 5.
    * ``src_norm``   — log-scaled distinct source count; 1 → 3 sources
                       is meaningful instead of pinned near 0.4.
    * ``accred_norm`` — NABH / JCI carry a heavy boost; PMJAY / CGHS /
                       ESI (payer panels) add smaller bumps. Often
                       zero because the flags are free-text-derived.
    * ``rich_norm``  — fraction of expected fields populated.
    * ``breadth_norm`` — ``text_score`` normalised. A row matching the
                         query in name + specialty + description is
                         more trustworthy than one matching only on
                         specialty, and ``text_score`` is the most
                         variable per-row signal we have.
    """
    import math

    trust = row.get("trust_rank")
    sources = row.get("distinct_source_count")

    trust_norm = 0.5
    if isinstance(trust, (int, float)):
        trust_norm = max(0.0, min(1.0, float(trust) / 5.0))

    src_norm = 0.5
    if isinstance(sources, (int, float)) and sources > 0:
        src_norm = min(1.0, math.log1p(float(sources)) / math.log1p(5.0))

    accred = 0.0
    if _truthy(row.get("mentions_nabh")):
        accred += 0.45
    if _truthy(row.get("mentions_jci")):
        accred += 0.45
    for key in ("mentions_pmjay", "mentions_cghs", "mentions_esi"):
        if _truthy(row.get(key)):
            accred += 0.10
    accred_norm = min(1.0, accred)

    populated = sum(
        1
        for field in _COMPLETENESS_FIELDS
        if _is_populated(row.get(field))
    )
    rich_norm = populated / float(len(_COMPLETENESS_FIELDS))

    # text_score range: 0 (no match) → ~10.5 (every field matched).
    # Divide by 6 so a "name + specialty + description" hit (~6.5)
    # already lands near 1.0; anything more is gravy.
    text_score = row.get("text_score")
    breadth_norm = 0.0
    if isinstance(text_score, (int, float)) and text_score > 0:
        breadth_norm = min(1.0, float(text_score) / 6.0)

    return (
        0.25 * trust_norm
        + 0.15 * src_norm
        + 0.20 * accred_norm
        + 0.15 * rich_norm
        + 0.25 * breadth_norm
    )


def _truthy(value: Any) -> bool:
    """Coerce gold-table boolean-ish cells (1/0, 'true'/'false', None)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        v = value.strip().lower()
        return v in {"1", "true", "t", "yes", "y"}
    return False


def _is_populated(value: Any) -> bool:
    """Tests whether a Delta cell holds a non-empty value (handles JSON-string lists)."""
    if value is None:
        return False
    if isinstance(value, str):
        s = value.strip()
        return bool(s) and s != "[]"
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _blend_confidence(base: float, quality: float) -> float:
    """Combine a match-type base with the row's quality, clamped to [0, 1].

    Quality gets the heavier weight (0.6) so identical match types (the
    common case — most queries hit a structured field) still produce
    visibly different confidences when the underlying facilities differ
    in trust signals.
    """
    blended = 0.40 * base + 0.60 * quality
    return max(0.0, min(1.0, blended))


def _pick_evidence_from_delta(row: dict[str, Any], query: str | None) -> Evidence | None:
    """Pick one evidence snippet from a Delta row, parsing JSON-string lists.

    Confidence is a blend of the *match type* (structured field > name >
    description > fuzzy) and the *row's quality* (trust_rank + source
    count), so the ranked list shows real per-facility variation instead
    of every row reading the same constant.
    """
    if not query:
        return None
    q = query.strip().lower()
    if not q:
        return None

    quality = _delta_row_quality(row)

    field_map = {
        "specialties": row.get("specialties"),
        "services": row.get("capability"),
        "procedures": row.get("procedure"),
        "equipment": row.get("equipment"),
    }
    for field, value in field_map.items():
        items = _parse_json_list(value)
        for item in items:
            if q in item.lower():
                return Evidence(
                    field=field,
                    snippet=item,
                    confidence=_blend_confidence(0.85, quality),
                )

    name = row.get("name") or ""
    if isinstance(name, str) and q in name.lower():
        return Evidence(
            field="name",
            snippet=name,
            confidence=_blend_confidence(0.95, quality),
        )

    desc = row.get("description") or ""
    if isinstance(desc, str):
        lo = desc.lower()
        idx = lo.find(q)
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(desc), idx + len(q) + 80)
            snippet = ("…" if start > 0 else "") + desc[start:end] + ("…" if end < len(desc) else "")
            return Evidence(
                field="description",
                snippet=snippet,
                confidence=_blend_confidence(0.60, quality),
            )

    from difflib import SequenceMatcher
    best: tuple[str, str, float] | None = None
    for field, value in field_map.items():
        for item in _parse_json_list(value):
            ratio = SequenceMatcher(None, q, item.lower()).ratio()
            if ratio >= 0.65 and (best is None or ratio > best[2]):
                best = (field, item, ratio)
    if best is not None:
        return Evidence(
            field=best[0],
            snippet=best[1],
            confidence=_blend_confidence(0.45 * best[2], quality),
        )

    return None


def _run_quick_search(
    session, body: SearchIn, origin: SearchOrigin
) -> list[SearchResultItem]:
    specialties_param = (
        json.dumps([s.lower() for s in body.specialties])
        if body.specialties
        else None
    )
    base_params: dict[str, Any] = {
        "q": (body.query or "").strip() or None,
        "lat": origin.lat,
        "lng": origin.lng,
        "specialties_filter": specialties_param,
        "min_conf": body.min_confidence,
        "radius_km": body.radius_km,
        "limit": min(body.limit, 200),
    }

    # Try the trigram-enhanced query first (fuzzy / typo-tolerant). If
    # ``pg_trgm`` isn't available the SQL raises a ProgrammingError for the
    # missing ``similarity`` function; we then transparently retry with the
    # legacy substring-only query.
    try:
        rows = (
            session.execute(
                _SEARCH_SQL,
                params={**base_params, "fuzzy_floor": _FUZZY_FLOOR},
            )
            .mappings()
            .all()
        )
    except ProgrammingError as exc:
        msg = str(exc).lower()
        if "similarity" in msg or "pg_trgm" in msg:
            logger.warning(
                "Trigram search unavailable, falling back to substring-only: %s",
                exc,
            )
            session.rollback()
            try:
                rows = (
                    session.execute(_SEARCH_SQL_FALLBACK, params=base_params)
                    .mappings()
                    .all()
                )
            except ProgrammingError as exc2:
                logger.warning("_run_quick_search fallback: %s", exc2)
                return []
        else:
            logger.warning("_run_quick_search: %s", exc)
            return []

    results: list[SearchResultItem] = []
    for row in rows:
        row_dict = dict(row)
        results.append(
            SearchResultItem(
                facility=_row_to_facility(row_dict),
                distance_km=row_dict.get("distance_km"),
                match_score=float(row_dict.get("match_score") or 0.0),
                top_evidence=_pick_evidence(row_dict, body.query),
            )
        )
    return results


@router.post("/search", response_model=SearchResults, operation_id="search")
def search(
    body: SearchIn,
    session: Dependencies.Session,
    ws: Dependencies.Client,
    config: Dependencies.Config,
) -> SearchResults:
    """Search the facility catalog.

    The pipeline is always:

    1. **Query Parser** (Llama 3.3 70B) extracts ``capability`` +
       ``location`` from natural-language input in any of the nine
       supported Indian languages or English. Skipped only when the
       caller already separated need from location (the structured
       two-box form on the landing page).
    2. **Facility Search** runs the deterministic SQL shortlist against
       Unity Catalog ``facilities_gold`` (or Lakebase as a fallback),
       blending text match, distance decay, and the gold table's
       pre-computed ``trust_rank``.
    3. **Trust Scorer** (rule-based) tags each row strong / partial /
       weak / suspicious / no-evidence so the coordinator sees the
       *evidence quality* of the match, not just the relevance score.

    Returns an empty result list (not a 500) when nothing is found so
    the UI shows the empty-state cleanly.
    """
    # Always run the LLM parser when ``query`` is multi-word \u2014 even if
    # ``location_text`` is set \u2014 so we can extract a concise
    # ``capability_text`` (e.g. "surgery") from a verbose query
    # ("emergency surgery"). Single-word queries skip the LLM since
    # there's nothing to extract.
    _q_strip = (body.query or "").strip()
    needs_parser = bool(_q_strip) and len(_q_strip.split()) >= 2
    parsed: dict[str, Any] = {}
    if needs_parser:
        ws_token = set_workspace(ws)
        ep_token = set_endpoint(config.llm_endpoint) if config.llm_endpoint else None
        try:
            parsed = parse_query(body.query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("query parser crashed (%s); using raw text", exc)
            parsed = {}
        finally:
            if ep_token is not None:
                reset_endpoint(ep_token)
            reset_workspace(ws_token)

    # Parser may return ``capability_text`` (legacy) or ``capability``
    # (current schema). Accept either; fall back to the raw user input.
    _parsed_capability = (
        (parsed.get("capability_text") if parsed else None)
        or (parsed.get("capability") if parsed else None)
    )
    refined_body = body.model_copy(
        update={
            "query": (
                _parsed_capability
                or body.query
                or ""
            ).strip()
            or None,
            "location_text": (
                (parsed.get("location_text") if parsed else None)
                or body.location_text
                or None
            ),
        }
    )
    origin = _resolve_origin(refined_body)
    parsed_loc = parsed.get("location") if isinstance(parsed, dict) else None
    if (
        isinstance(parsed_loc, dict)
        and parsed_loc.get("latitude") is not None
        and parsed_loc.get("longitude") is not None
    ):
        origin = SearchOrigin(
            lat=float(parsed_loc["latitude"]),
            lng=float(parsed_loc["longitude"]),
            label=str(parsed_loc.get("label") or origin.label or ""),
        )

    quick = _run_delta_search(ws, config, refined_body, origin)
    if quick is None:
        quick = (
            _run_quick_search(session, refined_body, origin)
            if session is not None
            else []
        )

    candidates = [_candidate_dict(item) for item in quick]
    try:
        result = run_referral_pipeline(
            ws=ws,
            raw_query=body.query or "",
            candidates=candidates,
            parsed_override=parsed or None,
            llm_endpoint=(config.llm_endpoint or None),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("agentic pipeline crashed (%s); returning shortlist", exc)
        return SearchResults(origin=origin, results=quick, mode="search")

    by_id = {str(item.facility.id): item for item in quick}
    enriched: list[SearchResultItem] = []
    for ranked in result.get("facilities") or []:
        fid = str(ranked.get("id") or "")
        base = by_id.get(fid)
        if base is None:
            continue
        enriched.append(
            SearchResultItem(
                facility=base.facility,
                distance_km=base.distance_km,
                match_score=base.match_score,
                top_evidence=base.top_evidence,
                trust_signal=ranked.get("trust_signal"),
                trust_rank=ranked.get("trust_rank"),
                evidence_summary=ranked.get("evidence_summary"),
                missing_evidence=ranked.get("missing_evidence") or None,
                quality_boost=ranked.get("quality_boost"),
                quality_reasons=ranked.get("quality_reasons") or None,
                attributes=(ranked.get("attributes") or None),
            )
        )

    # LLM evidence pass — single batched call to score the top results
    # with a real per-facility confidence. Falls back silently to the
    # rule-based scores if the LLM hops fail or return garbage. Bounded
    # at 5 facilities to keep latency under ~3s.
    # LLM evidence pass — single batched call to score the top 10 rows
    # with a real per-facility confidence. Falls back silently to the
    # rule-based scores if the LLM hops fail or return garbage. After
    # scoring we re-rank by LLM confidence and discard the un-scored
    # tail so the UI only ever shows results the LLM has actually
    # evaluated.
    LLM_TOP_N = 10
    if enriched:
        _apply_llm_evidence_scores(
            ws=ws,
            config=config,
            results=enriched,
            search_terms=_search_terms_for_llm(parsed, body),
            top_n=LLM_TOP_N,
        )
        enriched = _rerank_by_llm_confidence(enriched, top_n=LLM_TOP_N)
        enriched = enriched[:LLM_TOP_N]

    parsed_out = (
        ParsedQueryOut(
            raw_query=parsed.get("raw_query"),
            capability_text=parsed.get("capability_text"),
            location_text=parsed.get("location_text"),
            specialty_terms=parsed.get("specialty_terms"),
            location=parsed.get("location"),
            urgency=parsed.get("urgency"),
            language=parsed.get("language"),
        )
        if parsed
        else None
    )
    trace = [
        AgentTraceStep(
            agent=str(step.get("agent") or "step"),
            reasoning=step.get("reasoning") or None,
            output=step.get("output"),
            method=step.get("method") or None,
            latency_ms=step.get("latency_ms"),
        )
        for step in (result.get("agent_trace") or [])
    ]
    return SearchResults(
        origin=origin,
        results=enriched or quick,
        agent_trace=trace,
        parsed_query=parsed_out,
        mode="search",
    )


# ---------------------------------------------------------------------------
# Helpers shared by the search pipeline
# ---------------------------------------------------------------------------


def _candidate_dict(item: SearchResultItem) -> dict[str, Any]:
    """Flatten a search result into the dict shape the agents expect."""
    f = item.facility
    return {
        "id": str(f.id),
        "name": f.name,
        "type": f.type,
        "address": f.address,
        "city": f.city,
        "state": f.state,
        "pincode": f.pincode,
        "country": f.country,
        "latitude": f.latitude,
        "longitude": f.longitude,
        "specialties": f.specialties,
        "services": f.services,
        "procedures": f.procedures,
        "equipment": f.equipment,
        "raw_description": f.raw_description,
        "confidence": f.confidence,
        "source": f.source,
        "distance_km": item.distance_km,
        "match_score": item.match_score,
    }


def _search_terms_for_llm(
    parsed: dict[str, Any] | None, body: SearchIn
) -> list[str]:
    """Collect query tokens worth showing to the evidence-scoring LLM.

    Prefers the LLM parser's structured ``specialty_terms`` (already
    lemmatised), falls back to the parsed ``capability_text``, and finally
    to the raw query string. Always returns a list; never ``None``.
    """
    if parsed:
        terms = parsed.get("specialty_terms")
        if isinstance(terms, list) and terms:
            return [str(t) for t in terms if t]
        capability = parsed.get("capability_text")
        if isinstance(capability, str) and capability.strip():
            return [capability.strip()]
    if body.query and body.query.strip():
        return [body.query.strip()]
    return []


def _apply_llm_evidence_scores(
    *,
    ws,
    config: AppConfig,
    results: list[SearchResultItem],
    search_terms: list[str],
    top_n: int = 10,
) -> None:
    """Mutate ``results`` in-place with LLM-derived per-facility scores.

    Calls the evidence scorer agent on the first ``top_n`` rows. The
    LLM's ``confidence_score`` overrides ``top_evidence.confidence`` (so
    the UI badge varies per row) and its ``trust_signal`` /
    ``evidence_summary`` replace the rule-based ones. Untouched on
    failure: rule-based scores remain intact.
    """
    if not results:
        return
    targets = results[:top_n]

    ws_token = set_workspace(ws)
    ep_token = (
        set_endpoint(config.llm_endpoint) if config.llm_endpoint else None
    )
    try:
        scored = score_evidence_with_llm(
            facilities=[_candidate_dict(item) for item in targets],
            search_terms=search_terms,
            max_facilities=top_n,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm evidence scoring crashed (%s); keeping rules", exc)
        return
    finally:
        if ep_token is not None:
            reset_endpoint(ep_token)
        reset_workspace(ws_token)

    for item, score in zip(targets, scored):
        if score.get("method") != "llm":
            continue
        new_conf = score.get("confidence_score")
        if isinstance(new_conf, float):
            if item.top_evidence is not None:
                item.top_evidence = item.top_evidence.model_copy(
                    update={"confidence": new_conf}
                )
            else:
                # Build a minimal evidence record so the UI badge has a
                # numeric to render; the snippet is the LLM summary.
                item.top_evidence = Evidence(
                    field="llm",
                    snippet=str(score.get("evidence_summary") or ""),
                    confidence=new_conf,
                )
        if score.get("trust_signal"):
            item.trust_signal = str(score["trust_signal"])
        if score.get("evidence_summary"):
            item.evidence_summary = str(score["evidence_summary"])
        if score.get("missing_evidence"):
            item.missing_evidence = list(score["missing_evidence"])
        item.scoring_method = "llm"


_TRUST_RANK: dict[str, int] = {
    "strong_evidence": 4,
    "partial_evidence": 3,
    "weak_evidence": 2,
    "suspicious": 1,
    "no_evidence": 0,
}


def _rerank_by_llm_confidence(
    results: list[SearchResultItem], top_n: int = 10
) -> list[SearchResultItem]:
    """Sort the top ``top_n`` rows by LLM-derived confidence, then return.

    Untouched rows (those the LLM didn't score, identified by
    ``scoring_method != "llm"``) keep their rule-based rank below the
    LLM-scored cohort. Within the scored cohort we sort by:

    1. LLM ``trust_signal`` tier (strong > partial > weak > suspicious > none)
    2. Numeric LLM confidence (descending)
    3. Original rank (stable — preserves rule-based tiebreaker)

    This means a "98% strong_evidence" row will always outrank a
    "58% partial_evidence" row, regardless of distance or text score.
    """
    if not results:
        return results

    head = results[:top_n]
    tail = results[top_n:]

    indexed = list(enumerate(head))

    def sort_key(pair: tuple[int, SearchResultItem]):
        idx, item = pair
        if item.scoring_method != "llm":
            # Push un-scored rows to the bottom of the cohort but keep
            # their relative order via the original index.
            return (1, 0, 0.0, idx)
        signal_rank = _TRUST_RANK.get(item.trust_signal or "", 0)
        conf = (
            item.top_evidence.confidence
            if item.top_evidence is not None
            else 0.0
        )
        # Negate signal/confidence so higher values sort first.
        return (0, -signal_rank, -float(conf), idx)

    indexed.sort(key=sort_key)
    reordered_head = [item for _, item in indexed]
    return reordered_head + tail


# ---------------------------------------------------------------------------
# Submissions (provider self-attest + fieldwork surveyor)
# ---------------------------------------------------------------------------


@router.post(
    "/submissions",
    response_model=SubmissionOut,
    operation_id="createSubmission",
    status_code=status.HTTP_201_CREATED,
)
def create_submission(
    body: SubmissionIn,
    session: Dependencies.Session,
    headers: Dependencies.Headers,
) -> SubmissionOut:
    """Stage a provider self-attestation or fieldwork survey row.

    Status starts at ``pending``. Reviewers promote rows into the
    ``facilities`` table out-of-band in SQL.
    """
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Submissions require Lakebase; not configured.",
        )
    submitted_by = headers.user_email or headers.user_name
    row = FacilitySubmission(
        status=SubmissionStatus.pending,
        submission_type=body.submission_type,
        submitted_by=submitted_by,
        submitted_at=datetime.now(timezone.utc),
        payload=body.payload,
        captured_lat=body.captured_lat,
        captured_lng=body.captured_lng,
        captured_at=body.captured_at,
        photo_url=body.photo_url,
        notes=body.notes,
    )
    session.add(row)
    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.exception("create_submission failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save submission. Try again shortly.",
        ) from exc
    session.refresh(row)
    return SubmissionOut.model_validate(row)


@router.get(
    "/submissions/mine",
    response_model=list[SubmissionOut],
    operation_id="listMySubmissions",
)
def list_my_submissions(
    session: Dependencies.Session,
    headers: Dependencies.Headers,
    limit: int = Query(default=50, ge=1, le=200),
) -> Sequence[SubmissionOut]:
    """Return submissions made by the current user, newest first."""
    if session is None:
        return []
    me = headers.user_email or headers.user_name
    if not me:
        return []
    rows = session.exec(
        select(FacilitySubmission)
        .where(FacilitySubmission.submitted_by == me)
        .order_by(col(FacilitySubmission.submitted_at).desc())
        .limit(limit)
    ).all()
    return [SubmissionOut.model_validate(r) for r in rows]


@router.get(
    "/facilities/{facility_id}",
    response_model=FacilityOut,
    operation_id="getFacility",
)
def get_facility(
    facility_id: str,
    session: Dependencies.Session,
    ws: Dependencies.Client,
    config: Dependencies.Config,
) -> FacilityOut:
    """Fetch one facility for the detail / evidence drawer view.

    Looks in the Delta gold table first (where the production data
    lives) and falls back to Lakebase. ``facility_id`` is treated as
    opaque text so we accept both Delta ``unique_id`` strings and
    legacy Lakebase UUIDs.
    """
    warehouse_id = (config.delta_warehouse_id or "").strip()
    table = (config.delta_facilities_table or "").strip()
    if warehouse_id and table:
        try:
            rows = delta_query(
                ws,
                warehouse_id=warehouse_id,
                statement=f"SELECT * FROM {table} WHERE unique_id = :fid LIMIT 1",
                parameters={"fid": facility_id},
                wait_timeout="20s",
            )
            if rows:
                return _delta_row_to_facility(rows[0])
        except DeltaQueryError as exc:
            logger.warning("get_facility delta lookup failed: %s", exc)

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facility not found",
        )
    try:
        uid = UUID(facility_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facility not found",
        )
    row = session.get(Facility, uid)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Facility not found",
        )
    return FacilityOut.model_validate(row)
