"""Thin async-friendly wrapper around the Databricks SQL Statement
Execution API.

We use the SDK rather than ``databricks-sql-connector`` so the existing
``WorkspaceClient`` auth (user CLI profile in dev, admin SP in prod)
flows through automatically — no separate ``DATABRICKS_TOKEN`` to
manage and one less Python dependency to ship.

Parameters are bound by name (``:foo``) so callers never have to
string-format SQL fragments together.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import (
    StatementParameterListItem,
    StatementState,
)

logger = logging.getLogger(__name__)


class DeltaQueryError(RuntimeError):
    """Raised when a Databricks SQL statement fails or times out."""


_TYPE_BY_PYTHON: dict[type, str] = {
    int: "LONG",
    float: "DOUBLE",
    bool: "BOOLEAN",
}


def _to_param(name: str, value: Any) -> StatementParameterListItem:
    """Convert a Python value into a ``StatementParameterListItem``.

    ``None`` is rendered as ``NULL`` by leaving ``value`` unset. Strings
    default to ``STRING``; ints/floats/bools get explicit Spark types so
    the engine doesn't have to infer.
    """
    if value is None:
        return StatementParameterListItem(name=name, value=None, type="STRING")
    spark_type = _TYPE_BY_PYTHON.get(type(value), "STRING")
    # The SDK accepts the value as its string repr — Spark casts it
    # using ``type`` at execution time.
    rendered = str(value).lower() if isinstance(value, bool) else str(value)
    return StatementParameterListItem(name=name, value=rendered, type=spark_type)


def delta_query(
    ws: WorkspaceClient,
    warehouse_id: str,
    statement: str,
    parameters: Mapping[str, Any] | None = None,
    *,
    wait_timeout: str = "30s",
    row_limit: int | None = None,
) -> list[dict[str, Any]]:
    """Execute a SQL statement against a SQL warehouse and return rows.

    Args:
        ws: An authenticated ``WorkspaceClient``.
        warehouse_id: The SQL warehouse to run the statement on.
        statement: The SQL text (may reference ``:param`` placeholders).
        parameters: Mapping of placeholder name → Python value.
        wait_timeout: Synchronous wait window before the call returns.
            Spark uses up to this long before async polling kicks in.
        row_limit: Optional cap on rows returned to the client.

    Returns:
        A list of dicts keyed by column name. Empty list when the
        statement returns no rows.

    Raises:
        DeltaQueryError: When the statement transitions to FAILED /
        CANCELED, or when the SDK returns no result manifest at all.
    """
    params_list = [
        _to_param(k, v) for k, v in (parameters or {}).items()
    ]

    resp = ws.statement_execution.execute_statement(
        warehouse_id=warehouse_id,
        statement=statement,
        parameters=params_list or None,
        wait_timeout=wait_timeout,
        row_limit=row_limit,
    )

    status = resp.status
    if status is None or status.state in (
        StatementState.FAILED,
        StatementState.CANCELED,
        StatementState.CLOSED,
    ):
        err = (
            status.error.message
            if status is not None and status.error is not None
            else "unknown SDK error"
        )
        raise DeltaQueryError(f"Statement failed: {err}")

    # If the warehouse is still warming up the call can return PENDING
    # / RUNNING; poll until we hit a terminal state.
    statement_id = resp.statement_id
    while resp.status and resp.status.state in (
        StatementState.PENDING,
        StatementState.RUNNING,
    ):
        if not statement_id:
            raise DeltaQueryError("Polling required but no statement_id returned")
        resp = ws.statement_execution.get_statement(statement_id=statement_id)

    if resp.status and resp.status.state != StatementState.SUCCEEDED:
        err = (
            resp.status.error.message
            if resp.status.error is not None
            else f"non-SUCCESS terminal state {resp.status.state}"
        )
        raise DeltaQueryError(f"Statement failed: {err}")

    manifest = resp.manifest
    result = resp.result
    if manifest is None or manifest.schema is None or result is None:
        return []

    columns: list[str] = [
        col.name for col in (manifest.schema.columns or []) if col.name
    ]
    rows = result.data_array or []
    return [
        {col: value for col, value in zip(columns, row)}
        for row in rows
    ]
