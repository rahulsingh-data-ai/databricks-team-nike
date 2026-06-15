"""Agentic pipeline orchestration.

We only use the LLM for **query interpretation** — converting messy
natural-language input (any of the supported Indian languages) into a
structured ``{capability, location, urgency}`` triple that the
deterministic search and the rule-based trust scorer can act on.

Earlier iterations had a 5-node graph with LLM-driven recommendation
generation and per-row evidence re-scoring. We dropped those because
they added 8-12 s of latency per query and surfaced verbose
chain-of-thought that nobody reads in the UI. The product just needs
location recommendations, not a paragraph of LLM justification.

If you need the heavier nodes back later, the original implementation
lives on the ``feature/referral-copilot`` branch.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TypedDict

from databricks.sdk import WorkspaceClient

from ..scoring.evidence_formatter import format_evidence
from ..scoring.trust_scorer import attribute_flags, score_facility
from .llm_client import reset_workspace, set_workspace
from .query_parser import parse_query

logger = logging.getLogger(__name__)


class AgentTraceStep(TypedDict, total=False):
    """One row in the visible agent trace."""

    agent: str
    reasoning: str
    output: Any
    method: str
    latency_ms: float


class ReferralResult(TypedDict, total=False):
    query: dict[str, Any]
    recommendation_summary: str
    recommendation_reasoning: str
    result_count: int
    facilities: list[dict[str, Any]]
    district_health: dict | None
    agent_trace: list[AgentTraceStep]


def _now_ms(start: float) -> float:
    return round((time.time() - start) * 1000, 1)


# ---------------------------------------------------------------------------
# Node 1 — Query Parser
# ---------------------------------------------------------------------------

def _parse_query_node(raw_query: str) -> tuple[dict[str, Any], AgentTraceStep]:
    start = time.time()
    parsed = parse_query(raw_query)
    step: AgentTraceStep = {
        "agent": "Query Parser",
        "reasoning": parsed.get("reasoning", "") or "",
        "output": {
            "capability": parsed.get("capability_text"),
            "location": parsed.get("location_text"),
            "urgency": parsed.get("urgency"),
            "specialty_terms": parsed.get("specialty_terms"),
        },
        "method": parsed.get("method", ""),
        "latency_ms": _now_ms(start),
    }
    return parsed, step


# ---------------------------------------------------------------------------
# Node 3 — Trust / Evidence Scorer
# ---------------------------------------------------------------------------

def _score_node(
    candidates: list[dict[str, Any]],
    search_terms: list[str],
) -> tuple[list[dict[str, Any]], AgentTraceStep]:
    start = time.time()
    scored: list[dict[str, Any]] = []

    for facility in candidates:
        trust = score_facility(facility, search_terms)
        attrs = attribute_flags(facility)
        evidence = format_evidence(facility)
        scored.append({
            "unique_id": str(facility.get("id") or ""),
            "id": str(facility.get("id") or ""),
            "name": facility.get("name"),
            "facility_type": facility.get("type"),
            "type": facility.get("type"),
            "address": {
                "city": facility.get("city"),
                "state": facility.get("state"),
                "pincode": facility.get("pincode"),
                "raw": facility.get("address"),
            },
            "latitude": facility.get("latitude"),
            "longitude": facility.get("longitude"),
            "distance_km": (
                round(float(facility["distance_km"]), 1)
                if facility.get("distance_km") is not None
                else None
            ),
            "match_score": facility.get("match_score"),
            "trust_signal": trust["trust_signal"],
            "trust_rank": trust["trust_rank"],
            "quality_boost": trust.get("quality_boost", 0),
            "quality_reasons": trust.get("quality_reasons", []),
            "evidence_summary": trust["evidence_summary"],
            "missing_evidence": trust["missing_evidence"],
            "source_count": trust["source_count"],
            "evidence": evidence,
            "attributes": attrs,
            "raw_description": facility.get("raw_description"),
            "specialties": facility.get("specialties"),
            "services": facility.get("services"),
            "procedures": facility.get("procedures"),
            "equipment": facility.get("equipment"),
            "confidence": facility.get("confidence"),
            "source": facility.get("source"),
        })

    scored.sort(
        key=lambda f: (
            -(f.get("trust_rank") or 0),
            -(f.get("quality_boost") or 0),
            f.get("distance_km") if f.get("distance_km") is not None else 99999,
        )
    )

    step: AgentTraceStep = {
        "agent": "Evidence Scorer",
        "output": f"Scored {len(scored)} facilities",
        "method": "rule_based",
        "latency_ms": _now_ms(start),
    }
    return scored, step


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_referral_pipeline(
    *,
    ws: WorkspaceClient,
    raw_query: str,
    candidates: list[dict[str, Any]],
    parsed_override: dict[str, Any] | None = None,
    llm_endpoint: str | None = None,
) -> ReferralResult:
    """Run the 5-node pipeline synchronously.

    Args:
        ws: A ``WorkspaceClient`` used to call the LLM endpoint. Bound
            into a ``ContextVar`` so the agents don't have to thread it
            through every call.
        raw_query: The user's free-text query (any supported language).
        candidates: The deterministic shortlist from our SQL search.
            Each row is the same dict shape the rest of the backend
            uses for a ``Facility`` (with optional ``distance_km`` and
            ``match_score`` mixed in by the search).
        parsed_override: When the caller has already resolved a
            location (e.g. from the UI's autocomplete), pass it here to
            skip the geocoder round-trip.
        llm_endpoint: Override the LLM endpoint name. Defaults to the
            one configured on ``AppConfig.llm_endpoint``.

    Returns a ``ReferralResult`` containing the agent trace, the
    enriched + ranked facilities, and the recommendation summary.
    """
    from .llm_client import set_endpoint, reset_endpoint

    ws_token = set_workspace(ws)
    ep_token = set_endpoint(llm_endpoint) if llm_endpoint else None

    try:
        agent_trace: list[AgentTraceStep] = []

        # Node 1 — parse the query (LLM with regex fallback).
        if parsed_override:
            parsed = parsed_override
            agent_trace.append({
                "agent": "Query Parser",
                "output": {
                    "capability": parsed.get("capability_text"),
                    "location": parsed.get("location_text"),
                    "urgency": parsed.get("urgency"),
                    "specialty_terms": parsed.get("specialty_terms"),
                },
                "method": "supplied_by_caller",
                "latency_ms": 0.0,
            })
        else:
            parsed, step = _parse_query_node(raw_query)
            agent_trace.append(step)

        # Node 2 — search trace step (search itself ran upstream).
        agent_trace.append({
            "agent": "Facility Search",
            "output": f"Received {len(candidates)} shortlist candidates",
            "method": "facilities_gold",
            "latency_ms": 0.0,
        })

        # Node 3 — rule-based trust scoring on the SQL shortlist.
        scored, step = _score_node(
            candidates, parsed.get("specialty_terms") or []
        )
        agent_trace.append(step)

        return {
            "query": {
                "raw_query": parsed.get("raw_query", raw_query),
                "capability_text": parsed.get("capability_text"),
                "location_text": parsed.get("location_text"),
                "specialty_terms": parsed.get("specialty_terms"),
                "location": parsed.get("location"),
                "urgency": parsed.get("urgency"),
                "language": parsed.get("language", "en"),
            },
            "recommendation_summary": "",
            "recommendation_reasoning": "",
            "result_count": len(scored),
            "facilities": scored,
            "district_health": None,
            "agent_trace": agent_trace,
        }
    finally:
        if ep_token is not None:
            reset_endpoint(ep_token)
        reset_workspace(ws_token)
