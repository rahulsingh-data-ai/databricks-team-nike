"""SQL queries for facility search, location resolution, and district health."""

from __future__ import annotations

import json
import math
from typing import Any

from .databricks_sql import DatabricksSQLClient, _fqn, _bronze

# Silver/gold tables (cleaned, pre-computed)
FACILITIES = _fqn("facilities_clean")
PINCODE = _fqn("pincode_deduped")
NFHS = _fqn("nfhs_clean")
CAPABILITY_INDEX = _fqn("capability_index")
TRUST_SCORES = _fqn("facility_trust_scores")
DESERT_SCORES = _fqn("desert_scores")

# Bronze tables (raw, for full evidence detail)
FACILITIES_RAW = _bronze("facilities")

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
    clean = query.strip().replace("'", "''")

    sql = f"""
    SELECT
        district,
        statename,
        AVG(latitude) as avg_lat,
        AVG(longitude) as avg_lon,
        MIN(pincode) as pincode,
        COUNT(*) as match_count
    FROM {PINCODE}
    WHERE LOWER(district) = LOWER('{clean}')
       OR LOWER(divisionname) = LOWER('{clean}')
       OR LOWER(regionname) = LOWER('{clean}')
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
    distance_col = f"{_haversine_sql(lat, lon)} AS distance_km" if lat and lon else "NULL AS distance_km"

    # Build specialty filter: check if any term appears in the specialties JSON array
    specialty_conditions = []
    for term in specialty_terms:
        specialty_conditions.append(f"LOWER(specialties) LIKE '%{term.lower()}%'")

    # Also search in capability and procedure text
    keyword_conditions = []
    for term in specialty_terms:
        keyword_conditions.append(f"LOWER(capability) LIKE '%{term.lower()}%'")
        keyword_conditions.append(f"LOWER(procedure) LIKE '%{term.lower()}%'")

    specialty_filter = " OR ".join(specialty_conditions) if specialty_conditions else "TRUE"
    keyword_filter = " OR ".join(keyword_conditions) if keyword_conditions else "FALSE"

    where_parts = [f"(({specialty_filter}) OR ({keyword_filter}))"]

    if state:
        where_parts.append(f"LOWER(address_stateOrRegion) LIKE LOWER('%{state}%')")
    if district:
        where_parts.append(
            f"(LOWER(address_city) LIKE LOWER('%{district}%') "
            f"OR LOWER(address_stateOrRegion) LIKE LOWER('%{district}%'))"
        )

    where_clause = " AND ".join(where_parts)
    order_by = "distance_km ASC NULLS LAST" if lat and lon else "name ASC"

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
        {distance_col}
    FROM {FACILITIES}
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND {where_clause}
    ORDER BY {order_by}
    LIMIT {limit}
    """
    return db.execute(sql)


def get_facility_by_id(db: DatabricksSQLClient, facility_id: str) -> dict | None:
    """Get full facility record from bronze (raw) table for complete evidence."""
    clean_id = facility_id.strip().replace("'", "''")
    sql = f"""
    SELECT * FROM {FACILITIES_RAW}
    WHERE unique_id = '{clean_id}'
    """
    rows = db.execute(sql)
    return rows[0] if rows else None


def get_district_health(db: DatabricksSQLClient, district_name: str) -> dict | None:
    """Get NFHS-5 health indicators from the cleaned table."""
    clean = district_name.strip().replace("'", "''").lower()
    sql = f"""
    SELECT * FROM {NFHS}
    WHERE district_name = '{clean}'
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
