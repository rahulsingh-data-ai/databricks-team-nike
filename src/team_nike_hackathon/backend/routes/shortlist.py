"""Persistence routes (Lakebase / Postgres).

Tables:
    - shortlist        — facilities a planner saved
    - facility_overrides — manual trust-signal corrections
    - facility_reviews   — review decisions (verified / rejected / follow-up)
    - search_history     — past queries for resume / audit
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Field as SQLField
from sqlmodel import Session, SQLModel, select

from ..core.dependencies import Dependencies

router = APIRouter(tags=["persistence"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class ShortlistItem(SQLModel, table=True):
    __tablename__ = "shortlist"

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = SQLField(index=True)
    search_query: str | None = None
    facility_id: str = SQLField(index=True)
    facility_name: str
    capability: str | None = None
    trust_signal: str | None = None
    distance_km: float | None = None
    notes: str | None = None
    saved_at: str = SQLField(default_factory=_utc_now_iso)


_ALLOWED_OVERRIDE_TRUST = {
    "strong_evidence", "partial_evidence", "weak_evidence",
    "suspicious", "no_evidence",
}


class FacilityOverride(SQLModel, table=True):
    __tablename__ = "facility_overrides"

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = SQLField(index=True)
    facility_id: str = SQLField(index=True)
    capability: str | None = None
    overridden_trust_signal: str
    reason: str
    created_at: str = SQLField(default_factory=_utc_now_iso)


_ALLOWED_REVIEW_STATUS = {"verified", "rejected", "needs_follow_up"}


class FacilityReview(SQLModel, table=True):
    __tablename__ = "facility_reviews"

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = SQLField(index=True)
    facility_id: str = SQLField(index=True)
    status: str
    notes: str | None = None
    created_at: str = SQLField(default_factory=_utc_now_iso)


class SearchHistoryItem(SQLModel, table=True):
    __tablename__ = "search_history"

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = SQLField(index=True)
    query: str
    capability_text: str | None = None
    location_text: str | None = None
    result_count: int | None = None
    top_trust_signal: str | None = None
    created_at: str = SQLField(default_factory=_utc_now_iso, index=True)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SaveShortlistRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    search_query: str | None = None
    facility_id: str = Field(..., min_length=1)
    facility_name: str = Field(..., min_length=1)
    capability: str | None = None
    trust_signal: str | None = None
    distance_km: float | None = None
    notes: str | None = Field(default=None, max_length=2000)


class UpdateNotesRequest(BaseModel):
    notes: str = Field(..., max_length=2000)


class OverrideRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    facility_id: str = Field(..., min_length=1)
    capability: str | None = None
    overridden_trust_signal: str
    reason: str = Field(..., min_length=3, max_length=1000)


class ReviewRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    facility_id: str = Field(..., min_length=1)
    status: str
    notes: str | None = Field(default=None, max_length=2000)


class LogSearchRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1, max_length=500)
    capability_text: str | None = None
    location_text: str | None = None
    result_count: int | None = None
    top_trust_signal: str | None = None


# ---------------------------------------------------------------------------
# Shortlist
# ---------------------------------------------------------------------------

@router.post("/shortlist")
async def save_to_shortlist(body: SaveShortlistRequest, session: Dependencies.Session):
    """Save a facility to the user's shortlist."""
    item = ShortlistItem(**body.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"shortlist_id": item.id, "status": "saved"}


@router.get("/shortlist/{user_id}")
async def get_shortlist(
    user_id: str,
    session: Dependencies.Session,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get all saved facilities for a user."""
    items = session.exec(
        select(ShortlistItem)
        .where(ShortlistItem.user_id == user_id)
        .limit(limit)
    ).all()
    return {"items": [i.model_dump() for i in items], "count": len(items)}


@router.delete("/shortlist/{shortlist_id}")
async def remove_from_shortlist(shortlist_id: str, session: Dependencies.Session):
    item = session.get(ShortlistItem, shortlist_id)
    if not item:
        raise HTTPException(status_code=404, detail="Shortlist item not found")
    session.delete(item)
    session.commit()
    return {"status": "deleted"}


@router.patch("/shortlist/{shortlist_id}/notes")
async def update_notes(
    shortlist_id: str,
    body: UpdateNotesRequest,
    session: Dependencies.Session,
):
    item = session.get(ShortlistItem, shortlist_id)
    if not item:
        raise HTTPException(status_code=404, detail="Shortlist item not found")
    item.notes = body.notes
    session.add(item)
    session.commit()
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------

@router.post("/overrides")
async def add_override(body: OverrideRequest, session: Dependencies.Session):
    """Record a planner's manual trust-signal correction."""
    if body.overridden_trust_signal not in _ALLOWED_OVERRIDE_TRUST:
        raise HTTPException(
            400,
            f"overridden_trust_signal must be one of {sorted(_ALLOWED_OVERRIDE_TRUST)}",
        )
    item = FacilityOverride(**body.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"override_id": item.id, "status": "saved"}


@router.get("/overrides/{facility_id}")
async def get_overrides(
    facility_id: str,
    session: Dependencies.Session,
    limit: int = Query(default=50, ge=1, le=500),
):
    rows = session.exec(
        select(FacilityOverride)
        .where(FacilityOverride.facility_id == facility_id)
        .limit(limit)
    ).all()
    return {"overrides": [r.model_dump() for r in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@router.post("/reviews")
async def add_review(body: ReviewRequest, session: Dependencies.Session):
    """Record a review decision for a facility."""
    if body.status not in _ALLOWED_REVIEW_STATUS:
        raise HTTPException(
            400, f"status must be one of {sorted(_ALLOWED_REVIEW_STATUS)}"
        )
    item = FacilityReview(**body.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"review_id": item.id, "status": "saved"}


@router.get("/reviews/{facility_id}")
async def get_reviews(
    facility_id: str,
    session: Dependencies.Session,
    limit: int = Query(default=50, ge=1, le=500),
):
    rows = session.exec(
        select(FacilityReview)
        .where(FacilityReview.facility_id == facility_id)
        .limit(limit)
    ).all()
    return {"reviews": [r.model_dump() for r in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

@router.post("/search-history")
async def log_search(body: LogSearchRequest, session: Dependencies.Session):
    """Persist a search so the planner can resume it later."""
    item = SearchHistoryItem(**body.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"search_id": item.id, "status": "saved"}


@router.get("/search-history/{user_id}")
async def get_search_history(
    user_id: str,
    session: Dependencies.Session,
    limit: int = Query(default=50, ge=1, le=500),
):
    rows = session.exec(
        select(SearchHistoryItem)
        .where(SearchHistoryItem.user_id == user_id)
        .order_by(SearchHistoryItem.created_at.desc())
        .limit(limit)
    ).all()
    return {"items": [r.model_dump() for r in rows], "count": len(rows)}
