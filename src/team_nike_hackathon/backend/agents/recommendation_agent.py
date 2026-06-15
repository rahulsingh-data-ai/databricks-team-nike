"""Agent 5 — Recommendation generator with visible reasoning.

Takes the ranked + scored facility list and synthesises a 3-5 sentence
recommendation in the user's input language, with the LLM's chain of
thought exposed in a separate ``reasoning`` field so the coordinator
can see *why* the model is recommending what it does.

When the LLM is unavailable we fall back to a deterministic template
summary so the search still feels coherent.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..utils.prompt_loader import load_prompt
from .llm_client import call_llm

logger = logging.getLogger(__name__)


_ATTR_LABELS: list[tuple[str, str]] = [
    ("accepts_pmjay", "accepts PM-JAY"),
    ("accepts_cghs", "accepts CGHS"),
    ("accepts_esi", "accepts ESI"),
    ("nabh_accredited", "NABH-accredited"),
    ("jci_accredited", "JCI-accredited"),
    ("is_24x7", "24x7"),
    ("has_ambulance", "ambulance"),
    ("has_telemedicine", "telemedicine"),
    ("has_blood_bank", "blood bank"),
    ("has_icu", "ICU"),
    ("has_nicu", "NICU"),
    ("has_emergency", "emergency"),
    ("is_government", "government"),
    ("is_nonprofit", "non-profit"),
    ("offers_charity_care", "charity care"),
]


def _format_attributes(attrs: dict | None) -> str:
    if not attrs:
        return ""
    flags = [label for key, label in _ATTR_LABELS if attrs.get(key)]
    langs = attrs.get("languages") or []
    if langs:
        flags.append(f"languages: {', '.join(langs)}")
    return f" [{', '.join(flags)}]" if flags else ""


def generate_recommendation(
    query_text: str,
    facilities: list[dict],
    district_health: dict | None,
    search_terms: list[str],
    language: str = "en",
) -> dict[str, Any]:
    """Synthesise a recommendation paragraph + reasoning."""
    facility_summaries: list[str] = []
    for i, f in enumerate(facilities[:10], 1):
        attrs_str = _format_attributes(f.get("attributes"))
        distance = f.get("distance_km")
        dist_str = f"{distance:.1f}km" if isinstance(distance, (int, float)) else "?"
        facility_summaries.append(
            f"{i}. {f.get('name', '?')} "
            f"({f.get('facility_type') or f.get('type') or '?'}) "
            f"- {dist_str} away "
            f"- Trust: {f.get('trust_signal', '?')}"
            f"{attrs_str} "
            f"- Evidence: {f.get('evidence_summary', 'N/A')}"
        )

    if district_health:
        lines = [f"District: {district_health.get('district', '?')}"]
        for k, v in district_health.items():
            if k == "district" or v is None:
                continue
            lines.append(f"  - {k.replace('_', ' ')}: {v}")
        health_context = "\n".join(lines)
    else:
        health_context = "No district health data available."

    user_prompt = (
        f'Query: "{query_text}"\n'
        f"User language: {language}\n"
        f"Searched for: {', '.join(search_terms) or '(any)'}\n\n"
        f"Ranked facilities:\n{chr(10).join(facility_summaries) or '(none)'}\n\n"
        f"District health context:\n{health_context}\n\n"
        "Generate your recommendation."
    )

    system_prompt = load_prompt("recommender")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = call_llm(messages, max_tokens=800, temperature=0.2)
        content = response.get("content", "") or ""

        thinking = ""
        m = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL | re.IGNORECASE)
        if m:
            thinking = m.group(1).strip()
        a = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL | re.IGNORECASE)
        recommendation = a.group(1).strip() if a else content
        recommendation = re.sub(
            r"</?(?:thinking|answer)>", "", recommendation
        ).strip()

        return {
            "recommendation": recommendation,
            "reasoning": thinking,
            "method": "llm",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Recommendation LLM call failed: %s", exc)

    # Template fallback
    total = len(facilities)
    strong = sum(
        1 for f in facilities if f.get("trust_signal") == "strong_evidence"
    )
    top = facilities[0] if facilities else {}
    top_dist = top.get("distance_km")
    dist_str = f"{top_dist:.1f}km" if isinstance(top_dist, (int, float)) else "?"
    return {
        "recommendation": (
            f"Found {total} facilities. {strong} have strong evidence. "
            f"Top recommendation: {top.get('name', 'N/A')} "
            f"({dist_str}, {top.get('trust_signal', '?')}). "
            "Verify directly before referring."
        ),
        "reasoning": "LLM unavailable; used template summary.",
        "method": "template_fallback",
    }
