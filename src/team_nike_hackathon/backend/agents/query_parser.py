"""Agent 1 — Natural-language query parser.

Takes the raw user query (any of the nine supported Indian languages or
English) and extracts:

* ``capability_text``: the medical need (e.g. "dialysis")
* ``location_text``: the place name / pincode
* ``specialty_terms``: a small list of canonical specialty keywords
  derived from ``capability_text`` (used by the SQL search step)
* ``location``: a resolved ``{lat, lng, label}`` triple via our geocoder
* ``urgency``: ``routine`` / ``urgent`` / ``emergency``
* ``language``: ISO 639-1 code of the user's input

We try the LLM first (with chain-of-thought in ``<thinking>`` tags), and
fall back to a regex + keyword extractor when the LLM is unavailable or
the response can't be parsed. The fallback never raises — search has to
work even with no LLM.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..geocode import geocode
from ..utils.prompt_loader import load_prompt
from .llm_client import call_llm, parse_json_from_llm

logger = logging.getLogger(__name__)


LOCATION_PREPOSITIONS = ("near", "in", "around", "close to", "at")
PINCODE_RE = re.compile(r"\b(\d{6})\b")
_THINK_RE = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL | re.IGNORECASE)
_ANSWER_RE = re.compile(r"<answer>(.*?)</answer>", re.DOTALL | re.IGNORECASE)


# Lightweight English-side synonym map. Maps the user's free-text need to
# canonical specialty / service / procedure terms that exist in the
# Facility JSONB lists. We intentionally keep this short — the SQL step
# already does fuzzy trigram matching, so we only need to seed it with a
# few high-yield aliases.
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "dialysis": ("dialysis", "nephrology", "renal"),
    "kidney": ("nephrology", "dialysis", "renal"),
    "heart attack": ("cardiology", "cardiac surgery", "emergency"),
    "heart": ("cardiology", "cardiac"),
    "cardiac": ("cardiology", "cardiac surgery"),
    "delivery": ("maternity", "obstetrics", "gynecology"),
    "pregnancy": ("maternity", "obstetrics"),
    "maternity": ("maternity", "obstetrics", "gynecology"),
    "baby": ("pediatrics", "neonatology", "nicu"),
    "newborn": ("neonatology", "nicu", "pediatrics"),
    "nicu": ("neonatology", "nicu"),
    "icu": ("icu", "intensive care", "critical care"),
    "cancer": ("oncology", "chemotherapy", "radiotherapy"),
    "tumor": ("oncology", "surgery"),
    "fracture": ("orthopedics", "trauma"),
    "broken bone": ("orthopedics", "trauma"),
    "bone": ("orthopedics",),
    "diabetes": ("endocrinology", "diabetes"),
    "eye": ("ophthalmology",),
    "dental": ("dentistry", "dental"),
    "tooth": ("dentistry", "dental"),
    "skin": ("dermatology",),
    "mental health": ("psychiatry", "mental health"),
    "depression": ("psychiatry", "psychology"),
    "stroke": ("neurology", "emergency"),
    "brain": ("neurology", "neurosurgery"),
    "burn": ("burn unit", "trauma", "emergency"),
    "trauma": ("trauma", "emergency"),
    "tb": ("tuberculosis", "pulmonology"),
    "tuberculosis": ("tuberculosis", "pulmonology"),
    "asthma": ("pulmonology", "respiratory"),
    "lung": ("pulmonology", "respiratory"),
    "surgery": ("surgery", "general surgery"),
    "x-ray": ("radiology", "imaging"),
    "scan": ("radiology", "imaging"),
    "mri": ("radiology", "imaging"),
    "ct": ("radiology", "imaging"),
    "blood test": ("pathology", "laboratory"),
    "vaccination": ("vaccination", "immunization", "pediatrics"),
    "vaccine": ("vaccination", "immunization"),
}


def _expand_specialty_terms(capability_text: str) -> list[str]:
    """Map a free-text capability into a small set of canonical terms.

    Always includes the raw capability text so the SQL step can fuzzy-
    match it directly. Synonyms are added on top so a query like
    "dialysis" also hits facilities tagged "nephrology".
    """
    base = (capability_text or "").strip().lower()
    if not base:
        return []
    terms: list[str] = [base]
    for key, synonyms in _SYNONYMS.items():
        if key in base:
            for s in synonyms:
                if s not in terms:
                    terms.append(s)
    return terms[:8]


def _extract_cot(content: str) -> tuple[str, str]:
    if not content:
        return "", ""
    thinking = ""
    answer = content
    t = _THINK_RE.search(content)
    if t:
        thinking = t.group(1).strip()
    a = _ANSWER_RE.search(content)
    if a:
        answer = a.group(1).strip()
    return thinking, answer


def _keyword_split(query: str) -> tuple[str, str]:
    """Split a query into (capability_text, location_text) using prepositions."""
    capability_text = (query or "").strip()
    location_text = ""

    for prep in LOCATION_PREPOSITIONS:
        match = re.search(rf"\b{prep}\b", query, re.IGNORECASE)
        if match:
            capability_text = query[: match.start()].strip()
            location_text = query[match.end():].strip()
            break

    if not location_text:
        pin = PINCODE_RE.search(query)
        if pin:
            location_text = pin.group(1)

    return capability_text, location_text


def parse_query(raw_query: str) -> dict[str, Any]:
    """Parse a natural-language healthcare query.

    Returns a dict with everything the rest of the pipeline needs:
    ``raw_query``, ``capability_text``, ``location_text``,
    ``specialty_terms``, ``location`` (resolved place or ``None``),
    ``urgency``, ``language``, ``reasoning`` (LLM CoT, empty on
    fallback), and ``method`` (``"llm"`` or ``"keyword_fallback"``).
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
            "language": "en",
            "reasoning": "",
            "method": "keyword_fallback",
        }

    capability_text = raw_query
    location_text = ""
    urgency = "routine"
    language = "en"
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
        thinking, answer_text = _extract_cot(response.get("content", ""))
        reasoning = thinking
        parsed = parse_json_from_llm(answer_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query parser LLM failed: %s", exc)
        parsed = None

    if isinstance(parsed, dict) and parsed.get("capability"):
        capability_text = str(parsed.get("capability") or raw_query).strip()
        location_text = str(parsed.get("location") or "").strip()
        urgency = str(parsed.get("urgency") or "routine").strip().lower()
        language = str(parsed.get("language") or "en").strip().lower()[:5]
        method = "llm"
    else:
        capability_text, location_text = _keyword_split(raw_query)

    specialty_terms = _expand_specialty_terms(capability_text)

    location: dict[str, Any] | None = None
    if location_text:
        place = geocode(location_text)
        if place is not None:
            location = {
                "latitude": place.lat,
                "longitude": place.lng,
                "label": place.label,
            }

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
