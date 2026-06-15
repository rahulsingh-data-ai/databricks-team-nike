"""Citation builder.

Turns a facility's raw evidence fields (free-text claim arrays + source
URLs) into an explicit claim → source mapping so the UI can show *why*
we trust (or don't trust) every statement.

This is required by the track spec:
    "Cite the underlying facility text for any important claim,
     recommendation, score, or ranking."
"""

from __future__ import annotations

import json
import re
from typing import Any

_MAX_CLAIM_LEN = 400


def _parse_array(value: Any) -> list[str]:
    if value in (None, "", "null"):
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(v) for v in parsed if v]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return [str(value)]


def _norm(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def _matches_term(claim: str, term: str) -> bool:
    if not term:
        return False
    return _norm(term) in _norm(claim)


def build_citations(
    facility: dict[str, Any],
    search_terms: list[str] | None = None,
) -> dict[str, Any]:
    """Return a per-field citation map for one facility.

    Output shape::

        {
            "facility_id": "...",
            "facility_name": "...",
            "source_urls": [...],
            "source_types": [...],
            "claims": [
                {
                    "field": "capability" | "procedure" | "equipment"
                              | "description" | "specialties",
                    "claim": "Has dialysis machine",
                    "matches_search": true,
                    "supporting_sources": [...],
                },
                ...
            ],
            "summary": {
                "claim_count": N,
                "matching_claim_count": N,
                "source_url_count": N,
                "distinct_source_types": N,
            },
        }
    """
    search_terms = [t for t in (search_terms or []) if t]

    capability_claims = _parse_array(facility.get("capability"))
    procedure_claims = _parse_array(facility.get("procedure"))
    equipment_claims = _parse_array(facility.get("equipment"))
    specialties = _parse_array(facility.get("specialties"))
    description = facility.get("description") or ""

    source_urls = _parse_array(facility.get("source_urls"))
    source_types = _parse_array(facility.get("source_types"))
    distinct_source_types = sorted({s for s in source_types if s})

    claims: list[dict[str, Any]] = []

    def add(field: str, claim: str):
        c = (claim or "").strip()
        if not c:
            return
        truncated = c[:_MAX_CLAIM_LEN]
        matches = any(_matches_term(truncated, t) for t in search_terms)
        claims.append({
            "field": field,
            "claim": truncated,
            "matches_search": matches,
            "supporting_sources": source_urls[:5],
        })

    for c in capability_claims:
        add("capability", c)
    for c in procedure_claims:
        add("procedure", c)
    for c in equipment_claims:
        add("equipment", c)
    for s in specialties:
        add("specialties", s)
    if description and len(description.strip()) > 5:
        add("description", description)

    matching = [c for c in claims if c["matches_search"]]

    return {
        "facility_id": facility.get("unique_id"),
        "facility_name": facility.get("name"),
        "source_urls": source_urls,
        "source_types": distinct_source_types,
        "claims": claims,
        "summary": {
            "claim_count": len(claims),
            "matching_claim_count": len(matching),
            "source_url_count": len(source_urls),
            "distinct_source_types": len(distinct_source_types),
        },
    }
