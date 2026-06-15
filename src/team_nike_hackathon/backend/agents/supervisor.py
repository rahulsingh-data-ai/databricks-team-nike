"""Referral Copilot Supervisor — orchestrates tool-calling agent.

The supervisor receives a user command, asks the LLM which tools to
call, executes them, and *always* finishes with a synthesized
recommendation (even if the LLM forgot to add it to its tool plan).
Each tool call is traced through MLflow when configured.

A lightweight in-memory session store lets callers thread multiple
queries together by passing the same ``session_id``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from ..db.databricks_sql import DatabricksSQLClient
from ..utils.mlflow_tracer import ReferralTracer
from ..utils.prompt_loader import load_prompt
from .llm_client import call_llm, parse_json_from_llm
from .tools import TOOL_REGISTRY, execute_tool, get_tools_description

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session memory (in-memory, process-local; swap for Lakebase later)
# ---------------------------------------------------------------------------

_SESSION_LOCK = threading.Lock()
_SESSIONS: dict[str, dict[str, Any]] = {}
_SESSION_MAX_TURNS = 10


def _session_get(session_id: str | None) -> dict[str, Any]:
    if not session_id:
        return {}
    with _SESSION_LOCK:
        return dict(_SESSIONS.get(session_id, {}))


def _session_set(session_id: str | None, data: dict[str, Any]):
    if not session_id:
        return
    with _SESSION_LOCK:
        existing = _SESSIONS.get(session_id, {})
        history = existing.get("history", [])
        history.append({
            "query": data.get("query"),
            "capability_text": data.get("capability_text"),
            "location_text": data.get("location_text"),
            "result_count": data.get("result_count"),
            "ts": time.time(),
        })
        existing.update(data)
        existing["history"] = history[-_SESSION_MAX_TURNS:]
        _SESSIONS[session_id] = existing


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------

async def run_supervisor(
    command: str,
    db: DatabricksSQLClient,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Run the supervisor agent.

    Steps:
        1. LLM decides which tools to call.
        2. Each tool runs sequentially, with outputs injected into
           later tools' args.
        3. If the LLM never asked for ``generate_recommendation``, we
           call it as a final step so the response always contains a
           synthesized answer.
        4. Trace everything (MLflow opt-in).
    """
    start = time.time()
    tracer = ReferralTracer()
    tracer.start_run(command)

    session_context = _session_get(session_id)

    system_prompt = load_prompt("supervisor").replace(
        "{tools}", get_tools_description()
    )

    user_message = command
    if session_context.get("history"):
        prior = "\n".join(
            f"- {h.get('query')} -> {h.get('result_count')} results"
            for h in session_context["history"][-3:]
        )
        user_message = f"Previous queries in this session:\n{prior}\n\nNew query: {command}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        response = call_llm(messages, max_tokens=800, temperature=0.0)
        tool_calls_raw = parse_json_from_llm(response["content"])
    except Exception as e:
        logger.warning(f"Supervisor LLM failed, using default plan: {e}")
        tool_calls_raw = _default_tool_plan(command)

    if not isinstance(tool_calls_raw, list):
        tool_calls_raw = _default_tool_plan(command)

    executed: list[dict[str, Any]] = []
    context: dict[str, Any] = {}

    for tc in tool_calls_raw:
        if not isinstance(tc, dict):
            continue
        tool_name = tc.get("tool", "")
        if tool_name not in TOOL_REGISTRY:
            executed.append({
                "tool": tool_name,
                "success": False,
                "result_summary": f"unknown tool '{tool_name}'",
                "latency_ms": 0,
            })
            continue
        args = dict(tc.get("args") or {})
        args = _inject_context(tool_name, args, context, command)

        result = execute_tool(tool_name, args, db)
        success = "error" not in result
        executed.append({
            "tool": tool_name,
            "args": _safe_args(args),
            "result_summary": _summarize_result(result.get("result")),
            "latency_ms": result.get("latency_ms", 0),
            "success": success,
        })
        if success:
            context[tool_name] = result["result"]
        tracer.log_agent(f"tool_{tool_name}", result.get("latency_ms", 0))

    # Always finish with a recommendation if we have facilities.
    if "generate_recommendation" not in context and "search_facilities" in context:
        rec_args = _inject_context("generate_recommendation", {}, context, command)
        rec_result = execute_tool("generate_recommendation", rec_args, db)
        if "error" not in rec_result:
            context["generate_recommendation"] = rec_result["result"]
            executed.append({
                "tool": "generate_recommendation",
                "args": _safe_args(rec_args),
                "result_summary": "auto-invoked",
                "latency_ms": rec_result.get("latency_ms", 0),
                "success": True,
                "auto_invoked": True,
            })
            tracer.log_agent("tool_generate_recommendation", rec_result.get("latency_ms", 0))

    parse_out = context.get("parse_query", {}) or {}
    facilities = context.get("search_facilities") or []
    if isinstance(facilities, list):
        facilities = facilities[:20]
    rec = context.get("generate_recommendation") or {}
    final_answer = rec.get("recommendation") if isinstance(rec, dict) else None

    _session_set(session_id, {
        "query": command,
        "capability_text": parse_out.get("capability_text"),
        "location_text": parse_out.get("location_text"),
        "result_count": len(facilities) if isinstance(facilities, list) else 0,
    })

    if facilities and isinstance(facilities, list):
        tracer.log_results(
            len(facilities),
            (facilities[0].get("base_trust_signal") or facilities[0].get("trust_signal") or "unknown"),
            0.0,
        )
    tracer.end_run()

    return {
        "query": command,
        "session_id": session_id,
        "tool_calls": executed,
        "final_recommendation": final_answer,
        "parsed_query": parse_out,
        "facilities": facilities,
        "district_health": context.get("get_district_health"),
        "total_latency_ms": round((time.time() - start) * 1000, 1),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_tool_plan(command: str) -> list[dict]:
    return [
        {"tool": "parse_query", "args": {"query": command}},
        {"tool": "search_facilities", "args": {}},
        {"tool": "get_district_health", "args": {}},
        {"tool": "generate_recommendation", "args": {}},
    ]


def _inject_context(
    tool_name: str,
    args: dict,
    context: dict,
    command: str,
) -> dict:
    """Inject outputs from previous tools into the current tool's args."""
    parsed = context.get("parse_query") or {}
    loc = (parsed.get("location") or {}) if isinstance(parsed, dict) else {}

    if tool_name == "parse_query":
        args.setdefault("query", command)

    if tool_name == "search_facilities":
        args.setdefault("specialty_terms", parsed.get("specialty_terms", []))
        args.setdefault("lat", loc.get("latitude"))
        args.setdefault("lon", loc.get("longitude"))
        args.setdefault("state", loc.get("state"))
        args.setdefault("district", loc.get("district"))

    if tool_name == "vector_search":
        args.setdefault("query_text", parsed.get("capability_text", command))
        if loc.get("state") and "filters" not in args:
            args["filters"] = {"address_stateOrRegion": loc["state"]}

    if tool_name == "get_district_health":
        args.setdefault("district_name", loc.get("district", ""))

    if tool_name == "get_coverage_index":
        args.setdefault("district_name", loc.get("district"))

    if tool_name == "get_capability_gaps":
        args.setdefault("district_name", loc.get("district"))
        if parsed.get("specialty_terms"):
            args.setdefault("specialty", parsed["specialty_terms"][0])

    if tool_name == "generate_recommendation":
        args.setdefault("query", parsed.get("capability_text", command))
        if "search_facilities" in context:
            args.setdefault("facilities", (context["search_facilities"] or [])[:10])
        if "get_district_health" in context:
            args.setdefault("district_health", context["get_district_health"])
        args.setdefault("search_terms", parsed.get("specialty_terms", []))
        args.setdefault("language", parsed.get("language", "en"))

    return args


def _safe_args(args: dict) -> dict:
    safe: dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, list) and len(v) > 3:
            safe[k] = f"[{len(v)} items]"
        elif isinstance(v, str) and len(v) > 100:
            safe[k] = v[:100] + "..."
        elif isinstance(v, dict) and len(str(v)) > 200:
            safe[k] = "{...truncated...}"
        else:
            safe[k] = v
    return safe


def _summarize_result(result: Any) -> str:
    if result is None:
        return "null"
    if isinstance(result, list):
        return f"[{len(result)} items]"
    if isinstance(result, dict):
        keys = list(result.keys())[:5]
        return f"{{{', '.join(keys)}{'...' if len(result) > 5 else ''}}}"
    return str(result)[:100]
