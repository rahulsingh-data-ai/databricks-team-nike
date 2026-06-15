"""Rule-based trust scoring for facility evidence.

Classification rules:
- strong_evidence: multiple independent sources + capability match + recency signal
- partial_evidence: single source or indirect mention
- weak_evidence: only free-text mention, no structured source
- suspicious: conflicting info (e.g. claims ICU but is a clinic)
- no_evidence: searched capability not found anywhere
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any


class TrustSignal(str, Enum):
    STRONG = "strong_evidence"
    PARTIAL = "partial_evidence"
    WEAK = "weak_evidence"
    SUSPICIOUS = "suspicious"
    NONE = "no_evidence"

    @property
    def rank(self) -> int:
        return {
            TrustSignal.STRONG: 5,
            TrustSignal.PARTIAL: 4,
            TrustSignal.WEAK: 3,
            TrustSignal.SUSPICIOUS: 2,
            TrustSignal.NONE: 1,
        }[self]


def _parse_json_array(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).lower() for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [value.lower()] if value else []


def _count_sources(source_types: str | None) -> int:
    sources = _parse_json_array(source_types)
    return len(set(sources))


def _capability_in_specialties(search_terms: list[str], specialties: str | None) -> bool:
    spec_list = _parse_json_array(specialties)
    for term in search_terms:
        if any(term.lower() in s for s in spec_list):
            return True
    return False


def _capability_in_freetext(search_terms: list[str], *text_fields: str | None) -> bool:
    for field in text_fields:
        if not field:
            continue
        field_lower = field.lower()
        for term in search_terms:
            if term.lower() in field_lower:
                return True
    return False


def _has_conflicting_signals(facility: dict, search_terms: list[str]) -> bool:
    """Detect suspicious patterns like a clinic claiming ICU capability."""
    facility_type = (facility.get("facilityTypeId") or "").lower()
    high_capability_terms = {"icu", "nicu", "transplant", "neurosurgery", "cardiac surgery"}

    for term in search_terms:
        if term.lower() in high_capability_terms and facility_type in ("clinic", "dentist"):
            return True
    return False


def score_facility(
    facility: dict[str, Any],
    search_terms: list[str],
) -> dict[str, Any]:
    """Score a single facility's trust level for the searched capability.

    Returns dict with:
        trust_signal: TrustSignal enum value
        evidence_summary: human-readable explanation
        missing_evidence: list of what's unknown
    """
    specialties = facility.get("specialties")
    capability = facility.get("capability")
    procedure = facility.get("procedure")
    equipment = facility.get("equipment")
    description = facility.get("description")
    source_types = facility.get("source_types")
    source_urls = facility.get("source_urls")
    recency = facility.get("recency_of_page_update")
    social_count = facility.get("distinct_social_media_presence_count")
    staff_presence = facility.get("affiliated_staff_presence")
    logo = facility.get("custom_logo_presence")
    facts_count = facility.get("number_of_facts_about_the_organization")

    num_sources = _count_sources(source_types)
    in_specialties = _capability_in_specialties(search_terms, specialties)
    in_freetext = _capability_in_freetext(search_terms, capability, procedure, equipment, description)
    is_conflicting = _has_conflicting_signals(facility, search_terms)

    # Build missing evidence list
    missing = []
    if not facility.get("capacity"):
        missing.append("No bed capacity data")
    if not facility.get("yearEstablished"):
        missing.append("No establishment year")
    if not facility.get("numberDoctors"):
        missing.append("No doctor count")
    if not recency:
        missing.append("No recent verification timestamp")
    if num_sources <= 1:
        missing.append("No secondary source confirmation")
    if not facility.get("phone_numbers") and not facility.get("officialPhone"):
        missing.append("No contact phone number")
    if not source_urls:
        missing.append("No source URLs for verification")

    # Classification logic
    if is_conflicting:
        signal = TrustSignal.SUSPICIOUS
        summary = _build_suspicious_summary(facility, search_terms)
    elif in_specialties and num_sources >= 2:
        signal = TrustSignal.STRONG
        summary = _build_strong_summary(facility, search_terms, num_sources)
    elif in_specialties and num_sources == 1:
        signal = TrustSignal.PARTIAL
        summary = _build_partial_summary(facility, search_terms, "structured")
    elif in_freetext and num_sources >= 1:
        signal = TrustSignal.PARTIAL
        summary = _build_partial_summary(facility, search_terms, "freetext")
    elif in_freetext:
        signal = TrustSignal.WEAK
        summary = _build_weak_summary(facility, search_terms)
    else:
        signal = TrustSignal.NONE
        summary = _build_none_summary(search_terms)

    return {
        "trust_signal": signal.value,
        "trust_rank": signal.rank,
        "evidence_summary": summary,
        "missing_evidence": missing,
        "source_count": num_sources,
        "in_specialties": in_specialties,
        "in_freetext": in_freetext,
    }


def _build_strong_summary(facility: dict, terms: list[str], source_count: int) -> str:
    name = facility.get("name", "This facility")
    sources = _parse_json_array(facility.get("source_types"))
    source_list = ", ".join(set(sources)[:3]) if sources else "multiple sources"
    return (
        f"Confirmed by {source_count} independent sources ({source_list}). "
        f"Capability appears in structured specialties data."
    )


def _build_partial_summary(facility: dict, terms: list[str], match_type: str) -> str:
    if match_type == "structured":
        return "Listed in specialties but only one source confirms this capability."
    return "Mentioned in facility description but not in structured specialties. Single source."


def _build_weak_summary(facility: dict, terms: list[str]) -> str:
    return "Only mentioned in unstructured text with no verified source data."


def _build_suspicious_summary(facility: dict, terms: list[str]) -> str:
    ftype = facility.get("facilityTypeId", "unknown")
    return (
        f"Conflicting information: facility type is '{ftype}' but claims "
        f"advanced capabilities. Verify before referring."
    )


def _build_none_summary(terms: list[str]) -> str:
    term_str = ", ".join(terms[:3])
    return f"No evidence found for '{term_str}' in any facility data field."
