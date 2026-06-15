"""Streaming agent endpoint: SSE events as each pipeline node completes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..agents.graph import (
    ReferralState,
    enrich_node,
    parse_query_node,
    recommend_node,
    reset_db,
    score_node,
    search_node,
    set_db,
)
from ..db import DatabricksSQLDependency

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


class StreamRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)


async def _stream_pipeline(query: str, db) -> AsyncGenerator[str, None]:
    """Run pipeline nodes sequentially, emitting SSE events after each."""
    state: ReferralState = {"raw_query": query, "agent_trace": []}

    nodes = [
        ("parse_query", "Parsing your query...", parse_query_node),
        ("search", "Searching facilities...", search_node),
        ("score", "Scoring evidence...", score_node),
        ("enrich", "Loading district health context...", enrich_node),
        ("recommend", "Generating recommendation...", recommend_node),
    ]

    yield _sse_event("pipeline_start", {"query": query, "steps": len(nodes)})

    token = set_db(db)
    try:
        for i, (name, status_msg, node_fn) in enumerate(nodes, 1):
            yield _sse_event(
                "step_start",
                {"step": i, "name": name, "message": status_msg},
            )

            start = time.time()
            try:
                # Run sync node in a worker thread so we don't block the event loop.
                state = await asyncio.to_thread(node_fn, state)
                latency_ms = round((time.time() - start) * 1000, 1)
                yield _sse_event(
                    "step_complete",
                    {
                        "step": i,
                        "name": name,
                        "latency_ms": latency_ms,
                        "output": _get_step_output(name, state),
                    },
                )
            except Exception as e:  # noqa: BLE001
                logger.exception(f"Stream step {name} failed")
                yield _sse_event(
                    "step_error",
                    {"step": i, "name": name, "error": str(e)},
                )
    finally:
        reset_db(token)

    yield _sse_event(
        "pipeline_complete",
        {
            "result_count": len(state.get("scored_candidates") or []),
            "recommendation": state.get("recommendation", ""),
            "agent_trace": state.get("agent_trace") or [],
        },
    )

    yield _sse_event(
        "result",
        {
            "query": {
                "raw_query": state.get("raw_query"),
                "capability_text": state.get("capability_text"),
                "location_text": state.get("location_text"),
                "specialty_terms": state.get("specialty_terms"),
                "location": state.get("location"),
            },
            "recommendation_summary": state.get("recommendation", ""),
            "result_count": len(state.get("scored_candidates") or []),
            "facilities": (state.get("scored_candidates") or [])[:20],
            "district_health": state.get("district_health"),
            "agent_trace": state.get("agent_trace") or [],
        },
    )


def _get_step_output(name: str, state: ReferralState) -> dict:
    """Extract summary output for SSE event."""
    if name == "parse_query":
        return {
            "capability": state.get("capability_text"),
            "location": state.get("location_text"),
            "specialties": (state.get("specialty_terms") or [])[:5],
        }
    if name == "search":
        return {"candidates_found": len(state.get("candidates") or [])}
    if name == "score":
        scored = state.get("scored_candidates") or []
        return {
            "scored": len(scored),
            "top_facility": scored[0].get("name") if scored else None,
            "top_trust": scored[0].get("trust_signal") if scored else None,
        }
    if name == "enrich":
        dh = state.get("district_health") or {}
        return {"district": dh.get("district")}
    if name == "recommend":
        return {"recommendation": (state.get("recommendation") or "")[:200]}
    return {}


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    json_data = json.dumps({"type": event_type, **data}, default=str)
    return f"event: {event_type}\ndata: {json_data}\n\n"


@router.post("/stream")
async def stream_search(body: StreamRequest, db: DatabricksSQLDependency):
    """Stream the referral pipeline with SSE events per agent step."""
    return StreamingResponse(
        _stream_pipeline(body.query, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
