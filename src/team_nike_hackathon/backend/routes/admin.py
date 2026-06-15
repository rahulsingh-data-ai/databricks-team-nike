"""Admin / telemetry route.

Exposes aggregate stats about the system: number of facilities by trust
signal, most-searched specialties (from Lakebase search_history when
available), and the list of supervisor tools.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlmodel import select

from ..agents.tools import TOOLS
from ..core.dependencies import Dependencies
from ..db import DatabricksSQLDependency
from ..db.databricks_sql import _fqn
from .shortlist import SearchHistoryItem

router = APIRouter(tags=["admin"])

FACILITIES_GOLD = _fqn("facilities_gold")


@router.get("/admin/telemetry")
async def telemetry(db: DatabricksSQLDependency):
    """Aggregate stats: trust-signal distribution + tool catalog."""
    rows = db.execute(
        f"""
        SELECT base_trust_signal, COUNT(*) as cnt
        FROM {FACILITIES_GOLD}
        WHERE base_trust_signal IS NOT NULL
        GROUP BY base_trust_signal
        ORDER BY cnt DESC
        """
    )
    total = sum((r.get("cnt") or 0) for r in rows)
    return {
        "trust_distribution": rows,
        "total_facilities": total,
        "tool_catalog": [
            {"name": t["name"], "description": t["description"]} for t in TOOLS
        ],
    }


@router.get("/admin/recent-searches")
async def recent_searches(
    session: Dependencies.Session,
    limit: int = Query(default=20, ge=1, le=200),
):
    """Most recent searches across all users (Lakebase)."""
    rows = session.exec(
        select(SearchHistoryItem)
        .order_by(SearchHistoryItem.created_at.desc())
        .limit(limit)
    ).all()
    return {"items": [r.model_dump() for r in rows], "count": len(rows)}
