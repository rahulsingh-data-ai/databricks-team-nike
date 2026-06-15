"""Lakebase SQLAlchemy engine, session dependency, and table initialisation.

In production the SQLAlchemy engine connects to a Lakebase Autoscaling
Postgres endpoint (``WorkspaceClient.postgres``) via an admin service
principal whose OAuth credentials live in a Databricks secret scope. In
local development (``apx dev start``) the engine connects to the local
Postgres that apx vends via ``APX_DEV_DB_PORT`` so the app boots without
needing a real Lakebase endpoint or secret scope wired up.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncGenerator, TypeAlias

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors.platform import InternalError as _DbxInternalError
from fastapi import FastAPI, Request
from sqlalchemy import Engine, create_engine, event
from sqlmodel import Session, SQLModel, text

from ..lakebase_query import (
    DATABASE_NAME,
    ENDPOINT_NAME,
    POSTGRES_ROLE,
    get_endpoint_host,
    get_lakebase_ws,
    is_dev_mode,
    vend_db_token,
)
from ._base import LifespanDependency
from ._config import logger


# --- Engine creation ---


def _build_dev_engine_url() -> str:
    port = os.environ.get("APX_DEV_DB_PORT")
    password = os.environ.get("APX_DEV_DB_PWD")
    if port is None or password is None:
        raise ValueError(
            "APX server didn't provide APX_DEV_DB_PORT / APX_DEV_DB_PWD; "
            "please check the dev server logs"
        )
    logger.info("Using local dev database at localhost:%s", port)
    return (
        f"postgresql+psycopg://postgres:{password}"
        f"@localhost:{port}/postgres?sslmode=disable"
    )


def create_db_engine(ws: WorkspaceClient) -> Engine:
    """Create a SQLAlchemy engine.

    Local dev: connects to the apx-vended Postgres on ``APX_DEV_DB_PORT`` —
    no SSL, no password callback. Production: connects to the Lakebase
    Autoscaling Postgres ``ENDPOINT_NAME`` using the admin-SP
    ``WorkspaceClient`` from :func:`get_lakebase_ws`, with a per-connection
    OAuth token refresh.
    """
    if is_dev_mode():
        return create_engine(_build_dev_engine_url(), pool_size=4, pool_recycle=45 * 60)

    db_ws = get_lakebase_ws(ws)
    host = get_endpoint_host(db_ws)

    engine_url = f"postgresql+psycopg://{POSTGRES_ROLE}:@{host}:5432/{DATABASE_NAME}"
    engine_kwargs: dict[str, Any] = {
        "connect_args": {"sslmode": "require"},
        "pool_size": 8,
        "pool_recycle": 45 * 60,
        "pool_pre_ping": True,
    }
    engine = create_engine(engine_url, **engine_kwargs)

    def _refresh_token(dialect, conn_rec, cargs, cparams):
        cparams["password"] = vend_db_token(db_ws)

    event.listens_for(engine, "do_connect")(_refresh_token)

    logger.info(
        "SQLAlchemy engine created (endpoint=%s, database=%s)",
        ENDPOINT_NAME,
        DATABASE_NAME,
    )
    return engine


def validate_db(engine: Engine) -> None:
    """Smoke-test the database connection with ``SELECT 1``."""
    if is_dev_mode():
        logger.info("Validating local dev database connection")
    else:
        logger.info("Validating database connection to endpoint %s", ENDPOINT_NAME)

    try:
        with Session(engine) as session:
            session.connection().execute(text("SELECT 1"))
            session.close()
    except Exception:
        raise ConnectionError("Failed to connect to the database")
    logger.info("Database connection validated successfully")


def initialize_models(engine: Engine) -> None:
    """Create all SQLModel tables if they don't already exist."""
    logger.info("Initializing database models")
    SQLModel.metadata.create_all(engine)
    logger.info("Database models initialized successfully")


# --- Lifespan retry wrapper ---

# Databricks' control-plane API for credential vending occasionally 500s with
# a generic ``InternalError``. The SDK retries internally but gives up
# quickly, which means an otherwise healthy restart turns into a "Application
# startup failed" wall. We retry the boot path with backoff before
# surrendering.
_STARTUP_RETRY_ATTEMPTS = 8
_STARTUP_RETRY_INITIAL_DELAY = 1.5
_STARTUP_RETRY_MAX_DELAY = 15.0


async def _init_engine_with_retry(ws: WorkspaceClient) -> Engine:
    """Bring the Lakebase engine up, tolerating transient control-plane 500s."""
    delay = _STARTUP_RETRY_INITIAL_DELAY
    last_err: Exception | None = None
    for attempt in range(1, _STARTUP_RETRY_ATTEMPTS + 1):
        try:
            engine = await asyncio.to_thread(create_db_engine, ws)
            await asyncio.to_thread(validate_db, engine)
            return engine
        except _DbxInternalError as exc:
            last_err = exc
            if attempt >= _STARTUP_RETRY_ATTEMPTS:
                break
            logger.warning(
                "Lakebase startup: Databricks control-plane 500 "
                "(attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                _STARTUP_RETRY_ATTEMPTS,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, _STARTUP_RETRY_MAX_DELAY)
    assert last_err is not None
    raise last_err


# --- Dependency ---


class _LakebaseDependency(LifespanDependency):
    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncGenerator[None, None]:
        ws = app.state.workspace_client
        engine = await _init_engine_with_retry(ws)
        initialize_models(engine)
        app.state.engine = engine
        yield
        engine.dispose()

    @staticmethod
    def __call__(request: Request) -> Generator[Session, None, None]:
        with Session(bind=request.app.state.engine) as session:
            yield session


LakebaseDependency: TypeAlias = Annotated[Session, _LakebaseDependency.depends()]
