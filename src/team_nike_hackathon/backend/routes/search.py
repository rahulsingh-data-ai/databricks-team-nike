"""Search API route."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..agents.graph import run_referral_pipeline
from ..agents.supervisor import run_supervisor
from ..db import DatabricksSQLDependency

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=200)
    mode: str = Field(default="graph", pattern="^(graph|supervisor)$")
    session_id: str | None = Field(default=None, max_length=64)


@router.post("/search")
async def search(body: SearchRequest, db: DatabricksSQLDependency):
    """Run the referral search pipeline.

    Modes:
        - ``graph`` (default): LangGraph 5-node pipeline
        - ``supervisor``: LLM-driven dynamic tool-calling agent
    """
    if body.mode == "supervisor":
        return await run_supervisor(body.query, db, session_id=body.session_id)
    return await asyncio.to_thread(run_referral_pipeline, db, body.query)


@router.post("/agent/command")
async def agent_command(body: SearchRequest, db: DatabricksSQLDependency):
    """Supervisor agent endpoint — LLM decides which tools to use."""
    return await run_supervisor(body.query, db, session_id=body.session_id)
