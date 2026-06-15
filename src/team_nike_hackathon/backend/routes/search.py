"""Search API route."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from ..db import DatabricksSQLDependency
from ..agents.graph import run_referral_pipeline
from ..agents.supervisor import run_supervisor

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str
    limit: int = 20
    mode: str = "graph"


@router.post("/search")
async def search(body: SearchRequest, db: DatabricksSQLDependency):
    """Run the referral search pipeline.

    Accepts a natural language query like 'dialysis near Jaipur'
    and returns ranked, trust-scored facility results.

    Modes:
        - "graph": LangGraph 5-agent pipeline (default)
        - "supervisor": Supervisor agent with dynamic tool selection
    """
    if body.mode == "supervisor":
        return await run_supervisor(body.query, db)
    return run_referral_pipeline(db, body.query)


@router.post("/agent/command")
async def agent_command(body: SearchRequest, db: DatabricksSQLDependency):
    """Supervisor agent endpoint — LLM decides which tools to use."""
    return await run_supervisor(body.query, db)
