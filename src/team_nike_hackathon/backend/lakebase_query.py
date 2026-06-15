"""Lakebase connection management.

Provides a shared admin-SP ``WorkspaceClient`` and a psycopg ``ConnectionPool``
used by the SQLAlchemy engine in ``core/lakebase.py``. The admin SP's
``client_id`` / ``client_secret`` live in a Databricks secret scope and are
loaded once per process; both the SQLAlchemy engine and any raw-psycopg
callers share the same OAuth identity from there.

Mirrors the connection pattern of ``gpsi_apps_hub.backend.lakebase_query`` —
add domain-specific query helpers below the credential plumbing as the app
grows.
"""

from __future__ import annotations

import os
import threading
import uuid
from base64 import b64decode

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool

from .core._config import logger

# ---------------------------------------------------------------------------
# Shared Lakebase constants & credential helpers
# ---------------------------------------------------------------------------

# Name of the Lakebase database instance to connect to. Create this in the
# Databricks UI (Compute → Database Instances) before deploying.
INSTANCE_NAME = "team-nike-hackathon"

# Name of the Databricks secret scope that holds the admin-SP credentials.
# The scope must contain two keys:
#   - ``sp-client-id``      : the admin service principal's OAuth client id
#   - ``sp-client-secret``  : the admin service principal's OAuth client secret
# Create with:
#   databricks secrets create-scope team-nike-hackathon -p personal
#   databricks secrets put-secret team-nike-hackathon sp-client-id     -p personal
#   databricks secrets put-secret team-nike-hackathon sp-client-secret -p personal
SECRET_SCOPE = "team-nike-hackathon"

# Secret keys inside SECRET_SCOPE. Change these if you prefer a different
# naming convention in your scope.
SP_CLIENT_ID_KEY = "sp-client-id"
SP_CLIENT_SECRET_KEY = "sp-client-secret"


def is_dev_mode() -> bool:
    """True when running under the apx local dev server."""
    return os.environ.get("APX_DEV_DB_PORT") is not None


def get_database_name() -> str:
    """Lakebase database name to connect to.

    Defaults to Lakebase's built-in ``databricks_postgres`` database. Change
    this if you provision a custom database inside the instance.
    """
    return "databricks_postgres"


def _decode_secret(ws: WorkspaceClient, scope: str, key: str) -> str:
    raw = ws.secrets.get_secret(scope=scope, key=key).value
    if raw is None:
        raise ValueError(f"Secret {scope}/{key} has no value")
    return b64decode(raw).decode("utf-8")


_lakebase_ws: WorkspaceClient | None = None
_lakebase_ws_lock = threading.Lock()


def get_lakebase_ws(ws: WorkspaceClient) -> WorkspaceClient:
    """Return a ``WorkspaceClient`` authenticated as the admin service principal.

    Credentials are read once from ``SECRET_SCOPE`` and cached for the lifetime
    of the process. The passed-in ``ws`` is only used to read the secrets — the
    returned client is a separate identity, owned by the SP whose creds live
    in the scope.
    """
    global _lakebase_ws
    if _lakebase_ws is not None:
        return _lakebase_ws
    with _lakebase_ws_lock:
        if _lakebase_ws is not None:
            return _lakebase_ws
        _lakebase_ws = WorkspaceClient(
            host=ws.config.host,
            client_id=_decode_secret(ws, SECRET_SCOPE, SP_CLIENT_ID_KEY),
            client_secret=_decode_secret(ws, SECRET_SCOPE, SP_CLIENT_SECRET_KEY),
        )
        logger.info("Lakebase admin-SP WorkspaceClient initialised")
        return _lakebase_ws


# ---------------------------------------------------------------------------
# psycopg ConnectionPool (raw-SQL access)
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _build_pool(ws: WorkspaceClient) -> ConnectionPool:
    """Build a psycopg ``ConnectionPool`` with rotating OAuth tokens."""
    db_ws = get_lakebase_ws(ws)
    database_name = get_database_name()
    host = db_ws.database.get_database_instance(name=INSTANCE_NAME).read_write_dns

    class _RotatingTokenConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):
            kwargs["password"] = db_ws.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[kwargs.pop("_instance_name")],
            ).token
            kwargs.setdefault("sslmode", "require")
            return super().connect(conninfo, **kwargs)

    username = db_ws.current_user.me().user_name

    pool = ConnectionPool(
        conninfo=f"host={host} dbname={database_name} user={username}",
        connection_class=_RotatingTokenConnection,
        kwargs={"_instance_name": INSTANCE_NAME},
        min_size=1,
        max_size=8,
        open=True,
    )

    logger.info(
        "Lakebase pool created (instance=%s, database=%s)",
        INSTANCE_NAME,
        database_name,
    )
    return pool  # ty: ignore[invalid-return-type]


def get_pool(ws: WorkspaceClient) -> ConnectionPool:
    """Return the cached ``ConnectionPool``, creating it lazily on first call."""
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = _build_pool(ws)
        return _pool
