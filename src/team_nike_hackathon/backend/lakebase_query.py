"""Lakebase connection management.

Targets **Lakebase Autoscaling Postgres** (``WorkspaceClient.postgres``),
which uses ``projects → branches → endpoints``.

Identity switching:

* **Local dev** (running on your laptop, no ``DATABRICKS_APP_PORT``):
  use the ambient ``WorkspaceClient`` from the personal CLI profile — i.e.
  authenticate as *you*. Your user already has a Postgres role on the
  branch (the auto-created ``DATABRICKS_SUPERUSER`` role), so connections
  just work.
* **Deployed Databricks App** (``DATABRICKS_APP_PORT`` set): swap to the
  admin Service Principal whose OAuth ``client_id`` / ``client_secret``
  live in a Databricks secret scope. ``auth_type='oauth-m2m'`` is set
  explicitly so the SDK does not silently fall back to the app's own SP
  via the platform-injected env vars.

Whichever identity is in use, ``ws.current_user.me().user_name`` is the
Postgres role name to send as the connection user (the SDK reports the
email for users and the application id for service principals, which is
exactly what Lakebase assigns as ``postgres_role`` when you provision
the role).
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

# Lakebase endpoint identifier.
#
# Two shapes are supported:
#
# 1. **Autoscaling Postgres** — projects/branches/endpoints. Used on the
#    free-tier hackathon workspace. ENDPOINT_NAME looks like
#    ``projects/<id>/branches/<id>/endpoints/<id>``.
# 2. **Classic database instance** — a single named instance like
#    ``GPSI-Lakebase`` on the Nike workspace. ENDPOINT_NAME is just the
#    instance name; ``LAKEBASE_MODE=classic`` selects this path.
#
# Override via env vars: ``LAKEBASE_ENDPOINT_NAME`` (full path or instance
# name) and ``LAKEBASE_MODE`` (``autoscaling`` | ``classic``).
LAKEBASE_MODE = os.environ.get("LAKEBASE_MODE", "autoscaling").strip().lower()

_DEFAULT_AUTOSCALING_ENDPOINT = (
    "projects/dais-hackathon/branches/production/endpoints/primary"
)
ENDPOINT_NAME = os.environ.get(
    "LAKEBASE_ENDPOINT_NAME",
    os.environ.get("LAKEBASE_INSTANCE_NAME", _DEFAULT_AUTOSCALING_ENDPOINT),
)

# Postgres database name. ``databricks_postgres`` is the built-in default
# for both Lakebase variants; override with ``LAKEBASE_DB`` if you've
# created a named database inside the instance/branch.
DATABASE_NAME = os.environ.get("LAKEBASE_DB", "databricks_postgres")

# ---------------------------------------------------------------------------
# Secret scope (admin-SP OAuth credentials, prod only)
# ---------------------------------------------------------------------------

# Name of the Databricks secret scope holding the admin-SP creds. Required
# keys: ``sp-client-id`` and ``sp-client-secret``. Create with::
#
#   databricks secrets create-scope team-nike-hackathon -p personal
#   databricks secrets put-secret  team-nike-hackathon sp-client-id     -p personal
#   databricks secrets put-secret  team-nike-hackathon sp-client-secret -p personal
SECRET_SCOPE = "team-nike-hackathon"
SP_CLIENT_ID_KEY = "sp-client-id"
SP_CLIENT_SECRET_KEY = "sp-client-secret"


def is_deployed() -> bool:
    """True when running inside a Databricks App on the platform.

    Databricks Apps inject ``DATABRICKS_APP_PORT`` into the runtime env;
    local CLI dev (``apx dev start`` or plain ``uvicorn``) does not.
    """
    return "DATABRICKS_APP_PORT" in os.environ


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


def _build_admin_sp_ws(ws: WorkspaceClient) -> WorkspaceClient:
    """Build a ``WorkspaceClient`` authenticated as the admin service principal.

    ``auth_type='oauth-m2m'`` is set explicitly so the SDK does not silently
    fall back to ambient credentials (the deployed app's own SP env vars or
    the local ``databricks-cli`` profile).
    """
    return WorkspaceClient(
        host=ws.config.host,
        client_id=_decode_secret(ws, SECRET_SCOPE, SP_CLIENT_ID_KEY),
        client_secret=_decode_secret(ws, SECRET_SCOPE, SP_CLIENT_SECRET_KEY),
        auth_type="oauth-m2m",
    )


def get_db_client(ws: WorkspaceClient) -> WorkspaceClient:
    """Return the ``WorkspaceClient`` to use for Lakebase calls.

    Dev: the ambient ``ws`` (you). Prod: the admin SP loaded once from
    ``SECRET_SCOPE`` and cached for the lifetime of the process.
    """
    if not is_deployed():
        return ws

    global _lakebase_ws
    if _lakebase_ws is not None:
        return _lakebase_ws
    with _lakebase_ws_lock:
        if _lakebase_ws is not None:
            return _lakebase_ws
        _lakebase_ws = _build_admin_sp_ws(ws)
        logger.info("Lakebase admin-SP WorkspaceClient initialised")
        return _lakebase_ws


def vend_db_token(ws: WorkspaceClient) -> str:
    """Vend a short-lived OAuth token for the configured Lakebase endpoint.

    Selects the right SDK call based on ``LAKEBASE_MODE``:

    * ``autoscaling`` uses ``ws.postgres.generate_database_credential``
    * ``classic`` uses ``ws.database.generate_database_credential``
    """
    if LAKEBASE_MODE == "classic":
        from uuid import uuid4

        cred = ws.database.generate_database_credential(
            request_id=str(uuid4()),
            instance_names=[ENDPOINT_NAME],
        )
        if not cred.token:
            raise RuntimeError(
                f"Lakebase instance {ENDPOINT_NAME!r} returned no token"
            )
        return cred.token

    cred = ws.postgres.generate_database_credential(endpoint=ENDPOINT_NAME)
    if not cred.token:
        raise RuntimeError(
            f"Lakebase did not return a token for endpoint {ENDPOINT_NAME!r}"
        )
    return cred.token


def get_endpoint_host(ws: WorkspaceClient) -> str:
    """Return the read/write hostname of the configured Lakebase endpoint."""
    if LAKEBASE_MODE == "classic":
        instance = ws.database.get_database_instance(name=ENDPOINT_NAME)
        host = getattr(instance, "read_write_dns", None)
        if not host:
            raise RuntimeError(
                f"Lakebase instance {ENDPOINT_NAME!r} is not yet ready "
                f"(no read_write_dns)."
            )
        return host

    endpoint = ws.postgres.get_endpoint(ENDPOINT_NAME)
    host = (
        endpoint.status.hosts.host
        if endpoint.status and endpoint.status.hosts
        else None
    )
    if not host:
        raise RuntimeError(
            f"Lakebase endpoint {ENDPOINT_NAME!r} is not yet ready (no host)."
        )
    return host


def get_postgres_user(ws: WorkspaceClient) -> str:
    """Postgres role name = SDK ``user_name`` of the authenticated identity.

    Lakebase assigns the user's email (for ``USER`` roles) or the SP's
    application id (for ``SERVICE_PRINCIPAL`` roles) as the role's
    ``postgres_role``, which is what we pass as the Postgres ``user``.
    """
    user_name = ws.current_user.me().user_name
    if not user_name:
        raise RuntimeError("WorkspaceClient.current_user.me().user_name is empty")
    return user_name


# ---------------------------------------------------------------------------
# psycopg ConnectionPool (raw-SQL access)
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _build_pool(ws: WorkspaceClient) -> ConnectionPool:
    """Build a psycopg ``ConnectionPool`` with rotating OAuth tokens."""
    db_ws = get_db_client(ws)
    host = get_endpoint_host(db_ws)
    user = get_postgres_user(db_ws)

    class _RotatingTokenConnection(psycopg.Connection):
        @classmethod
        def connect(cls, conninfo: str = "", **kwargs):
            kwargs["password"] = vend_db_token(db_ws)
            kwargs.setdefault("sslmode", "require")
            return super().connect(conninfo, **kwargs)

    pool = ConnectionPool(
        conninfo=f"host={host} dbname={DATABASE_NAME} user={user}",
        connection_class=_RotatingTokenConnection,
        min_size=1,
        max_size=8,
        open=True,
    )

    logger.info(
        "Lakebase pool created (endpoint=%s, database=%s, user=%s)",
        ENDPOINT_NAME,
        DATABASE_NAME,
        user,
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
