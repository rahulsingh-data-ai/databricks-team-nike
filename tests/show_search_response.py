"""Invoke the same pipeline /api/search calls and pretty-print the response.

Run:
    set -a && source .env && set +a
    uv run python tests/show_search_response.py "dialysis near Jaipur"
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from team_nike_hackathon.backend.agents.graph import run_referral_pipeline
from team_nike_hackathon.backend.db.databricks_sql import DatabricksSQLClient


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "dialysis near Jaipur"
    db = DatabricksSQLClient(
        host=os.environ["DATABRICKS_HOST"],
        http_path=os.environ["DATABRICKS_HTTP_PATH"],
        token=os.environ["DATABRICKS_TOKEN"],
    )

    print(f">>> POST /api/search  body=" + json.dumps({"query": query, "limit": 5}))
    print()

    result = run_referral_pipeline(db, query)

    # Trim facility list to the same 5 the API caller would normally see first
    facilities = (result.get("facilities") or [])[:3]
    slim = {
        "query":                  result.get("query"),
        "recommendation_summary": result.get("recommendation_summary"),
        "result_count":           result.get("result_count"),
        "district_health":        result.get("district_health"),
        "agent_trace": [
            {
                "agent": s.get("agent"),
                "method": s.get("method"),
                "output": s.get("output"),
                "latency_ms": s.get("latency_ms"),
            }
            for s in (result.get("agent_trace") or [])
        ],
        "facilities_first_3": [
            {
                "name":             f.get("name"),
                "facility_type":    f.get("facility_type"),
                "address":          f.get("address"),
                "distance_km":      f.get("distance_km"),
                "trust_signal":     f.get("trust_signal"),
                "trust_rank":       f.get("trust_rank"),
                "quality_boost":    f.get("quality_boost"),
                "evidence_summary": f.get("evidence_summary"),
                "missing_evidence": f.get("missing_evidence"),
                "attributes":       f.get("attributes"),
                "search_method":    f.get("search_method"),
            }
            for f in facilities
        ],
    }

    print(json.dumps(slim, indent=2, default=str))


if __name__ == "__main__":
    main()
