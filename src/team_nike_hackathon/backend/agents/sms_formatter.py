"""Format pipeline results into short SMS replies.

SMS limit: 160 chars per segment (free), 1600 per message (concatenated).

Strategy:
    - 2-3 sentence summary
    - Top 2 facilities, name + distance + trust badge + 1-line evidence
    - Trailing prompt suggesting next actions (MORE, SAVE 1)
"""

from __future__ import annotations

TRUST_BADGE = {
    "strong_evidence":  "verified",
    "partial_evidence": "partial",
    "weak_evidence":    "weak",
    "suspicious":       "suspicious",
    "no_evidence":      "no evidence",
}


def _badge(signal: str | None) -> str:
    return TRUST_BADGE.get(signal or "", "?")


def _attr_chips(attrs: dict | None) -> str:
    """Short attribute tags for SMS — affordability + accreditation."""
    if not attrs:
        return ""
    chips: list[str] = []
    if attrs.get("accepts_pmjay"):
        chips.append("PM-JAY")
    if attrs.get("nabh_accredited"):
        chips.append("NABH")
    if attrs.get("is_government"):
        chips.append("Govt")
    if attrs.get("is_nonprofit"):
        chips.append("NGO")
    if attrs.get("offers_charity_care"):
        chips.append("charity")
    if attrs.get("is_24x7"):
        chips.append("24x7")
    return f" [{', '.join(chips)}]" if chips else ""


def format_sms_reply(result: dict, max_facilities: int = 2) -> str:
    """Compress a /api/search result into a tight SMS message."""
    parsed = result.get("query") or {}
    facilities = (result.get("facilities") or [])[:max_facilities]
    summary = (result.get("recommendation_summary") or "").strip()
    total = result.get("result_count") or 0

    if not facilities:
        cap = (parsed.get("capability_text") or "").strip()
        loc = (parsed.get("location_text") or "").strip()
        suffix = f' for "{cap}"' if cap else ""
        suffix += f" near {loc}" if loc else ""
        return f"No facilities found{suffix}. Try a different keyword or location."

    lines: list[str] = []

    if summary:
        if len(summary) > 220:
            summary = summary[:217].rsplit(" ", 1)[0] + "..."
        lines.append(summary)
        lines.append("")

    for i, f in enumerate(facilities, 1):
        name = (f.get("name") or "?")[:55]
        dist = f.get("distance_km")
        dist_s = f"{dist} km" if dist is not None else "?km"
        sig = _badge(f.get("trust_signal"))
        attrs = _attr_chips(f.get("attributes"))
        evidence = (f.get("evidence_summary") or "").strip()
        if len(evidence) > 110:
            evidence = evidence[:107] + "..."

        lines.append(f"{i}. {name} ({dist_s}) - {sig}{attrs}")
        if evidence:
            lines.append(f"   {evidence}")

    extra = max(total - max_facilities, 0)
    if extra:
        lines.append("")
        lines.append(f"Reply MORE for the next {min(extra, 3)} options.")
    lines.append("Reply SAVE 1 / SAVE 2 to add to your shortlist.")

    return "\n".join(lines).strip()
