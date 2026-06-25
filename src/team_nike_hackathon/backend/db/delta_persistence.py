"""Delta-backed persistence helpers for user state.

Lakebase (Postgres) is not configured on the Nike workspace, so the
spec-mandated "save or revise" surface lives in Delta tables under
``development.dev_gps_research_insights.user_*``. All access funnels
through ``delta_query`` so auth + warehouse selection match the search
path.

Two tables (deliberately minimal):

* ``user_shortlists`` \u2014 the **save** verb. A shortlist holds facility
  ids + notes; once a user decides, the same row gets
  ``chosen_facility_id`` + ``decision_reason`` set (no separate
  "decisions" table needed).
* ``user_overrides`` \u2014 the **revise** verb. Field-level corrections
  to facility data with ``status`` for moderation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from databricks.sdk import WorkspaceClient

from .delta import DeltaQueryError, delta_query


# --- Helpers -----------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return str(uuid4())


def _sql_array(values: list[str] | None) -> str:
    """Serialize a Python ``list[str]`` into a Spark SQL ``array(...)`` literal.

    SQL Statement Execution doesn't bind ``array`` parameters cleanly, so
    we inline the array literal with single-quote escaping.
    """
    if not values:
        return "array()"
    escaped = [v.replace("'", "''") for v in values]
    inner = ", ".join(f"'{v}'" for v in escaped)
    return f"array({inner})"


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Decode the ``facility_ids`` column back into a Python list.

    The SQL Statement Execution API serializes ARRAY<STRING> as a
    JSON-encoded string in the result envelope (e.g.
    ``'["a","b"]'``). Callers expect a real list, so we decode here.
    """
    import json

    if not row:
        return row
    raw = row.get("facility_ids")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                row["facility_ids"] = parsed
        except Exception:
            pass
    return row


# --- Shortlists (save + decide) ---------------------------------------------


def create_shortlist(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    user_email: str,
    name: str | None,
    query: str | None,
    facility_ids: list[str],
    notes: str | None,
) -> dict[str, Any]:
    """Insert a new shortlist row. Returns the persisted record."""
    sid = _new_id()
    now = _now_iso()
    delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"INSERT INTO {schema}.user_shortlists "
            f"(shortlist_id, user_email, name, query, facility_ids, notes, "
            f"chosen_facility_id, decision_reason, created_at, updated_at) "
            f"VALUES (:sid, :email, :name, :query, {_sql_array(facility_ids)}, "
            f":notes, NULL, NULL, timestamp'{now}', timestamp'{now}')"
        ),
        parameters={
            "sid": sid,
            "email": user_email,
            "name": name,
            "query": query,
            "notes": notes,
        },
    )
    return {
        "shortlist_id": sid,
        "user_email": user_email,
        "name": name,
        "query": query,
        "facility_ids": facility_ids,
        "notes": notes,
        "chosen_facility_id": None,
        "decision_reason": None,
        "created_at": now,
        "updated_at": now,
    }


def list_shortlists(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    user_email: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"SELECT * FROM {schema}.user_shortlists "
            f"WHERE user_email = :email "
            f"ORDER BY updated_at DESC LIMIT {int(limit)}"
        ),
        parameters={"email": user_email},
    )
    return [_normalize_row(r) for r in rows]


def get_shortlist(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    shortlist_id: str,
    user_email: str,
) -> dict[str, Any] | None:
    rows = delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"SELECT * FROM {schema}.user_shortlists "
            f"WHERE shortlist_id = :sid AND user_email = :email LIMIT 1"
        ),
        parameters={"sid": shortlist_id, "email": user_email},
    )
    return _normalize_row(rows[0]) if rows else None


def update_shortlist(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    shortlist_id: str,
    user_email: str,
    name: str | None = None,
    facility_ids: list[str] | None = None,
    notes: str | None = None,
    chosen_facility_id: str | None = None,
    decision_reason: str | None = None,
) -> dict[str, Any] | None:
    """Patch mutable fields. Passing ``chosen_facility_id`` records the
    decide verb in the same row \u2014 no separate decisions table."""
    sets: list[str] = []
    params: dict[str, Any] = {"sid": shortlist_id, "email": user_email}
    if name is not None:
        sets.append("name = :name")
        params["name"] = name
    if notes is not None:
        sets.append("notes = :notes")
        params["notes"] = notes
    if facility_ids is not None:
        sets.append(f"facility_ids = {_sql_array(facility_ids)}")
    if chosen_facility_id is not None:
        sets.append("chosen_facility_id = :chosen")
        params["chosen"] = chosen_facility_id
    if decision_reason is not None:
        sets.append("decision_reason = :reason")
        params["reason"] = decision_reason
    now = _now_iso()
    sets.append(f"updated_at = timestamp'{now}'")
    if len(sets) == 1:  # only the updated_at no-op
        return get_shortlist(
            ws, warehouse_id, schema,
            shortlist_id=shortlist_id, user_email=user_email,
        )
    delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"UPDATE {schema}.user_shortlists SET {', '.join(sets)} "
            f"WHERE shortlist_id = :sid AND user_email = :email"
        ),
        parameters=params,
    )
    return get_shortlist(
        ws, warehouse_id, schema,
        shortlist_id=shortlist_id, user_email=user_email,
    )


def delete_shortlist(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    shortlist_id: str,
    user_email: str,
) -> bool:
    existing = get_shortlist(
        ws, warehouse_id, schema,
        shortlist_id=shortlist_id, user_email=user_email,
    )
    if not existing:
        return False
    delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"DELETE FROM {schema}.user_shortlists "
            f"WHERE shortlist_id = :sid AND user_email = :email"
        ),
        parameters={"sid": shortlist_id, "email": user_email},
    )
    return True


# --- Overrides (revise) ------------------------------------------------------


def add_override(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    user_email: str,
    facility_id: str,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    reason: str | None,
) -> dict[str, Any]:
    oid = _new_id()
    now = _now_iso()
    delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"INSERT INTO {schema}.user_overrides "
            f"(override_id, user_email, facility_id, field_name, old_value, "
            f"new_value, reason, status, created_at) VALUES "
            f"(:oid, :email, :fid, :field, :old, :new, :reason, 'pending', "
            f"timestamp'{now}')"
        ),
        parameters={
            "oid": oid, "email": user_email, "fid": facility_id,
            "field": field_name, "old": old_value, "new": new_value,
            "reason": reason,
        },
    )
    return {
        "override_id": oid, "user_email": user_email, "facility_id": facility_id,
        "field_name": field_name, "old_value": old_value, "new_value": new_value,
        "reason": reason, "status": "pending", "created_at": now,
    }


def list_overrides(
    ws: WorkspaceClient,
    warehouse_id: str,
    schema: str,
    *,
    facility_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return delta_query(
        ws,
        warehouse_id=warehouse_id,
        statement=(
            f"SELECT * FROM {schema}.user_overrides WHERE facility_id = :fid "
            f"ORDER BY created_at DESC LIMIT {int(limit)}"
        ),
        parameters={"fid": facility_id},
    )


__all__ = [
    "DeltaQueryError",
    "create_shortlist",
    "list_shortlists",
    "get_shortlist",
    "update_shortlist",
    "delete_shortlist",
    "add_override",
    "list_overrides",
]
