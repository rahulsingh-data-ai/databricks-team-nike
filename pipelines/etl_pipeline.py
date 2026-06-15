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
SELECT *,
  CASE WHEN source_types IS NOT NULL
    THEN SIZE(FROM_JSON(source_types, 'ARRAY<STRING>')) ELSE 0
  END as source_count,
  CASE WHEN source_types IS NOT NULL
    THEN SIZE(ARRAY_DISTINCT(FROM_JSON(source_types, 'ARRAY<STRING>'))) ELSE 0
  END as distinct_source_count,
  CASE WHEN specialties IS NOT NULL
    THEN SIZE(FROM_JSON(specialties, 'ARRAY<STRING>')) ELSE 0
  END as specialty_count,
  CASE WHEN capability IS NOT NULL
    THEN SIZE(FROM_JSON(capability, 'ARRAY<STRING>')) ELSE 0
  END as capability_count,
  CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL
    THEN true ELSE false
  END as has_coordinates
FROM {BRONZE}.facilities
""")

print(f"facilities_clean: {spark.table(f'{TARGET}.facilities_clean').count()} rows")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {TARGET}.pincode_deduped AS
SELECT
  pincode, district, statename,
  AVG(TRY_CAST(latitude AS DOUBLE)) as latitude,
  AVG(TRY_CAST(longitude AS DOUBLE)) as longitude,
  COUNT(*) as office_count,
  FIRST(regionname) as regionname,
  FIRST(divisionname) as divisionname
FROM {BRONZE}.india_post_pincode_directory
GROUP BY pincode, district, statename
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
WITH district_facilities AS (
  SELECT
    LOWER(TRIM(address_stateOrRegion)) as state,
    LOWER(TRIM(address_city)) as city,
    COUNT(*) as total_facilities,
    SUM(CASE WHEN base_trust_signal IN ('strong_evidence','partial_evidence') THEN 1 ELSE 0 END) as trusted_facilities,
    AVG(trust_rank) as avg_trust_rank
  FROM {TARGET}.facility_trust_scores
  GROUP BY LOWER(TRIM(address_stateOrRegion)), LOWER(TRIM(address_city))
)
SELECT
  n.district_name, n.state_ut,
  COALESCE(f.total_facilities, 0) as total_facilities,
  COALESCE(f.trusted_facilities, 0) as trusted_facilities,
  COALESCE(f.avg_trust_rank, 0) as avg_trust_rank,
  n.institutional_birth_5y_pct,
  n.hh_member_covered_health_insurance_pct,
  n.all_w15_49_who_are_anaemic_pct,
  n.households_surveyed,
  ROUND(
    ((100 - COALESCE(n.institutional_birth_5y_pct, 50))
     + (100 - COALESCE(n.hh_member_covered_health_insurance_pct, 20)))
    / (COALESCE(f.trusted_facilities, 0) + 1), 2
  ) as desert_score
FROM {TARGET}.nfhs_clean n
LEFT JOIN district_facilities f
  ON n.district_name = f.city OR n.state_ut = f.state
ORDER BY desert_score DESC
""")

print(f"desert_scores: {spark.table(f'{TARGET}.desert_scores').count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

for table in ["facilities_clean", "pincode_deduped", "nfhs_clean", "capability_index", "facility_trust_scores", "desert_scores"]:
    count = spark.table(f"{TARGET}.{table}").count()
    print(f"{table:30s} {count:>10,} rows")

print("\nETL complete. All tables refreshed.")
