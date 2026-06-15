"""Main search pipeline: parse -> search -> score -> rank -> recommend.

Agentic version with Chain-of-Thought reasoning at each step.
Each agent's reasoning is captured and returned to the UI for transparency.
"""

from __future__ import annotations

from typing import Any

from ..db.databricks_sql import DatabricksSQLClient
from ..db.facility_queries import search_facilities, get_district_health
from ..scoring.trust_scorer import score_facility, TrustSignal
from ..scoring.evidence_formatter import format_evidence
from ..agents.query_agent import parse_query_with_llm
from ..agents.evidence_agent import score_evidence_with_llm
from ..agents.recommendation_agent import generate_recommendation
from ..pipeline.query_parser import parse_query as keyword_parse


def run_search(
    db: DatabricksSQLClient,
    raw_query: str,
    limit: int = 20,
    use_agents: bool = True,
) -> dict[str, Any]:
    """Execute the full referral search pipeline.

    Steps:
        1. Agent 1 (Query Parser): LLM with CoT extracts capability + location
        2. SQL Search: query silver/gold tables
        3. Rule-based scoring: fast trust classification for all results
        4. Agent 2 (Evidence Scorer): LLM deep-evaluates top 5 facilities
        5. Rank: trust signal (primary) then distance (secondary)
        6. Agent 3 (Recommender): LLM generates recommendation with reasoning

    All agent reasoning is captured in the response for UI transparency.
    """
    agent_trace = []

    # Step 1: Parse query
    if use_agents:
        parsed = parse_query_with_llm(db, raw_query)
        agent_trace.append({
            "agent": "Query Parser",
            "reasoning": parsed.get("reasoning", ""),
            "method": parsed.get("method", ""),
            "output": {
                "capability": parsed.get("capability_text"),
                "location": parsed.get("location_text"),
                "specialties": parsed.get("specialty_terms"),
            },
        })
    else:
        parsed = keyword_parse(db, raw_query)

    # Step 2: Search facilities
    location = parsed.get("location")
    candidates = search_facilities(
        db,
        specialty_terms=parsed["specialty_terms"],
        lat=location["latitude"] if location else None,
        lon=location["longitude"] if location else None,
        state=location["state"] if location else None,
        district=location["district"] if location else None,
        limit=limit,
    )

    # Step 3: Rule-based scoring for all candidates
    scored = []
    for facility in candidates:
        trust = score_facility(facility, parsed["specialty_terms"])
        evidence = format_evidence(facility)

        scored.append({
            "unique_id": facility["unique_id"],
            "name": facility["name"],
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
        })

    # Step 4: LLM evidence scoring for top facilities
    if use_agents and scored:
        llm_scores = score_evidence_with_llm(
            candidates[:5],
            parsed["specialty_terms"],
            max_facilities=5,
        )

        llm_score_map = {s["unique_id"]: s for s in llm_scores}
        for f in scored:
            if f["unique_id"] in llm_score_map:
                llm = llm_score_map[f["unique_id"]]
                f["trust_signal"] = llm["trust_signal"]
                f["evidence_summary"] = llm["evidence_summary"]
                f["missing_evidence"] = llm["missing_evidence"]
                f["agent_reasoning"] = llm.get("reasoning", "")
                f["scoring_method"] = llm.get("method", "")

                # Update trust rank based on LLM signal
                rank_map = {
                    "strong_evidence": 5, "partial_evidence": 4,
                    "weak_evidence": 3, "suspicious": 2, "no_evidence": 1,
                }
                f["trust_rank"] = rank_map.get(llm["trust_signal"], 1)

        agent_trace.append({
            "agent": "Evidence Scorer",
            "facilities_scored": len(llm_scores),
            "method": llm_scores[0].get("method", "") if llm_scores else "",
            "sample_reasoning": llm_scores[0].get("reasoning", "") if llm_scores else "",
        })

    # Step 5: Rank by trust (descending) then distance (ascending)
    scored.sort(key=lambda f: (
        -f["trust_rank"],
        f["distance_km"] if f["distance_km"] is not None else 99999,
    ))

    # Step 6: District health context
    district_health = None
    district_health_formatted = None
    if location and location.get("district"):
        district_health = get_district_health(db, location["district"])
        district_health_formatted = _format_district_health(district_health)

    # Step 7: Generate recommendation
    if use_agents:
        rec = generate_recommendation(
            raw_query, scored, district_health_formatted,
            parsed["specialty_terms"],
        )
        recommendation_summary = rec["recommendation"]
        agent_trace.append({
            "agent": "Recommendation Generator",
            "reasoning": rec.get("reasoning", ""),
            "method": rec.get("method", ""),
        })
    else:
        recommendation_summary = _template_summary(scored, parsed, district_health_formatted)

    return {
        "query": parsed,
        "recommendation_summary": recommendation_summary,
        "result_count": len(scored),
        "facilities": scored,
        "district_health": district_health_formatted,
        "agent_trace": agent_trace,
    }


def _template_summary(scored, parsed, district_health):
    """Fallback template summary when agents are disabled."""
    total = len(scored)
    strong = sum(1 for f in scored if f["trust_signal"] == TrustSignal.STRONG.value)
    partial = sum(1 for f in scored if f["trust_signal"] == TrustSignal.PARTIAL.value)
    loc_str = parsed.get("location_text") or "the searched area"
    cap_str = parsed.get("capability_text") or parsed.get("raw_query", "")

    summary = f"Found {total} facilities for '{cap_str}' near {loc_str}. "
    summary += f"{strong} with strong evidence, {partial} with partial evidence."

    if district_health:
        inst = district_health.get("institutional_birth_pct")
        if inst:
            summary += f" District institutional delivery rate: {inst}%."
    return summary


def _format_district_health(data: dict | None) -> dict | None:
    if not data:
        return None
    return {
        "district": data.get("district_name"),
        "state": data.get("state_ut"),
        "households_surveyed": data.get("households_surveyed"),
        "institutional_birth_pct": data.get("institutional_birth_5y_pct"),
        "health_insurance_pct": data.get("hh_member_covered_health_insurance_pct"),
        "women_anaemic_pct": data.get("all_w15_49_who_are_anaemic_pct"),
        "clean_fuel_pct": data.get("households_using_clean_fuel_for_cooking_pct"),
        "improved_sanitation_pct": data.get("hh_use_improved_sanitation_pct"),
    }
