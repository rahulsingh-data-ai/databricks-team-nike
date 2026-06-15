"""Lakebase connection management.

Provides a shared admin-SP ``WorkspaceClient`` and a psycopg ``ConnectionPool``
used by the SQLAlchemy engine in ``core/lakebase.py``. The admin SP's
``client_id`` / ``client_secret`` live in a Databricks secret scope and are
loaded once per process; both the SQLAlchemy engine and any raw-psycopg
callers share the same OAuth identity from there.

This module targets the **Lakebase Autoscaling Postgres** API
(``WorkspaceClient.postgres``), which uses ``projects → branches → endpoints``
instead of the older provisioned ``database_instances`` shape. The admin SP
must have a Postgres role provisioned on the target branch; the role's
``postgres_role`` value is what we send as the connection username.
"""

from __future__ import annotations

import os
import threading
from base64 import b64decode

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool

from .core._config import logger

# ---------------------------------------------------------------------------
# Lakebase Autoscaling Postgres location
# ---------------------------------------------------------------------------

# The Lakebase Autoscaling Postgres project / branch / endpoint to connect to.
# Provision these in the Databricks UI (Compute → Lakebase) before deploying.
# The full endpoint resource name is built from these three pieces.
PROJECT_ID = "dais-hackathon"
BRANCH_ID = "production"
ENDPOINT_ID = "primary"
ENDPOINT_NAME = (
    f"projects/{PROJECT_ID}/branches/{BRANCH_ID}/endpoints/{ENDPOINT_ID}"
)

# Postgres database name inside the branch. ``databricks_postgres`` is the
# built-in default for Lakebase Autoscaling Postgres; change this only if you
# provisioned a custom database.
DATABASE_NAME = "databricks_postgres"

# Postgres role (username) used to log into the database. This is the
# ``postgres_role`` value of the Lakebase role provisioned for the admin SP
# on ``BRANCH_ID`` — typically the SP's application id. Create the role with::
#
#   databricks postgres create-role \\
#       projects/<project>/branches/<branch> \\
#       --role-id team-nike-hackathon-admin-sp \\
#       --json '{"spec": {"identity_type": "SERVICE_PRINCIPAL", ...}}'
#
# (or via the Python SDK, see ``ws.postgres.create_role``).
POSTGRES_ROLE = "2a5b4d83-402c-4227-a472-c500fb69d191"

# ---------------------------------------------------------------------------
# Secret scope (admin-SP OAuth credentials)
# ---------------------------------------------------------------------------

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


def _decode_secret(ws: WorkspaceClient, scope: str, key: str) -> str:
    """Return the decoded secret value, with leading/trailing whitespace stripped.

    The strip is defensive: ``databricks secrets put-secret`` opens ``$EDITOR``
    and a final newline often sneaks into the saved file. Without the strip,
    OAuth client_id/client_secret values would carry the ``\\n`` and the IdP
    would reject them with ``invalid_client``.
    """
    raw = ws.secrets.get_secret(scope=scope, key=key).value
    if raw is None:
        raise ValueError(f"Secret {scope}/{key} has no value")
    return b64decode(raw).decode("utf-8").strip()


_lakebase_ws: WorkspaceClient | None = None
_lakebase_ws_lock = threading.Lock()


def get_lakebase_ws(ws: WorkspaceClient) -> WorkspaceClient:
    """Return a ``WorkspaceClient`` authenticated as the admin service principal.

    Credentials are read once from ``SECRET_SCOPE`` and cached for the lifetime
    of the process. The passed-in ``ws`` is only used to read the secrets — the
    returned client is a separate identity, owned by the SP whose creds live
    in the scope. ``auth_type='oauth-m2m'`` is set explicitly so the SDK does
    not silently fall back to ambient credentials (the deployed app's own SP
    env vars, the user's ``databricks-cli`` profile, etc.).
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
            auth_type="oauth-m2m",
        )
        logger.info("Lakebase admin-SP WorkspaceClient initialised")
        return _lakebase_ws


def vend_db_token(ws: WorkspaceClient) -> str:
    """Vend a short-lived OAuth token for the configured Lakebase endpoint.

    The returned token is what Postgres expects as the connection password
    (the SDK handles the round-trip with the Lakebase control plane).
    """
    return ws.postgres.generate_database_credential(endpoint=ENDPOINT_NAME).token


def get_endpoint_host(ws: WorkspaceClient) -> str:
    """Return the read/write hostname of the configured Lakebase endpoint."""
    return ws.postgres.get_endpoint(ENDPOINT_NAME).status.hosts.host


# ---------------------------------------------------------------------------
# psycopg ConnectionPool (raw-SQL access)
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _build_pool(ws: WorkspaceClient) -> ConnectionPool:
    """Build a psycopg ``ConnectionPool`` with rotating OAuth tokens."""
    db_ws = get_lakebase_ws(ws)
    host = get_endpoint_host(db_ws)

    class _RotatingTokenConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):
            kwargs["password"] = vend_db_token(db_ws)
            kwargs.setdefault("sslmode", "require")
            return super().connect(conninfo, **kwargs)

    pool = ConnectionPool(
        conninfo=f"host={host} dbname={DATABASE_NAME} user={POSTGRES_ROLE}",
        connection_class=_RotatingTokenConnection,
        min_size=1,
        max_size=8,
        open=True,
    )

    logger.info(
        "Lakebase pool created (endpoint=%s, database=%s)",
        ENDPOINT_NAME,
        DATABASE_NAME,
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
