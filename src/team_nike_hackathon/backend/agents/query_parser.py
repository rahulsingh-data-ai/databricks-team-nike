"""Shared natural-language query parser used by both the LangGraph
pipeline and the supervisor's ``parse_query`` tool.

Tries an LLM first (with CoT). Falls back to regex/keyword extraction
when the LLM is unavailable or returns malformed output.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..db.databricks_sql import DatabricksSQLClient
from ..db.facility_queries import map_query_to_specialties, resolve_location
from ..utils.prompt_loader import load_prompt
from .llm_client import call_llm, parse_json_from_llm

logger = logging.getLogger(__name__)

LOCATION_PREPOSITIONS = ("near", "in", "around", "close to", "at")
PINCODE_RE = re.compile(r"\b(\d{6})\b")


def _extract_cot(content: str) -> tuple[str, str]:
    """Pull <thinking> and <answer> blocks out of an LLM response."""
    thinking = ""
    answer = content or ""

    if not content:
        return thinking, answer

    t = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL | re.IGNORECASE)
    if t:
        thinking = t.group(1).strip()

    a = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL | re.IGNORECASE)
    if a:
        answer = a.group(1).strip()

    return thinking, answer


def _keyword_split(query: str) -> tuple[str, str]:
    """Split a query into (capability_text, location_text) using prepositions."""
    capability_text = query.strip()
    location_text = ""

    for prep in LOCATION_PREPOSITIONS:
        match = re.search(rf"\b{prep}\b", query, re.IGNORECASE)
        if match:
            capability_text = query[: match.start()].strip()
            location_text = query[match.end():].strip()
            break

    pin = PINCODE_RE.search(query)
    if pin and not location_text:
        location_text = pin.group(1)

    return capability_text, location_text


def parse_query(db: DatabricksSQLClient, raw_query: str) -> dict[str, Any]:
    """Parse a natural-language healthcare query.

    Returns:
        {
            "raw_query": original text,
            "capability_text": extracted care need,
            "location_text": extracted place,
            "specialty_terms": list of mapped specialty enums,
            "location": resolved location dict or None,
            "urgency": routine|urgent|emergency,
            "reasoning": LLM CoT (empty when falling back),
            "method": "llm" | "keyword_fallback",
        }
    """
    raw_query = (raw_query or "").strip()
    if not raw_query:
        return {
            "raw_query": "",
            "capability_text": "",
            "location_text": "",
            "specialty_terms": [],
            "location": None,
            "urgency": "routine",
            "reasoning": "",
            "method": "keyword_fallback",
        }

    capability_text = raw_query
    location_text = ""
    urgency = "routine"
    reasoning = ""
    method = "keyword_fallback"

    try:
        system_prompt = load_prompt("query_parser")
        response = call_llm(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_query},
            ],
            max_tokens=500,
            temperature=0.1,
        )
        reasoning, answer_text = _extract_cot(response.get("content", ""))
        parsed = parse_json_from_llm(answer_text)
    except Exception as e:  # noqa: BLE001 — never let LLM errors break the parser
        logger.warning(f"Query parser LLM failed: {e}")
        parsed = None

    language = "en"
    if isinstance(parsed, dict) and parsed.get("capability"):
        capability_text = str(parsed.get("capability", raw_query)).strip()
        location_text = str(parsed.get("location", "") or "").strip()
        urgency = str(parsed.get("urgency", "routine") or "routine").strip().lower()
        language = str(parsed.get("language", "en") or "en").strip().lower()[:5]
        method = "llm"
    else:
        capability_text, location_text = _keyword_split(raw_query)

    specialty_terms = map_query_to_specialties(capability_text or raw_query)
    location = resolve_location(db, location_text) if location_text else None

    return {
        "raw_query": raw_query,
        "capability_text": capability_text,
        "location_text": location_text,
        "specialty_terms": specialty_terms,
        "location": location,
        "urgency": urgency,
        "language": language,
        "reasoning": reasoning,
        "method": method,
    }
