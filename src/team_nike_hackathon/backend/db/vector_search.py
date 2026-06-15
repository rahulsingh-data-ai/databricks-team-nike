"""Vector search client for hybrid (keyword + semantic) facility search.

Uses Databricks Vector Search with databricks-gte-large-en embeddings.
"""

from __future__ import annotations

import os
import logging
import requests
from typing import Any

logger = logging.getLogger(__name__)

VS_INDEX = "workspace.referral_copilot.facilities_vs_index"
VS_ENDPOINT = "referral-copilot-vs"
DATABRICKS_HOST = os.environ.get("DATABRICKS_HOST", "dbc-8ca6fd25-084d.cloud.databricks.com")
DATABRICKS_TOKEN = os.environ.get("DATABRICKS_TOKEN", "")


def vector_search(
    query_text: str,
    num_results: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    """Search facilities using semantic similarity on search_text embeddings.

    Args:
        query_text: natural language search query
        num_results: max results to return
        filters: optional column filters (e.g. {"address_stateOrRegion": "Rajasthan"})

    Returns:
        List of facility dicts with similarity scores.
    """
    host = DATABRICKS_HOST
    if not host.startswith("https://"):
        host = f"https://{host}"

    url = f"{host}/api/2.0/vector-search/indexes/{VS_INDEX}/query"
    headers = {
        "Authorization": f"Bearer {DATABRICKS_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "query_text": query_text,
        "columns": [
            "unique_id", "name", "facilityTypeId",
            "address_city", "address_stateOrRegion", "address_zipOrPostcode",
            "latitude", "longitude",
            "specialties", "capability", "description",
            "source_types", "source_urls",
            "capacity", "numberDoctors", "yearEstablished",
            "base_trust_signal", "trust_rank", "missing_data_count",
            "distinct_source_count",
        ],
        "num_results": num_results,
    }

    if filters:
        filter_conditions = {}
        for key, value in filters.items():
            filter_conditions[key] = value
        payload["filters_json"] = filter_conditions

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = []
        columns = data.get("manifest", {}).get("columns", [])
        col_names = [c["name"] for c in columns]

        for row in data.get("result", {}).get("data_array", []):
            facility = dict(zip(col_names, row))
            # Last column is the similarity score
            facility["similarity_score"] = row[-1] if len(row) > len(col_names) - 1 else None
            results.append(facility)

        return results

    except Exception as e:
        logger.warning(f"Vector search failed: {e}")
        return []


def hybrid_search(
    query_text: str,
    keyword_results: list[dict],
    num_vector_results: int = 20,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    """Combine keyword SQL results with vector search results.

    Merges and deduplicates, boosting facilities that appear in both.
    """
    vector_results = vector_search(query_text, num_vector_results, filters)

    if not vector_results:
        return keyword_results

    # Index keyword results by unique_id
    keyword_map = {f["unique_id"]: f for f in keyword_results}
    seen = set()
    merged = []

    # First: facilities from keyword results (already trust-ranked)
    for f in keyword_results:
        uid = f["unique_id"]
        seen.add(uid)
        # Boost if also found by vector search
        f["search_method"] = "keyword+vector" if uid in {v["unique_id"] for v in vector_results} else "keyword"
        merged.append(f)

    # Second: vector-only results (semantic matches not caught by keyword)
    for f in vector_results:
        uid = f["unique_id"]
        if uid not in seen:
            seen.add(uid)
            f["search_method"] = "vector"
            merged.append(f)

    return merged
