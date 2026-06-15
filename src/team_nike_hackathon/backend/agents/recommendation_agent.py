"""Agent 4: Recommendation Generator with Chain-of-Thought.

Synthesizes search results, trust scores, and district health context
into a human-readable recommendation with visible reasoning.
"""

from __future__ import annotations

from typing import Any

from .llm_client import call_llm

SYSTEM_PROMPT = """You are a healthcare referral advisor for India.
Given a list of ranked facilities with trust signals and district health context,
generate a clear, honest recommendation for a health coordinator.

Think step by step in <thinking> tags about:
1. Which facilities have the strongest evidence?
2. What are the key trade-offs (distance vs trust)?
3. What health context is relevant from the district data?
4. What should the coordinator be cautious about?

Then in <answer> tags, write a 3-5 sentence recommendation that:
- Names the top 1-2 recommended facilities and WHY
- Flags any suspicious or weak-evidence facilities
- Mentions relevant district health context
- Ends with what information is MISSING that would improve the recommendation

Be honest. If evidence is weak, say so. Never overstate confidence.
"""


def generate_recommendation(
    query_text: str,
    facilities: list[dict],
    district_health: dict | None,
    search_terms: list[str],
) -> dict[str, Any]:
    """Generate a recommendation summary with visible CoT reasoning."""

    # Build context for the LLM
    facility_summaries = []
    for i, f in enumerate(facilities[:10], 1):
        facility_summaries.append(
            f"{i}. {f.get('name', '?')} ({f.get('facility_type', '?')}) "
            f"- {f.get('distance_km', '?')}km away "
            f"- Trust: {f.get('trust_signal', '?')} "
            f"- Evidence: {f.get('evidence_summary', 'N/A')}"
        )

    health_context = "No district health data available."
    if district_health:
        health_context = (
            f"District: {district_health.get('district', '?')}, {district_health.get('state', '?')}\n"
            f"Institutional delivery rate: {district_health.get('institutional_birth_pct', '?')}%\n"
            f"Health insurance coverage: {district_health.get('health_insurance_pct', '?')}%\n"
            f"Women anaemic: {district_health.get('women_anaemic_pct', '?')}%"
        )

    user_prompt = f"""Query: "{query_text}"
Searched for: {', '.join(search_terms)}

Ranked facilities:
{chr(10).join(facility_summaries)}

District health context:
{health_context}

Generate your recommendation."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
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
