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

    specialty_filter = " OR ".join(specialty_conditions) if specialty_conditions else "TRUE"
    keyword_filter = " OR ".join(keyword_conditions) if keyword_conditions else "FALSE"

    where_parts = [f"(({specialty_filter}) OR ({keyword_filter}))"]

    if state:
        where_parts.append(
            f"LOWER(address_stateOrRegion) LIKE {sql_like(state)}"
        )
    if district:
        where_parts.append(
            f"(LOWER(address_city) LIKE {sql_like(district)} "
            f"OR LOWER(address_stateOrRegion) LIKE {sql_like(district)})"
        )

    where_clause = " AND ".join(where_parts)
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
        distinct_source_count, search_text,
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
    """Get full facility record from gold table (all columns + trust + search_text)."""
    if not facility_id or not facility_id.strip():
        return None
    sql = f"""
    SELECT * FROM {FACILITIES_GOLD}
    WHERE unique_id = {sql_str(facility_id.strip())}
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
