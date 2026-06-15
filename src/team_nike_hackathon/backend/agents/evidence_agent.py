"""Agent 3: Evidence Scorer with Chain-of-Thought reasoning.

Evaluates each facility's evidence quality and assigns trust signals.
Shows reasoning for every decision (uncertainty-first principle).
"""

from __future__ import annotations

import json
from typing import Any

from .llm_client import call_llm, parse_json_from_llm

SYSTEM_PROMPT = """You are a healthcare evidence evaluator for India.
You assess whether a facility can ACTUALLY provide a specific medical capability,
based on available evidence. You must be honest about uncertainty.

CRITICAL RULES:
- "Unknown" is a valid and important output. Never hide gaps.
- Multiple independent sources > single source
- Structured specialties data > free-text claims
- A clinic claiming advanced surgery is suspicious
- Missing data must be explicitly stated

For each facility, think step by step in <thinking> tags, then provide your assessment in <answer> tags as JSON:
{
  "trust_signal": "strong_evidence" | "partial_evidence" | "weak_evidence" | "suspicious" | "no_evidence",
  "evidence_summary": "1-2 sentence explanation of WHY this trust level",
  "missing_evidence": ["list", "of", "what we don't know"],
  "confidence_note": "brief note on confidence level"
}
"""


def _build_facility_prompt(facility: dict, search_terms: list[str]) -> str:
    """Build a prompt describing facility evidence for evaluation."""
    name = facility.get("name", "Unknown")
    ftype = facility.get("facilityTypeId", "unknown")
    city = facility.get("address_city", "unknown")
    specialties = str(facility.get("specialties", ""))[:300]
    capability = str(facility.get("capability", ""))[:300]
    sources = str(facility.get("source_types", ""))[:200]
    source_urls = str(facility.get("source_urls", ""))[:200]
    capacity = facility.get("capacity", "unknown")
    doctors = facility.get("numberDoctors", "unknown")

    return f"""Evaluate this facility for: {', '.join(search_terms)}

Facility: {name}
Type: {ftype}
City: {city}
Specialties (structured): {specialties}
Capabilities (free-text claims): {capability}
Source types: {sources}
Source URLs: {source_urls}
Capacity: {capacity}
Doctor count: {doctors}
"""


def score_evidence_with_llm(
    facilities: list[dict],
    search_terms: list[str],
    max_facilities: int = 5,
) -> list[dict[str, Any]]:
    """Score top facilities using LLM evidence evaluation.

    Only scores the top N facilities via LLM (expensive).
    Remaining facilities keep their rule-based scores.
    Returns list of {facility_id, trust_signal, evidence_summary, missing_evidence, reasoning}.
    """
    results = []

    for facility in facilities[:max_facilities]:
        prompt = _build_facility_prompt(facility, search_terms)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            response = call_llm(messages, max_tokens=600, temperature=0.1)
            content = response["content"]

            import re
            thinking = ""
            think_match = re.search(r'<thinking>(.*?)</thinking>', content, re.DOTALL | re.IGNORECASE)
            if think_match:
                thinking = think_match.group(1).strip()

            answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL | re.IGNORECASE)
            answer_text = answer_match.group(1).strip() if answer_match else content

            parsed = parse_json_from_llm(answer_text)

            if parsed and "trust_signal" in parsed:
                results.append({
                    "unique_id": facility.get("unique_id"),
                    "trust_signal": parsed["trust_signal"],
                    "evidence_summary": parsed.get("evidence_summary", ""),
                    "missing_evidence": parsed.get("missing_evidence", []),
                    "confidence_note": parsed.get("confidence_note", ""),
                    "reasoning": thinking,
                    "method": "llm",
                })
                continue
        except Exception as e:
            pass

        # Fallback: keep existing rule-based score
        results.append({
            "unique_id": facility.get("unique_id"),
            "trust_signal": facility.get("trust_signal", "no_evidence"),
            "evidence_summary": facility.get("evidence_summary", "LLM scoring unavailable"),
            "missing_evidence": facility.get("missing_evidence", []),
            "confidence_note": "",
            "reasoning": "Rule-based scoring (LLM unavailable)",
            "method": "rule_based",
        })

    return results
