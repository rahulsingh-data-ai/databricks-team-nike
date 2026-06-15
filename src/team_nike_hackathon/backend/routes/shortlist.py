"""Persistence routes — backed by Delta tables in Unity Catalog.

Originally these used Lakebase (Postgres + SQLModel) but switching to
Delta keeps the stack simple: same warehouse, same connector, works
everywhere we already query.

Tables (all in workspace.referral_copilot):
    shortlist            — facilities a planner saved
    facility_overrides   — manual trust-signal corrections
    facility_reviews     — review decisions (verified / rejected / follow-up)
    search_history       — past queries for resume / audit
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import DatabricksSQLDependency
from ..db.databricks_sql import _fqn, sql_str

router = APIRouter(tags=["persistence"])

SHORTLIST    = _fqn("shortlist")
OVERRIDES    = _fqn("facility_overrides")
REVIEWS      = _fqn("facility_reviews")
HISTORY      = _fqn("search_history")

_ALLOWED_TRUST = {
    "strong_evidence", "partial_evidence", "weak_evidence",
    "suspicious", "no_evidence",
}
_ALLOWED_REVIEW_STATUS = {"verified", "rejected", "needs_follow_up"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts_lit(iso: str) -> str:
    """Render a timestamp for Spark SQL TIMESTAMP literal."""
    return f"TIMESTAMP {sql_str(iso)}"


def _nullable(value):
    return "NULL" if value is None else sql_str(value)


def _double(value):
    if value is None:
        return "NULL"
    try:
        return f"{float(value)}"
    except (TypeError, ValueError):
        return "NULL"


def _int(value):
    if value is None:
        return "NULL"
    try:
        return f"{int(value)}"
    except (TypeError, ValueError):
        return "NULL"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SaveShortlistRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=120)
    search_query: str | None = Field(default=None, max_length=500)
    facility_id: str = Field(..., min_length=1, max_length=120)
    facility_name: str = Field(..., min_length=1, max_length=300)
    capability: str | None = Field(default=None, max_length=120)
    trust_signal: str | None = Field(default=None, max_length=40)
    distance_km: float | None = None
    notes: str | None = Field(default=None, max_length=2000)


class UpdateNotesRequest(BaseModel):
    notes: str = Field(..., max_length=2000)


class OverrideRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=120)
    facility_id: str = Field(..., min_length=1, max_length=120)
    capability: str | None = Field(default=None, max_length=120)
    overridden_trust_signal: str
    reason: str = Field(..., min_length=3, max_length=1000)


class ReviewRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=120)
    facility_id: str = Field(..., min_length=1, max_length=120)
    status: str
    notes: str | None = Field(default=None, max_length=2000)


class LogSearchRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=120)
    query: str = Field(..., min_length=1, max_length=500)
    capability_text: str | None = Field(default=None, max_length=200)
    location_text: str | None = Field(default=None, max_length=200)
    result_count: int | None = Field(default=None, ge=0)
    top_trust_signal: str | None = Field(default=None, max_length=40)


# ---------------------------------------------------------------------------
# Shortlist
# ---------------------------------------------------------------------------

@router.post("/shortlist")
async def save_to_shortlist(body: SaveShortlistRequest, db: DatabricksSQLDependency):
    item_id = str(uuid4())
    now = _now_iso()
    sql = f"""
    INSERT INTO {SHORTLIST}
      (id, user_id, search_query, facility_id, facility_name, capability,
       trust_signal, distance_km, notes, saved_at)
    VALUES (
      {sql_str(item_id)},
      {sql_str(body.user_id)},
      {_nullable(body.search_query)},
      {sql_str(body.facility_id)},
      {sql_str(body.facility_name)},
      {_nullable(body.capability)},
      {_nullable(body.trust_signal)},
      {_double(body.distance_km)},
      {_nullable(body.notes)},
      {_ts_lit(now)}
    )
    """
    db.execute(sql)
    return {"shortlist_id": item_id, "status": "saved", "saved_at": now}


@router.get("/shortlist/{user_id}")
async def get_shortlist(
    user_id: str,
    db: DatabricksSQLDependency,
    limit: int = Query(default=100, ge=1, le=500),
):
    rows = db.execute(
        f"SELECT * FROM {SHORTLIST} "
        f"WHERE user_id = {sql_str(user_id)} "
        f"ORDER BY saved_at DESC LIMIT {limit}"
    )
    return {"items": rows, "count": len(rows)}


@router.delete("/shortlist/{shortlist_id}")
async def remove_from_shortlist(shortlist_id: str, db: DatabricksSQLDependency):
    rows = db.execute(
        f"SELECT id FROM {SHORTLIST} WHERE id = {sql_str(shortlist_id)} LIMIT 1"
    )
    if not rows:
        raise HTTPException(404, "Shortlist item not found")
    db.execute(f"DELETE FROM {SHORTLIST} WHERE id = {sql_str(shortlist_id)}")
    return {"status": "deleted"}


@router.patch("/shortlist/{shortlist_id}/notes")
async def update_notes(
    shortlist_id: str,
    body: UpdateNotesRequest,
    db: DatabricksSQLDependency,
):
    rows = db.execute(
        f"SELECT id FROM {SHORTLIST} WHERE id = {sql_str(shortlist_id)} LIMIT 1"
    )
    if not rows:
        raise HTTPException(404, "Shortlist item not found")
    db.execute(
        f"UPDATE {SHORTLIST} SET notes = {sql_str(body.notes)} "
        f"WHERE id = {sql_str(shortlist_id)}"
    )
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

@router.post("/overrides")
async def add_override(body: OverrideRequest, db: DatabricksSQLDependency):
    if body.overridden_trust_signal not in _ALLOWED_TRUST:
        raise HTTPException(
            400,
            f"overridden_trust_signal must be one of {sorted(_ALLOWED_TRUST)}",
        )
    override_id = str(uuid4())
    now = _now_iso()
    db.execute(
        f"INSERT INTO {OVERRIDES} (id, user_id, facility_id, capability, "
        f"overridden_trust_signal, reason, created_at) VALUES ("
        f"{sql_str(override_id)}, {sql_str(body.user_id)}, "
        f"{sql_str(body.facility_id)}, {_nullable(body.capability)}, "
        f"{sql_str(body.overridden_trust_signal)}, {sql_str(body.reason)}, "
        f"{_ts_lit(now)})"
    )
    return {"override_id": override_id, "status": "saved", "created_at": now}


@router.get("/overrides/{facility_id}")
async def get_overrides(
    facility_id: str,
    db: DatabricksSQLDependency,
    limit: int = Query(default=50, ge=1, le=500),
):
    rows = db.execute(
        f"SELECT * FROM {OVERRIDES} "
        f"WHERE facility_id = {sql_str(facility_id)} "
        f"ORDER BY created_at DESC LIMIT {limit}"
    )
    return {"overrides": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@router.post("/reviews")
async def add_review(body: ReviewRequest, db: DatabricksSQLDependency):
    if body.status not in _ALLOWED_REVIEW_STATUS:
        raise HTTPException(
            400, f"status must be one of {sorted(_ALLOWED_REVIEW_STATUS)}"
        )
    review_id = str(uuid4())
    now = _now_iso()
    db.execute(
        f"INSERT INTO {REVIEWS} (id, user_id, facility_id, status, notes, "
        f"created_at) VALUES ("
        f"{sql_str(review_id)}, {sql_str(body.user_id)}, "
        f"{sql_str(body.facility_id)}, {sql_str(body.status)}, "
        f"{_nullable(body.notes)}, {_ts_lit(now)})"
    )
    return {"review_id": review_id, "status": "saved", "created_at": now}


@router.get("/reviews/{facility_id}")
async def get_reviews(
    facility_id: str,
    db: DatabricksSQLDependency,
    limit: int = Query(default=50, ge=1, le=500),
):
    rows = db.execute(
        f"SELECT * FROM {REVIEWS} "
        f"WHERE facility_id = {sql_str(facility_id)} "
        f"ORDER BY created_at DESC LIMIT {limit}"
    )
    return {"reviews": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

@router.post("/search-history")
async def log_search(body: LogSearchRequest, db: DatabricksSQLDependency):
    item_id = str(uuid4())
    now = _now_iso()
    db.execute(
        f"INSERT INTO {HISTORY} (id, user_id, query, capability_text, "
        f"location_text, result_count, top_trust_signal, created_at) VALUES ("
        f"{sql_str(item_id)}, {sql_str(body.user_id)}, "
        f"{sql_str(body.query)}, {_nullable(body.capability_text)}, "
        f"{_nullable(body.location_text)}, {_int(body.result_count)}, "
        f"{_nullable(body.top_trust_signal)}, {_ts_lit(now)})"
    )
    return {"search_id": item_id, "status": "saved", "created_at": now}


@router.get("/search-history/{user_id}")
async def get_search_history(
    user_id: str,
    db: DatabricksSQLDependency,
    limit: int = Query(default=50, ge=1, le=500),
):
    rows = db.execute(
        f"SELECT * FROM {HISTORY} "
        f"WHERE user_id = {sql_str(user_id)} "
        f"ORDER BY created_at DESC LIMIT {limit}"
    )
    return {"items": rows, "count": len(rows)}
