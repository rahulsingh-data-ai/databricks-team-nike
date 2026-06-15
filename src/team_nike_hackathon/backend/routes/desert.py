"""Healthcare Desert Radar API route."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import DatabricksSQLDependency
from ..db.facility_queries import get_desert_scores

router = APIRouter(tags=["desert-radar"])


@router.get("/desert-radar")
async def desert_radar(
    db: DatabricksSQLDependency,
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get healthcare desert scores by district.

    Returns districts scored by: health_risk / (trusted_facility_count + 1).
    Higher score = worse desert (high need, low trusted coverage).
    """
    scores = get_desert_scores(db, limit=limit)
    return {
        "districts": scores,
        "count": len(scores),
        "description": "Healthcare Desert Zones: High need, low trusted facility coverage",
    }
