"""Search API route."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from ..db import DatabricksSQLDependency
from ..pipeline.search_pipeline import run_search

router = APIRouter(tags=["search"])


class SearchRequest(BaseModel):
    query: str
    limit: int = 20


@router.post("/search")
async def search(body: SearchRequest, db: DatabricksSQLDependency):
    """Run the referral search pipeline.

    Accepts a natural language query like 'dialysis near Jaipur'
    and returns ranked, trust-scored facility results.
    """
    result = run_search(db, body.query, limit=body.limit)
    return result
