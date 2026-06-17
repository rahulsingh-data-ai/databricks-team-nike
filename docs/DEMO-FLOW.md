# MatchCare — Architecture & Flow (Demo Reference)

## 1. Medallion Architecture (ETL)

```mermaid
flowchart LR
    subgraph Bronze["Bronze — Raw Marketplace Data"]
        B1["facilities\n10,088 rows × 51 cols"]
        B2["india_post_pincode_directory\n165,627 rows"]
        B3["nfhs_5_district_health_indicators\n706 district rows"]
    end

    subgraph Silver["Silver — Cleaned & Normalized"]
        S1["facilities_clean\n9,964 rows"]
        S2["pincode_deduped"]
        S3["nfhs_clean"]
    end

    subgraph Gold["Gold — Enriched & Scored"]
        G1["facilities_gold\n9,953 rows × 96 cols"]
        G2["facility_trust_scores"]
        G3["desert_scores\n706 districts"]
        G4["capability_index\n278K rows"]
    end

    B1 -->|"NULL scrub, dedup,\ncoord filter, JSON repair"| S1
    B2 -->|"dedup, India bbox filter"| S2
    B3 -->|"cast indicators to numeric"| S3

    S1 -->|"26 regex attribute flags\ntrust scoring"| G1
    S1 --> G2
    S2 -->|"pincode geo-resolve\nstate/district validation"| G1
    S3 -->|"disease burden\nvs facility coverage"| G3
    S1 --> G4
```

### How each source table is used

| Source Table | Feeds Into | Purpose |
|---|---|---|
| `facilities` | `facilities_clean` → `facilities_gold` | Core facility records — name, location, specialties, capabilities, equipment, description |
| `india_post_pincode_directory` | `pincode_deduped` → geo-resolve in `facilities_gold` | Validates pincodes against official India Post data. Cross-checks state vs pincode first-digit zone. Produces `pincode_confidence` and `needs_geo_review` flags. 582 facilities flagged for mismatch. |
| `nfhs_5_district_health_indicators` | `nfhs_clean` → `desert_scores` | District-level disease burden (anaemia %, institutional birth %, insurance coverage %). Joined with facility density to compute healthcare "desert" scores — high burden + low trusted-facility coverage = underserved district. |

### Data cleaning steps

```mermaid
flowchart LR
    R["Raw\n10,088"] --> C1["Remove\nNULL bytes"]
    C1 --> C2["Replace literal\n'null' / '[]'\nwith SQL NULL"]
    C2 --> C3["Filter coords\noutside India\nlat 6-38\nlon 68-98"]
    C3 --> C4["Dedup by\nunique_id"]
    C4 --> C5["Coerce\nmixed types\ncapacity\nDOUBLE→STRING"]
    C5 --> C6["Geo-resolve\npincodes vs\nIndia Post"]
    C6 --> CL["Clean\n9,953"]
```

---

## 2. Search Flow (per user query)

```mermaid
flowchart TD
    A["👤 User types\n'dialysis' + 'Jaipur'"]
    B["FastAPI\nPOST /api/search"]
    C["Step 1: SQL Keyword Search\nagainst facilities_gold\nDelta Lake"]
    D["Top 10 Results\nranked by text_score +\ndistance + trust_rank"]
    E["Step 2: Format as JSON\nspecialties, capability,\nequipment, description"]
    F["Step 3: LLM Evidence Scorer\nLlama 3.3 70B\nsingle batched call"]
    G["LLM Returns:\nconfidence_score 0-1\ntrust_signal\nevidence_summary\nmissing_evidence"]
    H["Step 4: Re-rank\nstrong > partial > weak >\nsuspicious > no-evidence"]
    I["📱 UI Renders\ntrust badges + cited evidence\n+ What's Missing"]

    A --> B
    B --> C
    C --> D
    D --> E
    E --> F
    F --> G
    G --> H
    H --> I
```

### What happens at each step

**Step 1 — SQL Keyword Search**
- Weighted LIKE match across 6 text columns: name (×3), description (×1), specialties (×2.5), capability (×1.5), procedure (×1.5), equipment (×1)
- Blended with haversine distance decay from Jaipur coordinates
- Boosted by pre-computed `trust_rank` from ETL
- Returns top 20, trimmed to top 10 for LLM

**Step 2 — Format as JSON**
- Each facility row becomes a compact card: name, type, location, specialties, capabilities, procedures, equipment, description, source, per-field signals
- The LLM never touches the database — it only sees what we feed it

**Step 3 — LLM Evidence Scorer**
- Single batched call to Llama 3.3 70B with all 10 facility cards
- System prompt forces 4-step reasoning: (1) What sources confirm this capability? (2) Are sources independent? (3) Does facility type match the claim? (4) What data is missing?
- Returns per-facility: `confidence_score`, `trust_signal`, `evidence_summary`, `missing_evidence`
- If LLM fails → rule-based scores stay intact. Search never breaks.

**Step 4 — Re-rank**
- Sort by tier first (strong always above partial, regardless of %)
- Within same tier, sort by confidence_score descending
- Tiebreaker: original keyword relevance

---

## 3. Tech Stack

```mermaid
flowchart LR
    subgraph Frontend
        UI["React\nTanStack Router\nTailwind CSS"]
    end

    subgraph Backend
        API["FastAPI\nEndpoints"]
        LLM["Llama 3.3 70B\nvia Databricks\nModel Serving"]
    end

    subgraph Data["Delta Lake"]
        GLD["facilities_gold\n9,953 × 96"]
        DS["desert_scores\n706 districts"]
        PT["Persistence\nshortlist\noverrides\nreviews\nsearch_history"]
    end

    UI -->|"POST /api/search"| API
    UI -->|"POST /api/shortlist\nPOST /api/overrides\nPOST /api/reviews"| API
    API -->|"SQL query"| GLD
    API -->|"evidence scoring"| LLM
    API -->|"save / revise"| PT
```

---

## 4. Persistence (Save / Revise)

```mermaid
flowchart LR
    U["👤 User"] -->|"Save facility"| SL["POST /api/shortlist\n→ shortlist table"]
    U -->|"Suggest correction"| OV["POST /api/overrides\n→ facility_overrides table"]
    U -->|"Mark as verified"| RV["POST /api/reviews\n→ facility_reviews table"]
    U -->|"Auto-logged"| SH["POST /api/search-history\n→ search_history table"]

    SL2["GET /api/shortlist/user_id"] -->|"Retrieve saved list"| U
    OV2["GET /api/overrides/facility_id"] -->|"View corrections"| U
    RV2["GET /api/reviews/facility_id"] -->|"View decisions"| U
```
