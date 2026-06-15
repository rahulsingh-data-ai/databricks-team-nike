"""Coverage Index + Capability Gaps API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..db import DatabricksSQLDependency
from ..db.databricks_sql import _fqn, sql_str

router = APIRouter(tags=["coverage"])

COVERAGE_TABLE = _fqn("district_coverage_index")
GAPS_TABLE = _fqn("district_capability_gaps")
_ALLOWED_GAP_STATUS = {"missing", "critical", "low", "available"}


@router.get("/coverage")
async def district_coverage(
    db: DatabricksSQLDependency,
    limit: int = Query(default=100, ge=1, le=500),
):
    """District-level coverage index: trusted facilities per household surveyed."""
    rows = db.execute(
        f"SELECT * FROM {COVERAGE_TABLE} "
        f"ORDER BY coverage_index ASC LIMIT {limit}"
    )
    return {
        "districts": rows,
        "count": len(rows),
        "description": (
            "Hospital Coverage Index: trusted facilities per 1,000 households surveyed"
        ),
    }


@router.get("/coverage/{district_name}")
async def district_coverage_detail(
    district_name: str, db: DatabricksSQLDependency
):
    """Get coverage details for a specific district."""
    if not district_name or not district_name.strip():
        raise HTTPException(400, "district_name is required")
    rows = db.execute(
        f"SELECT * FROM {COVERAGE_TABLE} "
        f"WHERE district_name = {sql_str(district_name.strip().lower())} "
        f"LIMIT 1"
    )
    if not rows:
        raise HTTPException(404, "District not found")
    return rows[0]


@router.get("/gaps")
async def capability_gaps(
    db: DatabricksSQLDependency,
    district: str | None = None,
    specialty: str | None = None,
    gap_status: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
):
    """Capability gaps: which specialties are missing in which districts."""
    where_parts: list[str] = []
    if district:
        where_parts.append(
            f"district_name = {sql_str(district.strip().lower())}"
        )
    if specialty:
        where_parts.append(
            f"specialty = {sql_str(specialty.strip().lower())}"
        )
    if gap_status:
        status = gap_status.strip().lower()
        if status not in _ALLOWED_GAP_STATUS:
            raise HTTPException(
                400,
                f"gap_status must be one of {sorted(_ALLOWED_GAP_STATUS)}",
            )
        where_parts.append(f"gap_status = {sql_str(status)}")

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    rows = db.execute(
        f"SELECT * FROM {GAPS_TABLE} {where_clause} "
        f"ORDER BY gap_status, district_name LIMIT {limit}"
    )
    return {
        "gaps": rows,
        "count": len(rows),
        "description": "Capability gaps: missing specialties per district",
    }


@router.get("/gaps/summary")
async def gaps_summary(db: DatabricksSQLDependency):
    """Summary of capability gaps across all districts."""
    rows = db.execute(
        f"""
        SELECT
            specialty,
            SUM(CASE WHEN gap_status = 'missing' THEN 1 ELSE 0 END) as missing_districts,
            SUM(CASE WHEN gap_status = 'critical' THEN 1 ELSE 0 END) as critical_districts,
            SUM(CASE WHEN gap_status = 'low' THEN 1 ELSE 0 END) as low_districts,
            SUM(CASE WHEN gap_status = 'available' THEN 1 ELSE 0 END) as available_districts
        FROM {GAPS_TABLE}
        GROUP BY specialty
        ORDER BY missing_districts DESC
        """
    )
    return {"specialties": rows, "count": len(rows)}
