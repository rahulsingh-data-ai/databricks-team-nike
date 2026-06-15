"""
Referral Copilot — Bronze → Silver → Gold ETL Pipeline
Delta Live Tables (DLT) pipeline for incremental data processing.

In production, the Virtue Foundation's FDR pipeline continuously crawls
web sources and updates facility records. This pipeline incrementally
processes those updates through our medallion architecture.

Bronze (source): databricks_virtue_foundation_dataset_dais_2026.virtue_foundation_dataset
Silver (cleaned): workspace.referral_copilot (facilities_clean, pincode_deduped, nfhs_clean)
Gold (app-ready): workspace.referral_copilot (capability_index, facility_trust_scores, desert_scores)
"""

import dlt
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, StringType

BRONZE_CATALOG = "databricks_virtue_foundation_dataset_dais_2026"
BRONZE_SCHEMA = "virtue_foundation_dataset"


# ============================================================
# SILVER LAYER — Cleaned, typed, normalized
# ============================================================

@dlt.table(
    name="facilities_clean",
    comment="Cleaned facility records with parsed source counts and coordinate flags",
)
def facilities_clean():
    df = spark.read.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.facilities")
    return (
        df.withColumn(
            "source_count",
            F.when(F.col("source_types").isNotNull(),
                   F.size(F.from_json(F.col("source_types"), ArrayType(StringType()))))
            .otherwise(0),
        )
        .withColumn(
            "distinct_source_count",
            F.when(F.col("source_types").isNotNull(),
                   F.size(F.array_distinct(F.from_json(F.col("source_types"), ArrayType(StringType())))))
            .otherwise(0),
        )
        .withColumn(
            "specialty_count",
            F.when(F.col("specialties").isNotNull(),
                   F.size(F.from_json(F.col("specialties"), ArrayType(StringType()))))
            .otherwise(0),
        )
        .withColumn(
            "capability_count",
            F.when(F.col("capability").isNotNull(),
                   F.size(F.from_json(F.col("capability"), ArrayType(StringType()))))
            .otherwise(0),
        )
        .withColumn(
            "has_coordinates",
            F.col("latitude").isNotNull() & F.col("longitude").isNotNull(),
        )
    )


@dlt.table(
    name="pincode_deduped",
    comment="Deduplicated pincode directory — one row per (pincode, district, state) with averaged coordinates",
)
def pincode_deduped():
    df = spark.read.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.india_post_pincode_directory")
    return (
        df.withColumn("lat_num", F.try_cast(F.col("latitude"), "double"))
        .withColumn("lon_num", F.try_cast(F.col("longitude"), "double"))
        .groupBy("pincode", "district", "statename")
        .agg(
            F.avg("lat_num").alias("latitude"),
            F.avg("lon_num").alias("longitude"),
            F.count("*").alias("office_count"),
            F.first("regionname").alias("regionname"),
            F.first("divisionname").alias("divisionname"),
        )
    )


@dlt.table(
    name="nfhs_clean",
    comment="Normalized NFHS-5 district health indicators with lowercase district/state names",
)
def nfhs_clean():
    df = spark.read.table(f"{BRONZE_CATALOG}.{BRONZE_SCHEMA}.nfhs_5_district_health_indicators")
    return (
        df.withColumn("district_name", F.lower(F.trim(F.col("district_name"))))
        .withColumn("state_ut", F.lower(F.trim(F.col("state_ut"))))
        .select(
            "district_name", "state_ut", "households_surveyed",
            "institutional_birth_5y_pct", "institutional_birth_in_public_facility_5y_pct",
            "hh_member_covered_health_insurance_pct", "hh_electricity_pct",
            "hh_improved_water_pct", "hh_use_improved_sanitation_pct",
            "households_using_clean_fuel_for_cooking_pct",
            "all_w15_49_who_are_anaemic_pct",
            "non_pregnant_w15_49_who_are_anaemic_lt_12_0_g_dl_22_pct",
            "women_age_15_49_years_whose_bmi_bmi_is_underweight_bmi_lt_1_pct",
            "women_age_15_49_years_who_are_overweight_obese_bmi_gte_25_0_pct",
            "prev_diarrhoea_2wk_child_u5_pct",
            "children_prev_symptoms_of_acute_respiratory_infection_ari_2_pct",
            "women_age_30_49_years_ever_undergone_a_cervical_screen_pct",
            "women_age_30_49_years_ever_undergone_a_breast_exam_pct",
            "w15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
            "m15_plus_with_high_or_very_high_gt_140_mg_dl_blood_sugar_or_pct",
            "w15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
            "m15_plus_with_high_bp_sys_gte_140_mmhg_and_or_dia_gte_90_mm_pct",
        )
    )


# ============================================================
# GOLD LAYER — Aggregated, pre-computed, app-ready
# ============================================================

@dlt.table(
    name="capability_index",
    comment="Exploded capability index — one row per (facility, specialty) for fast search",
)
def capability_index():
    facilities = dlt.read("facilities_clean")
    return (
        facilities.filter(F.col("specialties").isNotNull())
        .select(
            "unique_id", "name", "facilityTypeId",
            "address_city", "address_stateOrRegion", "address_zipOrPostcode",
            "latitude", "longitude", "source_count", "has_coordinates",
            F.explode(F.from_json(F.col("specialties"), ArrayType(StringType()))).alias("specialty"),
        )
        .withColumn("specialty", F.lower(F.trim(F.col("specialty"))))
    )


@dlt.table(
    name="facility_trust_scores",
    comment="Pre-computed trust signal per facility based on source diversity and data completeness",
)
def facility_trust_scores():
    facilities = dlt.read("facilities_clean")
    return (
        facilities.withColumn(
            "base_trust_signal",
            F.when(
                (F.col("facilityTypeId").isin("clinic", "dentist")) & (F.col("specialty_count") > 20),
                F.lit("suspicious"),
            )
            .when(
                (F.col("distinct_source_count") >= 3) & (F.col("specialty_count") > 0),
                F.lit("strong_evidence"),
            )
            .when(
                (F.col("distinct_source_count") == 2) & (F.col("specialty_count") > 0),
                F.lit("partial_evidence"),
            )
            .when(
                (F.col("distinct_source_count") >= 1) & (F.col("specialty_count") > 0),
                F.lit("partial_evidence"),
            )
            .when(
                (F.col("distinct_source_count") >= 1) & (F.col("capability_count") > 0),
                F.lit("weak_evidence"),
            )
            .when(F.col("capability_count") > 0, F.lit("weak_evidence"))
            .otherwise(F.lit("no_evidence")),
        )
        .withColumn(
            "trust_rank",
            F.when(F.col("base_trust_signal") == "strong_evidence", 5)
            .when(F.col("base_trust_signal") == "partial_evidence", 4)
            .when(F.col("base_trust_signal") == "weak_evidence", 3)
            .when(F.col("base_trust_signal") == "suspicious", 2)
            .otherwise(1),
        )
        .withColumn(
            "missing_data_count",
            (F.when(F.col("capacity").isNull(), 1).otherwise(0)
             + F.when(F.col("numberDoctors").isNull(), 1).otherwise(0)
             + F.when(F.col("yearEstablished").isNull(), 1).otherwise(0)
             + F.when(F.col("recency_of_page_update").isNull(), 1).otherwise(0)
             + F.when(F.col("distinct_source_count") <= 1, 1).otherwise(0)
             + F.when(F.col("phone_numbers").isNull() & F.col("officialPhone").isNull(), 1).otherwise(0)),
        )
        .select(
            "unique_id", "name", "facilityTypeId",
            "address_city", "address_stateOrRegion",
            "latitude", "longitude",
            "source_count", "distinct_source_count",
            "specialty_count", "capability_count", "has_coordinates",
            "base_trust_signal", "trust_rank", "missing_data_count",
        )
    )


@dlt.table(
    name="desert_scores",
    comment="Healthcare desert scores: high disease burden vs low trusted facility coverage per district",
)
def desert_scores():
    trust = dlt.read("facility_trust_scores")
    nfhs = dlt.read("nfhs_clean")

    district_facilities = (
        trust.withColumn("state", F.lower(F.trim(F.col("address_stateOrRegion"))))
        .withColumn("city", F.lower(F.trim(F.col("address_city"))))
        .groupBy("state", "city")
        .agg(
            F.count("*").alias("total_facilities"),
            F.sum(F.when(F.col("base_trust_signal").isin("strong_evidence", "partial_evidence"), 1).otherwise(0))
            .alias("trusted_facilities"),
            F.avg("trust_rank").alias("avg_trust_rank"),
        )
    )

    return (
        nfhs.join(
            district_facilities,
            (nfhs.district_name == district_facilities.city)
            | (nfhs.state_ut == district_facilities.state),
            "left",
        )
        .withColumn("total_facilities", F.coalesce(F.col("total_facilities"), F.lit(0)))
        .withColumn("trusted_facilities", F.coalesce(F.col("trusted_facilities"), F.lit(0)))
        .withColumn("avg_trust_rank", F.coalesce(F.col("avg_trust_rank"), F.lit(0)))
        .withColumn(
            "desert_score",
            F.round(
                ((100 - F.coalesce(F.col("institutional_birth_5y_pct"), F.lit(50)))
                 + (100 - F.coalesce(F.col("hh_member_covered_health_insurance_pct"), F.lit(20))))
                / (F.col("trusted_facilities") + 1),
                2,
            ),
        )
        .select(
            "district_name", "state_ut",
            "total_facilities", "trusted_facilities", "avg_trust_rank",
            "institutional_birth_5y_pct", "hh_member_covered_health_insurance_pct",
            "all_w15_49_who_are_anaemic_pct", "households_surveyed",
            "desert_score",
        )
        .orderBy(F.desc("desert_score"))
    )
