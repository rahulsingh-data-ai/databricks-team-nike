"""LLM client for Databricks foundation-model serving endpoints.

We use the same ``WorkspaceClient.serving_endpoints.query()`` path that
authenticates the rest of the app (your CLI profile in dev, the admin SP
in prod). That keeps secrets out of code and avoids the dual ``mlflow``
+ ``DATABRICKS_TOKEN`` setup the original referral-copilot branch used.

The active ``WorkspaceClient`` and endpoint name are injected per-request
via ``contextvars`` rather than threaded through every agent function,
so the prompt-running code stays small and synchronous-friendly.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

logger = logging.getLogger(__name__)


_WS_CTX: ContextVar[WorkspaceClient | None] = ContextVar("matchcare_ws", default=None)
_ENDPOINT_CTX: ContextVar[str] = ContextVar(
    "matchcare_llm_endpoint",
    default="databricks-meta-llama-3-3-70b-instruct",
)


def set_workspace(ws: WorkspaceClient):
    """Bind a ``WorkspaceClient`` to the current async/sync context."""
    return _WS_CTX.set(ws)


def reset_workspace(token):
    _WS_CTX.reset(token)


def set_endpoint(name: str):
    """Bind the LLM endpoint name to the current context."""
    return _ENDPOINT_CTX.set(name)


def reset_endpoint(token):
    _ENDPOINT_CTX.reset(token)


_ROLE_MAP: dict[str, ChatMessageRole] = {
    "system": ChatMessageRole.SYSTEM,
    "user": ChatMessageRole.USER,
    "assistant": ChatMessageRole.ASSISTANT,
}


def call_llm(
    messages: list[dict[str, str]],
    max_tokens: int = 2000,
    temperature: float = 0.1,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Call a Databricks chat-completions endpoint.

    ``messages`` follows the OpenAI shape: ``[{role, content}, ...]``.
    Returns ``{"content": str, "model": str, "method": "databricks_sdk"}``
    on success.

    Raises ``RuntimeError`` if no ``WorkspaceClient`` has been bound for
    the current request. Callers should wrap this in a try/except and
    fall back to a deterministic path so an LLM outage never breaks the
    user-facing search.
    """
    ws = _WS_CTX.get()
    if ws is None:
        raise RuntimeError(
            "No WorkspaceClient bound. Call set_workspace(ws) before "
            "invoking call_llm()."
        )
    ep = endpoint or _ENDPOINT_CTX.get()

    chat_messages = [
        ChatMessage(
            role=_ROLE_MAP.get(m.get("role", "user"), ChatMessageRole.USER),
            content=m.get("content", ""),
        )
        for m in messages
    ]

    response = ws.serving_endpoints.query(
        name=ep,
        messages=chat_messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("LLM response had no choices")
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if not content:
        # Some endpoints return choices[0].text; fall back gracefully.
        content = getattr(choices[0], "text", "") or ""
    return {"content": content, "model": ep, "method": "databricks_sdk"}


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def parse_json_from_llm(content: str) -> dict | list | None:
    """Extract JSON from an LLM response, tolerating markdown code fences."""
    if not content:
        return None
    fenced = _JSON_FENCE_RE.search(content)
    text = fenced.group(1).strip() if fenced else content.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Last-ditch: find the first balanced object/array.
    brace = text.find("{")
    bracket = text.find("[")
    starts = [i for i in (brace, bracket) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError:
        return None
