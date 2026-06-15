"""Coverage Index + Capability Gaps API routes."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import DatabricksSQLDependency
from ..db.databricks_sql import _fqn

router = APIRouter(tags=["coverage"])

COVERAGE_TABLE = _fqn("district_coverage_index")
GAPS_TABLE = _fqn("district_capability_gaps")


@router.get("/coverage")
async def district_coverage(db: DatabricksSQLDependency, limit: int = 100):
    """District-level coverage index: trusted facilities per household surveyed.

    Returns districts ranked by coverage (worst first).
    """
    rows = db.execute(f"""
        SELECT * FROM {COVERAGE_TABLE}
        ORDER BY coverage_index ASC
        LIMIT {limit}
    """)
    return {
        "districts": rows,
        "count": len(rows),
        "description": "Hospital Coverage Index: trusted facilities per 1,000 households surveyed",
    }


@router.get("/coverage/{district_name}")
async def district_coverage_detail(district_name: str, db: DatabricksSQLDependency):
    """Get coverage details for a specific district."""
    clean = district_name.strip().replace("'", "''").lower()
    rows = db.execute(f"""
        SELECT * FROM {COVERAGE_TABLE}
        WHERE district_name = '{clean}'
        LIMIT 1
    """)
    if not rows:
        return {"error": "District not found"}
    return rows[0]


@router.get("/gaps")
async def capability_gaps(db: DatabricksSQLDependency, district: str | None = None, specialty: str | None = None, gap_status: str | None = None, limit: int = 200):
    """Capability gaps: which specialties are missing in which districts.

    Filter by district, specialty, or gap_status (missing/critical/low/available).
    """
    where_parts = []
    if district:
        where_parts.append(f"district_name = '{district.strip().lower()}'")
    if specialty:
        where_parts.append(f"specialty = '{specialty.strip().lower()}'")
    if gap_status:
        where_parts.append(f"gap_status = '{gap_status.strip().lower()}'")

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    rows = db.execute(f"""
        SELECT * FROM {GAPS_TABLE}
        {where_clause}
        ORDER BY gap_status, district_name
        LIMIT {limit}
    """)
    return {
        "gaps": rows,
        "count": len(rows),
        "description": "Capability gaps: missing specialties per district",
    }


@router.get("/gaps/summary")
async def gaps_summary(db: DatabricksSQLDependency):
    """Summary of capability gaps across all districts."""
    rows = db.execute(f"""
        SELECT
            specialty,
            SUM(CASE WHEN gap_status = 'missing' THEN 1 ELSE 0 END) as missing_districts,
            SUM(CASE WHEN gap_status = 'critical' THEN 1 ELSE 0 END) as critical_districts,
            SUM(CASE WHEN gap_status = 'low' THEN 1 ELSE 0 END) as low_districts,
            SUM(CASE WHEN gap_status = 'available' THEN 1 ELSE 0 END) as available_districts
        FROM {GAPS_TABLE}
        GROUP BY specialty
        ORDER BY missing_districts DESC
    """)
    return {"specialties": rows, "count": len(rows)}
