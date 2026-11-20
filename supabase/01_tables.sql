-- OrthoParity database: tables, indexes and public read-only access
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.

create extension if not exists pg_trgm;

-- ---------------------------------------------------------------- predicate data (FDA 510(k) clearances and their predicates)
create table if not exists pc_devices (
  knumber            text primary key,
  device_name        text,
  applicant          text,
  decision_date      text,        -- YYYY-MM-DD as text
  decision_year      text,
  product_code       text,
  regulation_number  text,
  device_class       text,
  review_panel       text,
  segment            text,        -- unofficial segment (assigned by Claude, not FDA); blank outside the starting set
  in_starting_set    boolean not null default false,
  status             text,        -- continues | stopped | not extracted
  stop_reason        text,
  summary_url        text,
  brand              text,        -- first distinctive word of the device name (starting set only)
  company_root       text         -- applicant without suffixes such as Inc. or LLC (starting set only)
);
create table if not exists pc_edges (
  edge_id            bigint primary key,
  child              text not null,     -- the device whose Summary cites the predicate
  predicate          text not null,     -- the number the chain follows (after any review correction)
  number_as_printed  text,              -- filled only when a review corrected the printed number
  role               text,              -- primary | reference
  confidence         text,              -- HIGH | MEDIUM | LOW
  review_decision    text,
  review_source      text,              -- parser | Claude review
  page               text,
  printed_label      text,
  evidence           text,
  list_order         integer
);
create table if not exists pc_flags (
  flag_id            bigint primary key,
  knumber            text not null,
  flag_type          text,
  number             text,
  detail             text,
  review_decision    text
);
create table if not exists pc_meta (
  key                text primary key,
  value              text
);
create index if not exists pc_edges_child on pc_edges (child);
create index if not exists pc_edges_predicate on pc_edges (predicate);
create index if not exists pc_flags_knumber on pc_flags (knumber);
create index if not exists pc_devices_brand on pc_devices (brand);
create index if not exists pc_devices_search on pc_devices
  using gin (lower(coalesce(device_name, '') || ' ' || coalesce(applicant, '')) gin_trgm_ops);
create table if not exists pc_product_codes (
  product_code       text primary key,
  fda_name           text,
  regulation_number  text,
  device_class       text,
  fda_definition     text,
  plain_name         text,        -- plain-English name (Claude draft until reviewed)
  plain_description  text,
  anatomy            text,
  procedures         text,
  kind               text,        -- implant | instrument | capital equipment
  segment            text,        -- most common unofficial segment for the code
  clearances         integer,     -- orthopedic clearances with this code
  reviewed           boolean not null default false
);
create table if not exists pc_ifu (
  knumber            text primary key,
  ifu_text           text,        -- Indications for Use, verbatim from the 510(k) PDF (whitespace collapsed)
  page               text,
  source             text,        -- FDA form | Summary section
  found              boolean not null default false
);
create index if not exists pc_devices_code on pc_devices (product_code);

-- ---------------------------------------------------------------- vendor and payment data (CMS Open Payments 2019-2025, FDA GUDID)
-- mode: 'pit' = as owned at the time (default); 'current' = current owner with acquired companies' history.
create table if not exists pc_vendors (
  vendor_id text primary key, display_name text, current_parent text, segment text, basis text, reviewed boolean,
  note text, clearances integer, first_clearance_year integer, last_clearance_year integer,
  gudid_ortho_devices integer, gudid_brands integer, payment_kind text, rolls_up_to text);
create table if not exists pc_vendor_names (vendor_id text, source text, raw_name text, basis text);
create table if not exists pc_vendor_lineage (
  vendor_id text, parent text, relation text, valid_from date, valid_to date, source_url text, note text, reviewed boolean);
create table if not exists pc_portfolio_brands (
  vendor_id text, brand text, product_codes text, knumbers text, devices integer, in_distribution integer, implantable boolean);
create table if not exists pc_portfolio_510k (
  vendor_id text, knumber text, device_name text, applicant text, product_code text, decision_date date,
  gudid_brand text, gudid_devices integer, gudid_in_distribution integer);
create table if not exists pc_op_vendor_year (
  mode text, vendor_id text, year integer, nature_group text, transactions integer, amount double precision, recipients integer);
create table if not exists pc_op_vendor_profile (
  mode text, vendor_id text, year integer, total double precision, transactions integer, to_entities double precision,
  equity_forms double precision, acquisitions double precision, debt_forgiveness double precision,
  to_teaching_hospitals double precision, recipients integer, physicians integer, food_r integer, travel_r integer,
  consulting_r integer, royalty_r integer, top1pct_share double precision, top10_share double precision,
  median_per_recipient double precision, bucket_json jsonb);
create table if not exists pc_op_entity (
  vendor_pit text, vendor_current text, payer_id text, payer_name text, year integer, amount double precision,
  recipients integer, royalty double precision, food double precision);
create table if not exists pc_op_product (
  knumber text, tier integer, year integer, nature_group text, brand text, vendor_pit text, transactions integer,
  amount double precision, recipients integer);
create table if not exists pc_op_product_top (
  mode text, vendor_id text, brand text, amount double precision, transactions integer, royalty double precision,
  engagement double precision, rank integer);
create table if not exists pc_op_research (
  vendor_entity text, vendor_pit text, vendor_current text, year integer, study_name text, ct_gov_id text,
  amount double precision, payments integer, preclinical boolean, knumbers text);
create table if not exists pc_op_relationship (
  mode text, vendor_id text, rkey text, year integer, bucket text, consulting boolean, royalty boolean,
  speaking_services boolean, amount double precision);
create table if not exists pc_op_ownership (
  vendor_pit text, vendor_current text, year integer, holders integer, invested double precision, value double precision);
create index if not exists pc_vendor_names_v on pc_vendor_names (vendor_id);
create index if not exists pc_vendor_names_trgm on pc_vendor_names using gin (raw_name gin_trgm_ops);
create index if not exists pc_vendor_names_raw on pc_vendor_names (raw_name, source);
create index if not exists pc_vendors_trgm on pc_vendors using gin (display_name gin_trgm_ops);
create index if not exists pc_portfolio_brands_v on pc_portfolio_brands (vendor_id);
create index if not exists pc_portfolio_510k_v on pc_portfolio_510k (vendor_id);
create index if not exists pc_portfolio_510k_k on pc_portfolio_510k (knumber);
create index if not exists pc_op_vendor_year_v on pc_op_vendor_year (vendor_id, mode);
create index if not exists pc_op_vendor_profile_v on pc_op_vendor_profile (vendor_id, mode, year);
create index if not exists pc_op_entity_v on pc_op_entity (vendor_pit);
create index if not exists pc_op_entity_c on pc_op_entity (vendor_current);
create index if not exists pc_op_product_k on pc_op_product (knumber);
create index if not exists pc_op_product_top_v on pc_op_product_top (vendor_id, mode);
create index if not exists pc_op_research_p on pc_op_research (vendor_pit);
create index if not exists pc_op_research_c on pc_op_research (vendor_current);
create index if not exists pc_op_relationship_v on pc_op_relationship (vendor_id, mode, rkey);
create index if not exists pc_op_ownership_p on pc_op_ownership (vendor_pit);
-- research studies in orthopedic scope. Open Payments research rows from diversified companies include
-- cardiac, neurovascular, neuromodulation and other non-orthopedic trials. pc_refresh_research_scope() marks each
-- row: out if the study name is clearly non-orthopedic; in if it names an orthopedic 510(k), an orthopedic topic,
-- or one of the vendor's top orthopedic brands; otherwise in only for vendors whose payments are mostly orthopedic.
-- Run it again after re-importing pc_op_research.
alter table pc_op_research add column if not exists ortho boolean;

-- business lines sold to another company (reference/vendor_divestitures.csv); each row has a public source
create table if not exists pc_vendor_divestitures (
  seller text, buyer text, effective date, product_codes text, decided_before date, source_url text, note text);

-- ---------------------------------------------------------------- recalls (openFDA device recalls, 2002 to present)
create table if not exists pc_recalls (
  recall_number text, event_id text, initiated date, posted date, terminated date, status text, recall_class text,
  product_code text, knumbers text, recalling_firm text, vendor_id text, vendor_basis text, product text, reason text,
  root_cause text, quantity text);
create index if not exists pc_recalls_v on pc_recalls (vendor_id);
create index if not exists pc_recalls_code on pc_recalls (product_code);
create index if not exists pc_recalls_event on pc_recalls (event_id);
create index if not exists pc_recalls_k on pc_recalls using gin (string_to_array(knumbers, '|'));

-- ---------------------------------------------------------------- procedures (CMS Medicare Inpatient and Outpatient Hospitals by
-- Provider and Service, national figures). Payments: medicare_pays = Medicare's share; total = Medicare plus the patient's
-- deductible and coinsurance plus any third-party payment; patient_other_pays = the difference. No charges, no hospitals.
create table if not exists pc_procedures (
  family_id text primary key, sort_order integer, name text, description text, drgs text, flagship text,
  data_year integer, discharges integer, hospitals integer, medicare_pays integer, patient_other_pays integer,
  total_payment integer, patient_other_share double precision,
  supply_medicare_30 integer, supply_medicare_40 integer, supply_medicare_50 integer,
  supply_total_30 integer, supply_total_40 integer, supply_total_50 integer, supply_note text);
create table if not exists pc_procedure_drg (
  family_id text, drg text, drg_desc text, discharges integer, hospitals integer, medicare_pays integer,
  patient_other_pays integer, total_payment integer, share_of_family double precision,
  hospital_medicare_p25 integer, hospital_medicare_median integer, hospital_medicare_p75 integer, note text,
  spread_note text);
-- added 2026-11-19: why a supply range or a hospital spread is missing (safe to run again)
alter table pc_procedures add column if not exists supply_note text;
alter table pc_procedure_drg add column if not exists spread_note text;
create table if not exists pc_procedure_apc (
  apc text primary key, apc_desc text, data_year integer, services integer, patients_reported integer, hospitals integer,
  medicare_pays integer, patient_other_pays integer, total_allowed integer);
create table if not exists pc_procedure_outpatient (
  family_id text, cpt text, procedure text, outpatient_status text, apc text, apc_services integer,
  apc_medicare_pays integer, apc_patient_other_pays integer, apc_total_allowed integer, source text, source_url text);
create table if not exists pc_procedure_devices (
  family_id text, role text, product_code text, plain_name text, fda_name text, clearances_all integer,
  clearances_recent integer, active_vendors integer, status text);
create table if not exists pc_supply_evidence (
  source text, procedure text, data_years text, measure text, result text, source_url text);
create index if not exists pc_procedure_drg_f on pc_procedure_drg (family_id);
create index if not exists pc_procedure_outpatient_f on pc_procedure_outpatient (family_id);
create index if not exists pc_procedure_devices_f on pc_procedure_devices (family_id);
create index if not exists pc_procedure_devices_code on pc_procedure_devices (product_code);
create index if not exists pc_portfolio_510k_code on pc_portfolio_510k (product_code, decision_date);

-- ---------------------------------------------------------------- public read-only access
-- Anyone can read these tables and call the public functions; nobody can write through the website.
grant usage on schema public to anon, authenticated;
do $$
declare t text;
begin
  foreach t in array array['pc_devices','pc_edges','pc_flags','pc_meta','pc_product_codes','pc_ifu',
    'pc_vendors','pc_vendor_names','pc_vendor_lineage','pc_portfolio_brands','pc_portfolio_510k',
    'pc_op_vendor_year','pc_op_vendor_profile','pc_op_entity','pc_op_product','pc_op_product_top','pc_op_research',
    'pc_op_relationship','pc_op_ownership','pc_recalls','pc_vendor_divestitures','pc_procedures','pc_procedure_drg','pc_procedure_apc',
    'pc_procedure_outpatient','pc_procedure_devices','pc_supply_evidence']
  loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (true)', t);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;
