CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
  user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT,
  name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS searches (
  search_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(user_id),
  query_text TEXT,
  parsed_capability TEXT,
  parsed_location TEXT,
  parsed_pincode BIGINT,
  parsed_district TEXT,
  parsed_state TEXT,
  result_count INT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shortlist (
  shortlist_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(user_id),
  search_id UUID REFERENCES searches(search_id),
  facility_id TEXT,
  facility_name TEXT,
  capability TEXT,
  trust_signal TEXT,
  distance_km FLOAT,
  notes TEXT,
  saved_at TIMESTAMPTZ DEFAULT now()
);
