"""Main search pipeline: parse -> search -> score -> rank."""

from __future__ import annotations

from typing import Any

from ..db.databricks_sql import DatabricksSQLClient
from ..db.facility_queries import (
    search_facilities,
    get_district_health,
)
from ..scoring.trust_scorer import score_facility, TrustSignal
from ..scoring.evidence_formatter import format_evidence
from .query_parser import parse_query


def run_search(db: DatabricksSQLClient, raw_query: str, limit: int = 20) -> dict[str, Any]:
    """Execute the full referral search pipeline.

    Steps:
        1. Parse query into capability + location
        2. Search facilities by specialty + location
        3. Score each facility's trust level
        4. Rank by trust signal (primary) then distance (secondary)
        5. Enrich with district health context

    Returns complete result payload for the API response.
    """
    # Step 1: Parse
    parsed = parse_query(db, raw_query)

    # Step 2: Search
    location = parsed.get("location")
    candidates = search_facilities(
        db,
        specialty_terms=parsed["specialty_terms"],
        lat=location["latitude"] if location else None,
        lon=location["longitude"] if location else None,
        state=location["state"] if location else None,
        district=location["district"] if location else None,
        limit=limit,
    )

    # Step 3: Score each facility
    scored = []
    for facility in candidates:
        trust = score_facility(facility, parsed["specialty_terms"])
        evidence = format_evidence(facility)

        scored.append({
            "unique_id": facility["unique_id"],
            "name": facility["name"],
            "facility_type": facility.get("facilityTypeId"),
            "address": {
                "city": facility.get("address_city"),
                "state": facility.get("address_stateOrRegion"),
                "pincode": facility.get("address_zipOrPostcode"),
            },
            "latitude": facility.get("latitude"),
            "longitude": facility.get("longitude"),
            "distance_km": round(facility.get("distance_km") or 0, 1) if facility.get("distance_km") else None,
            "trust_signal": trust["trust_signal"],
            "trust_rank": trust["trust_rank"],
            "evidence_summary": trust["evidence_summary"],
            "missing_evidence": trust["missing_evidence"],
            "source_count": trust["source_count"],
            "evidence": evidence,
        })

    # Step 4: Rank by trust (descending) then distance (ascending)
    scored.sort(key=lambda f: (
        -f["trust_rank"],
        f["distance_km"] if f["distance_km"] is not None else 99999,
    ))

    # Step 5: District health context
    district_health = None
    if location and location.get("district"):
        district_health = get_district_health(db, location["district"])

    # Build recommendation summary
    total = len(scored)
    strong = sum(1 for f in scored if f["trust_signal"] == TrustSignal.STRONG.value)
    partial = sum(1 for f in scored if f["trust_signal"] == TrustSignal.PARTIAL.value)
    weak = sum(1 for f in scored if f["trust_signal"] in (TrustSignal.WEAK.value, TrustSignal.SUSPICIOUS.value, TrustSignal.NONE.value))

    loc_str = parsed.get("location_text") or "the searched area"
    cap_str = parsed.get("capability_text") or raw_query

    summary = (
        f"Found {total} facilities for '{cap_str}' near {loc_str}. "
        f"{strong} with strong evidence, {partial} with partial evidence, "
        f"{weak} with weak or no evidence."
    )

    if district_health:
        inst_birth = district_health.get("institutional_birth_5y_pct")
        insurance = district_health.get("hh_member_covered_health_insurance_pct")
        if inst_birth is not None:
            summary += f" District institutional delivery rate: {inst_birth}%."
        if insurance is not None:
            summary += f" Health insurance coverage: {insurance}%."

    return {
        "query": parsed,
        "recommendation_summary": summary,
        "result_count": total,
        "facilities": scored,
        "district_health": _format_district_health(district_health),
    }


def _format_district_health(data: dict | None) -> dict | None:
    if not data:
        return None
    return {
        "district": data.get("district_name"),
        "state": data.get("state_ut"),
        "households_surveyed": data.get("households_surveyed"),
        "institutional_birth_pct": data.get("institutional_birth_5y_pct"),
        "health_insurance_pct": data.get("hh_member_covered_health_insurance_pct"),
        "child_stunting_pct": data.get("child_u5_who_are_stunted_height_for_age_18_pct"),
        "women_anaemic_pct": data.get("all_w15_49_who_are_anaemic_pct"),
        "clean_fuel_pct": data.get("households_using_clean_fuel_for_cooking_pct"),
        "improved_sanitation_pct": data.get("hh_use_improved_sanitation_pct"),
    }
