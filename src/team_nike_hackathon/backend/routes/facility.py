"""Facility detail API route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import DatabricksSQLDependency
from ..db.facility_queries import get_facility_by_id
from ..scoring.evidence_formatter import format_evidence

router = APIRouter(tags=["facility"])


@router.get("/facility/{facility_id}")
async def facility_detail(facility_id: str, db: DatabricksSQLDependency):
    """Get full facility record with formatted evidence."""
    facility = get_facility_by_id(db, facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail="Facility not found")

    evidence = format_evidence(facility)

    return {
        "facility": facility,
        "evidence": evidence,
    }
