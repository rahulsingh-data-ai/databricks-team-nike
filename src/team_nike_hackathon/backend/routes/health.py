"""Health check API route."""

from __future__ import annotations

import asyncio
import logging
import os

import requests
from fastapi import APIRouter

from ..db import DatabricksSQLDependency

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

DATABRICKS_HOST = os.environ.get(
    "DATABRICKS_HOST", "dbc-8ca6fd25-084d.cloud.databricks.com"
)
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
LLM_ENDPOINT = os.environ.get(
    "LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct"
)
VS_INDEX = os.environ.get(
    "VS_INDEX_NAME", "workspace.referral_copilot.facilities_vs_index"
)


def _host_url() -> str:
    host = DATABRICKS_HOST
    if not host.startswith("https://"):
        host = f"https://{host}"
    return host


def _check_vector_search() -> dict:
    if not DATABRICKS_TOKEN:
        return {"status": "skipped", "reason": "no token"}
    url = f"{_host_url()}/api/2.0/vector-search/indexes/{VS_INDEX}"
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {DATABRICKS_TOKEN}"},
            timeout=5,
        )
        if resp.status_code != 200:
            return {"status": "error", "http_status": resp.status_code}
        data = resp.json()
        ready = bool(data.get("status", {}).get("ready"))
        return {
            "status": "ready" if ready else "provisioning",
            "ready": ready,
            "indexed_rows": data.get("status", {}).get("indexed_row_count"),
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)[:200]}


def _check_llm() -> dict:
    if not DATABRICKS_TOKEN:
        return {"status": "skipped", "reason": "no token"}
    url = f"{_host_url()}/ai-gateway/mlflow/v1/chat/completions"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {DATABRICKS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_ENDPOINT,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return {"status": "ready", "endpoint": LLM_ENDPOINT}
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        return {
            "status": "error",
            "endpoint": LLM_ENDPOINT,
            "http_status": resp.status_code,
            "message": body.get("message", "")[:200],
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)[:200]}


@router.get("/health")
async def health(db: DatabricksSQLDependency):
    """Full system health check.

    Probes Databricks SQL, Vector Search, and the LLM endpoint in parallel.
    Lakebase is checked indirectly through dependency injection on its own
    routes — adding a probe here would require a Session, which isn't
    available until the Lakebase lifespan completes.
    """
    db_check = await asyncio.to_thread(db.health_check)
    vs_check = await asyncio.to_thread(_check_vector_search)
    llm_check = await asyncio.to_thread(_check_llm)

    overall = "ok"
    for c in (db_check, vs_check, llm_check):
        if c.get("status") == "error":
            overall = "degraded"
            break
        if c.get("status") == "provisioning" and overall == "ok":
            overall = "degraded"

    return {
        "status": overall,
        "databricks_sql": db_check,
        "vector_search": vs_check,
        "llm": llm_check,
    }
