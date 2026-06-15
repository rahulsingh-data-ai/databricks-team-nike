"""Capabilities listing API route — thread-safe TTL cache."""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter

from ..db import DatabricksSQLDependency
from ..db.facility_queries import get_capabilities_list

router = APIRouter(tags=["capabilities"])

_TTL_SECONDS = 600
_lock = threading.Lock()
_cache: dict = {"value": None, "loaded_at": 0.0}


def _get_cached(db) -> list[str]:
    now = time.time()
    with _lock:
        cached = _cache["value"]
        loaded_at = _cache["loaded_at"]
    if cached is not None and (now - loaded_at) < _TTL_SECONDS:
        return cached

    fresh = get_capabilities_list(db)
    with _lock:
        _cache["value"] = fresh
        _cache["loaded_at"] = time.time()
    return fresh


@router.get("/capabilities")
async def capabilities(db: DatabricksSQLDependency):
    """Return distinct list of all specialties found in the facilities table."""
    values = _get_cached(db)
    return {"capabilities": values, "count": len(values)}
