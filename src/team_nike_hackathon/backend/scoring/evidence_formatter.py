"""Format raw facility rows into the structured-evidence shape the UI
expects.

A piece of evidence is just a ``(field, value, confidence, source)``
tuple plus a short human-readable summary. The frontend's
``EvidenceDrawer`` renders this list as a series of cards.
"""

from __future__ import annotations

from typing import Any


def _confidence_for(facility: dict[str, Any], field: str) -> float | None:
    conf = facility.get("confidence")
    if isinstance(conf, dict) and field in conf:
        try:
            value = float(conf[field])
        except (TypeError, ValueError):
            return None
        return max(0.0, min(1.0, value))
    return None


def _format_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value or "")


def format_evidence(facility: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a facility row into a list of evidence cards.

    Each card is ``{label, value, confidence, source}`` so the UI can
    render them uniformly. ``confidence`` is ``None`` when the ETL did
    not provide a score for that field — we don't make one up.
    """
    source = facility.get("source") or "directory"
    rows: list[dict[str, Any]] = []

    field_labels: list[tuple[str, str]] = [
        ("specialties", "Specialties"),
        ("services", "Services"),
        ("procedures", "Procedures"),
        ("equipment", "Equipment"),
    ]
    for field, label in field_labels:
        value = facility.get(field)
        if not value:
            continue
        rows.append({
            "label": label,
            "value": _format_list(value),
            "confidence": _confidence_for(facility, field),
            "source": source,
        })

    addr_bits = [
        facility.get("address"),
        facility.get("city"),
        facility.get("state"),
        facility.get("pincode"),
    ]
    addr = ", ".join(str(b) for b in addr_bits if b)
    if addr:
        rows.append({
            "label": "Address",
            "value": addr,
            "confidence": _confidence_for(facility, "address"),
            "source": source,
        })

    if facility.get("raw_description"):
        rows.append({
            "label": "Description",
            "value": str(facility["raw_description"])[:400],
            "confidence": _confidence_for(facility, "raw_description"),
            "source": source,
        })

    return rows
