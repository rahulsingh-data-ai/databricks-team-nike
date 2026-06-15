"""LangGraph pipeline for the Referral Copilot.

Five-node StateGraph: parse_query -> search -> score -> enrich -> recommend.

The Databricks SQL client is *not* stored in LangGraph state (LangGraph
state should remain JSON-serializable). Instead, the client is passed via
a ``contextvars.ContextVar`` set in the entry-point function. Each node
reads it through ``_current_db()``.
"""

from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ..db.databricks_sql import DatabricksSQLClient
from ..db.facility_queries import (
    get_district_health,
    search_facilities,
)
from ..db.vector_search import hybrid_search
from ..scoring.evidence_formatter import format_evidence
from ..scoring.trust_scorer import score_facility
from ..utils.mlflow_tracer import ReferralTracer
from .query_parser import parse_query

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request-scoped DB injection without leaking the client into graph state.
# ---------------------------------------------------------------------------

_DB_CTX: ContextVar[DatabricksSQLClient | None] = ContextVar(
    "referral_db", default=None
)


def _current_db() -> DatabricksSQLClient:
    db = _DB_CTX.get()
    if db is None:
        raise RuntimeError(
            "DatabricksSQLClient not set. Call set_db() before invoking the graph."
        )
    return db


def set_db(db: DatabricksSQLClient):
    """Bind a DB client to the current async/sync context."""
    return _DB_CTX.set(db)


def reset_db(token):
    """Reset the contextvar after the graph finishes."""
    _DB_CTX.reset(token)


class ReferralState(TypedDict, total=False):
    raw_query: str
    capability_text: str
    location_text: str
    specialty_terms: list[str]
    location: dict | None
    urgency: str
    candidates: list[dict]
    scored_candidates: list[dict]
    district_health: dict | None
    recommendation: str
    agent_trace: list[dict]
    error: str | None


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def parse_query_node(state: ReferralState) -> ReferralState:
    """Agent 1: Parse the user query into structured components."""
    start = time.time()
    db = _current_db()
    parsed = parse_query(db, state.get("raw_query", ""))

    trace = state.get("agent_trace") or []
    trace.append({
        "agent": "Query Parser",
        "reasoning": parsed.get("reasoning", ""),
        "output": {
            "capability": parsed.get("capability_text"),
            "location": parsed.get("location_text"),
            "urgency": parsed.get("urgency"),
        },
        "method": parsed.get("method"),
        "latency_ms": round((time.time() - start) * 1000, 1),
    })

    return {
        **state,
        "capability_text": parsed.get("capability_text", ""),
        "location_text": parsed.get("location_text", ""),
        "specialty_terms": parsed.get("specialty_terms", []),
        "location": parsed.get("location"),
        "urgency": parsed.get("urgency", "routine"),
        "agent_trace": trace,
    }


def search_node(state: ReferralState) -> ReferralState:
    """Agent 2: Search facilities using keyword SQL + vector hybrid."""
    start = time.time()
    db = _current_db()
    location = state.get("location") or {}

    candidates = search_facilities(
        db,
        specialty_terms=state.get("specialty_terms") or [],
        lat=location.get("latitude"),
        lon=location.get("longitude"),
        state=location.get("state"),
        district=location.get("district"),
        limit=20,
    )

    vector_filter = (
        {"address_stateOrRegion": location["state"]}
        if location.get("state")
        else None
    )
    candidates = hybrid_search(
        state.get("raw_query", ""),
        candidates,
        num_vector_results=20,
        filters=vector_filter,
    )

    trace = state.get("agent_trace") or []
    trace.append({
        "agent": "Facility Search",
        "output": f"Found {len(candidates)} candidates (keyword + vector hybrid)",
        "latency_ms": round((time.time() - start) * 1000, 1),
    })
    return {**state, "candidates": candidates, "agent_trace": trace}


def score_node(state: ReferralState) -> ReferralState:
    """Agent 3: Rule-based scoring for all, LLM scoring for the top 5."""
    start = time.time()
    candidates = state.get("candidates") or []
    search_terms = state.get("specialty_terms") or []

    scored: list[dict] = []
    for facility in candidates:
        trust = score_facility(facility, search_terms)
        evidence = format_evidence(facility)
        scored.append({
            "unique_id": facility.get("unique_id"),
            "name": facility.get("name"),
            "facility_type": facility.get("facilityTypeId"),
            "address": {
                "city": facility.get("address_city"),
                "state": facility.get("address_stateOrRegion"),
                "pincode": facility.get("address_zipOrPostcode"),
            },
            "latitude": facility.get("latitude"),
            "longitude": facility.get("longitude"),
            "distance_km": (
                round(facility.get("distance_km") or 0, 1)
                if facility.get("distance_km") is not None
                else None
            ),
            "trust_signal": trust["trust_signal"],
            "trust_rank": trust["trust_rank"],
            "evidence_summary": trust["evidence_summary"],
            "missing_evidence": trust["missing_evidence"],
            "source_count": trust["source_count"],
            "evidence": evidence,
            "search_method": facility.get("search_method", "keyword"),
        })

    if scored:
        try:
            from .evidence_agent import score_evidence_with_llm

            llm_scores = score_evidence_with_llm(
                candidates[:5], search_terms, max_facilities=5
            )
            llm_map = {s["unique_id"]: s for s in llm_scores}
            rank_map = {
                "strong_evidence": 5,
                "partial_evidence": 4,
                "weak_evidence": 3,
                "suspicious": 2,
                "no_evidence": 1,
            }
            for f in scored:
                upgrade = llm_map.get(f["unique_id"])
                if not upgrade:
                    continue
                f["trust_signal"] = upgrade["trust_signal"]
                f["trust_rank"] = rank_map.get(upgrade["trust_signal"], 1)
                f["evidence_summary"] = upgrade.get("evidence_summary", f["evidence_summary"])
                f["missing_evidence"] = upgrade.get("missing_evidence", f["missing_evidence"])
                f["agent_reasoning"] = upgrade.get("reasoning", "")
                f["scoring_method"] = upgrade.get("method", "")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"LLM evidence scoring failed; using rule-based only: {e}")

    scored.sort(
        key=lambda f: (
            -f["trust_rank"],
            f["distance_km"] if f["distance_km"] is not None else 99999,
        )
    )

    trace = state.get("agent_trace") or []
    trace.append({
        "agent": "Evidence Scorer",
        "output": f"Scored {len(scored)} facilities",
        "latency_ms": round((time.time() - start) * 1000, 1),
    })
    return {**state, "scored_candidates": scored, "agent_trace": trace}


def enrich_node(state: ReferralState) -> ReferralState:
    """Agent 4: Enrich with district health context."""
    start = time.time()
    db = _current_db()
    location = state.get("location") or {}

    district_health = None
    if location.get("district"):
        raw = get_district_health(db, location["district"])
        if raw:
            district_health = {
                "district": raw.get("district_name"),
                "state": raw.get("state_ut"),
                "households_surveyed": raw.get("households_surveyed"),
                "institutional_birth_pct": raw.get("institutional_birth_5y_pct"),
                "health_insurance_pct": raw.get(
                    "hh_member_covered_health_insurance_pct"
                ),
                "women_anaemic_pct": raw.get("all_w15_49_who_are_anaemic_pct"),
            }

    trace = state.get("agent_trace") or []
    trace.append({
        "agent": "Context Enricher",
        "output": f"District health: {'loaded' if district_health else 'not found'}",
        "latency_ms": round((time.time() - start) * 1000, 1),
    })
    return {**state, "district_health": district_health, "agent_trace": trace}


def recommend_node(state: ReferralState) -> ReferralState:
    """Agent 5: Generate recommendation with CoT reasoning."""
    start = time.time()
    from .recommendation_agent import generate_recommendation

    rec = generate_recommendation(
        state.get("raw_query", ""),
        state.get("scored_candidates") or [],
        state.get("district_health"),
        state.get("specialty_terms") or [],
    )

    trace = state.get("agent_trace") or []
    trace.append({
        "agent": "Recommendation Generator",
        "reasoning": rec.get("reasoning", ""),
        "output": (rec.get("recommendation", "") or "")[:200],
        "method": rec.get("method"),
        "latency_ms": round((time.time() - start) * 1000, 1),
    })
    return {**state, "recommendation": rec.get("recommendation", ""), "agent_trace": trace}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(ReferralState)
    graph.add_node("parse_query", parse_query_node)
    graph.add_node("search", search_node)
    graph.add_node("score", score_node)
    graph.add_node("enrich", enrich_node)
    graph.add_node("recommend", recommend_node)

    graph.set_entry_point("parse_query")
    graph.add_edge("parse_query", "search")
    graph.add_edge("search", "score")
    graph.add_edge("score", "enrich")
    graph.add_edge("enrich", "recommend")
    graph.add_edge("recommend", END)
    return graph.compile()


referral_graph = build_graph()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run_referral_pipeline(db: DatabricksSQLClient, query: str) -> dict[str, Any]:
    """Run the LangGraph pipeline synchronously.

    Wrap this in ``asyncio.to_thread`` from async routes to avoid
    blocking the event loop.
    """
    tracer = ReferralTracer()
    tracer.start_run(query)

    token = set_db(db)
    try:
        result = referral_graph.invoke({
            "raw_query": query,
            "agent_trace": [],
        })
    finally:
        reset_db(token)

    scored = result.get("scored_candidates", []) or []
    if scored:
        avg_rank = sum(f["trust_rank"] for f in scored) / len(scored)
        tracer.log_results(len(scored), scored[0]["trust_signal"], avg_rank)
    for step in result.get("agent_trace") or []:
        tracer.log_agent(step.get("agent", "step"), step.get("latency_ms", 0))
    tracer.end_run()

    return {
        "query": {
            "raw_query": result.get("raw_query"),
            "capability_text": result.get("capability_text"),
            "location_text": result.get("location_text"),
            "specialty_terms": result.get("specialty_terms"),
            "location": result.get("location"),
            "urgency": result.get("urgency"),
        },
        "recommendation_summary": result.get("recommendation", ""),
        "result_count": len(scored),
        "facilities": scored,
        "district_health": result.get("district_health"),
        "agent_trace": result.get("agent_trace") or [],
    }
