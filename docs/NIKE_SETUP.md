# Running on the Nike Databricks workspace

This branch (`nike/referral-copilot`) clones Buka's MatchCare backend +
UI from `main` and re-points it at the Nike workspace
(`https://nike-sole-react.cloud.databricks.com`) so we can use
Lakebase, Claude Sonnet 4-6, and the team's existing SQL warehouse.

## Why move off the free-tier workspace

| | Free-tier | Nike |
|---|---|---|
| Lakebase | hit JWT auth wall; instance not auto-provisioned for the app | `GPSI-Lakebase` already AVAILABLE |
| Claude / GPT-5 endpoints | rate-limit 0 on Claude Opus 4-8 | 69 LLM endpoints ready, including Claude Sonnet 4-6, Opus 4-6/4-7/4-8, GPT-5-4, Llama 4 Maverick |
| SQL warehouse | Serverless Starter (XXSMALL) | `NikeSoleSql-wdc_glops` PRO |
| Catalog perms | workspace.referral_copilot only | full access under `development.dev_gps_research_insights` |

## What you need to do once before the app boots

### 1. Install the Virtue Foundation dataset from Marketplace

The hackathon's bronze dataset
(`databricks_virtue_foundation_dataset_dais_2026`) is shared via
Databricks Open Sharing. It exists on the free-tier workspace but not
on Nike. Open the **Marketplace** in the Nike workspace and install
"Virtue Foundation – DAIS 2026 Dataset" → catalog stays as
`databricks_virtue_foundation_dataset_dais_2026`.

### 2. Pick a schema for our medallion tables

We default to `development.dev_gps_research_insights.*` (used by
test_ai). If you'd rather isolate, create a new schema:

```sql
CREATE SCHEMA IF NOT EXISTS development.referral_copilot;
```

and update `TEAM_NIKE_HACKATHON_DELTA_FACILITIES_TABLE` in `.env` to
`development.referral_copilot.facilities_gold`.

### 3. Set environment variables

```bash
cp .env.nike.example .env
# fill in DATABRICKS_TOKEN and TWILIO_* values
```

`.env.nike.example` already has the right host, warehouse id, Lakebase
instance name, and LLM endpoint baked in.

### 4. Confirm the Lakebase instance + role

The classic Lakebase API (which we now use when
`LAKEBASE_MODE=classic`) needs:

- `LAKEBASE_INSTANCE_NAME=GPSI-Lakebase` (already in `.env.nike.example`)
- The Postgres role for the SDK caller (you, on local dev) to exist on
  the instance.

Test from a shell:

```bash
set -a && source .env && set +a
uv run python - <<'PY'
import os, uuid
from databricks.sdk import WorkspaceClient
ws = WorkspaceClient()
cred = ws.database.generate_database_credential(
    request_id=str(uuid.uuid4()),
    instance_names=["GPSI-Lakebase"],
)
print("token:", cred.token[:30], "...")
inst = ws.database.get_database_instance(name="GPSI-Lakebase")
print("host:", inst.read_write_dns)
PY
```

If you get a token back and a hostname, Lakebase is good to go and
SQLModel tables (`facilities`, `facility_submissions`) will auto-create
the first time the app boots.

### 5. Run the ETL on Nike

Open `pipelines/etl_pipeline.py` in the Nike workspace as a notebook,
update the `TARGET` constant to your chosen catalog/schema, attach it
to the SQL warehouse (`046329acb5dabe1f`), and run all cells.

Expected output:

- silver: `facilities_clean`, `pincode_deduped`, `nfhs_clean`
- gold: `facilities_gold`, `capability_index`, `facility_trust_scores`,
  `desert_scores`, `district_coverage_index`,
  `district_capability_gaps`
- supporting: `facility_embeddings`, `facility_geo_audit`

Row counts should mirror what we had on the free-tier workspace:
~9,953 facility rows after data-quality filters.

### 6. (Optional) Re-create the vector search index

```bash
# Hostname + token used by curl below come from your .env
ENDPOINT_NAME="referral-copilot-vs"
INDEX_NAME="development.dev_gps_research_insights.facilities_vs_index"
# 1. create endpoint
# 2. create DELTA_SYNC index on facilities_vs_source
```

Detailed commands are in `pipelines/etl_pipeline.py` and the prior
commit log on the `feature/referral-copilot` branch.

## Starting the app

```bash
set -a && source .env && set +a
uv run uvicorn team_nike_hackathon.backend.app:app --port 8000
```

Lifespan order (from `core/_factory.py`):

1. `_ConfigDependency` — loads `AppConfig` from env
2. `_WorkspaceClientDependency` — `WorkspaceClient()` from your CLI
   profile (dev) or the deployed SP (prod)
3. `_LakebaseDependency` — vends a token, connects with SQLAlchemy,
   runs `SQLModel.metadata.create_all` to auto-create the tables

When you see `INFO: Application startup complete.` the app is ready.

## Smoke-test from outside the app

```bash
uv run python tests/smoke_endpoints.py
```

(Already validates all endpoints end-to-end against the real
Databricks workspace — green on the free-tier; should be green here
too once the dataset + tables exist.)

## Diffs vs the free-tier branch

* `core/_config.py` defaults LLM to `databricks-claude-sonnet-4-6`
* `core/_config.py` defaults Delta facilities table to the Nike schema
* `lakebase_query.py` now picks autoscaling vs classic API at runtime
  via `LAKEBASE_MODE` (default still autoscaling so Buka's original
  setup keeps working).
