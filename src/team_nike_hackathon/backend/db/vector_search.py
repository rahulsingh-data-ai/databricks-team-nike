"""Vector search client for hybrid (keyword + semantic) facility search.

Uses Databricks Vector Search with databricks-gte-large-en embeddings.
"""

from __future__ import annotations

import json
import os
import logging
import requests
from typing import Any

logger = logging.getLogger(__name__)

VS_INDEX = os.environ.get(
    "VS_INDEX_NAME", "workspace.referral_copilot.facilities_vs_index"
)
VS_ENDPOINT = os.environ.get("VS_ENDPOINT_NAME", "referral-copilot-vs")
DATABRICKS_HOST = os.environ.get(
    "DATABRICKS_HOST", "dbc-8ca6fd25-084d.cloud.databricks.com"
)
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")

VS_RETURN_COLUMNS = [
    "unique_id", "name", "facilityTypeId",
    "address_city", "address_stateOrRegion", "address_zipOrPostcode",
    "latitude", "longitude",
    "specialties", "capability", "description",
    "source_types", "source_urls",
    "capacity", "numberDoctors", "yearEstablished",
    "base_trust_signal", "trust_rank", "missing_data_count",
    "distinct_source_count",
]


def vector_search(
    query_text: str,
    num_results: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    """Search facilities using semantic similarity on search_text embeddings.

    Args:
        query_text: natural language search query
        num_results: max results to return (capped at 200)
        filters: optional column filters
            (e.g. {"address_stateOrRegion": "Rajasthan"})

    Returns:
        List of facility dicts. Each row includes a ``similarity_score``.
        Returns an empty list on any error (caller can fall back to keyword search).
    """
    if not query_text or not DATABRICKS_TOKEN:
        return []

    num_results = max(1, min(int(num_results or 20), 200))

    host = DATABRICKS_HOST
    if not host.startswith("https://"):
        host = f"https://{host}"

    url = f"{host}/api/2.0/vector-search/indexes/{VS_INDEX}/query"
    headers = {
        "Authorization": f"Bearer {DATABRICKS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "query_text": query_text,
        "columns": VS_RETURN_COLUMNS,
        "num_results": num_results,
    }

    if filters:
        payload["filters_json"] = json.dumps(filters)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.warning(f"Vector search request failed: {e}")
        return []
    except ValueError as e:
        logger.warning(f"Vector search response was not JSON: {e}")
        return []

    columns = data.get("manifest", {}).get("columns", []) or []
    col_names = [c.get("name") for c in columns]
    data_rows = data.get("result", {}).get("data_array", []) or []

    results: list[dict] = []
    for row in data_rows:
        if not row:
            continue
        # Vector Search appends a `__db_score` column as the last entry.
        score_idx = None
        if col_names and col_names[-1] in ("__db_score", "score"):
            score_idx = len(col_names) - 1
            facility_cols = col_names[:-1]
            facility_vals = row[: len(facility_cols)]
        elif len(row) == len(col_names) + 1:
            # Score is appended without an explicit column name in the manifest.
            score_idx = len(row) - 1
            facility_cols = col_names
            facility_vals = row[: len(col_names)]
        else:
            facility_cols = col_names
            facility_vals = row[: len(col_names)]

        facility = dict(zip(facility_cols, facility_vals))
        facility["similarity_score"] = (
            row[score_idx] if score_idx is not None else None
        )
        results.append(facility)

    return results


def hybrid_search(
    query_text: str,
    keyword_results: list[dict],
    num_vector_results: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    """Combine keyword SQL results with vector search results.

    Merges and deduplicates, tagging facilities that appear in both.
    Keyword results keep their distance-based ordering;
    vector-only results are appended afterwards.
    """
    vector_results = vector_search(query_text, num_vector_results, filters)

    if not vector_results:
        return keyword_results

    vector_ids = {v.get("unique_id") for v in vector_results}
    keyword_ids: set[str] = set()
    merged: list[dict] = []

    for f in keyword_results:
        uid = f.get("unique_id")
        if not uid:
            continue
        keyword_ids.add(uid)
        f["search_method"] = (
            "keyword+vector" if uid in vector_ids else "keyword"
        )
        merged.append(f)

    for f in vector_results:
        uid = f.get("unique_id")
        if not uid or uid in keyword_ids:
            continue
        f["search_method"] = "vector"
        merged.append(f)

    return merged
