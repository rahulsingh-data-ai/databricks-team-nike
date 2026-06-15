"""Tool definitions and registry for the Referral Copilot supervisor.

Each tool is a JSON schema dict + a Python handler function.
The supervisor LLM decides which tools to call and in what order.
"""

from __future__ import annotations

import json
import time
import logging
from typing import Any, Callable

from ..db.databricks_sql import DatabricksSQLClient, _fqn, sql_str
from ..db.facility_queries import (
    resolve_location, search_facilities, get_facility_by_id,
    get_district_health, get_capabilities_list, get_desert_scores,
)
from ..db.vector_search import vector_search
from ..scoring.trust_scorer import score_facility
from ..scoring.evidence_formatter import format_evidence

COVERAGE_TABLE = _fqn("district_coverage_index")
GAPS_TABLE = _fqn("district_capability_gaps")
ALLOWED_GAP_STATUS = {"missing", "critical", "low", "available"}

logger = logging.getLogger(__name__)

# ============================================================
# Tool Schema Definitions (JSON for LLM)
# ============================================================

TOOLS = [
    {
        "name": "parse_query",
        "description": "Parse a natural language healthcare query into structured components: capability needed, location, urgency level.",
        "parameters": {
            "query": "string — the raw user query, e.g. 'dialysis near Jaipur'",
        },
    },
    {
        "name": "resolve_location",
        "description": "Resolve a location name (city, district, pincode) to coordinates and administrative region using India's pincode directory.",
        "parameters": {
            "location_text": "string — city name, district, or 6-digit pincode",
        },
    },
    {
        "name": "search_facilities",
        "description": "Search healthcare facilities by specialty and location. Returns facilities sorted by distance with trust signals.",
        "parameters": {
            "specialty_terms": "list[string] — medical specialties to search for, e.g. ['nephrology', 'dialysis']",
            "lat": "float | null — latitude of search center",
            "lon": "float | null — longitude of search center",
            "state": "string | null — state name filter",
            "district": "string | null — district/city name filter",
            "limit": "int — max results (default 20)",
        },
    },
    {
        "name": "vector_search",
        "description": "Semantic search across facility descriptions using embeddings. Finds facilities even if exact keywords don't match.",
        "parameters": {
            "query_text": "string — natural language search query",
            "num_results": "int — max results (default 20, max 200)",
            "filters": "dict | null — optional column filters, e.g. {\"address_stateOrRegion\": \"Rajasthan\"}",
        },
    },
    {
        "name": "score_evidence",
        "description": "Score a facility's evidence quality for a specific capability. Returns trust signal, evidence summary, and missing data.",
        "parameters": {
            "facility": "dict — facility record from search results",
            "search_terms": "list[string] — capability terms being searched",
        },
    },
    {
        "name": "get_facility_detail",
        "description": "Get the full record for a specific facility by ID, including all evidence fields.",
        "parameters": {
            "facility_id": "string — unique_id of the facility",
        },
    },
    {
        "name": "get_district_health",
        "description": "Get NFHS-5 district health indicators (institutional delivery rate, insurance coverage, anaemia, etc.) for context enrichment.",
        "parameters": {
            "district_name": "string — district name",
        },
    },
    {
        "name": "get_desert_scores",
        "description": "Get healthcare desert scores showing districts with high disease burden but low trusted facility coverage.",
        "parameters": {
            "limit": "int — max results (default 50)",
        },
    },
    {
        "name": "generate_recommendation",
        "description": "Generate a final recommendation summary based on scored facilities and district health context.",
        "parameters": {
            "query": "string — original user query",
            "facilities": "list[dict] — scored facility results",
            "district_health": "dict | null — NFHS-5 district context",
        },
    },
    {
        "name": "get_coverage_index",
        "description": "Get the Hospital Coverage Index for districts — trusted facilities per household surveyed. Shows which districts have the worst coverage.",
        "parameters": {
            "district_name": "string | null — specific district, or null for worst districts",
            "limit": "int — max results (default 20)",
        },
    },
    {
        "name": "get_capability_gaps",
        "description": "Find which medical specialties are missing in a district. Shows gaps like 'no nephrology in Bahraich district'.",
        "parameters": {
            "district_name": "string | null — district to check",
            "specialty": "string | null — specific specialty to check across districts",
            "limit": "int — max results (default 50)",
        },
    },
    {
        "name": "compare_facilities",
        "description": "Compare two facilities side-by-side with evidence diff, showing what each has that the other doesn't.",
        "parameters": {
            "facility_a": "string — unique_id of first facility",
            "facility_b": "string — unique_id of second facility",
            "capability": "string | null — capability to compare on",
        },
    },
    {
        "name": "build_citations",
        "description": "Build an explicit claim -> source URL map for a facility. Use this when the user asks 'why should I trust this?' or wants to see the evidence behind a claim.",
        "parameters": {
            "facility_id": "string — unique_id of the facility",
            "capability": "string | null — capability to highlight matching claims",
        },
    },
]


# ============================================================
# Tool Handler Functions
# ============================================================

def _tool_parse_query(args: dict, db: DatabricksSQLClient) -> dict:
    """Parse query into capability + location using the shared parser."""
    from .query_parser import parse_query

    return parse_query(db, args.get("query", ""))


def _tool_resolve_location(args: dict, db: DatabricksSQLClient) -> dict:
    result = resolve_location(db, args.get("location_text", ""))
    return result or {"error": "Location not found"}


def _tool_search_facilities(args: dict, db: DatabricksSQLClient) -> list[dict]:
    results = search_facilities(
        db,
        specialty_terms=args.get("specialty_terms", []),
        lat=args.get("lat"),
        lon=args.get("lon"),
        state=args.get("state"),
        district=args.get("district"),
        limit=args.get("limit", 20),
    )
    return results


def _tool_vector_search(args: dict, db: DatabricksSQLClient) -> list[dict]:
    filters = args.get("filters")
    if filters is not None and not isinstance(filters, dict):
        filters = None
    return vector_search(
        args.get("query_text", ""),
        num_results=args.get("num_results", 20),
        filters=filters,
    )


def _tool_score_evidence(args: dict, db: DatabricksSQLClient) -> dict:
    facility = args.get("facility", {})
    terms = args.get("search_terms", [])
    trust = score_facility(facility, terms)
    evidence = format_evidence(facility)
    return {**trust, "evidence": evidence}


def _tool_get_facility_detail(args: dict, db: DatabricksSQLClient) -> dict:
    result = get_facility_by_id(db, args.get("facility_id", ""))
    return result or {"error": "Facility not found"}


def _tool_get_district_health(args: dict, db: DatabricksSQLClient) -> dict:
    result = get_district_health(db, args.get("district_name", ""))
    return result or {"error": "District not found"}


def _tool_get_desert_scores(args: dict, db: DatabricksSQLClient) -> list[dict]:
    return get_desert_scores(db, limit=args.get("limit", 50))


def _tool_generate_recommendation(args: dict, db: DatabricksSQLClient) -> dict:
    from .recommendation_agent import generate_recommendation
    return generate_recommendation(
        args.get("query", ""),
        args.get("facilities", []),
        args.get("district_health"),
        args.get("search_terms", []),
        language=args.get("language", "en"),
    )


def _tool_get_coverage_index(args: dict, db: DatabricksSQLClient) -> list[dict]:
    district = args.get("district_name")
    limit = max(1, min(int(args.get("limit") or 20), 200))
    if district:
        return db.execute(
            f"SELECT * FROM {COVERAGE_TABLE} "
            f"WHERE district_name = {sql_str(district.strip().lower())} "
            f"LIMIT 1"
        )
    return db.execute(
        f"SELECT * FROM {COVERAGE_TABLE} ORDER BY coverage_index ASC LIMIT {limit}"
    )


def _tool_get_capability_gaps(args: dict, db: DatabricksSQLClient) -> list[dict]:
    parts: list[str] = []
    if args.get("district_name"):
        parts.append(
            f"district_name = {sql_str(args['district_name'].strip().lower())}"
        )
    if args.get("specialty"):
        parts.append(
            f"specialty = {sql_str(args['specialty'].strip().lower())}"
        )
    where = "WHERE " + " AND ".join(parts) if parts else ""
    limit = max(1, min(int(args.get("limit") or 50), 200))
    return db.execute(
        f"SELECT * FROM {GAPS_TABLE} {where} ORDER BY gap_status LIMIT {limit}"
    )


def _tool_compare_facilities(args: dict, db: DatabricksSQLClient) -> dict:
    a = get_facility_by_id(db, args.get("facility_a", ""))
    b = get_facility_by_id(db, args.get("facility_b", ""))
    if not a or not b:
        return {"error": "One or both facilities not found"}
    cap = args.get("capability")
    terms = [cap] if cap else []
    score_a = score_facility(a, terms)
    score_b = score_facility(b, terms)
    return {
        "facility_a": {"name": a.get("name"), "trust": score_a},
        "facility_b": {"name": b.get("name"), "trust": score_b},
    }


def _tool_build_citations(args: dict, db: DatabricksSQLClient) -> dict:
    from ..scoring.citations import build_citations

    facility = get_facility_by_id(db, args.get("facility_id", ""))
    if not facility:
        return {"error": "Facility not found"}
    capability = args.get("capability")
    return build_citations(facility, [capability] if capability else [])


# ============================================================
# Tool Registry
# ============================================================

TOOL_REGISTRY: dict[str, Callable] = {
    "parse_query": _tool_parse_query,
    "resolve_location": _tool_resolve_location,
    "search_facilities": _tool_search_facilities,
    "vector_search": _tool_vector_search,
    "score_evidence": _tool_score_evidence,
    "get_facility_detail": _tool_get_facility_detail,
    "get_district_health": _tool_get_district_health,
    "get_desert_scores": _tool_get_desert_scores,
    "generate_recommendation": _tool_generate_recommendation,
    "get_coverage_index": _tool_get_coverage_index,
    "get_capability_gaps": _tool_get_capability_gaps,
    "compare_facilities": _tool_compare_facilities,
    "build_citations": _tool_build_citations,
}


def get_tools_description() -> str:
    """Format tools for injection into supervisor prompt."""
    lines = []
    for tool in TOOLS:
        params = ", ".join(f"{k}: {v}" for k, v in tool["parameters"].items())
        lines.append(f"- {tool['name']}({params}): {tool['description']}")
    return "\n".join(lines)


def execute_tool(tool_name: str, args: dict, db: DatabricksSQLClient) -> dict:
    """Execute a tool by name. Returns result + timing."""
    handler = TOOL_REGISTRY.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}

    start = time.time()
    try:
        result = handler(args, db)
        latency_ms = (time.time() - start) * 1000
        return {"result": result, "latency_ms": round(latency_ms, 1)}
    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        logger.error(f"Tool {tool_name} failed: {e}")
        return {"error": str(e), "latency_ms": round(latency_ms, 1)}
