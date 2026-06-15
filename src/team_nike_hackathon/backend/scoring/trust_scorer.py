"""Rule-based trust scoring for facility evidence.

The original referral-copilot scorer assumed a flat Databricks SQL row
with ~30 boolean columns (``mentions_pmjay``, ``lang_hindi``, etc.). Our
schema instead keeps everything in JSONB:

* ``specialties: list[str]``
* ``services: list[str]``
* ``procedures: list[str]``
* ``equipment: list[str]``
* ``raw_description: str`` (the messy LLM-extracted blob)
* ``confidence: dict[str, float]``

So we infer the high-signal flags (PM-JAY accepted, NABH-accredited, etc.)
by keyword-scanning the free-text fields and combine that with the
per-field confidence dict the ETL produced.

Classification:

* ``strong_evidence`` — capability appears in structured ``specialties``,
  multiple source signals (confidence keys), and at least one quality
  boost (NABH / govt / charity / etc).
* ``partial_evidence`` — capability in ``specialties`` but only one
  signal, or capability only in ``services``/``procedures``.
* ``weak_evidence`` — capability only in ``raw_description``.
* ``suspicious`` — facility ``type`` is ``clinic``/``pharmacy`` but the
  capability requires ICU/NICU/surgery.
* ``no_evidence`` — capability not found anywhere.
"""

from __future__ import annotations

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


# Keyword scans of the ``raw_description`` blob. We only set a flag if the
# substring actually appears — these are conservative signals, not
# guesses.
_KEYWORD_FLAGS: dict[str, tuple[str, ...]] = {
    "accepts_pmjay": ("pmjay", "pm-jay", "ayushman bharat", "ab-pmjay"),
    "accepts_cghs": ("cghs",),
    "accepts_esi": ("esi", "esic"),
    "nabh_accredited": ("nabh", "national accreditation board for hospitals"),
    "jci_accredited": ("jci", "joint commission international"),
    "is_24x7": ("24x7", "24/7", "24-hour", "round the clock"),
    "has_ambulance": ("ambulance",),
    "has_telemedicine": ("telemedicine", "teleconsultation"),
    "has_blood_bank": ("blood bank", "blood-bank"),
    "has_icu": ("icu", "intensive care"),
    "has_nicu": ("nicu", "neonatal intensive"),
    "has_emergency": ("emergency room", "casualty", "trauma center"),
    "is_government": ("government", "govt hospital", "public hospital"),
    "is_private": ("private hospital", "private clinic"),
    "is_nonprofit": ("nonprofit", "non-profit", "trust hospital", "charitable"),
    "offers_charity_care": ("free treatment", "charity", "subsidised", "subsidized"),
}

_LANGUAGE_FLAGS: dict[str, str] = {
    "lang_hindi": "Hindi",
    "lang_tamil": "Tamil",
    "lang_telugu": "Telugu",
    "lang_bengali": "Bengali",
    "lang_marathi": "Marathi",
    "lang_gujarati": "Gujarati",
    "lang_kannada": "Kannada",
    "lang_malayalam": "Malayalam",
}

# Capabilities that imply a high-acuity facility — if the user is asking
# for these and the facility is a clinic/pharmacy/dentist, we flag it as
# suspicious.
_HIGH_ACUITY_TERMS = {
    "icu",
    "nicu",
    "transplant",
    "neurosurgery",
    "cardiac surgery",
    "trauma",
    "burn unit",
    "dialysis",
}

_LOW_ACUITY_TYPES = {"clinic", "dentist", "pharmacy"}


def _as_lower_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).lower() for v in value if v is not None]
    if isinstance(value, str):
        return [value.lower()]
    return []


def attribute_flags(facility: dict[str, Any]) -> dict[str, Any]:
    """Infer the boolean / language attributes from our facility shape.

    Returns a flat dict compatible with the original referral-copilot
    scorer expectations, so the LLM prompts can be re-used unchanged.
    """
    blob_parts: list[str] = []
    for field in ("raw_description", "name"):
        v = facility.get(field)
        if isinstance(v, str):
            blob_parts.append(v)
    for field in ("specialties", "services", "procedures", "equipment"):
        v = facility.get(field)
        if isinstance(v, list):
            blob_parts.extend(str(x) for x in v if x is not None)
    blob = " ".join(blob_parts).lower()

    flags: dict[str, Any] = {}
    for key, needles in _KEYWORD_FLAGS.items():
        flags[key] = any(n in blob for n in needles)
    for key, lang_name in _LANGUAGE_FLAGS.items():
        flags[key] = lang_name.lower() in blob
    flags["languages"] = [
        _LANGUAGE_FLAGS[k] for k, present in flags.items()
        if k in _LANGUAGE_FLAGS and present
    ]
    return flags


def _capability_in_list(search_terms: list[str], items: list[str]) -> bool:
    if not search_terms or not items:
        return False
    lower = [s.lower() for s in items]
    for term in search_terms:
        t = term.lower()
        if any(t in item or item in t for item in lower):
            return True
    return False


def _capability_in_text(search_terms: list[str], *texts: str | None) -> bool:
    if not search_terms:
        return False
    blob = " ".join((t or "").lower() for t in texts)
    return any(term.lower() in blob for term in search_terms)


def _is_suspicious(facility: dict, search_terms: list[str]) -> bool:
    ftype = (facility.get("type") or "").lower()
    if ftype not in _LOW_ACUITY_TYPES:
        return False
    for term in search_terms:
        if term.lower() in _HIGH_ACUITY_TERMS:
            return True
    return False


def _quality_boosts(facility: dict[str, Any]) -> tuple[int, list[str]]:
    """Independent quality signals (not based on the facility's own claims).

    For MatchCare-style data we lean on the ETL's per-field
    ``confidence`` dict + presence of structured fields. More distinct
    confidence keys + higher average → more independent corroboration.
    """
    boost = 0
    reasons: list[str] = []

    confidence = facility.get("confidence") or {}
    if isinstance(confidence, dict) and confidence:
        keys = [k for k, v in confidence.items() if isinstance(v, (int, float))]
        avg = (
            sum(float(confidence[k]) for k in keys) / len(keys)
            if keys
            else 0.0
        )
        if len(keys) >= 4:
            boost += 1
            reasons.append(f"{len(keys)} fields corroborated")
        if avg >= 0.75:
            boost += 1
            reasons.append(f"avg confidence {avg:.2f}")

    if facility.get("source"):
        boost += 1
        reasons.append(f"sourced from {facility['source']}")

    services = facility.get("services") or []
    if isinstance(services, list) and len(services) >= 3:
        boost += 1
        reasons.append(f"{len(services)} services listed")

    raw = (facility.get("raw_description") or "")
    if isinstance(raw, str) and len(raw) >= 200:
        boost += 1
        reasons.append("rich description")

    return boost, reasons


def _evidence_summary(
    facility: dict, search_terms: list[str], signal: TrustSignal
) -> str:
    name = facility.get("name") or "Facility"
    matched_terms = ", ".join(search_terms[:3]) if search_terms else "the request"
    confidence = facility.get("confidence") or {}
    source = facility.get("source") or "directory"

    if signal is TrustSignal.STRONG:
        return (
            f"{name} lists {matched_terms} as a core specialty and is "
            f"corroborated by {len(confidence)} structured fields from {source}."
        )
    if signal is TrustSignal.PARTIAL:
        return (
            f"{name} mentions {matched_terms} in its directory listing "
            f"(from {source}) but secondary corroboration is limited."
        )
    if signal is TrustSignal.WEAK:
        return (
            f"{name} references {matched_terms} only in its free-text "
            f"description — directly verify before referring."
        )
    if signal is TrustSignal.SUSPICIOUS:
        return (
            f"{name} is classified as a "
            f"{facility.get('type') or 'small practice'} but the request "
            f"({matched_terms}) typically requires a hospital — likely a "
            f"data-quality issue."
        )
    return f"No evidence found that {name} provides {matched_terms}."


def _missing_evidence(facility: dict) -> list[str]:
    missing: list[str] = []
    confidence = facility.get("confidence") or {}
    if not confidence:
        missing.append("No per-field confidence scores")
    if not facility.get("services"):
        missing.append("No structured services list")
    if not facility.get("procedures"):
        missing.append("No procedures listed")
    if not facility.get("equipment"):
        missing.append("No equipment data")
    raw = facility.get("raw_description") or ""
    if not isinstance(raw, str) or len(raw) < 80:
        missing.append("Description is sparse")
    if not facility.get("source"):
        missing.append("No source attribution")
    return missing


def score_facility(
    facility: dict[str, Any],
    search_terms: list[str],
) -> dict[str, Any]:
    """Score one facility's trust level for the requested capability.

    Returns a dict with ``trust_signal``, ``trust_rank``, ``evidence_summary``,
    ``missing_evidence``, ``quality_boost``, ``quality_reasons``, and
    ``source_count`` so the recommendation prompt has a structured
    handle on the evidence.
    """
    specialties = facility.get("specialties") or []
    services = facility.get("services") or []
    procedures = facility.get("procedures") or []
    equipment = facility.get("equipment") or []
    description = facility.get("raw_description") or ""

    in_structured = (
        _capability_in_list(search_terms, specialties)
        or _capability_in_list(search_terms, services)
        or _capability_in_list(search_terms, procedures)
        or _capability_in_list(search_terms, equipment)
    )
    in_freetext = _capability_in_text(search_terms, description)
    suspicious = _is_suspicious(facility, search_terms)

    confidence = facility.get("confidence") or {}
    source_count = (
        len([k for k, v in confidence.items() if isinstance(v, (int, float))])
        if isinstance(confidence, dict)
        else 0
    )

    if suspicious:
        signal = TrustSignal.SUSPICIOUS
    elif in_structured and source_count >= 3:
        signal = TrustSignal.STRONG
    elif in_structured:
        signal = TrustSignal.PARTIAL
    elif in_freetext:
        signal = TrustSignal.WEAK
    else:
        signal = TrustSignal.NONE

    quality_boost, quality_reasons = _quality_boosts(facility)

    return {
        "trust_signal": signal.value,
        "trust_rank": signal.rank,
        "evidence_summary": _evidence_summary(facility, search_terms, signal),
        "missing_evidence": _missing_evidence(facility),
        "quality_boost": quality_boost,
        "quality_reasons": quality_reasons,
        "source_count": source_count,
    }
