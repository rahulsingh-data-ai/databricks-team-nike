"""Databricks SQL connector for Unity Catalog queries."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncGenerator, TypeAlias

from databricks import sql as dbsql
from fastapi import FastAPI, Request

from ..core._base import LifespanDependency
from ..core._config import logger

BRONZE_CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
BRONZE_SCHEMA = "virtue_foundation_dataset"
SILVER_GOLD_CATALOG = "workspace"
SILVER_GOLD_SCHEMA = "referral_copilot"


def _bronze(table: str) -> str:
    return f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.{table}"


def _fqn(table: str) -> str:
    """Silver/gold tables in workspace.referral_copilot."""
    return f"{SILVER_GOLD_CATALOG}.{SILVER_GOLD_SCHEMA}.{table}"


def sql_str(value: Any) -> str:
    """Render a Python value as a safe SQL string literal.

    Returns ``NULL`` for ``None``. Escapes single quotes by doubling them
    and strips backslashes/null bytes to keep generated SQL well-formed
    even when the input came from an LLM.
    """
    if value is None:
        return "NULL"
    text = str(value).replace("\\", "").replace("\x00", "")
    return "'" + text.replace("'", "''") + "'"


def sql_like(value: Any) -> str:
    """Render a Python value as a SQL LIKE pattern (lowercased)."""
    if value is None:
        return "''"
    text = str(value).lower().replace("\\", "").replace("\x00", "")
    return "'%" + text.replace("'", "''") + "%'"


class DatabricksSQLClient:
    """Thin wrapper around databricks-sql-connector for query execution."""

    def __init__(self, host: str, http_path: str, token: str):
        self._host = host
        self._http_path = http_path
        self._token = token

    def _connect(self):
        return dbsql.connect(
            server_hostname=self._host,
            http_path=self._http_path,
            access_token=self._token,
        )

    def execute(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

    def execute_scalar(self, query: str) -> Any:
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query)
                return cursor.fetchone()[0]

    def health_check(self) -> dict:
        try:
            count = self.execute_scalar(
                f"SELECT COUNT(*) FROM {_fqn('facilities_gold')}"
            )
            return {"status": "connected", "facilities_count": count}
        except Exception as e:
            return {"status": "error", "error": str(e)}


class _DatabricksSQLDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        host = os.environ.get("DATABRICKS_HOST", "dbc-8ca6fd25-084d.cloud.databricks.com")
        http_path = os.environ.get("DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/1c11bafa432cc107")
        token = os.environ.get("DATABRICKS_TOKEN", "")

        client = DatabricksSQLClient(host, http_path, token)
        health = client.health_check()
        logger.info(f"Databricks SQL: {health}")

        app.state.dbsql = client
        yield

    @staticmethod
    def __call__(request: Request) -> DatabricksSQLClient:
        return request.app.state.dbsql


DatabricksSQLDependency: TypeAlias = Annotated[DatabricksSQLClient, _DatabricksSQLDependency.depends()]
