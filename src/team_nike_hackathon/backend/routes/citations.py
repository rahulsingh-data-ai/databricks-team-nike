"""Citation API route.

Returns explicit claim -> source mappings for a facility so UI can
display "this claim is backed by these sources".
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db import DatabricksSQLDependency
from ..db.facility_queries import get_facility_by_id
from ..scoring.citations import build_citations

router = APIRouter(tags=["citations"])


@router.get("/citations/{facility_id}")
async def facility_citations(
    facility_id: str,
    db: DatabricksSQLDependency,
    capability: str | None = Query(default=None, max_length=120),
):
    """Get every evidence claim for a facility with linked source URLs.

    Pass ``capability`` (e.g. ``dialysis``) to flag which claims match
    the searched capability — the UI can highlight those.
    """
    facility = get_facility_by_id(db, facility_id)
    if not facility:
        raise HTTPException(404, "Facility not found")

    search_terms = [capability] if capability else []
    return build_citations(facility, search_terms)
