"""Shortlist CRUD API routes using Lakebase."""

from __future__ import annotations

from uuid import uuid4
from datetime import datetime, timezone

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException
from sqlmodel import Field, SQLModel, Session, select

from ..core.dependencies import Dependencies

router = APIRouter(tags=["shortlist"])


# --- SQLModel Tables ---

class ShortlistItem(SQLModel, table=True):
    __tablename__ = "shortlist"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str
    search_query: str | None = None
    facility_id: str
    facility_name: str
    capability: str | None = None
    trust_signal: str | None = None
    distance_km: float | None = None
    notes: str | None = None
    saved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# --- Request/Response Models ---

class SaveRequest(BaseModel):
    user_id: str
    search_query: str | None = None
    facility_id: str
    facility_name: str
    capability: str | None = None
    trust_signal: str | None = None
    distance_km: float | None = None
    notes: str | None = None


class UpdateNotesRequest(BaseModel):
    notes: str


# --- Routes ---

@router.post("/shortlist")
async def save_to_shortlist(body: SaveRequest, session: Dependencies.Session):
    """Save a facility to the user's shortlist."""
    item = ShortlistItem(**body.model_dump())
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"shortlist_id": item.id, "status": "saved"}


@router.get("/shortlist/{user_id}")
async def get_shortlist(user_id: str, session: Dependencies.Session):
    """Get all saved facilities for a user."""
    items = session.exec(
        select(ShortlistItem).where(ShortlistItem.user_id == user_id)
    ).all()
    return {"items": [item.model_dump() for item in items], "count": len(items)}


@router.delete("/shortlist/{shortlist_id}")
async def remove_from_shortlist(shortlist_id: str, session: Dependencies.Session):
    """Remove a facility from the shortlist."""
    item = session.get(ShortlistItem, shortlist_id)
    if not item:
        raise HTTPException(status_code=404, detail="Shortlist item not found")
    session.delete(item)
    session.commit()
    return {"status": "deleted"}


@router.patch("/shortlist/{shortlist_id}/notes")
async def update_notes(shortlist_id: str, body: UpdateNotesRequest, session: Dependencies.Session):
    """Update notes on a shortlist item."""
    item = session.get(ShortlistItem, shortlist_id)
    if not item:
        raise HTTPException(status_code=404, detail="Shortlist item not found")
    item.notes = body.notes
    session.add(item)
    session.commit()
    return {"status": "updated"}
