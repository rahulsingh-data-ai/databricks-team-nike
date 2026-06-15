"""Health check API route."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import DatabricksSQLDependency

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DatabricksSQLDependency):
    """Full system health check."""
    db_health = db.health_check()
    return {
        "databricks": db_health,
        "status": "ok" if db_health["status"] == "connected" else "degraded",
    }
