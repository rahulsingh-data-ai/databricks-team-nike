"""Format evidence details for display in the UI."""

from __future__ import annotations

import json
from typing import Any


def _safe_parse_json(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [value] if value else []


def format_evidence(facility: dict[str, Any]) -> dict[str, Any]:
    """Format a facility's raw evidence fields into display-ready structure."""
    specialties = _safe_parse_json(facility.get("specialties"))
    capabilities = _safe_parse_json(facility.get("capability"))
    procedures = _safe_parse_json(facility.get("procedure"))
    equipment_list = _safe_parse_json(facility.get("equipment"))
    sources = _safe_parse_json(facility.get("source_types"))
    source_urls = _safe_parse_json(facility.get("source_urls"))

    # Truncate long lists for readability
    max_display = 10

    attributes = {
        "accepts_pmjay": bool(facility.get("mentions_pmjay")),
        "accepts_cghs": bool(facility.get("mentions_cghs")),
        "accepts_esi": bool(facility.get("mentions_esi")),
        "nabh_accredited": bool(facility.get("mentions_nabh")),
        "jci_accredited": bool(facility.get("mentions_jci")),
        "iso_certified": bool(facility.get("mentions_iso")),
        "is_24x7": bool(facility.get("is_24x7")),
        "has_ambulance": bool(facility.get("has_ambulance")),
        "has_telemedicine": bool(facility.get("has_telemedicine")),
        "has_blood_bank": bool(facility.get("has_blood_bank")),
        "has_icu": bool(facility.get("mentions_icu")),
        "has_nicu": bool(facility.get("mentions_nicu")),
        "has_emergency": bool(facility.get("mentions_emergency")),
        "is_government": bool(facility.get("is_government_mentioned")),
        "is_private": bool(facility.get("is_private_mentioned")),
        "is_nonprofit": bool(facility.get("is_nonprofit_mentioned")),
        "offers_charity_care": bool(facility.get("offers_charity_care")),
        "is_ngo_source": bool(facility.get("is_ngo_source")),
        "languages": [
            lang for lang, flag in [
                ("Hindi", facility.get("lang_hindi")),
                ("Tamil", facility.get("lang_tamil")),
                ("Telugu", facility.get("lang_telugu")),
                ("Bengali", facility.get("lang_bengali")),
                ("Marathi", facility.get("lang_marathi")),
                ("Gujarati", facility.get("lang_gujarati")),
                ("Kannada", facility.get("lang_kannada")),
                ("Malayalam", facility.get("lang_malayalam")),
            ] if bool(flag)
        ],
    }

    return {
        "specialties": specialties[:max_display],
        "specialties_count": len(specialties),
        "capabilities": capabilities[:max_display],
        "capabilities_count": len(capabilities),
        "procedures": procedures[:max_display],
        "procedures_count": len(procedures),
        "equipment": equipment_list[:max_display],
        "equipment_count": len(equipment_list),
        "source_types": sorted({s for s in sources if s}),
        "source_urls": source_urls[:5],
        "description": (facility.get("description") or "")[:500],
        "attributes": attributes,
        "metadata": {
            "facility_type": facility.get("facilityTypeId"),
            "organization_type": facility.get("organization_type"),
            "capacity": facility.get("capacity"),
            "number_doctors": facility.get("numberDoctors"),
            "year_established": facility.get("yearEstablished"),
            "recency_of_update": facility.get("recency_of_page_update"),
            "social_media_count": facility.get("distinct_social_media_presence_count"),
            "has_staff_presence": facility.get("affiliated_staff_presence"),
            "has_custom_logo": facility.get("custom_logo_presence"),
            "facts_count": facility.get("number_of_facts_about_the_organization"),
        },
    }
