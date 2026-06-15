"""Smoke test for every endpoint's underlying logic.

Calls each route handler / query function directly against the real
Databricks workspace (no uvicorn / no Lakebase). Prints PASS / FAIL for
each so we know the backend is wired correctly before Buka deploys.

Run:
    set -a && source .env && set +a
    uv run python tests/smoke_endpoints.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from typing import Any

# Make the package importable when run from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from team_nike_hackathon.backend.db.databricks_sql import DatabricksSQLClient
from team_nike_hackathon.backend.db.facility_queries import (
    get_capabilities_list,
    get_desert_scores,
    get_district_health,
    get_facility_by_id,
    map_query_to_specialties,
    resolve_location,
    search_facilities,
)
from team_nike_hackathon.backend.scoring.citations import build_citations
from team_nike_hackathon.backend.scoring.evidence_formatter import format_evidence
from team_nike_hackathon.backend.scoring.trust_scorer import score_facility


def _client() -> DatabricksSQLClient:
    return DatabricksSQLClient(
        host=os.environ.get("DATABRICKS_HOST", "dbc-8ca6fd25-084d.cloud.databricks.com"),
        http_path=os.environ.get(
            "DATABRICKS_HTTP_PATH", "/sql/1.0/warehouses/1c11bafa432cc107"
        ),
        token=os.environ.get("DATABRICKS_TOKEN", ""),
    )


# ---------------------------------------------------------------------------
# Per-route checks
# ---------------------------------------------------------------------------

def check_health(db) -> dict:
    out = db.health_check()
    assert out["status"] == "connected", out
    assert out["facilities_count"] > 9000
    return {"facilities_count": out["facilities_count"]}


def check_capabilities(db) -> dict:
    caps = get_capabilities_list(db)
    assert len(caps) > 50, f"only got {len(caps)} capabilities"
    assert "cardiology" in caps
    return {"count": len(caps), "sample": caps[:5]}


def check_resolve_location(db) -> dict:
    loc = resolve_location(db, "Jaipur")
    assert loc and loc["state"].lower() == "rajasthan", loc
    return loc


def check_search(db) -> dict:
    terms = map_query_to_specialties("dialysis")
    rows = search_facilities(
        db, specialty_terms=terms,
        lat=26.91, lon=75.79, state="Rajasthan", district="Jaipur", limit=5,
    )
    assert len(rows) >= 1, "no facilities returned"
    top = rows[0]
    assert top.get("name"), "first row missing name"
    return {"results": len(rows), "top": top["name"]}


def check_facility_by_id(db, facility_id: str) -> dict:
    row = get_facility_by_id(db, facility_id)
    assert row, f"facility {facility_id} not found"
    return {"name": row.get("name"), "city": row.get("address_city")}


def check_trust_scoring(db) -> dict:
    rows = search_facilities(
        db, specialty_terms=["cardiology"],
        lat=12.97, lon=77.59, state="Karnataka", district="Bangalore", limit=1,
    )
    assert rows, "no rows to score"
    score = score_facility(rows[0], ["cardiology"])
    assert score["trust_signal"] in {
        "strong_evidence", "partial_evidence", "weak_evidence",
        "suspicious", "no_evidence",
    }
    return {
        "signal": score["trust_signal"],
        "rank": score["trust_rank"],
        "quality_boost": score.get("quality_boost"),
        "missing_count": len(score["missing_evidence"]),
    }


def check_evidence_formatter(db) -> dict:
    rows = search_facilities(
        db, specialty_terms=["pediatrics"],
        lat=21.27, lon=81.66, state="Chhattisgarh", district="Raipur", limit=1,
    )
    assert rows
    ev = format_evidence(rows[0])
    assert "attributes" in ev
    return {
        "specialties": ev["specialties_count"],
        "sources": len(ev["source_types"]),
        "attrs_pmjay": ev["attributes"]["accepts_pmjay"],
        "attrs_nabh": ev["attributes"]["nabh_accredited"],
        "attrs_24x7": ev["attributes"]["is_24x7"],
    }


def check_citations(db) -> dict:
    rows = search_facilities(
        db, specialty_terms=["cardiology"],
        lat=12.97, lon=77.59, state="Karnataka", district="Bangalore", limit=1,
    )
    assert rows
    cit = build_citations(rows[0], ["cardiology"])
    assert "claims" in cit
    return {
        "claim_count": cit["summary"]["claim_count"],
        "matching": cit["summary"]["matching_claim_count"],
        "sources": cit["summary"]["source_url_count"],
    }


def check_district_health(db) -> dict:
    row = get_district_health(db, "Jaipur")
    assert row, "Jaipur not found in NFHS-5"
    return {
        "institutional_birth": row.get("institutional_birth_5y_pct"),
        "insurance_pct": row.get("hh_member_covered_health_insurance_pct"),
    }


def check_desert_scores(db) -> dict:
    rows = get_desert_scores(db, limit=5)
    assert len(rows) == 5
    return {"top_district": rows[0]["district_name"], "score": rows[0]["desert_score"]}


def check_coverage(db) -> dict:
    rows = db.execute(
        "SELECT * FROM workspace.referral_copilot.district_coverage_index "
        "ORDER BY coverage_index ASC LIMIT 3"
    )
    assert len(rows) == 3
    return {"worst": rows[0]["district_name"], "covered_count": rows[0]["trusted_facilities"]}


def check_gaps(db) -> dict:
    rows = db.execute(
        "SELECT * FROM workspace.referral_copilot.district_capability_gaps "
        "WHERE gap_status = 'missing' LIMIT 3"
    )
    return {"missing_examples": len(rows)}


def check_shortlist_crud(db) -> dict:
    user_id = "smoke_test_user"
    item_id = "smoke_" + str(int(time.time()))
    # insert
    db.execute(
        f"INSERT INTO workspace.referral_copilot.shortlist "
        f"(id, user_id, facility_id, facility_name, saved_at) "
        f"VALUES ('{item_id}', '{user_id}', 'fac_x', 'Test Hospital', "
        f"TIMESTAMP '2026-06-15T00:00:00Z')"
    )
    # read
    rows = db.execute(
        f"SELECT id FROM workspace.referral_copilot.shortlist "
        f"WHERE user_id = '{user_id}' AND id = '{item_id}'"
    )
    assert len(rows) == 1, "row not found after insert"
    # update
    db.execute(
        f"UPDATE workspace.referral_copilot.shortlist "
        f"SET notes = 'tested' WHERE id = '{item_id}'"
    )
    # delete
    db.execute(
        f"DELETE FROM workspace.referral_copilot.shortlist WHERE id = '{item_id}'"
    )
    return {"insert": "ok", "select": "ok", "update": "ok", "delete": "ok"}


def check_sms_formatter():
    from team_nike_hackathon.backend.agents.sms_formatter import format_sms_reply
    fake = {
        "query": {"capability_text": "dialysis", "location_text": "Jaipur"},
        "facilities": [
            {
                "name": "SMS Hospital", "facility_type": "hospital",
                "distance_km": 12.5, "trust_signal": "strong_evidence",
                "evidence_summary": "4 sources confirm nephrology",
                "attributes": {"accepts_pmjay": True, "nabh_accredited": True, "is_24x7": True},
            },
        ],
        "recommendation_summary": "Top pick: SMS Hospital",
        "result_count": 8,
    }
    text = format_sms_reply(fake)
    assert "SMS Hospital" in text
    assert "PM-JAY" in text or "NABH" in text
    return {"reply_chars": len(text)}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

CHECKS = [
    ("GET  /api/health             ",                check_health),
    ("GET  /api/capabilities       ",                check_capabilities),
    ("internal: resolve_location() ",                check_resolve_location),
    ("POST /api/search             ",                check_search),
    ("internal: trust_scorer       ",                check_trust_scoring),
    ("internal: evidence_formatter ",                check_evidence_formatter),
    ("GET  /api/citations/{id}     ",                check_citations),
    ("GET  /api/desert-radar       ",                check_desert_scores),
    ("GET  /api/coverage           ",                check_coverage),
    ("GET  /api/gaps               ",                check_gaps),
    ("internal: district_health    ",                check_district_health),
    ("Delta CRUD: /api/shortlist   ",                check_shortlist_crud),
]

OFFLINE_CHECKS = [
    ("internal: sms_formatter      ", check_sms_formatter),
]


def main():
    db = _client()
    pass_ct = 0
    fail_ct = 0
    total_start = time.time()

    # Find an existing facility_id for the by-id check
    rows = db.execute(
        "SELECT unique_id FROM workspace.referral_copilot.facilities_gold LIMIT 1"
    )
    sample_id = rows[0]["unique_id"] if rows else None

    print(f"{'endpoint':<32s} {'lat (ms)':>10s}  result")
    print("-" * 100)

    for label, fn in CHECKS:
        start = time.time()
        try:
            if fn is check_facility_by_id:
                result: Any = fn(db, sample_id)
            else:
                result = fn(db)
            ms = round((time.time() - start) * 1000, 1)
            print(f"PASS  {label}  {ms:>10}  {str(result)[:80]}")
            pass_ct += 1
        except Exception as e:  # noqa: BLE001
            ms = round((time.time() - start) * 1000, 1)
            print(f"FAIL  {label}  {ms:>10}  {e!r}")
            traceback.print_exc(limit=2)
            fail_ct += 1

    # also exercise facility_by_id with a real id
    if sample_id:
        start = time.time()
        try:
            r = check_facility_by_id(db, sample_id)
            ms = round((time.time() - start) * 1000, 1)
            print(f"PASS  GET  /api/facility/{{id}}      {ms:>10}  {str(r)[:80]}")
            pass_ct += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  GET  /api/facility/{{id}}     {e!r}")
            fail_ct += 1

    for label, fn in OFFLINE_CHECKS:
        start = time.time()
        try:
            result = fn()
            ms = round((time.time() - start) * 1000, 1)
            print(f"PASS  {label}  {ms:>10}  {str(result)[:80]}")
            pass_ct += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL  {label}  {e!r}")
            fail_ct += 1

    total = round(time.time() - total_start, 1)
    print("-" * 100)
    print(f"{pass_ct} passed, {fail_ct} failed in {total}s")
    sys.exit(0 if fail_ct == 0 else 1)


if __name__ == "__main__":
    main()
