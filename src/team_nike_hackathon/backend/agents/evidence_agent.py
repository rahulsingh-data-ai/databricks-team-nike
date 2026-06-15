"""Agent 3 — Evidence scorer with batched LLM call.

Scores the top N rule-shortlisted facilities by asking the LLM, in a
single batched call, whether each one can actually deliver the requested
capability. The rule-based ``trust_scorer`` already produced a plausible
signal for every result; this LLM pass is an *upgrade* path for the top
of the list — we only run it on the top 5-8 because it adds latency to
the request.

Failure is silent: if the LLM is unavailable or returns garbage we just
keep the rule-based score for the affected rows. Search should always
complete.

The output is a numeric ``confidence_score`` (0-100) per facility, plus
the categorical ``trust_signal`` and a short ``evidence_summary``. The
numeric score drives the UI's confidence badge so it varies meaningfully
across the result set (vs. the rule-based blend, which clusters tightly
when underlying data clusters).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..utils.prompt_loader import load_prompt
from .llm_client import call_llm, parse_json_from_llm

logger = logging.getLogger(__name__)


def _list_str(value: Any, limit: int = 6) -> str:
    """Stringify a list of strings, truncating to keep prompt size sane."""
    if isinstance(value, list):
        items = [str(v) for v in value if v is not None]
        if not items:
            return "—"
        head = items[:limit]
        suffix = f" (+{len(items) - limit} more)" if len(items) > limit else ""
        return ", ".join(head) + suffix
    if value:
        return str(value)
    return "—"


def _summarise_facility(facility: dict[str, Any], idx: int) -> str:
    """Compact one-card representation of a facility for the prompt.

    Each card is delimited with ``### Facility N`` so the LLM can index
    rows by position even if it loses track of the JSON ids.
    """
    unique_id = (
        facility.get("id")
        or facility.get("unique_id")
        or f"row-{idx}"
    )
    name = facility.get("name") or "Unknown"
    ftype = facility.get("type") or "unknown type"
    city = facility.get("city") or "?"
    state = facility.get("state") or "?"
    specialties = _list_str(facility.get("specialties"))
    services = _list_str(facility.get("services"))
    procedures = _list_str(facility.get("procedures"))
    equipment = _list_str(facility.get("equipment"))
    description = (facility.get("raw_description") or "")[:400] or "—"
    source = facility.get("source") or "directory"

    confidence = facility.get("confidence") or {}
    if isinstance(confidence, dict) and confidence:
        conf_str = ", ".join(
            f"{k}={float(v):.2f}"
            for k, v in confidence.items()
            if isinstance(v, (int, float))
        ) or "—"
    else:
        conf_str = "—"

    return (
        f"### Facility {idx + 1}\n"
        f"id: {unique_id}\n"
        f"Name: {name}\n"
        f"Type: {ftype}\n"
        f"Location: {city}, {state}\n"
        f"Specialties: {specialties}\n"
        f"Services: {services}\n"
        f"Procedures: {procedures}\n"
        f"Equipment: {equipment}\n"
        f"Source: {source}\n"
        f"Per-field signals: {conf_str}\n"
        f"Description: {description}\n"
    )


def score_evidence_with_llm(
    facilities: list[dict[str, Any]],
    search_terms: list[str],
    max_facilities: int = 10,
) -> list[dict[str, Any]]:
    """Batch-score the top ``max_facilities`` rows in a single LLM call.

    Args:
        facilities: List of facility dicts. The first ``max_facilities``
            entries are sent to the LLM in input order.
        search_terms: Tokens describing what the user is looking for
            (e.g. ``["cancer", "care"]``). Passed verbatim to the prompt.
        max_facilities: Cap the number of facilities scored to keep the
            prompt under the context budget. 10 is a good default; the
            ``max_tokens`` budget below scales linearly with this.

    Returns:
        A list of ``{unique_id, trust_signal, confidence_score (0-1),
        evidence_summary, missing_evidence, method}`` dicts. Length
        equals ``min(len(facilities), max_facilities)``. Failures fall
        back to the rule-based values already on each facility.
    """
    if not facilities:
        return []

    targets = facilities[:max_facilities]

    system_prompt = load_prompt("evidence_scorer")
    cards = "\n".join(_summarise_facility(f, i) for i, f in enumerate(targets))
    user_prompt = (
        f"User is looking for: {', '.join(search_terms) if search_terms else '(any healthcare capability)'}\n\n"
        f"Score each of the {len(targets)} facilities below. Return ONE JSON "
        f"object with key `scores` whose value is an array of length {len(targets)}, "
        f"in the same order as the input.\n\n"
        f"{cards}"
    )

    parsed: dict | list | None = None
    raw_content = ""
    # ~180 tokens per facility score (trust_signal + confidence + 1-line
    # summary + small missing_evidence list) → 10 facilities ≈ 1800
    # tokens. 2200 buys a little headroom so the JSON never truncates.
    max_tokens = max(1200, 220 * len(targets))
    try:
        response = call_llm(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        raw_content = response.get("content", "") or ""
        parsed = parse_json_from_llm(raw_content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Evidence-scorer LLM call failed: %s", exc)

    scores_list: list[dict[str, Any]] = []
    if isinstance(parsed, dict):
        candidate = parsed.get("scores") if "scores" in parsed else parsed
        if isinstance(candidate, list):
            scores_list = [s for s in candidate if isinstance(s, dict)]
        elif isinstance(parsed, dict) and "trust_signal" in parsed:
            scores_list = [parsed]
    elif isinstance(parsed, list):
        scores_list = [s for s in parsed if isinstance(s, dict)]

    if scores_list and len(scores_list) != len(targets):
        logger.warning(
            "LLM returned %d scores for %d facilities; truncating/padding",
            len(scores_list),
            len(targets),
        )

    results: list[dict[str, Any]] = []
    for i, facility in enumerate(targets):
        unique_id = str(
            facility.get("id") or facility.get("unique_id") or f"row-{i}"
        )
        llm_score = scores_list[i] if i < len(scores_list) else None
        if llm_score and "trust_signal" in llm_score:
            raw_conf = llm_score.get("confidence_score")
            conf_float = _coerce_confidence(raw_conf)
            results.append(
                {
                    "unique_id": unique_id,
                    "trust_signal": str(
                        llm_score.get("trust_signal") or "no_evidence"
                    ),
                    "confidence_score": conf_float,
                    "evidence_summary": str(
                        llm_score.get("evidence_summary") or ""
                    ),
                    "missing_evidence": _coerce_string_list(
                        llm_score.get("missing_evidence")
                    ),
                    "method": "llm",
                }
            )
        else:
            results.append(
                {
                    "unique_id": unique_id,
                    "trust_signal": facility.get("trust_signal")
                    or "no_evidence",
                    "confidence_score": None,
                    "evidence_summary": facility.get(
                        "evidence_summary", "LLM scoring unavailable"
                    ),
                    "missing_evidence": facility.get("missing_evidence") or [],
                    "method": "rule_based",
                }
            )

    return results


def _coerce_confidence(value: Any) -> float | None:
    """Coerce the LLM's ``confidence_score`` to a float in ``[0, 1]``."""
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num > 1:
        num = num / 100.0
    return max(0.0, min(1.0, num))


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return []


# Used by tests / other callers that want to round-trip the raw response.
__all__ = ["score_evidence_with_llm"]


def _debug_dump(parsed: Any, raw: str) -> str:  # pragma: no cover - debug only
    """Helper for debugging: emit the LLM payload as JSON."""
    return json.dumps({"parsed": parsed, "raw": raw[:1000]}, default=str)
