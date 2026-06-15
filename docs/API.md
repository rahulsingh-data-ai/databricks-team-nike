# Referral Copilot — Backend API

All endpoints share the prefix `/api`. Responses are JSON unless noted.
The backend serves the SPA at `/`, so during local dev your frontend
can call relative paths.

## Two ways into the same pipeline

```
                      ┌─────────────────────────────┐
   Web UI ────POST────┤                             │
   (this is you)      │  Supervisor / LangGraph     │
                      │  parse → search → score →   │  ──► same recommendation
   SMS / phone ──────►│  enrich → recommend         │
   (Twilio webhook)   └─────────────────────────────┘
```

Same data, same trust scoring, same multilingual support, same
persistence — the only difference is the response shape (rich JSON for
the UI, ≤160-char text for SMS).

---

## 1. Core search flow

### `POST /api/search`

Run the full 5-node LangGraph pipeline. **This is the primary endpoint
the UI uses.**

Request:
```json
{
  "query": "dialysis near Jaipur",
  "limit": 20,
  "mode": "graph",
  "session_id": null
}
```

| field | type | notes |
|---|---|---|
| `query` | string, 1-500 chars | natural language, any of the 9 supported languages |
| `limit` | int, 1-200, default 20 | max facilities to return |
| `mode` | `"graph"` (default) or `"supervisor"` | graph = deterministic pipeline; supervisor = LLM picks tools |
| `session_id` | string \| null | only used by supervisor mode for multi-turn |

Response (graph mode):
```json
{
  "query": {
    "raw_query": "dialysis near Jaipur",
    "capability_text": "dialysis",
    "location_text": "Jaipur",
    "specialty_terms": ["nephrology", "internalMedicine"],
    "location": {
      "district": "JAIPUR",
      "state": "RAJASTHAN",
      "latitude": 26.91,
      "longitude": 75.79,
      "pincode": 302001
    },
    "urgency": "routine",
    "language": "en"
  },
  "recommendation_summary": "Among 8 results, SMS Hospital ...",
  "result_count": 8,
  "facilities": [ /* see Facility card */ ],
  "district_health": { "district", "state", "institutional_birth_5y_pct", ... },
  "agent_trace": [
    { "agent": "Query Parser", "reasoning": "...", "output": {...}, "latency_ms": 1234 },
    { "agent": "Facility Search", "output": "Found 12 candidates", "latency_ms": 850 },
    { "agent": "Evidence Scorer", "output": "Scored 12 facilities", "latency_ms": 12345 },
    { "agent": "Context Enricher", "output": "District health: loaded", "latency_ms": 200 },
    { "agent": "Recommendation Generator", "reasoning": "...", "output": "...", "latency_ms": 3000 }
  ]
}
```

**Facility card** (each item in `facilities`):
```json
{
  "unique_id": "fa8ffca9-...",
  "name": "SMS Hospital",
  "facility_type": "hospital",
  "address": { "city": "Jaipur", "state": "Rajasthan", "pincode": "302001" },
  "latitude": 26.91, "longitude": 75.79,
  "distance_km": 12.5,
  "trust_signal": "strong_evidence",   // strong_evidence | partial_evidence | weak_evidence | suspicious | no_evidence
  "trust_rank": 5,                     // 1..5, higher is better
  "quality_boost": 3,                  // 0..5, FDR independent metadata signals
  "quality_reasons": ["recently updated", "affiliated staff listed", "3 social media channels"],
  "evidence_summary": "Confirmed by 4 independent sources ...",
  "missing_evidence": ["No bed capacity data (75% of facilities lack this)", "..."],
  "source_count": 4,
  "search_method": "keyword+vector",   // keyword | vector | keyword+vector
  "evidence": {
    "specialties": ["nephrology", "cardiology", ...],
    "specialties_count": 28,
    "capabilities": [...], "capabilities_count": N,
    "procedures": [...],   "procedures_count": N,
    "equipment": [...],    "equipment_count": N,
    "source_types": ["overture", "dynamic", "constant"],
    "source_urls": ["https://...", "..."],
    "description": "...",
    "metadata": { "facility_type", "capacity", "number_doctors", "year_established", "recency_of_update", ... },
    "attributes": { /* see below */ }
  },
  "attributes": {
    "accepts_pmjay": false,
    "accepts_cghs": false,
    "accepts_esi": false,
    "nabh_accredited": true,
    "jci_accredited": false,
    "is_24x7": true,
    "has_ambulance": true,
    "has_telemedicine": false,
    "has_blood_bank": true,
    "has_icu": true,
    "has_nicu": false,
    "has_emergency": true,
    "is_government": true,
    "is_private": false,
    "is_nonprofit": false,
    "offers_charity_care": false,
    "is_ngo_source": false,
    "languages": ["Hindi", "English"]
  }
}
```

### `POST /api/stream`

Same pipeline as `/search` but streams **Server-Sent Events** as each
node completes. Use `EventSource` on the frontend for a "thinking..." UX.

Request body: `{ "query": "..." }`

Event sequence (each `event:` is one SSE block):
- `pipeline_start` — `{ "query", "steps": 5 }`
- `step_start` × 5 — `{ "step", "name", "message" }`
- `step_complete` × 5 — `{ "step", "name", "latency_ms", "output": { ... } }`
- `pipeline_complete` — `{ "result_count", "recommendation", "agent_trace" }`
- `result` — same shape as `/search` response

### `POST /api/agent/command`

Alternate to `/search` that uses the **supervisor**: the LLM picks
which tools to call dynamically rather than running a fixed graph.
Useful for "explore" UX where the answer doesn't fit the standard
search-result shape.

Returns:
```json
{
  "query": "string",
  "session_id": "...",
  "tool_calls": [ { "tool", "args", "result_summary", "latency_ms", "success" } ],
  "final_recommendation": "string",
  "parsed_query": { ... },
  "facilities": [ /* same Facility cards */ ],
  "district_health": { ... },
  "total_latency_ms": 12345
}
```

---

## 2. Facility detail / evidence

### `GET /api/facility/{facility_id}`

Full record + formatted evidence + attributes.

Returns:
```json
{
  "facility": { /* raw facilities_gold row */ },
  "evidence": { /* same shape as `evidence` field in Facility card */ }
}
```

### `GET /api/citations/{facility_id}?capability=dialysis`

Per-claim → source URL mapping. **This satisfies the track's "cite the
underlying facility text" requirement.**

Returns:
```json
{
  "facility_id": "fa8ffca9-...",
  "facility_name": "SMS Hospital",
  "source_urls": ["https://...", "..."],
  "source_types": ["overture", "dynamic", "constant"],
  "claims": [
    {
      "field": "capability",       // capability | procedure | equipment | description | specialties
      "claim": "Has dialysis machine on site",
      "matches_search": true,      // does this claim mention the searched capability?
      "supporting_sources": ["https://..."]   // up to 5 source URLs that back this claim
    },
    ...
  ],
  "summary": {
    "claim_count": 47,
    "matching_claim_count": 6,
    "source_url_count": 8,
    "distinct_source_types": 4
  }
}
```

### `GET /api/compare?facility_a={id1}&facility_b={id2}&capability=...`

Side-by-side diff.

Returns:
```json
{
  "facility_a": { "id", "name", "type", "city", "state", "trust": {...}, "evidence": {...} },
  "facility_b": { ... },
  "diff": {
    "specialties_only_in_a": [...],
    "specialties_only_in_b": [...],
    "specialties_shared": [...],
    "trust_comparison": { "a": "strong_evidence", "b": "partial_evidence", "better": "a" },
    "missing_data_comparison": { "a_missing": [...], "b_missing": [...], "a_missing_count", "b_missing_count" },
    "source_comparison": { "a_sources": 4, "b_sources": 2 }
  }
}
```

---

## 3. Reference data (search UI)

### `GET /api/capabilities`
All distinct specialties from the dataset (for filter chips). Cached
10 min.
```json
{ "capabilities": ["anesthesia", "cardiology", ..., "urology"], "count": 187 }
```

### `GET /api/health`
System probe.
```json
{
  "status": "ok",                                  // ok | degraded
  "databricks_sql": { "status": "connected", "facilities_count": 9953 },
  "vector_search":  { "status": "ready", "ready": true, "indexed_rows": 9953 },
  "llm":            { "status": "ready", "endpoint": "databricks-meta-llama-3-3-70b-instruct" }
}
```

---

## 4. Healthcare Desert + Coverage views

### `GET /api/desert-radar?limit=100`
Districts ranked by `desert_score` (heatmap source).
```json
{
  "districts": [
    {
      "district_name": "shahjahanpur",
      "state_ut": "uttar pradesh",
      "total_facilities": 1,
      "trusted_facilities": 0,
      "institutional_birth_5y_pct": 63.3,
      "hh_member_covered_health_insurance_pct": 38.2,
      "desert_score": 122.5
    },
    ...
  ],
  "count": 100,
  "description": "Healthcare Desert Zones: High need, low trusted facility coverage"
}
```

### `GET /api/coverage?limit=100`
Hospital Coverage Index (worst first).

### `GET /api/coverage/{district_name}`
Single-district detail; 404 if not found.

### `GET /api/gaps?district=...&specialty=...&gap_status=missing&limit=200`
Capability gaps. `gap_status` ∈ {`missing`, `critical`, `low`, `available`}.

### `GET /api/gaps/summary`
Per-specialty rollup: how many districts lack each specialty.

---

## 5. Persistence (Lakebase, deploys w/ Buka's bundle)

All routes 404 / 500 cleanly until Lakebase is reachable.

### Shortlist
- `POST /api/shortlist` `{ user_id, search_query, facility_id, facility_name, capability, trust_signal, distance_km, notes }`
- `GET /api/shortlist/{user_id}?limit=100`
- `PATCH /api/shortlist/{id}/notes` `{ "notes": "..." }`
- `DELETE /api/shortlist/{id}`

### Manual overrides
- `POST /api/overrides` — planner corrects a trust signal
  `{ user_id, facility_id, capability, overridden_trust_signal, reason }`
  - `overridden_trust_signal` must be one of `strong_evidence | partial_evidence | weak_evidence | suspicious | no_evidence`
- `GET /api/overrides/{facility_id}?limit=50`

### Review decisions
- `POST /api/reviews` `{ user_id, facility_id, status, notes }`
  - `status` must be one of `verified | rejected | needs_follow_up`
- `GET /api/reviews/{facility_id}?limit=50`

### Search history
- `POST /api/search-history` `{ user_id, query, capability_text, location_text, result_count, top_trust_signal }`
- `GET /api/search-history/{user_id}?limit=50`

---

## 6. SMS (demo / optional)

### `POST /api/sms/simulate-inbound`
Pretend a phone texted in. **No Twilio creds required** — perfect for
demo screens that show the SMS UX in the browser.

Request:
```json
{ "phone": "+919812345678", "body": "dialysis near Jaipur" }
```

Response:
```json
{
  "reply": "Found 8 ... 1. SMS Hospital (12.5 km) - verified [Govt, NABH, 24x7] ...",
  "thread": [ { "direction": "inbound", "body", "timestamp" }, ... ]
}
```

Keyword commands the user can send: `HELP`, `MORE`, `SAVE 1`, `SAVE 2`.

### `GET /api/sms/threads`
All conversations.

### `GET /api/sms/thread/{phone}`
Single conversation.

---

## 7. Admin / telemetry (optional)

- `GET /api/admin/telemetry` — trust signal distribution + supervisor tool catalog
- `GET /api/admin/recent-searches?limit=20` — recent searches across users (Lakebase)

---

## 8. apx-scaffold endpoints

- `GET /api/version` — app version
- `GET /api/current-user` — logged-in Databricks user (OBO token)

---

## Frontend v1 — the minimum set

| UI element | Endpoint |
|---|---|
| Search page | `POST /api/search` |
| Search chips | `GET /api/capabilities` |
| Streaming "thinking" UI | `POST /api/stream` |
| Facility detail page | `GET /api/facility/{id}` |
| "Why trust this?" tab | `GET /api/citations/{id}` |
| Compare two facilities | `GET /api/compare` |
| Healthcare Desert heatmap | `GET /api/desert-radar` |
| Coverage Index page | `GET /api/coverage` |
| Capability gaps page | `GET /api/gaps`, `GET /api/gaps/summary` |
| Save flow | `POST /api/shortlist` + `GET /api/shortlist/{user_id}` |
| Health badge | `GET /api/health` |

Everything beyond that is incremental (overrides, reviews, search history,
SMS demo, admin telemetry).

---

## Error contract

- `400` — bad request body (Pydantic validation, e.g. `gap_status` not in whitelist)
- `404` — entity not found (`/facility/{id}`, `/coverage/{district}`)
- `500` — unexpected — body has `{ "detail": "..." }`

The supervisor and graph endpoints **never raise**; they always return a
`200` with a `final_recommendation` (falling back to a template summary
when the LLM is unavailable). Tool failures appear as `success: false`
inside `tool_calls`.

---

## Auth (production)

When deployed as a Databricks App, every request from the embedded SPA
carries `X-Forwarded-Access-Token` (OBO). The backend uses
`Dependencies.UserClient` for any on-behalf-of action. For the v1 UI
nothing else is required from the frontend.
