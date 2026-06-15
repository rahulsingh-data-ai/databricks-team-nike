"""Compare mode: side-by-side facility comparison with evidence diff."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import DatabricksSQLDependency
from ..db.facility_queries import get_facility_by_id
from ..scoring.evidence_formatter import format_evidence
from ..scoring.trust_scorer import score_facility

router = APIRouter(tags=["compare"])


@router.get("/compare")
async def compare_facilities(
    db: DatabricksSQLDependency,
    facility_a: str,
    facility_b: str,
    capability: str | None = None,
):
    """Compare two facilities side-by-side with evidence diff.

    Returns both facilities with trust scores, evidence breakdown,
    and a diff highlighting what each has that the other doesn't.
    """
    a = get_facility_by_id(db, facility_a)
    b = get_facility_by_id(db, facility_b)

    if not a:
        raise HTTPException(404, f"Facility {facility_a} not found")
    if not b:
        raise HTTPException(404, f"Facility {facility_b} not found")

    search_terms = [capability] if capability else []

    score_a = score_facility(a, search_terms)
    score_b = score_facility(b, search_terms)
    evidence_a = format_evidence(a)
    evidence_b = format_evidence(b)

    # Build diff
    specs_a = set(evidence_a.get("specialties", []))
    specs_b = set(evidence_b.get("specialties", []))

    diff = {
        "specialties_only_in_a": sorted(specs_a - specs_b),
        "specialties_only_in_b": sorted(specs_b - specs_a),
        "specialties_shared": sorted(specs_a & specs_b),
        "trust_comparison": {
            "a": score_a["trust_signal"],
            "b": score_b["trust_signal"],
            "better": "a" if score_a["trust_rank"] > score_b["trust_rank"]
                      else "b" if score_b["trust_rank"] > score_a["trust_rank"]
                      else "equal",
        },
        "missing_data_comparison": {
            "a_missing": score_a["missing_evidence"],
            "b_missing": score_b["missing_evidence"],
            "a_missing_count": len(score_a["missing_evidence"]),
            "b_missing_count": len(score_b["missing_evidence"]),
        },
        "source_comparison": {
            "a_sources": score_a["source_count"],
            "b_sources": score_b["source_count"],
        },
    }

    return {
        "facility_a": {
            "id": facility_a,
            "name": a.get("name"),
            "type": a.get("facilityTypeId"),
            "city": a.get("address_city"),
            "state": a.get("address_stateOrRegion"),
            "trust": score_a,
            "evidence": evidence_a,
        },
        "facility_b": {
            "id": facility_b,
            "name": b.get("name"),
            "type": b.get("facilityTypeId"),
            "city": b.get("address_city"),
            "state": b.get("address_stateOrRegion"),
            "trust": score_b,
            "evidence": evidence_b,
        },
        "diff": diff,
    }
