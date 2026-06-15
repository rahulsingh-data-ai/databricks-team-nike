"""Admin / telemetry route.

Exposes aggregate stats about the system: number of facilities by trust
signal, most-searched specialties (from Lakebase search_history when
available), and the list of supervisor tools.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..agents.tools import TOOLS
from ..db import DatabricksSQLDependency
from ..db.databricks_sql import _fqn

router = APIRouter(tags=["admin"])

FACILITIES_GOLD = _fqn("facilities_gold")
SEARCH_HISTORY = _fqn("search_history")


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
    db: DatabricksSQLDependency,
    limit: int = Query(default=20, ge=1, le=200),
):
    """Most recent searches across all users (Delta search_history table)."""
    rows = db.execute(
        f"SELECT * FROM {SEARCH_HISTORY} "
        f"ORDER BY created_at DESC LIMIT {limit}"
    )
    return {"items": rows, "count": len(rows)}
