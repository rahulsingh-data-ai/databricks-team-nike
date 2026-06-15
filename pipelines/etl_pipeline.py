# Databricks notebook source
# MAGIC %md
# MAGIC # Referral Copilot — Bronze → Silver → Gold ETL
# MAGIC
# MAGIC Medallion architecture for healthcare facility data.
# MAGIC
# MAGIC - **Bronze**: Raw FDR data (shared via Marketplace)
# MAGIC - **Silver**: Cleaned, typed, normalized
# MAGIC - **Gold**: Pre-computed trust scores, capability index, desert scores
# MAGIC
# MAGIC In production, this runs on a daily schedule to pick up new facility data from the FDR crawl.

# COMMAND ----------

BRONZE = "databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset"
TARGET = "workspace.referral_copilot"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Silver Layer

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.facilities_clean AS
SELECT
  unique_id, name, organization_type, facilityTypeId, operatorTypeId,
  affiliationTypeIds, content_table_id,
  address_line1, address_line2, address_line3,
  address_city, address_stateOrRegion, address_zipOrPostcode,
  address_country, address_countryCode, countries, area,
  latitude, longitude, coordinates, cluster_id,
  -- Clean nullable fields (empty strings -> NULL)
  NULLIF(NULLIF(NULLIF(phone_numbers, ''), 'null'), 'N/A') as phone_numbers,
  NULLIF(NULLIF(NULLIF(officialPhone, ''), 'null'), 'N/A') as officialPhone,
  NULLIF(NULLIF(email, ''), 'null') as email,
  NULLIF(NULLIF(websites, ''), 'null') as websites,
  NULLIF(NULLIF(officialWebsite, ''), 'null') as officialWebsite,
  NULLIF(NULLIF(facebookLink, ''), 'null') as facebookLink,
  NULLIF(NULLIF(NULLIF(NULLIF(yearEstablished, ''), 'null'), 'Unknown'), 'unknown') as yearEstablished,
  NULLIF(NULLIF(acceptsVolunteers, ''), 'null') as acceptsVolunteers,
  description, specialties,
  -- Array fields: replace literal "null" / "[]" strings with SQL NULL so
  -- FROM_JSON downstream returns NULL only for genuinely missing data.
  CASE WHEN LOWER(TRIM(capability))   IN ('null','[]') THEN NULL ELSE capability   END AS capability,
  CASE WHEN LOWER(TRIM(procedure))    IN ('null','[]') THEN NULL ELSE procedure    END AS procedure,
  CASE WHEN LOWER(TRIM(equipment))    IN ('null','[]') THEN NULL ELSE equipment    END AS equipment,
  CASE WHEN LOWER(TRIM(source_types)) IN ('null','[]') THEN NULL ELSE source_types END AS source_types,
  source_ids, source_urls, source_content_id, source,
  NULLIF(NULLIF(NULLIF(NULLIF(numberDoctors, ''), 'null'), '0'), 'unknown') as numberDoctors,
  NULLIF(NULLIF(NULLIF(NULLIF(capacity, ''), 'null'), '0'), 'unknown') as capacity,
  recency_of_page_update, distinct_social_media_presence_count,
  affiliated_staff_presence, custom_logo_presence,
  number_of_facts_about_the_organization,
  post_metrics_most_recent_social_media_post_date,
  post_metrics_post_count, engagement_metrics_n_followers,
  engagement_metrics_n_likes, engagement_metrics_n_engagements,
  -- Computed counts
  CASE WHEN source_types IS NOT NULL AND LENGTH(source_types) > 5
    THEN SIZE(FROM_JSON(source_types, 'ARRAY<STRING>')) ELSE 0 END as source_count,
  CASE WHEN source_types IS NOT NULL AND LENGTH(source_types) > 5
    THEN SIZE(ARRAY_DISTINCT(FROM_JSON(source_types, 'ARRAY<STRING>'))) ELSE 0 END as distinct_source_count,
  CASE WHEN specialties IS NOT NULL AND LENGTH(specialties) > 5
    THEN SIZE(FROM_JSON(specialties, 'ARRAY<STRING>')) ELSE 0 END as specialty_count,
  CASE WHEN capability IS NOT NULL AND LENGTH(capability) > 5
    THEN SIZE(FROM_JSON(capability, 'ARRAY<STRING>')) ELSE 0 END as capability_count,
  CASE WHEN procedure IS NOT NULL AND LENGTH(procedure) > 5
    THEN SIZE(FROM_JSON(procedure, 'ARRAY<STRING>')) ELSE 0 END as procedure_count,
  CASE WHEN equipment IS NOT NULL AND LENGTH(equipment) > 5
    THEN SIZE(FROM_JSON(equipment, 'ARRAY<STRING>')) ELSE 0 END as equipment_count,
  -- Boolean flags
  (latitude IS NOT NULL AND longitude IS NOT NULL) as has_coordinates,
  (description IS NOT NULL AND LENGTH(description) > 5) as has_description,
  (NULLIF(NULLIF(NULLIF(NULLIF(numberDoctors, ''), 'null'), '0'), 'unknown') IS NOT NULL) as has_doctors,
  (NULLIF(NULLIF(NULLIF(NULLIF(capacity, ''), 'null'), '0'), 'unknown') IS NOT NULL) as has_capacity,
  (NULLIF(NULLIF(NULLIF(NULLIF(yearEstablished, ''), 'null'), 'Unknown'), 'unknown') IS NOT NULL) as has_year_established
FROM {BRONZE}.facilities
WHERE
  -- Data quality filters:
  -- 1) Drop ~54 misaligned rows where unique_id holds markdown fragments
  --    and the real fields shifted into the wrong columns (no name/coords)
  -- 2) Drop ~6 rows with coordinates outside India's bounding box
  --    (lat/lon clearly swapped or randomly garbled by upstream extractor)
  name IS NOT NULL
  AND TRIM(name) <> ''
  AND latitude IS NOT NULL
  AND longitude IS NOT NULL
  AND latitude BETWEEN 6 AND 38
  AND longitude BETWEEN 68 AND 98
""")

print(f"facilities_clean: {spark.table(f'{TARGET}.facilities_clean').count()} rows")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.pincode_deduped AS
WITH agg AS (
  SELECT
    pincode, district, statename,
    AVG(TRY_CAST(latitude AS DOUBLE)) as latitude,
    AVG(TRY_CAST(longitude AS DOUBLE)) as longitude,
    COUNT(*) as office_count,
    FIRST(regionname) as regionname,
    FIRST(divisionname) as divisionname
  FROM {BRONZE}.india_post_pincode_directory
  GROUP BY pincode, district, statename
)
SELECT
  pincode, district, statename,
  -- Drop coordinates that fell outside India's bounding box. The source
  -- CSV has ~400 pincodes with garbled lat/lon values that skew the AVG.
  CASE WHEN latitude BETWEEN 6 AND 38 AND longitude BETWEEN 68 AND 98
       THEN latitude  ELSE NULL END as latitude,
  CASE WHEN latitude BETWEEN 6 AND 38 AND longitude BETWEEN 68 AND 98
       THEN longitude ELSE NULL END as longitude,
  office_count, regionname, divisionname
FROM agg
""")

print(f"pincode_deduped: {spark.table(f'{TARGET}.pincode_deduped').count()} rows")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.nfhs_clean AS
SELECT
  LOWER(TRIM(district_name)) as district_name,
  LOWER(TRIM(state_ut)) as state_ut,
  households_surveyed,
  institutional_birth_5y_pct,
  institutional_birth_in_public_facility_5y_pct,
  hh_member_covered_health_insurance_pct,
  hh_electricity_pct,
  hh_improved_water_pct,
  hh_use_improved_sanitation_pct,
  households_using_clean_fuel_for_cooking_pct,
  all_w15_49_who_are_anaemic_pct,
  non_pregnant_w15_49_who_are_anaemic_lt_12_0_g_dl_22_pct,
  prev_diarrhoea_2wk_child_u5_pct,
  children_prev_symptoms_of_acute_respiratory_infection_ari_2_pct,
  women_age_30_49_years_ever_undergone_a_cervical_screen_pct,
  women_age_30_49_years_ever_undergone_a_breast_exam_pct,
  w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct,
  m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct,
  w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct,
  m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct
FROM {BRONZE}.nfhs_5_district_health_indicators
""")

print(f"nfhs_clean: {spark.table(f'{TARGET}.nfhs_clean').count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gold Layer

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.capability_index AS
SELECT
  f.unique_id, f.name, f.facilityTypeId,
  f.address_city, f.address_stateOrRegion, f.address_zipOrPostcode,
  f.latitude, f.longitude, f.source_count, f.has_coordinates,
  LOWER(TRIM(spec.specialty)) as specialty
FROM {TARGET}.facilities_clean f
LATERAL VIEW EXPLODE(FROM_JSON(f.specialties, 'ARRAY<STRING>')) spec AS specialty
WHERE f.specialties IS NOT NULL
""")

print(f"capability_index: {spark.table(f'{TARGET}.capability_index').count()} rows")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.facility_trust_scores AS
SELECT
  unique_id, name, facilityTypeId,
  address_city, address_stateOrRegion,
  latitude, longitude,
  source_count, distinct_source_count,
  specialty_count, capability_count, has_coordinates,
  CASE
    WHEN facilityTypeId IN ('clinic','dentist') AND specialty_count > 20 THEN 'suspicious'
    WHEN distinct_source_count >= 3 AND specialty_count > 0 THEN 'strong_evidence'
    WHEN distinct_source_count = 2 AND specialty_count > 0 THEN 'partial_evidence'
    WHEN distinct_source_count >= 1 AND specialty_count > 0 THEN 'partial_evidence'
    WHEN distinct_source_count >= 1 AND capability_count > 0 THEN 'weak_evidence'
    WHEN capability_count > 0 THEN 'weak_evidence'
    ELSE 'no_evidence'
  END as base_trust_signal,
  CASE
    WHEN facilityTypeId IN ('clinic','dentist') AND specialty_count > 20 THEN 2
    WHEN distinct_source_count >= 3 AND specialty_count > 0 THEN 5
    WHEN distinct_source_count = 2 AND specialty_count > 0 THEN 4
    WHEN distinct_source_count >= 1 AND specialty_count > 0 THEN 3
    WHEN distinct_source_count >= 1 AND capability_count > 0 THEN 3
    WHEN capability_count > 0 THEN 2
    ELSE 1
  END as trust_rank,
  (CASE WHEN capacity IS NULL THEN 1 ELSE 0 END
   + CASE WHEN numberDoctors IS NULL THEN 1 ELSE 0 END
   + CASE WHEN yearEstablished IS NULL THEN 1 ELSE 0 END
   + CASE WHEN recency_of_page_update IS NULL THEN 1 ELSE 0 END
   + CASE WHEN distinct_source_count <= 1 THEN 1 ELSE 0 END
   + CASE WHEN phone_numbers IS NULL AND officialPhone IS NULL THEN 1 ELSE 0 END
  ) as missing_data_count
FROM {TARGET}.facilities_clean
""")

print(f"facility_trust_scores: {spark.table(f'{TARGET}.facility_trust_scores').count()} rows")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.desert_scores AS
WITH dist_facilities AS (
  SELECT
    LOWER(TRIM(address_city))           as district_key,
    LOWER(TRIM(address_stateOrRegion))  as state_key,
    COUNT(*)                            as total_facilities,
    SUM(CASE WHEN base_trust_signal IN ('strong_evidence','partial_evidence')
             THEN 1 ELSE 0 END)         as trusted_facilities,
    AVG(trust_rank)                     as avg_trust_rank
  FROM {TARGET}.facility_trust_scores
  GROUP BY LOWER(TRIM(address_city)), LOWER(TRIM(address_stateOrRegion))
),
district_match AS (
  SELECT
    n.district_name, n.state_ut,
    n.households_surveyed,
    n.institutional_birth_5y_pct,
    n.hh_member_covered_health_insurance_pct,
    n.all_w15_49_who_are_anaemic_pct,
    -- Prefer a city-name match, fall back to state-name match.
    -- Aggregate so each NFHS district appears exactly once.
    MAX(COALESCE(f1.total_facilities,   f2.total_facilities,   0)) as total_facilities,
    MAX(COALESCE(f1.trusted_facilities, f2.trusted_facilities, 0)) as trusted_facilities,
    MAX(COALESCE(f1.avg_trust_rank,     f2.avg_trust_rank,     0)) as avg_trust_rank
  FROM {TARGET}.nfhs_clean n
  LEFT JOIN dist_facilities f1 ON n.district_name = f1.district_key
  LEFT JOIN dist_facilities f2 ON n.state_ut      = f2.state_key
                              AND f1.district_key IS NULL
  GROUP BY n.district_name, n.state_ut, n.households_surveyed,
           n.institutional_birth_5y_pct,
           n.hh_member_covered_health_insurance_pct,
           n.all_w15_49_who_are_anaemic_pct
)
SELECT
  district_name, state_ut,
  total_facilities, trusted_facilities, avg_trust_rank,
  institutional_birth_5y_pct,
  hh_member_covered_health_insurance_pct,
  all_w15_49_who_are_anaemic_pct,
  households_surveyed,
  ROUND(
    ((100 - COALESCE(institutional_birth_5y_pct, 50))
     + (100 - COALESCE(hh_member_covered_health_insurance_pct, 20)))
    / (trusted_facilities + 1), 2
  ) as desert_score
FROM district_match
ORDER BY desert_score DESC
""")

print(f"desert_scores: {spark.table(f'{TARGET}.desert_scores').count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Final Gold Table + Vector Search Source

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.facilities_gold AS
WITH deduped AS (
  SELECT f.*, t.base_trust_signal, t.trust_rank, t.missing_data_count, e.search_text,
    ROW_NUMBER() OVER (PARTITION BY f.unique_id ORDER BY f.distinct_source_count DESC) as rn
  FROM {TARGET}.facilities_clean f
  LEFT JOIN (SELECT DISTINCT unique_id, base_trust_signal, trust_rank, missing_data_count
             FROM {TARGET}.facility_trust_scores) t ON f.unique_id = t.unique_id
  LEFT JOIN {TARGET}.facility_embeddings e ON f.unique_id = e.unique_id
),
base AS (SELECT * EXCEPT(rn) FROM deduped WHERE rn = 1),
enriched AS (
  SELECT b.*,
    CONCAT_WS(' ',
      COALESCE(b.description, ''), COALESCE(b.capability, ''),
      COALESCE(b.procedure, ''),   COALESCE(b.equipment, '')
    ) AS evidence_blob,
    LOWER(COALESCE(b.source_types, '')) AS source_types_lc
  FROM base b
)
SELECT *,
  -- Affordability / insurance signals
  (LOWER(evidence_blob) RLIKE '\\\\b(pm-?jay|ayushman|pradhan mantri jan arogya)\\\\b') AS mentions_pmjay,
  (LOWER(evidence_blob) RLIKE '\\\\b(cghs)\\\\b') AS mentions_cghs,
  (LOWER(evidence_blob) RLIKE '\\\\b(esi|esic)\\\\b') AS mentions_esi,
  -- Accreditation signals
  (LOWER(evidence_blob) RLIKE '\\\\bnabh\\\\b') AS mentions_nabh,
  (LOWER(evidence_blob) RLIKE '\\\\bjci\\\\b') AS mentions_jci,
  (LOWER(evidence_blob) RLIKE '\\\\biso ?900[0-9]') AS mentions_iso,
  -- Service signals
  (LOWER(evidence_blob) RLIKE '24 ?(x|/) ?7|24 hour|round the clock') AS is_24x7,
  (LOWER(evidence_blob) RLIKE '\\\\b(ambulance)\\\\b') AS has_ambulance,
  (LOWER(evidence_blob) RLIKE 'tele[- ]?medicine|tele[- ]?consult|teleconsultation|tele[- ]?health|video consult|online consult') AS has_telemedicine,
  (LOWER(evidence_blob) RLIKE 'blood bank') AS has_blood_bank,
  (LOWER(evidence_blob) RLIKE '\\\\b(icu|intensive care unit)\\\\b') AS mentions_icu,
  (LOWER(evidence_blob) RLIKE '\\\\b(nicu|neonatal intensive)\\\\b') AS mentions_nicu,
  (LOWER(evidence_blob) RLIKE 'emergency') AS mentions_emergency,
  -- Ownership signals
  (LOWER(evidence_blob) RLIKE 'government hospital|govt hospital|district hospital|sarkari|aiims|public health centre|primary health centre|\\\\bphc\\\\b|community health centre|\\\\bchc\\\\b') AS is_government_mentioned,
  (LOWER(evidence_blob) RLIKE 'private (hospital|clinic|nursing home)|corporate hospital') AS is_private_mentioned,
  (LOWER(evidence_blob) RLIKE 'trust hospital|charitable trust|charity|non[- ]?profit|nonprofit|foundation|missionary|society') OR source_types_lc LIKE '%mongo_ngo%' AS is_nonprofit_mentioned,
  (LOWER(evidence_blob) RLIKE 'free treatment|no cost|no fee|sliding scale|subsidi[sz]ed|concessional|\\\\bbpl\\\\b|below poverty line') AS offers_charity_care,
  -- Language signals
  (LOWER(evidence_blob) RLIKE '\\\\b(hindi)\\\\b') AS lang_hindi,
  (LOWER(evidence_blob) RLIKE '\\\\b(tamil)\\\\b') AS lang_tamil,
  (LOWER(evidence_blob) RLIKE '\\\\b(telugu)\\\\b') AS lang_telugu,
  (LOWER(evidence_blob) RLIKE '\\\\b(bengali|bangla)\\\\b') AS lang_bengali,
  (LOWER(evidence_blob) RLIKE '\\\\b(marathi)\\\\b') AS lang_marathi,
  (LOWER(evidence_blob) RLIKE '\\\\b(gujarati)\\\\b') AS lang_gujarati,
  (LOWER(evidence_blob) RLIKE '\\\\b(kannada)\\\\b') AS lang_kannada,
  (LOWER(evidence_blob) RLIKE '\\\\b(malayalam)\\\\b') AS lang_malayalam,
  source_types_lc LIKE '%mongo_ngo%' AS is_ngo_source
FROM enriched
""")
print(f"facilities_gold (pre geo-resolve): {spark.table(f'{TARGET}.facilities_gold').count()} rows")

# Drop internal helper columns; they're only needed during the build above.
spark.sql(f"ALTER TABLE {TARGET}.facilities_gold DROP COLUMNS IF EXISTS (evidence_blob, source_types_lc)")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Geo resolution
# MAGIC Normalize the pincode (strip spaces) and use the India Post directory
# MAGIC to derive an authoritative state + district. This catches facilities
# MAGIC where address_stateOrRegion is actually a city ("Navi Mumbai") or a
# MAGIC stale label ("Orissa").

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.facilities_gold AS
WITH pin_lookup AS (
  SELECT pincode, MIN(district) district, MIN(statename) statename
  FROM {TARGET}.pincode_deduped
  WHERE LOWER(TRIM(statename)) <> 'na'
  GROUP BY pincode
),
state_alias AS (
  SELECT * FROM (VALUES
    ('tamilnadu','tamil nadu'),('orissa','odisha'),
    ('pondicherry','puducherry'),('punjab region','punjab'),
    ('uttaranchal','uttarakhand'),('uttarpradesh','uttar pradesh'),
    ('andhrapradesh','andhra pradesh'),('madhyapradesh','madhya pradesh'),
    ('j&k','jammu and kashmir'),('chattisgarh','chhattisgarh'),
    ('newdelhi','delhi'),('new delhi','delhi'),
    ('navi mumbai','maharashtra'),('thane','maharashtra'),
    ('pune','maharashtra'),('mumbai','maharashtra'),('nagpur','maharashtra'),
    ('chennai','tamil nadu'),('coimbatore','tamil nadu'),('madurai','tamil nadu'),
    ('bengaluru','karnataka'),('bangalore','karnataka'),('mysore','karnataka'),
    ('hyderabad','telangana'),('kolkata','west bengal'),
    ('thiruvananthapuram','kerala'),('kochi','kerala'),('ernakulam','kerala'),
    ('kozhikode','kerala'),('malappuram','kerala'),('kollam','kerala')
  ) AS t(alias, canonical)
)
pincode_zones AS (
  -- First-digit -> India Post regional zone -> allowed states.
  -- Used to flag impossible combos like a Maharashtra pincode (4xxxxx)
  -- labelled as Tamil Nadu.
  SELECT * FROM (VALUES
    (1, ARRAY('delhi','haryana','punjab','himachal pradesh','jammu and kashmir','ladakh','chandigarh')),
    (2, ARRAY('uttar pradesh','uttarakhand')),
    (3, ARRAY('rajasthan','gujarat','dadra and nagar haveli','daman and diu')),
    (4, ARRAY('maharashtra','madhya pradesh','chhattisgarh','goa')),
    (5, ARRAY('andhra pradesh','karnataka','telangana')),
    (6, ARRAY('tamil nadu','kerala','puducherry','lakshadweep')),
    (7, ARRAY('west bengal','odisha','assam','arunachal pradesh','manipur',
              'meghalaya','mizoram','nagaland','sikkim','tripura',
              'andaman and nicobar islands')),
    (8, ARRAY('bihar','jharkhand'))
  ) AS t(zone, states)
)
scored AS (
  SELECT
    g.unique_id,
    TRIM(REPLACE(g.address_zipOrPostcode, ' ', '')) AS pin_clean,
    g.address_zipOrPostcode  AS raw_pincode,
    g.address_city           AS claimed_city,
    g.address_stateOrRegion  AS claimed_state,
    p.statename              AS pin_state,
    p.district               AS pin_district,
    sa.canonical             AS alias_state,
    z.zone                   AS pin_zone,
    z.states                 AS allowed_states
  FROM {TARGET}.facilities_gold g
  LEFT JOIN pin_lookup p
    ON TRY_CAST(TRIM(REPLACE(g.address_zipOrPostcode, ' ', '')) AS BIGINT) = p.pincode
  LEFT JOIN state_alias sa
    ON LOWER(TRIM(g.address_stateOrRegion)) = sa.alias
  LEFT JOIN pincode_zones z
    ON z.zone = TRY_CAST(SUBSTRING(TRIM(REPLACE(g.address_zipOrPostcode, ' ', '')), 1, 1) AS INT)
)
SELECT
  g.*,
  -- Single clean geo columns
  CASE WHEN s.pin_clean RLIKE '^[0-9]{{6}}$' THEN s.pin_clean END AS pincode,
  LOWER(TRIM(COALESCE(s.pin_state, s.alias_state, g.address_stateOrRegion))) AS state,
  LOWER(TRIM(COALESCE(s.pin_district, g.address_city))) AS district,
  CASE
    WHEN g.address_zipOrPostcode IS NULL OR TRIM(g.address_zipOrPostcode) = '' THEN 0.0
    WHEN NOT (s.pin_clean RLIKE '^[0-9]{{6}}$') THEN 0.1
    WHEN s.pin_state IS NULL THEN 0.3
    WHEN LOWER(TRIM(s.pin_state)) <> COALESCE(s.alias_state, LOWER(TRIM(g.address_stateOrRegion))) THEN 0.5
    WHEN s.pin_zone IS NOT NULL AND NOT ARRAY_CONTAINS(s.allowed_states,
       LOWER(TRIM(COALESCE(s.pin_state, s.alias_state, g.address_stateOrRegion)))
    ) THEN 0.6
    ELSE 1.0
  END AS pincode_confidence,
  -- needs_geo_review = pincode_confidence < 0.8 (computed below in a second pass)
  (
    CASE
      WHEN g.address_zipOrPostcode IS NULL OR TRIM(g.address_zipOrPostcode) = '' THEN 0.0
      WHEN NOT (s.pin_clean RLIKE '^[0-9]{{6}}$') THEN 0.1
      WHEN s.pin_state IS NULL THEN 0.3
      WHEN LOWER(TRIM(s.pin_state)) <> COALESCE(s.alias_state, LOWER(TRIM(g.address_stateOrRegion))) THEN 0.5
      WHEN s.pin_zone IS NOT NULL AND NOT ARRAY_CONTAINS(s.allowed_states,
         LOWER(TRIM(COALESCE(s.pin_state, s.alias_state, g.address_stateOrRegion)))
      ) THEN 0.6
      ELSE 1.0
    END
  ) < 0.8 AS needs_geo_review
FROM {TARGET}.facilities_gold g
JOIN scored s ON g.unique_id = s.unique_id
""")
# Drop the now-redundant address_zipOrPostcode (replaced by `pincode`)
spark.sql(f"ALTER TABLE {TARGET}.facilities_gold DROP COLUMN IF EXISTS address_zipOrPostcode")
print(f"facilities_gold (with clean geo): {spark.table(f'{TARGET}.facilities_gold').count()} rows")

# COMMAND ----------

# Build the geo audit table from the in-progress gold rows. We rerun the
# pincode validation logic here so the audit table is self-contained
# (doesn't depend on intermediate columns the clean gold doesn't carry).
spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.facility_geo_audit AS
WITH pin_lookup AS (
  SELECT pincode, MIN(district) district, MIN(statename) statename
  FROM {TARGET}.pincode_deduped
  WHERE LOWER(TRIM(statename)) <> 'na'
  GROUP BY pincode
),
src AS (
  SELECT
    unique_id, name,
    address_zipOrPostcode AS raw_pincode_original,
    TRIM(REPLACE(address_zipOrPostcode, ' ', '')) AS pin_clean,
    address_city AS claimed_city,
    address_stateOrRegion AS claimed_state
  FROM {TARGET}.facilities_clean
)
SELECT
  s.unique_id,
  s.name,
  s.raw_pincode_original,
  s.pin_clean,
  (s.pin_clean RLIKE '^[0-9]{{6}}$') AS pincode_valid_format,
  p.statename  AS pin_state_directory,
  p.district   AS pin_district_directory,
  s.claimed_city,
  s.claimed_state,
  g.pincode    AS resolved_pincode,
  g.state      AS resolved_state,
  g.district   AS resolved_district,
  g.pincode_confidence,
  g.needs_geo_review
FROM src s
LEFT JOIN pin_lookup p
  ON TRY_CAST(s.pin_clean AS BIGINT) = p.pincode
LEFT JOIN {TARGET}.facilities_gold g
  ON s.unique_id = g.unique_id
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.facilities_vs_source AS
SELECT unique_id, name, facilityTypeId, address_city, address_stateOrRegion,
  pincode, state, district, pincode_confidence, needs_geo_review,
  latitude, longitude, specialties, capability, description,
  source_types, source_urls, capacity, numberDoctors, yearEstablished,
  base_trust_signal, trust_rank, missing_data_count, distinct_source_count,
  has_doctors, has_capacity, has_year_established, has_coordinates,
  mentions_pmjay, mentions_nabh, is_24x7, has_ambulance, has_telemedicine,
  is_government_mentioned, is_nonprofit_mentioned, offers_charity_care, mentions_icu,
  search_text
FROM {TARGET}.facilities_gold
""")
print(f"facilities_vs_source: {spark.table(f'{TARGET}.facilities_vs_source').count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

for table in ["facilities_clean", "pincode_deduped", "nfhs_clean", "capability_index", "facility_trust_scores", "desert_scores", "facilities_gold", "facilities_vs_source"]:
    count = spark.table(f"{TARGET}.{table}").count()
    print(f"{table:30s} {count:>10,} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Refresh Vector Search Index

# COMMAND ----------

import requests, os

host = os.environ.get("DATABRICKS_HOST", spark.conf.get("spark.databricks.workspaceUrl", ""))
if not host.startswith("https://"):
    host = f"https://{host}"

token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().getOrElse(None)
VS_INDEX = "workspace.referral_copilot.facilities_vs_index"

try:
    resp = requests.post(
        f"{host}/api/2.0/vector-search/indexes/{VS_INDEX}/sync",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30,
    )
    print(f"Vector index sync triggered: {resp.status_code} {resp.text[:200]}")
except Exception as e:
    print(f"Vector index sync skipped: {e}")

# COMMAND ----------

print("\nETL complete. All tables refreshed. Vector index sync triggered.")
