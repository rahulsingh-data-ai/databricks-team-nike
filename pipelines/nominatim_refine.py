# Databricks notebook source
# MAGIC %md
# MAGIC # Nominatim Pincode Refinement
# MAGIC
# MAGIC For every facility flagged with `pincode_status != 'valid'`, call
# MAGIC OpenStreetMap Nominatim's reverse-geocode endpoint to get a second
# MAGIC opinion on the pincode. Persist the results into
# MAGIC `workspace.referral_copilot.facility_pincode_nominatim` and a small
# MAGIC agreement-summary table.
# MAGIC
# MAGIC Nominatim usage policy: max 1 request / second. With ~580 facilities
# MAGIC that's ~10 minutes wall time.
# MAGIC
# MAGIC Source: Nominatim is free, no API key needed. We send a descriptive
# MAGIC `User-Agent` so they can contact us if there's an issue.

# COMMAND ----------

import json
import time
import urllib.parse
import urllib.request

from pyspark.sql.types import (
    DoubleType, StringType, StructField, StructType, BooleanType,
)

TARGET = "workspace.referral_copilot"
NOMINATIM_BASE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "referral-copilot-hackathon/0.1 (dais-2026)"
RATE_LIMIT_SECONDS = 1.1   # Nominatim asks for <= 1 req/s; pad a bit
TIMEOUT_SECONDS = 12

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Pull bad-pincode facilities from gold

# COMMAND ----------

candidates = spark.sql(f"""
    SELECT
        unique_id,
        name,
        latitude,
        longitude,
        address_zipOrPostcode as our_pincode,
        state_resolved        as our_state,
        district_resolved     as our_district,
        correction_distance_km as india_post_distance_km
    FROM {TARGET}.facilities_gold
    WHERE pincode_status <> 'valid'
      AND latitude BETWEEN 6 AND 38
      AND longitude BETWEEN 68 AND 98
    ORDER BY unique_id
""").collect()

rows = [r.asDict() for r in candidates]
print(f"Refining {len(rows)} facilities via Nominatim")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Call Nominatim (single-threaded, rate-limited)

# COMMAND ----------

def reverse_geocode(lat: float, lon: float) -> dict:
    url = (
        f"{NOMINATIM_BASE}?format=json&lat={lat}&lon={lon}"
        "&zoom=18&addressdetails=1"
    )
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
        return json.loads(r.read())


results = []
errors = 0
start = time.time()

for i, row in enumerate(rows, 1):
    payload = {
        "unique_id":          row["unique_id"],
        "our_pincode":        row["our_pincode"],
        "our_state":          row["our_state"],
        "our_district":       row["our_district"],
        "india_post_distance_km": row.get("india_post_distance_km"),
        "nom_pincode":        None,
        "nom_city":           None,
        "nom_state":          None,
        "nom_lat":            None,
        "nom_lon":            None,
        "nom_display":        None,
        "agrees_with_post":   None,
        "error":              None,
    }
    try:
        data = reverse_geocode(row["latitude"], row["longitude"])
        addr = (data or {}).get("address", {}) or {}
        nom_pin = addr.get("postcode")
        payload["nom_pincode"] = nom_pin
        payload["nom_city"]    = (addr.get("city") or addr.get("town")
                                  or addr.get("village") or addr.get("suburb"))
        payload["nom_state"]   = addr.get("state")
        payload["nom_lat"]     = float(data["lat"]) if data.get("lat") else None
        payload["nom_lon"]     = float(data["lon"]) if data.get("lon") else None
        payload["nom_display"] = data.get("display_name")
        payload["agrees_with_post"] = (
            nom_pin is not None and nom_pin == row["our_pincode"]
        )
    except Exception as e:  # noqa: BLE001
        payload["error"] = str(e)[:200]
        errors += 1

    results.append(payload)

    if i % 50 == 0:
        elapsed = round(time.time() - start)
        print(f"[{i:>4}/{len(rows)}] elapsed={elapsed}s errors={errors}")
    time.sleep(RATE_LIMIT_SECONDS)

print(f"\nDone. errors={errors}/{len(rows)}, total {round(time.time()-start)}s")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Persist as Delta tables

# COMMAND ----------

schema = StructType([
    StructField("unique_id",              StringType(), False),
    StructField("our_pincode",            StringType(), True),
    StructField("our_state",              StringType(), True),
    StructField("our_district",           StringType(), True),
    StructField("india_post_distance_km", DoubleType(), True),
    StructField("nom_pincode",            StringType(), True),
    StructField("nom_city",               StringType(), True),
    StructField("nom_state",              StringType(), True),
    StructField("nom_lat",                DoubleType(), True),
    StructField("nom_lon",                DoubleType(), True),
    StructField("nom_display",            StringType(), True),
    StructField("agrees_with_post",       BooleanType(), True),
    StructField("error",                  StringType(), True),
])

df = spark.createDataFrame(results, schema)
df.write.mode("overwrite").saveAsTable(f"{TARGET}.facility_pincode_nominatim")
print(f"Wrote {df.count()} rows to {TARGET}.facility_pincode_nominatim")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Agreement summary

# COMMAND ----------

summary = spark.sql(f"""
    SELECT
        SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errored,
        SUM(CASE WHEN nom_pincode IS NULL AND error IS NULL THEN 1 ELSE 0 END) AS nominatim_no_postcode,
        SUM(CASE WHEN agrees_with_post THEN 1 ELSE 0 END) AS agrees_with_india_post,
        SUM(CASE WHEN nom_pincode IS NOT NULL AND NOT agrees_with_post THEN 1 ELSE 0 END) AS differs,
        COUNT(*) AS total
    FROM {TARGET}.facility_pincode_nominatim
""").collect()[0].asDict()

print(json.dumps(summary, indent=2, default=str))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. (Optional) Boost pincode_confidence in facilities_gold
# MAGIC We deliberately do NOT pollute facilities_gold with separate
# MAGIC ``nominatim_*`` columns. The detailed Nominatim data lives in the
# MAGIC audit table ``facility_pincode_nominatim``. Here we only nudge the
# MAGIC trust signal: when Nominatim agrees with our India Post snap,
# MAGIC bump ``pincode_confidence`` toward 1.0.

# COMMAND ----------

spark.sql(f"""
    MERGE INTO {TARGET}.facilities_gold g
    USING (
        SELECT unique_id, agrees_with_post
        FROM {TARGET}.facility_pincode_nominatim
        WHERE agrees_with_post = true
    ) n
    ON g.unique_id = n.unique_id
    WHEN MATCHED THEN UPDATE SET g.pincode_confidence = GREATEST(g.pincode_confidence, 0.95)
""")
print("Pincode confidence boosted for facilities where Nominatim agrees")
