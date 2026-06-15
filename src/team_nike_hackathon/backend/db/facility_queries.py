"""SQL queries for facility search, location resolution, and district health."""

from __future__ import annotations

import json
import math
from typing import Any

from .databricks_sql import DatabricksSQLClient, _fqn, _bronze, sql_str, sql_like

# Gold table (single source of truth — all columns + trust + search_text)
FACILITIES_GOLD = _fqn("facilities_gold")

# Supporting tables
PINCODE = _fqn("pincode_deduped")
NFHS = _fqn("nfhs_clean")
CAPABILITY_INDEX = _fqn("capability_index")
DESERT_SCORES = _fqn("desert_scores")

# Known specialties enum values for mapping natural language to DB values
SPECIALTY_KEYWORDS: dict[str, list[str]] = {
    "dialysis": ["nephrology", "internalMedicine"],
    "emergency": ["emergencyMedicine", "criticalCareMedicine", "emergencyPreparednessAndDisasterResponse"],
    "surgery": ["generalSurgery", "orthopedicSurgery", "neurosurgery", "pediatricSurgery"],
    "maternity": ["gynecologyAndObstetrics", "neonatologyPerinatalMedicine", "maternalFetalMedicine"],
    "cardiac": ["cardiology", "cardiovascularSurgery", "interventionalCardiology"],
    "cancer": ["oncology", "gynecologicalOncology", "radiationOncology", "surgicalOncology"],
    "pediatric": ["pediatrics", "pediatricSurgery", "pediatricEmergencyMedicine"],
    "orthopedic": ["orthopedicSurgery", "pediatricOrthopedicSurgery", "shoulderAndElbowOrthopedicSurgery"],
    "neurology": ["neurology", "neurosurgery"],
    "eye": ["ophthalmology"],
    "dental": ["dentistry"],
    "icu": ["criticalCareMedicine", "pulmonology"],
    "nicu": ["neonatologyPerinatalMedicine", "pediatrics"],
    "trauma": ["emergencyMedicine", "burnAndTraumaPlasticSurgery", "orthopedicSurgery"],
    "skin": ["dermatology"],
    "mental": ["psychiatry"],
    "ent": ["otolaryngology"],
    "urology": ["urology"],
    "physiotherapy": ["physicalMedicineAndRehabilitation"],
}


def _haversine_sql(lat: float, lon: float) -> str:
    """SQL expression for haversine distance in km from a fixed point."""
    return f"""
    (6371 * acos(
        LEAST(1.0, GREATEST(-1.0,
            cos(radians({lat})) * cos(radians(latitude))
            * cos(radians(longitude) - radians({lon}))
            + sin(radians({lat})) * sin(radians(latitude))
        ))
    ))"""


def resolve_location(db: DatabricksSQLClient, query: str) -> dict[str, Any] | None:
    """Resolve a location name to pincode, district, state, lat/lon.

    Uses the deduped pincode table (already has avg lat/lon per pincode).
    """
    if not query or not query.strip():
        return None
    needle = sql_str(query.strip().lower())

    sql = f"""
    SELECT
        district,
        statename,
        AVG(latitude) as avg_lat,
        AVG(longitude) as avg_lon,
        MIN(pincode) as pincode,
        COUNT(*) as match_count
    FROM {PINCODE}
    WHERE LOWER(district) = {needle}
       OR LOWER(divisionname) = {needle}
       OR LOWER(regionname) = {needle}
    GROUP BY district, statename
    ORDER BY match_count DESC
    LIMIT 1
    """
    rows = db.execute(sql)
    if not rows:
        return None
    r = rows[0]
    if r["avg_lat"] is None or r["avg_lon"] is None:
        return None
    return {
        "district": r["district"],
        "state": r["statename"],
        "latitude": float(r["avg_lat"]),
        "longitude": float(r["avg_lon"]),
        "pincode": r["pincode"],
    }


def search_facilities(
    db: DatabricksSQLClient,
    specialty_terms: list[str],
    lat: float | None = None,
    lon: float | None = None,
    state: str | None = None,
    district: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search facilities by specialty terms with optional geo filtering.

    Matches against the specialties JSON array column.
    Returns results sorted by distance if lat/lon provided.
    """
    limit = max(1, min(int(limit or 20), 200))
    use_geo = lat is not None and lon is not None
    distance_col = (
        f"{_haversine_sql(float(lat), float(lon))} AS distance_km"
        if use_geo else "NULL AS distance_km"
    )

    specialty_conditions: list[str] = []
    keyword_conditions: list[str] = []
    for term in specialty_terms or []:
        if not term or not str(term).strip():
            continue
        pattern = sql_like(term)
        specialty_conditions.append(f"LOWER(specialties) LIKE {pattern}")
        keyword_conditions.append(f"LOWER(capability) LIKE {pattern}")
        keyword_conditions.append(f"LOWER(procedure) LIKE {pattern}")

    has_terms = bool(specialty_conditions)
    specialty_filter = " OR ".join(specialty_conditions) if specialty_conditions else "TRUE"
    keyword_filter = " OR ".join(keyword_conditions) if keyword_conditions else "FALSE"

    where_parts: list[str] = []
    if has_terms:
        where_parts.append(f"(({specialty_filter}) OR ({keyword_filter}))")
    # When no specialty terms are provided we still need geo or admin filters;
    # otherwise return only facilities with coordinates so the result is meaningful.
    if not has_terms and not use_geo and not state and not district:
        return []

    if state:
        where_parts.append(
            f"LOWER(address_stateOrRegion) LIKE {sql_like(state)}"
        )
    if district:
        where_parts.append(
            f"(LOWER(address_city) LIKE {sql_like(district)} "
            f"OR LOWER(address_stateOrRegion) LIKE {sql_like(district)})"
        )

    where_clause = " AND ".join(where_parts) if where_parts else "TRUE"
    order_by = "distance_km ASC NULLS LAST" if use_geo else "name ASC"

    sql = f"""
    SELECT
        unique_id, name, facilityTypeId, organization_type,
        address_line1, address_city, address_stateOrRegion, address_zipOrPostcode,
        latitude, longitude,
        specialties, capability, procedure, equipment,
        source_types, source_ids, source_urls, source_content_id,
        description, capacity, numberDoctors, yearEstablished,
        recency_of_page_update, distinct_social_media_presence_count,
        affiliated_staff_presence, custom_logo_presence,
        number_of_facts_about_the_organization,
        base_trust_signal, trust_rank, missing_data_count,
        has_doctors, has_capacity, has_year_established,
        distinct_source_count,
        mentions_pmjay, mentions_cghs, mentions_esi,
        mentions_nabh, mentions_jci, mentions_iso,
        is_24x7, has_ambulance, has_telemedicine, has_blood_bank,
        mentions_icu, mentions_nicu, mentions_emergency,
        is_government_mentioned, is_private_mentioned, is_nonprofit_mentioned,
        offers_charity_care, is_ngo_source,
        lang_hindi, lang_tamil, lang_telugu, lang_bengali,
        lang_marathi, lang_gujarati, lang_kannada, lang_malayalam,
        search_text,
        {distance_col}
    FROM {FACILITIES_GOLD}
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND {where_clause}
    ORDER BY {order_by}
    LIMIT {limit}
    """
    return db.execute(sql)


def get_facility_by_id(db: DatabricksSQLClient, facility_id: str) -> dict | None:
    """Get full facility record from gold table (all columns + trust + search_text).

    Defensively drops rows where the upstream pipeline misaligned columns
    (no name / no coordinates) so the detail endpoint never returns a junk
    record.
    """
    if not facility_id or not facility_id.strip():
        return None
    sql = f"""
    SELECT * FROM {FACILITIES_GOLD}
    WHERE unique_id = {sql_str(facility_id.strip())}
      AND name IS NOT NULL
      AND latitude IS NOT NULL
    """
    rows = db.execute(sql)
    return rows[0] if rows else None


def get_district_health(db: DatabricksSQLClient, district_name: str) -> dict | None:
    """Get NFHS-5 health indicators from the cleaned table."""
    if not district_name or not district_name.strip():
        return None
    sql = f"""
    SELECT * FROM {NFHS}
    WHERE district_name = {sql_str(district_name.strip().lower())}
    LIMIT 1
    """
    rows = db.execute(sql)
    return rows[0] if rows else None


# Per-capability NFHS-5 indicator selection.
# Picks the columns most relevant for the searched care need.
_CAPABILITY_INDICATORS: dict[str, list[str]] = {
    "maternity": [
        "institutional_birth_5y_pct",
        "institutional_birth_in_public_facility_5y_pct",
    ],
    "pediatric": [
        "prev_diarrhoea_2wk_child_u5_pct",
        "children_prev_symptoms_of_acute_respiratory_infection_ari_2_pct",
    ],
    "cardiac": [
        "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
        "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
    ],
    "diabetes": [
        "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
        "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
    ],
    "dialysis": [
        "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
        "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
    ],
    "cancer": [
        "women_age_30_49_years_ever_undergone_a_cervical_screen_pct",
        "women_age_30_49_years_ever_undergone_a_breast_exam_pct",
    ],
    "anaemia": [
        "all_w15_49_who_are_anaemic_pct",
        "non_pregnant_w15_49_who_are_anaemic_lt_12_0_g_dl_22_pct",
    ],
}

_BASELINE_INDICATORS = [
    "institutional_birth_5y_pct",
    "hh_member_covered_health_insurance_pct",
    "all_w15_49_who_are_anaemic_pct",
    "households_using_clean_fuel_for_cooking_pct",
    "hh_use_improved_sanitation_pct",
]


def pick_district_indicators(
    district_row: dict | None,
    capability_terms: list[str] | None,
) -> dict[str, Any]:
    """Pick the most relevant NFHS-5 indicators for the searched capability.

    Returns a flat dict of {indicator_name: value} plus the baseline metrics
    we always show (district + state name + sample size).
    """
    if not district_row:
        return {}

    out: dict[str, Any] = {
        "district": district_row.get("district_name"),
        "state": district_row.get("state_ut"),
        "households_surveyed": district_row.get("households_surveyed"),
    }

    selected: list[str] = list(_BASELINE_INDICATORS)
    for term in capability_terms or []:
        key = term.lower()
        for trigger, cols in _CAPABILITY_INDICATORS.items():
            if trigger in key:
                selected.extend(cols)

    for col in dict.fromkeys(selected):
        if col in district_row:
            out[col] = district_row[col]
    return out


def get_capabilities_list(db: DatabricksSQLClient) -> list[str]:
    """Get distinct specialty values from the pre-exploded capability index."""
    sql = f"""
    SELECT DISTINCT specialty
    FROM {CAPABILITY_INDEX}
    ORDER BY specialty
    """
    rows = db.execute(sql)
    return [r["specialty"] for r in rows]


def get_desert_scores(db: DatabricksSQLClient, limit: int = 100) -> list[dict]:
    """Get pre-computed healthcare desert scores from gold table."""
    limit = max(1, min(int(limit or 100), 500))
    sql = f"""
    SELECT * FROM {DESERT_SCORES}
    ORDER BY desert_score DESC
    LIMIT {limit}
    """
    return db.execute(sql)


def map_query_to_specialties(query: str) -> list[str]:
    """Map natural language query terms to specialties enum values."""
    query_lower = query.lower()
    matched = []
    for keyword, specialties in SPECIALTY_KEYWORDS.items():
        if keyword in query_lower:
            matched.extend(specialties)

    # Deduplicate while preserving order
    seen = set()
    result = []
    for s in matched:
        if s not in seen:
            seen.add(s)
            result.append(s)

    # If no keyword match, use the raw query words as specialty search terms
    if not result:
        words = [w.strip() for w in query_lower.split() if len(w.strip()) > 3]
        result = words

    return result
