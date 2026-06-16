# MatchCare — Referral Copilot

> **DAIS 2026 Hackathon | Track 3: Where should a patient or coordinator actually go?**

MatchCare turns 10,000 messy Indian healthcare facility records into evidence-backed referrals. Type a care need and location — *"dialysis near Jaipur"*, *"emergency surgery near Patna"* — and get a ranked shortlist where every claim is cited, every score is explained, and uncertainty is visible.

---

## How it meets the spec

| Core Requirement | How MatchCare addresses it |
|---|---|
| **Run as a Databricks App on Free Edition** | Deployed via `databricks bundle deploy`. FastAPI backend, React frontend, SQL Warehouse for queries — no cluster provisioning needed. |
| **Use the provided facility dataset** | Reads the Virtue Foundation Marketplace dataset (10,088 records) through a Bronze → Silver → Gold medallion pipeline. Gold table: 9,953 clean facilities with 26 derived attribute flags. |
| **Clear non-technical user workflow** | Two-box search: "What care?" + "Where?". One click to see ranked results on a map. One click to open the evidence drawer with trust badges, cited text, and a "What's Missing" section. |
| **Cite underlying facility text** | Every result carries a `top_evidence` snippet — the exact `specialties` / `capability` / `description` string that drove the match — plus a per-claim confidence %. |
| **Communicate uncertainty** | Five-level trust signal (strong / partial / weak / suspicious / no-evidence). Pincode confidence score. `needs_geo_review` flag. "What's Missing" section listing data gaps per facility. |
| **Persist user actions** | Four Delta tables — `shortlist`, `facility_overrides`, `facility_reviews`, `search_history` — with full CRUD API endpoints. |

---

## Architecture

```
User (browser)
  │
  ├── Search: "dialysis near Jaipur"
  │
  ▼
React UI (Vite + TanStack Router + Tailwind)
  │
  ├── POST /api/search
  │
  ▼
FastAPI Backend
  │
  ├── 1. LLM Query Parser (Llama 3.3 70B) — optional, for free-form queries
  ├── 2. Keyword SQL Search — against facilities_gold (Delta)
  ├── 3. LLM Evidence Scorer — top 10 re-scored for per-facility confidence
  ├── 4. LLM Re-rank — final order by evidence strength
  │
  ▼
Databricks SQL Warehouse
  │
  ├── facilities_gold (9,953 rows × 96 cols)
  ├── facility_trust_scores
  ├── desert_scores (706 district-level)
  ├── capability_index (278K rows)
  └── user_* persistence tables
```

---

## Data pipeline (ETL)

**Bronze** (raw Marketplace data) → **Silver** (cleaned, typed, normalized) → **Gold** (trust-scored, attribute-flagged, geo-resolved)

Key transformations:
- NULL-byte scrub, empty-string / `"null"` / `"[]"` literal cleanup
- India bounding-box coordinate filter, dedup by `unique_id`
- 26 regex-derived attribute flags from free text (PM-JAY, NABH, 24x7, ambulance, telemedicine, charity care, government/private/NGO, 9 language flags)
- Pincode geo-resolution against India Post directory with first-digit zone validation (582 facilities flagged for review)
- NFHS-5 district health indicators joined for desert scoring

Run the ETL:
```bash
# Via Databricks Workflows (job already exists)
databricks bundle run referral_copilot_etl

# Or manually in a notebook
# Open pipelines/etl_pipeline.py in the workspace
```

---

## Search pipeline (per query)

| Step | Method | What it does |
|---|---|---|
| Query Parser | Llama 3.3 70B (skipped when location is structured) | Extracts capability + location from natural language |
| Facility Search | SQL keyword match + distance decay + trust_rank | Deterministic shortlist from `facilities_gold` |
| Evidence Scorer | Llama 3.3 70B (single batched call on top 10) | Per-facility confidence score, trust signal, evidence summary, missing evidence list |
| Re-rank | Python sort on LLM output | Final ordering by evidence strength |

Fallback: if the LLM is slow or unavailable, rule-based scores are kept. Search always completes.

---

## Persistence (save / revise)

| Endpoint | Table | User action |
|---|---|---|
| `POST /api/shortlist` | `shortlist` | Save a facility to your list |
| `PATCH /api/shortlist/{id}/notes` | `shortlist` | Add notes to a saved facility |
| `DELETE /api/shortlist/{id}` | `shortlist` | Remove from list |
| `POST /api/overrides` | `facility_overrides` | Suggest a data correction |
| `POST /api/reviews` | `facility_reviews` | Mark as verified / rejected / needs follow-up |
| `POST /api/search-history` | `search_history` | Auto-logged per search |
| `GET /api/shortlist/{user_id}` | `shortlist` | Retrieve your saved list |
| `GET /api/overrides/{facility_id}` | `facility_overrides` | View corrections for a facility |
| `GET /api/reviews/{facility_id}` | `facility_reviews` | View review decisions |

---

## Quick start

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html)
- A Databricks workspace with the Virtue Foundation Marketplace dataset installed

### Local development

```bash
# Install dependencies
uv sync

# Set environment variables
cp .env.example .env
# Edit .env with your DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_HTTP_PATH

# Start the backend
uv run uvicorn team_nike_hackathon.backend.app:app --port 8000

# Open http://localhost:8000
```

### Deploy to Databricks

```bash
# Build frontend + backend wheel
apx build

# Deploy app + ETL job
databricks bundle deploy

# Start the app
databricks bundle run team-nike-hackathon-app
```

---

## Repo structure

```
├── pipelines/
│   └── etl_pipeline.py          # Bronze → Silver → Gold ETL
├── src/team_nike_hackathon/
│   ├── backend/
│   │   ├── agents/              # LLM client, query parser, evidence scorer
│   │   ├── core/                # FastAPI factory, config, dependencies
│   │   ├── db/                  # Databricks SQL client, facility queries
│   │   ├── routes/              # Persistence endpoints (shortlist, overrides, reviews)
│   │   ├── scoring/             # Trust scorer, evidence formatter, citations
│   │   ├── router.py            # Main API router (search + inline endpoints)
│   │   └── app.py               # FastAPI app entry point
│   └── ui/                      # React frontend
├── docs/
│   ├── API.md                   # Full endpoint reference
│   └── HANDOFF.md               # Frontend integration guide
├── databricks.yml               # Bundle config (app + ETL job)
└── pyproject.toml               # Python dependencies
```

---

## Demo script (3 minutes)

1. **Search** — "dialysis near Jaipur" → 10 ranked facilities with trust badges on the map
2. **Evidence** — click "View evidence" on Soni Hospital → see cited specialties, "VERIFIED 92%", "What's Missing" section
3. **Second query** — "emergency surgery near Patna" → IGIMS Patna at #1 with ESI + 24x7 + ICU flags
4. **Uncertainty** — point out pincode confidence, trust signal variation, missing-evidence callouts
5. **Persistence** — show the `POST /api/shortlist` call saving a facility, `GET` retrieving it

---

## Team

- **Rahul Singh** — Backend, ETL pipeline, LLM integration, data quality, deployment
- **Bukaiheanacho** — Frontend UI, React components, evidence drawer, map view

---

Built with [apx](https://github.com/databricks-solutions/apx) on Databricks Free Edition.
