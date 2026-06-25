"""Save / decide / revise endpoints backed by Delta tables.

Closes the spec gap "let users save or revise their work". Two tables
under ``development.dev_gps_research_insights.user_*``:

* ``user_shortlists`` \u2014 the **save** + **decide** verbs. A shortlist
  becomes a "decision" by setting ``chosen_facility_id`` +
  ``decision_reason`` via PATCH.
* ``user_overrides`` \u2014 the **revise** verb. Field-level corrections
  to facility data with ``status`` for moderation.

User identity comes from Databricks Apps ``X-Forwarded-Email`` /
``X-Forwarded-Preferred-Username`` headers. In local dev with no
headers the routes 401.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..core import Dependencies, logger
from ..db import DeltaQueryError
from ..db import delta_persistence as dp


router = APIRouter()


def _config_or_503(config) -> tuple[str, str]:
    """Return (warehouse_id, schema) or raise 503 when Delta isn't configured."""
    warehouse_id = (config.delta_warehouse_id or "").strip()
    table = (config.delta_facilities_table or "").strip()
    if not warehouse_id or not table:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Delta persistence not configured (warehouse / table empty).",
        )
    schema = ".".join(table.split(".")[:2]) if table.count(".") >= 2 else table
    return warehouse_id, schema


def _require_user(headers) -> str:
    email = (headers.user_email or headers.user_name or "").strip()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User identity required (X-Forwarded-Email header).",
        )
    return email


# --- Shortlists (save + decide) ---------------------------------------------


class ShortlistIn(BaseModel):
    name: str | None = None
    query: str | None = None
    facility_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class ShortlistPatch(BaseModel):
    name: str | None = None
    facility_ids: list[str] | None = None
    notes: str | None = None
    chosen_facility_id: str | None = None
    decision_reason: str | None = None


@router.post(
    "/shortlists",
    status_code=status.HTTP_201_CREATED,
    operation_id="createShortlist",
)
def create_shortlist(
    body: ShortlistIn,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    headers: Dependencies.Headers,
) -> dict[str, Any]:
    warehouse_id, schema = _config_or_503(config)
    email = _require_user(headers)
    try:
        return dp.create_shortlist(
            ws, warehouse_id, schema,
            user_email=email,
            name=body.name, query=body.query,
            facility_ids=body.facility_ids, notes=body.notes,
        )
    except DeltaQueryError as exc:
        logger.exception("create_shortlist failed")
        raise HTTPException(status_code=502, detail=f"Persistence error: {exc}") from exc


@router.get("/shortlists", operation_id="listMyShortlists")
def list_my_shortlists(
    ws: Dependencies.Client,
    config: Dependencies.Config,
    headers: Dependencies.Headers,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    warehouse_id, schema = _config_or_503(config)
    email = _require_user(headers)
    try:
        return dp.list_shortlists(
            ws, warehouse_id, schema, user_email=email, limit=limit,
        )
    except DeltaQueryError as exc:
        logger.exception("list_my_shortlists failed")
        raise HTTPException(status_code=502, detail=f"Persistence error: {exc}") from exc


@router.get("/shortlists/{shortlist_id}", operation_id="getShortlist")
def get_shortlist(
    shortlist_id: str,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    headers: Dependencies.Headers,
) -> dict[str, Any]:
    warehouse_id, schema = _config_or_503(config)
    email = _require_user(headers)
    row = dp.get_shortlist(
        ws, warehouse_id, schema,
        shortlist_id=shortlist_id, user_email=email,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Shortlist not found")
    return row


@router.patch("/shortlists/{shortlist_id}", operation_id="updateShortlist")
def update_shortlist(
    shortlist_id: str,
    body: ShortlistPatch,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    headers: Dependencies.Headers,
) -> dict[str, Any]:
    warehouse_id, schema = _config_or_503(config)
    email = _require_user(headers)
    row = dp.update_shortlist(
        ws, warehouse_id, schema,
        shortlist_id=shortlist_id, user_email=email,
        name=body.name, facility_ids=body.facility_ids, notes=body.notes,
        chosen_facility_id=body.chosen_facility_id,
        decision_reason=body.decision_reason,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Shortlist not found")
    return row


@router.delete(
    "/shortlists/{shortlist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteShortlist",
)
def delete_shortlist(
    shortlist_id: str,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    headers: Dependencies.Headers,
) -> None:
    warehouse_id, schema = _config_or_503(config)
    email = _require_user(headers)
    ok = dp.delete_shortlist(
        ws, warehouse_id, schema,
        shortlist_id=shortlist_id, user_email=email,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Shortlist not found")


# --- Overrides (revise) ------------------------------------------------------


class OverrideIn(BaseModel):
    field_name: str
    old_value: str | None = None
    new_value: str | None = None
    reason: str | None = None


@router.post(
    "/facilities/{facility_id}/overrides",
    status_code=status.HTTP_201_CREATED,
    operation_id="addFacilityOverride",
)
def add_facility_override(
    facility_id: str,
    body: OverrideIn,
    ws: Dependencies.Client,
    config: Dependencies.Config,
    headers: Dependencies.Headers,
) -> dict[str, Any]:
    warehouse_id, schema = _config_or_503(config)
    email = _require_user(headers)
    return dp.add_override(
        ws, warehouse_id, schema,
        user_email=email, facility_id=facility_id,
        field_name=body.field_name, old_value=body.old_value,
        new_value=body.new_value, reason=body.reason,
    )


@router.get(
    "/facilities/{facility_id}/overrides",
    operation_id="listFacilityOverrides",
)
def list_facility_overrides(
    facility_id: str,
    ws: Dependencies.Client,
    config: Dependencies.Config,
) -> list[dict[str, Any]]:
    warehouse_id, schema = _config_or_503(config)
    return dp.list_overrides(
        ws, warehouse_id, schema, facility_id=facility_id,
    )


__all__ = ["router"]
