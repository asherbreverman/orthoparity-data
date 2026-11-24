-- 14_asc_rates.sql: Medicare ASC payment rates for the key procedure codes of each procedure family.
-- Written by `python orthoparity.py load-asc` from CMS's ASC Addenda AA and FF. Don't edit by hand; rerun the step.
-- Safe to run again. Run order after an import: 07, 13, 14, 12, 05.

create table if not exists pc_procedure_asc (
  family_id text not null, cpt text not null, procedure text, sort_order int, asc_status text, payment_indicator text,
  device_intensive boolean, asc_rate numeric, device_share numeric, device_portion numeric, rate_year int,
  source text, source_url text, primary key (family_id, cpt));
alter table pc_procedure_asc enable row level security;
drop policy if exists "public read" on pc_procedure_asc;
create policy "public read" on pc_procedure_asc for select to anon, authenticated using (cpt is not null);
grant select on pc_procedure_asc to anon, authenticated;

delete from pc_procedure_asc;
insert into pc_procedure_asc (family_id, cpt, procedure, sort_order, asc_status, payment_indicator, device_intensive,
  asc_rate, device_share, device_portion, rate_year, source, source_url) values
  ('hip_knee_replacement', '27447', 'Total knee replacement', 1, 'On the ASC list', 'J8', true, 9753.23, 0.4384, 6087.90, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('hip_knee_replacement', '27130', 'Total hip replacement', 2, 'On the ASC list', 'J8', true, 10049.10, 0.4786, 6646.14, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('revision_hip_knee', '27134', 'Revision total hip replacement', 3, 'On the ASC list', 'J8', true, 9618.53, 0.4201, 5833.77, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('revision_hip_knee', '27487', 'Revision total knee replacement', 4, 'On the ASC list', 'J8', true, 14566.54, 0.5598, 10635.79, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('hip_fracture_replacement', '27236', 'Hemiarthroplasty for femoral neck fracture', 5, 'On the ASC list', 'J8', true, 5162.05, 0.3634, 2831.12, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('hip_femur_fixation', '27245', 'Intramedullary nail, hip fracture', 6, 'On the ASC list', 'J8', true, 5341.66, 0.4069, 3170.01, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('hip_femur_fixation', '27244', 'Plate and screw (sliding hip screw), hip fracture', 7, 'On the ASC list', 'J8', true, 4941.55, 0.3100, 2415.10, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('shoulder_elbow_replacement', '23472', 'Total shoulder replacement', 8, 'On the ASC list', 'J8', true, 14900.86, 0.5930, 11266.57, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('thoracolumbar_fusion', '22612', 'Posterolateral lumbar fusion, single level', 9, 'On the ASC list', 'J8', true, 14388.30, 0.5421, 10299.50, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('thoracolumbar_fusion', '22630', 'Posterior lumbar interbody fusion, single level', 10, 'On the ASC list', 'J8', true, 23123.22, 0.5833, 17311.00, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('thoracolumbar_fusion', '22633', 'Combined posterolateral and interbody lumbar fusion, single level', 11, 'On the ASC list', 'J8', true, 23400.05, 0.6009, 17833.32, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc'),
  ('cervical_fusion', '22551', 'Anterior cervical discectomy and fusion (ACDF), single level', 12, 'On the ASC list', 'J8', true, 9570.70, 0.4136, 5743.51, 2027, 'CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF', 'https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/asc-regulations-and-notices/cms-1850-fc');

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
