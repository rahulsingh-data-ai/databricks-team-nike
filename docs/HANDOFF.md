# Handoff to Buka

ETL fixes are in (commit `d9edda5`). Backend search + persistence endpoints all work. Two items left for the hackathon checklist:

## 1. Deploy the app to free-tier

```bash
databricks bundle deploy            # from the repo root, your free-tier profile
databricks bundle run team-nike-hackathon-app
```

## 2. Wire 3 buttons in the UI

Backend is done; just need the click paths. Full request/response shapes in `docs/API.md`.

| Button | Endpoint | When to fire |
|---|---|---|
| **Save shortlist** | `POST /api/shortlist` (one call per saved facility) | After a search, on a facility card |
| **Pick as final choice** | `PATCH /api/shortlist/{id}/notes` *or* `POST /api/reviews` (status=`verified`) | From the shortlist drawer |
| **Suggest correction** | `POST /api/overrides` (field/trust_signal correction) | In the evidence drawer, edit-pencil icon |

User identity for `user_id` field: lift from `headers.user_email` (X-Forwarded-Email) on the request — Databricks Apps injects it automatically.
