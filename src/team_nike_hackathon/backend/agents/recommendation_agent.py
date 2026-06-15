"""Agent 4: Recommendation Generator with Chain-of-Thought.

Synthesizes search results, trust scores, district health context, and
extracted attributes (PM-JAY, NABH, govt, charity, languages) into a
human-readable recommendation with visible reasoning. Honors the
user's input language for the final answer.
"""

from __future__ import annotations

from typing import Any

from ..utils.prompt_loader import load_prompt
from .llm_client import call_llm


def _format_attributes(attrs: dict) -> str:
    if not attrs:
        return ""
    flags: list[str] = []
    mapping = [
        ("accepts_pmjay", "accepts PM-JAY"),
        ("accepts_cghs", "accepts CGHS"),
        ("nabh_accredited", "NABH-accredited"),
        ("jci_accredited", "JCI-accredited"),
        ("is_24x7", "24x7"),
        ("has_ambulance", "ambulance"),
        ("has_telemedicine", "telemedicine"),
        ("has_blood_bank", "blood bank"),
        ("has_icu", "ICU"),
        ("has_nicu", "NICU"),
        ("is_government", "government"),
        ("is_nonprofit", "non-profit"),
        ("offers_charity_care", "charity care"),
    ]
    for key, label in mapping:
        if attrs.get(key):
            flags.append(label)
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
    """Generate a recommendation summary with visible CoT reasoning."""

    facility_summaries: list[str] = []
    for i, f in enumerate(facilities[:10], 1):
        attrs_str = _format_attributes(f.get("attributes") or {})
        facility_summaries.append(
            f"{i}. {f.get('name', '?')} ({f.get('facility_type', '?')}) "
            f"- {f.get('distance_km', '?')}km away "
            f"- Trust: {f.get('trust_signal', '?')}"
            f"{attrs_str} "
            f"- Evidence: {f.get('evidence_summary', 'N/A')}"
        )

    if district_health:
        district = district_health.get("district", "?")
        state = district_health.get("state", "?")
        indicator_lines = [f"District: {district}, {state}"]
        sample = district_health.get("households_surveyed")
        if sample is not None:
            indicator_lines.append(f"Households surveyed: {sample}")
        for k, v in district_health.items():
            if k in ("district", "state", "households_surveyed") or v is None:
                continue
            label = k.replace("_pct", "%").replace("_", " ")
            indicator_lines.append(f"  - {label}: {v}")
        health_context = "\n".join(indicator_lines)
    else:
        health_context = "No district health data available."

    user_prompt = (
        f'Query: "{query_text}"\n'
        f"User language: {language}\n"
        f"Searched for: {', '.join(search_terms)}\n\n"
        f"Ranked facilities:\n{chr(10).join(facility_summaries)}\n\n"
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
        content = response["content"]

        import re
        thinking = ""
        think_match = re.search(r'<thinking>(.*?)</thinking>', content, re.DOTALL | re.IGNORECASE)
        if think_match:
            thinking = think_match.group(1).strip()

        answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL | re.IGNORECASE)
        recommendation = answer_match.group(1).strip() if answer_match else content

        # Clean any remaining tags
        recommendation = re.sub(r'</?(?:thinking|answer)>', '', recommendation).strip()

        return {
            "recommendation": recommendation,
            "reasoning": thinking,
            "method": "llm",
        }
    except Exception as e:
        # Fallback to template-based summary
        total = len(facilities)
        strong = sum(1 for f in facilities if f.get("trust_signal") == "strong_evidence")
        top = facilities[0] if facilities else {}

        return {
            "recommendation": (
                f"Found {total} facilities. "
                f"{strong} have strong evidence. "
                f"Top recommendation: {top.get('name', 'N/A')} "
                f"({top.get('distance_km', '?')}km, {top.get('trust_signal', '?')}). "
                f"Verify directly before referring."
            ),
            "reasoning": f"LLM unavailable ({e}). Used template summary.",
            "method": "template_fallback",
        }
