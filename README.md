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

## Anticipated judge questions

### Search & Ranking

**Q: How does the LLM Query Parser work?**
> When a user types a free-form query like "emergency surgery near Patna", the parser (Llama 3.3 70B) extracts structured fields: `capability: "surgery"`, `location: "Patna"`, `urgency: "emergency"`, `specialty_terms: ["surgery", "general surgery"]`. This avoids literal-phrase matching ("emergency surgery" = 5 hits) and instead searches for the right medical term ("surgery" = 2,008 hits). The parser is skipped when the UI sends a structured two-box request (care need + location separately) — no LLM latency in that path.

**Q: Why keyword SQL instead of vector search?**
> Two reasons: (1) Free Edition warehouse cold-starts are 15–20s; adding a vector search endpoint doubles that. (2) Our keyword search already blends 6 weighted LIKE matches (name ×3, description ×1, specialties ×2.5, capability ×1.5, procedure ×1.5, equipment ×1) plus distance decay plus pre-computed `trust_rank`. For a dataset of ~10K records this covers >95% of queries well. Vector search index exists in code and can be enabled with one env var when a faster warehouse is available.

**Q: What does the LLM evidence scorer actually do?**
> After keyword search returns the top results, we send facility cards (name, specialties, capabilities, description, equipment) to Llama 3.3 70B in a single batched call. The LLM returns per-facility: `confidence_score` (0–1), `trust_signal` (strong/partial/weak/suspicious/no-evidence), `evidence_summary` (one-line explanation), and `missing_evidence` (list of data gaps). These override the rule-based scores so the UI shows "VERIFIED 92%" instead of a generic badge. If the LLM fails, rule-based scores remain — search never breaks.

**Q: How is the final ranking determined?**
> Three-layer sort: (1) LLM trust signal tier (strong > partial > weak > suspicious > no-evidence), (2) LLM confidence score descending, (3) original keyword relevance as tiebreaker. This means a "62% strong_evidence" facility always ranks above a "95% weak_evidence" one.

### Data Quality & Trust

**Q: How do you handle the messy data?**
> Three-pass medallion pipeline. Bronze is raw. Silver scrubs NULL bytes, replaces literal `"null"` / `"[]"` strings with SQL NULL, deduplicates by `unique_id`, filters coordinates outside India's bounding box (lat 6–38, lon 68–98), and coerces mixed-type columns. Gold extracts 26 boolean attribute flags via regex over concatenated free-text fields, computes trust rank from source breadth + capability evidence, and geo-resolves pincodes against the India Post directory.

**Q: What are the 26 attribute flags?**
> Mined from `description + capability + procedure + equipment` via regex: `mentions_pmjay`, `mentions_nabh`, `mentions_cghs`, `mentions_esi`, `mentions_jci`, `mentions_iso`, `is_24x7`, `has_ambulance`, `has_telemedicine`, `has_blood_bank`, `mentions_icu`, `mentions_nicu`, `mentions_emergency`, `is_government_mentioned`, `is_private_mentioned`, `is_nonprofit_mentioned`, `offers_charity_care`, `lang_hindi`, `lang_tamil`, `lang_telugu`, `lang_bengali`, `lang_marathi`, `lang_gujarati`, `lang_kannada`, `lang_malayalam`, `is_ngo_source`. Zero LLM cost — pure SQL, runs in seconds.

**Q: How do you communicate uncertainty?**
> Five mechanisms: (1) Five-level `trust_signal` badge on every result card, (2) numeric `confidence_score` from LLM (the "VERIFIED 92%" chip), (3) `pincode_confidence` score (0.0–1.0) flagging geographic mismatches, (4) `needs_geo_review` boolean for facilities where pincode doesn't match claimed state, (5) "What's Missing" section listing specific data gaps per facility (e.g., "no explicit 'general surgery' specialty tag", "single source").

**Q: Why are some facilities marked "suspicious"?**
> A facility typed as `clinic` or `dentist` that claims 20+ specialties triggers the `suspicious` signal. This catches data quality issues where a small clinic inherited specialties from a larger parent organization during the FDR pipeline's entity resolution.

### Persistence & User Workflow

**Q: How does save/revise work without Lakebase?**
> Four Delta tables on the same SQL warehouse: `shortlist`, `facility_overrides`, `facility_reviews`, `search_history`. All CRUD goes through the Databricks SQL Statement Execution API — same auth, same warehouse, no extra infrastructure. Lakebase init is optional and gracefully skipped when not configured.

**Q: What happens when a user submits a correction?**
> `POST /api/overrides` inserts a row with `status: "pending"`. The correction is visible to all users viewing that facility (`GET /api/overrides/{facility_id}`). A future moderation workflow can promote corrections into `facilities_gold` — we didn't build the admin UI but the data model supports it.

### Architecture & Tradeoffs

**Q: Why not use a full agentic pipeline for every query?**
> We built one (5-node LangGraph with chain-of-thought reasoning on `feature/referral-copilot`). It added 8–12 seconds per query on Free Edition. For a 3-minute demo with a cold warehouse, that's unusable. We kept the LLM for evidence scoring (single batched call, ~2–3s) and made everything else deterministic. The agentic pipeline can be reactivated with one code path switch when a faster warehouse is available.

**Q: Why Delta tables instead of Lakebase for persistence?**
> Lakebase requires a database instance resource in the bundle — adds provisioning time and a Postgres dependency. Delta tables use the same warehouse the search already runs on. For a hackathon where simplicity wins, one fewer moving part matters.

**Q: How portable is this across workspaces?**
> ETL parameters (`bronze_schema`, `target_schema`) are notebook widgets with defaults. The backend reads `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DELTA_WAREHOUSE_ID`, `DELTA_FACILITIES_TABLE` from environment variables. Lakebase is optional. We've run the same codebase on both Free Edition and an internal Nike workspace by changing only `.env`.

---

## Team

- **Rahul Singh** — Backend, ETL pipeline, LLM integration, data quality, deployment
- **Bukaiheanacho** — Frontend UI, React components, evidence drawer, map view

---

Built with [apx](https://github.com/databricks-solutions/apx) on Databricks Free Edition.
