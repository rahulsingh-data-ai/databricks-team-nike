"""Agent 1: Query Parser with Chain-of-Thought reasoning.

Takes raw natural language query and extracts structured search parameters.
Shows its reasoning for transparency (judging criteria).
"""

from __future__ import annotations

from typing import Any

from .llm_client import call_llm, parse_json_from_llm
from ..db.databricks_sql import DatabricksSQLClient
from ..db.facility_queries import resolve_location, map_query_to_specialties

SYSTEM_PROMPT = """You are a healthcare facility search assistant for India.
Given a user query, extract the care need and location.

Think step by step inside <thinking> tags, then provide your answer inside <answer> tags.

Your answer MUST be valid JSON with these fields:
{
  "capability": "the medical capability or service needed",
  "location": "the city, district, or area name",
  "urgency": "routine" | "urgent" | "emergency",
  "notes": "any additional context from the query"
}

Examples:
- "dialysis near Jaipur" -> {"capability": "dialysis", "location": "Jaipur", "urgency": "routine", "notes": ""}
- "emergency surgery near Patna" -> {"capability": "surgery", "location": "Patna", "urgency": "emergency", "notes": ""}
- "NICU near 302001" -> {"capability": "NICU", "location": "302001", "urgency": "urgent", "notes": "pincode-based search"}
"""

import re


def _extract_thinking(content: str) -> tuple[str, str]:
    """Extract <thinking> and <answer> from CoT response."""
    thinking = ""
    answer = content

    think_match = re.search(r'<thinking>(.*?)</thinking>', content, re.DOTALL | re.IGNORECASE)
    if think_match:
        thinking = think_match.group(1).strip()

    answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL | re.IGNORECASE)
    if answer_match:
        answer = answer_match.group(1).strip()

    return thinking, answer


def parse_query_with_llm(db: DatabricksSQLClient, raw_query: str) -> dict[str, Any]:
    """Parse query using LLM with CoT, then resolve location via DB.

    Returns structured query with reasoning trace visible to UI.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": raw_query},
    ]

    try:
        response = call_llm(messages, max_tokens=500, temperature=0.1)
        content = response["content"]
        thinking, answer_text = _extract_thinking(content)
        parsed = parse_json_from_llm(answer_text)
    except Exception as e:
        parsed = None
        thinking = f"LLM call failed: {e}. Falling back to keyword parsing."

    # Fallback to keyword-based parsing if LLM fails
    if not parsed or "capability" not in parsed:
        from ..pipeline.query_parser import parse_query as keyword_parse
        fallback = keyword_parse(db, raw_query)
        return {
            **fallback,
            "reasoning": thinking or "Used keyword-based parsing (LLM unavailable)",
            "method": "keyword_fallback",
        }

    capability_text = parsed.get("capability", raw_query)
    location_text = parsed.get("location", "")

    specialty_terms = map_query_to_specialties(capability_text)

    location = None
    if location_text:
        location = resolve_location(db, location_text)

    return {
        "raw_query": raw_query,
        "capability_text": capability_text,
        "location_text": location_text,
        "specialty_terms": specialty_terms,
        "location": location,
        "urgency": parsed.get("urgency", "routine"),
        "reasoning": thinking or "Query parsed successfully",
        "method": "llm",
    }
