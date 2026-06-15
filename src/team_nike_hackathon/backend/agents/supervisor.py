"""Referral Copilot Supervisor — orchestrates tool-calling agent.

The supervisor receives a user command, asks the LLM which tools to call,
executes them, and returns results. Each tool call is traced.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .llm_client import call_llm, parse_json_from_llm
from .tools import TOOL_REGISTRY, execute_tool, get_tools_description
from ..utils.prompt_loader import load_prompt
from ..db.databricks_sql import DatabricksSQLClient

logger = logging.getLogger(__name__)


async def run_supervisor(
    command: str,
    db: DatabricksSQLClient,
) -> dict[str, Any]:
    """Run the supervisor agent: LLM decides tools → execute → return.

    Returns:
        {
            "tool_calls": [{"tool": ..., "args": ..., "result": ..., "latency_ms": ...}],
            "final_output": ...,
            "total_latency_ms": ...,
            "agent_trace": [...],
        }
    """
    start = time.time()
    agent_trace = []

    # Build supervisor prompt with tool descriptions
    system_prompt = load_prompt("supervisor").replace("{tools}", get_tools_description())

    # Ask LLM what tools to call
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": command},
    ]

    try:
        response = call_llm(messages, max_tokens=800, temperature=0.0)
        tool_calls_raw = parse_json_from_llm(response["content"])
    except Exception as e:
        logger.error(f"Supervisor LLM failed: {e}")
        tool_calls_raw = _default_tool_plan(command)

    if not isinstance(tool_calls_raw, list):
        tool_calls_raw = _default_tool_plan(command)

    # Execute each tool call
    executed = []
    context = {}  # Accumulated state from tool outputs

    for tc in tool_calls_raw:
        tool_name = tc.get("tool", "")
        args = tc.get("args", {})

        # Inject context from previous tool outputs
        args = _inject_context(tool_name, args, context)

        result = execute_tool(tool_name, args, db)
        executed.append({
            "tool": tool_name,
            "args": _safe_args(args),
            "result_summary": _summarize_result(result.get("result")),
            "latency_ms": result.get("latency_ms", 0),
            "success": "error" not in result,
        })

        # Store output for downstream tools
        if "error" not in result:
            context[tool_name] = result["result"]

        agent_trace.append({
            "agent": f"Tool: {tool_name}",
            "latency_ms": result.get("latency_ms", 0),
            "success": "error" not in result,
        })

    total_ms = (time.time() - start) * 1000

    return {
        "tool_calls": executed,
        "context": context,
        "total_latency_ms": round(total_ms, 1),
        "agent_trace": agent_trace,
    }


def _default_tool_plan(command: str) -> list[dict]:
    """Fallback tool plan when LLM fails to produce one."""
    return [
        {"tool": "parse_query", "args": {"query": command}},
        {"tool": "search_facilities", "args": {}},
        {"tool": "generate_recommendation", "args": {}},
    ]


def _inject_context(tool_name: str, args: dict, context: dict) -> dict:
    """Inject outputs from previous tools into the current tool's args."""
    parsed = context.get("parse_query", {})

    if tool_name == "search_facilities" and "specialty_terms" not in args:
        if parsed:
            loc = parsed.get("location", {}) or {}
            args.setdefault("specialty_terms", parsed.get("specialty_terms", []))
            args.setdefault("lat", loc.get("latitude"))
            args.setdefault("lon", loc.get("longitude"))
            args.setdefault("state", loc.get("state"))
            args.setdefault("district", loc.get("district"))

    if tool_name == "vector_search" and "query_text" not in args:
        args.setdefault("query_text", parsed.get("capability_text", ""))

    if tool_name == "get_district_health" and "district_name" not in args:
        loc = parsed.get("location", {}) or {}
        args.setdefault("district_name", loc.get("district", ""))

    if tool_name == "generate_recommendation":
        args.setdefault("query", parsed.get("capability_text", ""))
        if "search_facilities" in context:
            args.setdefault("facilities", context["search_facilities"][:10])
        if "get_district_health" in context:
            args.setdefault("district_health", context["get_district_health"])
        args.setdefault("search_terms", parsed.get("specialty_terms", []))

    return args


def _safe_args(args: dict) -> dict:
    """Truncate large args for trace display."""
    safe = {}
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
    """Summarize a tool result for trace display."""
    if result is None:
        return "null"
    if isinstance(result, list):
        return f"[{len(result)} items]"
    if isinstance(result, dict):
        keys = list(result.keys())[:5]
        return f"{{{', '.join(keys)}{'...' if len(result) > 5 else ''}}}"
    return str(result)[:100]
