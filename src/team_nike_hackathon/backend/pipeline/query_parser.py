"""Parse natural language search queries into structured components.

Uses keyword/regex extraction first. LLM upgrade can be added later.
"""

from __future__ import annotations

import re
from typing import Any

from ..db.facility_queries import map_query_to_specialties, resolve_location, DatabricksSQLClient

# Common location prepositions to split on
LOCATION_PREPOSITIONS = ["near", "in", "around", "close to", "nearby", "at"]


def parse_query(db: DatabricksSQLClient, raw_query: str) -> dict[str, Any]:
    """Parse a raw query like 'dialysis near Jaipur' into structured fields.

    Returns:
        {
            "raw_query": original text,
            "capability_text": "dialysis",
            "location_text": "Jaipur",
            "specialty_terms": ["nephrology", "internalMedicine"],
            "location": { "district": ..., "state": ..., "latitude": ..., "longitude": ..., "pincode": ... } | None
        }
    """
    query = raw_query.strip()
    capability_text = query
    location_text = ""

    # Try to split on location prepositions
    for prep in LOCATION_PREPOSITIONS:
        pattern = rf"\b{prep}\b"
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            capability_text = query[:match.start()].strip()
            location_text = query[match.end():].strip()
            break

    # Check if it's a pincode (6 digits)
    pincode_match = re.search(r"\b(\d{6})\b", location_text or query)

    specialty_terms = map_query_to_specialties(capability_text)

    # Resolve location
    location = None
    if pincode_match:
        location = resolve_location(db, pincode_match.group(1))
    elif location_text:
        location = resolve_location(db, location_text)

    return {
        "raw_query": raw_query,
        "capability_text": capability_text or raw_query,
        "location_text": location_text,
        "specialty_terms": specialty_terms,
        "location": location,
    }
