"""Capabilities listing API route."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import DatabricksSQLDependency
from ..db.facility_queries import get_capabilities_list

router = APIRouter(tags=["capabilities"])

_cache: list[str] | None = None


@router.get("/capabilities")
async def capabilities(db: DatabricksSQLDependency):
    """Return distinct list of all specialties found in the facilities table."""
    global _cache
    if _cache is None:
        _cache = get_capabilities_list(db)
    return {"capabilities": _cache, "count": len(_cache)}
