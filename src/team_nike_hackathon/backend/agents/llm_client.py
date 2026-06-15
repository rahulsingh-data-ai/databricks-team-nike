"""LLM client for Databricks AI Gateway.

Uses mlflow.deployments for serving endpoint calls.
Falls back to direct HTTP if mlflow is unavailable.
"""

from __future__ import annotations

import os
import json
import logging
import requests
from typing import Any

logger = logging.getLogger(__name__)

LLM_ENDPOINT = os.environ.get("LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "dbc-8ca6fd25-084d.cloud.databricks.com")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")


def get_llm_client():
    """Get MLflow deployments client for serving endpoints."""
    try:
        import mlflow.deployments
        return mlflow.deployments.get_deploy_client("databricks")
    except Exception as e:
        logger.warning(f"MLflow deployments client not available: {e}")
        return None


def call_llm(
    messages: list[dict[str, str]],
    max_tokens: int = 2000,
    temperature: float = 0.1,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Call LLM via AI Gateway. Returns parsed response with reasoning.

    Tries mlflow.deployments first, falls back to direct HTTP.
    """
    endpoint = endpoint or LLM_ENDPOINT

    # Try mlflow client first
    client = get_llm_client()
    if client:
        try:
            response = client.predict(
                endpoint=endpoint,
                inputs={
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            content = response["choices"][0]["message"]["content"]
            return {"content": content, "model": endpoint, "method": "mlflow"}
        except Exception as e:
            logger.warning(f"MLflow predict failed: {e}, falling back to HTTP")

    # Fallback: direct HTTP
    host = DATABRICKS_HOST
    if not host.startswith("https://"):
        host = f"https://{host}"

    url = f"{host}/ai-gateway/mlflow/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DATABRICKS_TOKEN}",
    }
    payload = {
        "model": endpoint,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return {"content": content, "model": endpoint, "method": "http"}


def parse_json_from_llm(content: str) -> dict | list | None:
    """Extract JSON from LLM response, handling markdown code fences."""
    import re
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    text = json_match.group(1).strip() if json_match else content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        brace = text.find('{')
        bracket = text.find('[')
        start = min(i for i in (brace, bracket) if i >= 0) if max(brace, bracket) >= 0 else -1
        if start >= 0:
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                pass
    return None
