"""LangGraph pipeline for the Referral Copilot.

Defines a StateGraph with nodes for each agent step.
The graph can be invoked synchronously or streamed for SSE.
"""

from __future__ import annotations

import time
import logging
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from ..db.databricks_sql import DatabricksSQLClient
from ..db.facility_queries import (
    search_facilities, get_district_health, resolve_location,
    map_query_to_specialties,
)
from ..db.vector_search import hybrid_search
from ..scoring.trust_scorer import score_facility
from ..scoring.evidence_formatter import format_evidence
from ..utils.mlflow_tracer import ReferralTracer

logger = logging.getLogger(__name__)


class ReferralState(TypedDict, total=False):
    raw_query: str
    db: Any
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


# ============================================================
# Node Functions
# ============================================================

def parse_query_node(state: ReferralState) -> ReferralState:
    """Agent 1: Parse the user query into structured components."""
    start = time.time()
    db = state["db"]
    query = state["raw_query"]

    from .llm_client import call_llm, parse_json_from_llm
    from ..utils.prompt_loader import load_prompt
    import re

    system_prompt = load_prompt("query_parser")
    try:
        response = call_llm(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": query}],
            max_tokens=500, temperature=0.1,
        )
        content = response["content"]

        thinking = ""
        think_match = re.search(r'<thinking>(.*?)</thinking>', content, re.DOTALL | re.IGNORECASE)
        if think_match:
            thinking = think_match.group(1).strip()

        answer_match = re.search(r'<answer>(.*?)</answer>', content, re.DOTALL | re.IGNORECASE)
        answer_text = answer_match.group(1).strip() if answer_match else content
        parsed = parse_json_from_llm(answer_text)
    except Exception as e:
        parsed = None
        thinking = f"LLM failed: {e}"

    if parsed and "capability" in parsed:
        capability_text = parsed["capability"]
        location_text = parsed.get("location", "")
        urgency = parsed.get("urgency", "routine")
    else:
        # Keyword fallback
        capability_text = query
        location_text = ""
        urgency = "routine"
        for prep in ["near", "in", "around", "close to", "at"]:
            match = re.search(rf"\b{prep}\b", query, re.IGNORECASE)
            if match:
                capability_text = query[:match.start()].strip()
                location_text = query[match.end():].strip()
                break

    specialty_terms = map_query_to_specialties(capability_text)
    location = resolve_location(db, location_text) if location_text else None

    latency = (time.time() - start) * 1000
    trace = state.get("agent_trace", [])
    trace.append({
        "agent": "Query Parser",
        "reasoning": thinking,
        "output": {"capability": capability_text, "location": location_text, "urgency": urgency},
        "latency_ms": round(latency, 1),
    })

    return {
        **state,
        "capability_text": capability_text,
        "location_text": location_text,
        "specialty_terms": specialty_terms,
        "location": location,
        "urgency": urgency,
        "agent_trace": trace,
    }


def search_node(state: ReferralState) -> ReferralState:
    """Agent 2: Search facilities using keyword SQL + vector hybrid."""
    start = time.time()
    db = state["db"]
    location = state.get("location")

    # Keyword search
    candidates = search_facilities(
        db,
        specialty_terms=state.get("specialty_terms", []),
        lat=location["latitude"] if location else None,
        lon=location["longitude"] if location else None,
        state=location["state"] if location else None,
        district=location["district"] if location else None,
        limit=20,
    )

    # Hybrid: merge with vector search
    state_filter = {"address_stateOrRegion": location["state"]} if location and location.get("state") else None
    candidates = hybrid_search(
        state["raw_query"], candidates,
        num_vector_results=20, filters=state_filter,
    )

    latency = (time.time() - start) * 1000
    trace = state.get("agent_trace", [])
    trace.append({
        "agent": "Facility Search",
        "output": f"Found {len(candidates)} candidates (keyword + vector hybrid)",
        "latency_ms": round(latency, 1),
    })

    return {**state, "candidates": candidates, "agent_trace": trace}


def score_node(state: ReferralState) -> ReferralState:
    """Agent 3: Score evidence and rank facilities."""
    start = time.time()
    candidates = state.get("candidates", [])
    search_terms = state.get("specialty_terms", [])

    scored = []
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
            "distance_km": round(facility.get("distance_km") or 0, 1) if facility.get("distance_km") else None,
            "trust_signal": trust["trust_signal"],
            "trust_rank": trust["trust_rank"],
            "evidence_summary": trust["evidence_summary"],
            "missing_evidence": trust["missing_evidence"],
            "source_count": trust["source_count"],
            "evidence": evidence,
            "search_method": facility.get("search_method", "keyword"),
        })

    # LLM-score top 5
    from .evidence_agent import score_evidence_with_llm
    if scored:
        llm_scores = score_evidence_with_llm(candidates[:5], search_terms, max_facilities=5)
        llm_map = {s["unique_id"]: s for s in llm_scores}
        rank_map = {"strong_evidence": 5, "partial_evidence": 4, "weak_evidence": 3, "suspicious": 2, "no_evidence": 1}
        for f in scored:
            if f["unique_id"] in llm_map:
                llm = llm_map[f["unique_id"]]
                f["trust_signal"] = llm["trust_signal"]
                f["trust_rank"] = rank_map.get(llm["trust_signal"], 1)
                f["evidence_summary"] = llm["evidence_summary"]
                f["missing_evidence"] = llm["missing_evidence"]
                f["agent_reasoning"] = llm.get("reasoning", "")
                f["scoring_method"] = llm.get("method", "")

    # Rank: trust descending, distance ascending
    scored.sort(key=lambda f: (-f["trust_rank"], f["distance_km"] if f["distance_km"] is not None else 99999))

    latency = (time.time() - start) * 1000
    trace = state.get("agent_trace", [])
    trace.append({
        "agent": "Evidence Scorer",
        "output": f"Scored {len(scored)} facilities, top 5 via LLM",
        "latency_ms": round(latency, 1),
    })

    return {**state, "scored_candidates": scored, "agent_trace": trace}


def enrich_node(state: ReferralState) -> ReferralState:
    """Agent 4: Enrich with district health context."""
    start = time.time()
    db = state["db"]
    location = state.get("location")

    district_health = None
    if location and location.get("district"):
        raw = get_district_health(db, location["district"])
        if raw:
            district_health = {
                "district": raw.get("district_name"),
                "state": raw.get("state_ut"),
                "households_surveyed": raw.get("households_surveyed"),
                "institutional_birth_pct": raw.get("institutional_birth_5y_pct"),
                "health_insurance_pct": raw.get("hh_member_covered_health_insurance_pct"),
                "women_anaemic_pct": raw.get("all_w15_49_who_are_anaemic_pct"),
            }

    latency = (time.time() - start) * 1000
    trace = state.get("agent_trace", [])
    trace.append({
        "agent": "Context Enricher",
        "output": f"District health: {'loaded' if district_health else 'not found'}",
        "latency_ms": round(latency, 1),
    })

    return {**state, "district_health": district_health, "agent_trace": trace}


def recommend_node(state: ReferralState) -> ReferralState:
    """Agent 5: Generate recommendation with CoT reasoning."""
    start = time.time()

    from .recommendation_agent import generate_recommendation
    rec = generate_recommendation(
        state.get("raw_query", ""),
        state.get("scored_candidates", []),
        state.get("district_health"),
        state.get("specialty_terms", []),
    )

    latency = (time.time() - start) * 1000
    trace = state.get("agent_trace", [])
    trace.append({
        "agent": "Recommendation Generator",
        "reasoning": rec.get("reasoning", ""),
        "output": rec.get("recommendation", "")[:200],
        "latency_ms": round(latency, 1),
    })

    return {**state, "recommendation": rec.get("recommendation", ""), "agent_trace": trace}


# ============================================================
# Build Graph
# ============================================================

def build_graph() -> StateGraph:
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


# ============================================================
# Entry Points
# ============================================================

def run_referral_pipeline(db: DatabricksSQLClient, query: str) -> dict[str, Any]:
    """Run the full LangGraph referral pipeline synchronously."""
    tracer = ReferralTracer()
    tracer.start_run(query)

    initial_state: ReferralState = {
        "raw_query": query,
        "db": db,
        "agent_trace": [],
    }

    result = referral_graph.invoke(initial_state)

    # Log to MLflow
    scored = result.get("scored_candidates", [])
    if scored:
        avg_rank = sum(f["trust_rank"] for f in scored) / len(scored)
        tracer.log_results(len(scored), scored[0]["trust_signal"], avg_rank)
    for step in result.get("agent_trace", []):
        tracer.log_agent(step["agent"], step.get("latency_ms", 0))
    tracer.end_run()

    # Clean db reference from output
    result.pop("db", None)

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
        "result_count": len(result.get("scored_candidates", [])),
        "facilities": result.get("scored_candidates", []),
        "district_health": result.get("district_health"),
        "agent_trace": result.get("agent_trace", []),
    }
