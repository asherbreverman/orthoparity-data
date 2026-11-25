-- OrthoParity database: procedure view (Medicare payments by procedure family) and the procedure links on device pages
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.
-- Reads pc_procedures, pc_procedure_drg, pc_procedure_apc, pc_procedure_outpatient, pc_procedure_devices and
-- pc_supply_evidence (written by  python orthoparity.py load-medicare-hospitals). National figures only.
-- Device pages get procedure names and roles, never a dollar figure.

-- what every procedure page must say about the data (shown with the numbers, not hidden behind a link)
create or replace function pc_procedure_notes() returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'source', 'CMS Medicare Inpatient Hospitals and Medicare Outpatient Hospitals by Provider and Service (data.cms.gov)',
    'definitions', jsonb_build_array(
      jsonb_build_object('term', 'Medicare pays', 'text',
        'Medicare''s own payment to the hospital, averaged per case and weighted by volume across hospitals.'),
      jsonb_build_object('term', 'Patient and other payers', 'text',
        'The patient''s deductible and coinsurance plus any secondary insurer (Medigap, Medicaid, a retiree plan). '
        || 'It shows what the hospital bills. Collections can run lower.'),
      jsonb_build_object('term', 'Total payment', 'text',
        'Everything the hospital is owed for the case: Medicare plus patient and other payers.'),
      jsonb_build_object('term', 'Supply range', 'text',
        'The payment times 30%, 40% and 50%. A planning reference drawn from published studies of implant cost '
        || 'as a share of payment, for comparing with a hospital''s own supply cost per case. It is not a standard or a target. '
        || 'Shown only for procedures that a published study covers.'),
      jsonb_build_object('term', 'Hospital spread', 'text',
        'The 25th percentile, median and 75th percentile of each hospital''s own average Medicare payment for a DRG. '
        || 'Shown only when at least 5 hospitals report the DRG.'),
      jsonb_build_object('term', 'Active vendors', 'text',
        'Companies, grouped by current owner, with at least one 510(k) in the category decided in the five years '
        || 'before the FDA data ends. A clearance shows a company can sell a product, not that it does.')),
    'limitations', jsonb_build_array(
      'Original Medicare fee-for-service only. Medicare Advantage, Medicaid and commercial payers are not in the data.',
      'CMS hides any hospital and DRG with fewer than 11 discharges (11 services for outpatient), so totals and hospital '
        || 'counts run low, most for low-volume DRGs.',
      'A DRG pays for the whole hospital stay: room, staff, operating room, drugs and supplies. No public data shows what '
        || 'a hospital pays for devices.',
      'Payments vary by hospital with local wages, teaching status and other adjustments. The national average is a '
        || 'reference point, not any one hospital''s payment.',
      'Medicare pays primary hip and knee replacement under the same DRGs (469 and 470) and the same outpatient group '
        || '(APC 5115), so the data can''t separate hip from knee. Much of this surgery is now outpatient.',
      'Outpatient payment groups (APCs) cover many procedures each. The outpatient file reports APCs, not procedure codes.',
      'These are 2024 DRGs. CMS added new spine fusion DRGs in fiscal year 2025 and renumbered more on October 1, 2026: '
        || 'knee surgery with an infection diagnosis moved from DRGs 485 to 487 to DRG 400, and hip or knee revision from '
        || '466 to 468 to DRG 449. DRG titles come from the CMS MS-DRG v41.1 Definitions Manual.',
      'Most hand, foot, knee arthroscopy and sports medicine surgery is now outpatient, so the inpatient numbers for those '
        || 'procedures are small. Some musculoskeletal DRGs (476, 495, 498, 499, 503, 505, 506 to 510 and 514) had no hospital '
        || 'with 11 or more Medicare discharges in 2024, so they don''t appear.',
      'Device categories list what a typical case can use. Real cases vary. Many biologics and PMA devices are outside '
        || 'the 510(k) data, so they don''t appear. A reviewed category was checked against public coding guides and the '
        || 'CMS DRG manual, not by a clinician; a draft one has not been checked yet.',
      'A payment figure is a fact about Medicare, not a judgment about any hospital, vendor, GPO or IDN.'))
$$;

-- questions for a hospital team to work through with its own numbers
drop function if exists pc_procedure_worksheet();
create or replace function pc_procedure_worksheet(fam text default null) returns jsonb language sql immutable as $$
  select jsonb_build_array(
    jsonb_build_object('step', 1, 'question', 'Which implants does a typical case use, and how many of each?',
      'hint', case fam
        when 'hip_knee_replacement' then 'For example: a femoral component, a tibial tray, an insert and a patella; or an acetabular shell, a liner, a femoral stem and a head.'
        when 'revision_hip_knee' then 'For example: revision stems, augments or cones, a constrained insert, an acetabular shell and a liner.'
        when 'hip_fracture_replacement' then 'For example: a femoral stem, a unipolar or bipolar head, and cement.'
        when 'hip_femur_fixation' then 'For example: an intramedullary nail, or a sliding hip screw and side plate, with lag and locking screws.'
        when 'shoulder_elbow_replacement' then 'For example: a humeral stem, a glenoid baseplate and glenosphere or a glenoid component, and screws.'
        when 'thoracolumbar_fusion' then 'For example: pedicle screws, rods, set screws, an interbody cage.'
        when 'cervical_fusion' then 'For example: an interbody cage, an anterior plate and screws.'
        when 'spine_surgery_no_fusion' then 'For example: an interspinous device, a disc replacement or graft material, if used.'
        when 'lower_extremity_humerus' then 'For example: a nail or plate, locking and cortical screws.'
        when 'foot_soft_tissue' then 'For example: plates, screws, staples or anchors.'
        when 'knee_surgery_no_replacement' then 'For example: anchors, screws, grafts or plates.'
        when 'upper_extremity_no_replacement' then 'For example: plates, screws, anchors or pins.'
        else 'For example: the main implants, the screws, plates or pins that hold them, and any cement or graft.' end),
    jsonb_build_object('step', 2, 'question', 'What does the hospital pay per unit for each, and what does the construct cost per case?',
      'hint', 'Units times price, added up across the construct.'),
    jsonb_build_object('step', 3, 'question', 'What else goes into the case?',
      'hint', 'Biologics, cement, disposables, and any per-case fee for navigation or a robot.'),
    jsonb_build_object('step', 4, 'question', 'What share of the payment does the full supply cost take?',
      'hint', 'Supply cost per case divided by Medicare''s payment, and again by the total payment.'),
    jsonb_build_object('step', 5, 'question', 'How does that compare with the supply range and the published studies on this page, where they are shown?',
      'hint', 'Studies found wide variation between hospitals. A share outside the range is a reason to look closer, not a verdict.'),
    jsonb_build_object('step', 6, 'question', 'Of the payment, how much goes to supplies and how much is left for the rest of the case?',
      'hint', 'The rest covers staff, operating room time, the stay and everything else the hospital provides.'),
    jsonb_build_object('step', 7, 'question', 'Do these cases stay inpatient, or can some move to outpatient?',
      'hint', 'See the outpatient table. Payment differs by setting.'))
$$;

-- active vendors for one product code: current owner, at least one 510(k) in the five years before the data ends
create or replace function pc_code_vendors(code text, lim int default 100)
returns jsonb language sql stable as $$
  with win as materialized (select pc_data_end() - interval '5 years' as since),
  recent as (
    select coalesce(v.rolls_up_to, p.vendor_id) as owner, p.knumber, p.decision_date
    from pc_portfolio_510k p left join pc_vendors v on v.vendor_id = p.vendor_id cross join win w
    where p.product_code = upper(code) and p.decision_date > w.since),
  agg as (
    select r.owner, count(distinct r.knumber) as clearances, max(r.decision_date) as latest from recent r group by r.owner)
  select coalesce(jsonb_agg(jsonb_build_object('vendor_id', a.owner, 'name', coalesce(o.display_name, a.owner),
                                               'clearances', a.clearances, 'latest', a.latest)
                            order by a.clearances desc, a.latest desc, a.owner), '[]'::jsonb)
  from (select * from agg order by clearances desc, latest desc, owner limit lim) a
  left join pc_vendors o on o.vendor_id = a.owner
$$;

-- every procedure family, for the procedures index page
-- Phase 9: one family's ASC rates as {low, high, year, codes: [...]}; null when the family has no loaded ASC code.
-- Reads pc_procedure_asc only when 14_asc_rates.sql has created it, so this file still runs before 14.
create or replace function pc_procedure_asc_summary(fam text)
returns jsonb language plpgsql stable as $$
declare r jsonb;
begin
  if to_regclass('public.pc_procedure_asc') is null then return null; end if;
  execute $q$
    select case when count(*) = 0 then null else jsonb_build_object(
      'low', min(asc_rate), 'high', max(asc_rate), 'year', max(rate_year),
      'codes', jsonb_agg(jsonb_build_object('cpt', cpt, 'procedure', procedure, 'asc_rate', asc_rate,
                                            'device_portion', device_portion, 'status', asc_status) order by sort_order)) end
      from pc_procedure_asc where family_id = $1 and asc_rate is not null $q$
    into r using fam;
  return r;
end $$;

create or replace function pc_procedure_list()
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'procedures', coalesce((select jsonb_agg(jsonb_build_object(
        'family_id', p.family_id, 'name', p.name, 'description', p.description,
        'drgs', string_to_array(p.drgs, '|'), 'flagship', p.flagship = 'yes', 'data_year', p.data_year,
        'discharges', p.discharges, 'hospitals', p.hospitals, 'medicare_pays', p.medicare_pays,
        'patient_other_pays', p.patient_other_pays, 'total_payment', p.total_payment,
        'device_categories', (select count(*) from pc_procedure_devices d where d.family_id = p.family_id),
        -- Phase 9: CY 2027 ASC national rates for the family's key procedure codes (null when none are loaded)
        'asc', pc_procedure_asc_summary(p.family_id))
      order by p.sort_order) from pc_procedures p), '[]'::jsonb),
    'asc_note', 'ASC rates are CMS CY 2027 national rates before wage adjustment, for the 12 procedure codes loaded so '
                || 'far. A range spans the loaded codes in the family. Hospital outpatient payments are not shown yet.',
    'notes', pc_procedure_notes())
$$;

-- one procedure family: payments, DRGs, outpatient status, device categories with active vendors, evidence, worksheet
create or replace function pc_procedure(fid text, vendors_per_code int default 100)
returns jsonb language plpgsql stable as $$
declare p pc_procedures; res jsonb;
begin
  select * into p from pc_procedures where family_id = lower(trim(fid));
  if not found then
    return jsonb_build_object('found', false, 'family_id', fid);
  end if;
  select jsonb_build_object(
    'found', true,
    'family', jsonb_build_object(
      'family_id', p.family_id, 'name', p.name, 'description', p.description, 'drgs', string_to_array(p.drgs, '|'),
      'flagship', p.flagship = 'yes', 'data_year', p.data_year, 'discharges', p.discharges, 'hospitals', p.hospitals),
    'payment', jsonb_build_object(
      'medicare_pays', p.medicare_pays, 'patient_other_pays', p.patient_other_pays, 'total_payment', p.total_payment,
      'patient_other_share', p.patient_other_share),
    'supply_range', jsonb_build_object(
      'shares', jsonb_build_array(0.30, 0.40, 0.50),
      'on_medicare', jsonb_build_array(p.supply_medicare_30, p.supply_medicare_40, p.supply_medicare_50),
      'on_total', jsonb_build_array(p.supply_total_30, p.supply_total_40, p.supply_total_50),
      'note', nullif(p.supply_note, '')),
    'drgs', coalesce((select jsonb_agg(jsonb_build_object(
        'drg', d.drg, 'description', d.drg_desc, 'discharges', d.discharges, 'hospitals', d.hospitals,
        'medicare_pays', d.medicare_pays, 'patient_other_pays', d.patient_other_pays, 'total_payment', d.total_payment,
        'share_of_family', d.share_of_family,
        'hospital_medicare_spread', case when d.hospital_medicare_median is null then null else jsonb_build_object(
          'p25', d.hospital_medicare_p25, 'median', d.hospital_medicare_median, 'p75', d.hospital_medicare_p75) end,
        'spread_note', nullif(d.spread_note, ''),
        'note', d.note) order by d.discharges desc, d.drg::int)
      from pc_procedure_drg d where d.family_id = p.family_id), '[]'::jsonb),
    'outpatient', coalesce((select jsonb_agg(jsonb_build_object(
        'cpt', o.cpt, 'procedure', o.procedure, 'status', o.outpatient_status, 'apc', o.apc,
        'apc_services', o.apc_services, 'apc_medicare_pays', o.apc_medicare_pays,
        'apc_patient_other_pays', o.apc_patient_other_pays, 'apc_total_allowed', o.apc_total_allowed,
        'apc_description', a.apc_desc, 'source', o.source, 'source_url', o.source_url) order by o.cpt)
      from pc_procedure_outpatient o left join pc_procedure_apc a on a.apc = o.apc
      where o.family_id = p.family_id), '[]'::jsonb),
    'devices', coalesce((select jsonb_agg(jsonb_build_object(
        'role', d.role, 'product_code', d.product_code, 'plain_name', d.plain_name, 'fda_name', d.fda_name,
        'clearances_all', d.clearances_all, 'clearances_recent', d.clearances_recent,
        'active_vendors', d.active_vendors, 'status', d.status,
        'vendors', pc_code_vendors(d.product_code, vendors_per_code))
      order by array_position(array['implant','biologic','cement and accessories','enabling technology'], d.role),
               d.active_vendors desc, d.product_code)
      from pc_procedure_devices d where d.family_id = p.family_id), '[]'::jsonb),
    'evidence', coalesce((select jsonb_agg(to_jsonb(e)) from pc_supply_evidence e), '[]'::jsonb),
    'worksheet', pc_procedure_worksheet(p.family_id),
    'vendor_window', jsonb_build_object('from', (pc_data_end() - interval '5 years')::date, 'to', pc_data_end()),
    'notes', pc_procedure_notes())
  into res;
  return res;
end $$;

-- device pages: the procedures where this 510(k)'s product code is used. Names and roles only, no dollars.
create or replace function pc_code_procedures(code text)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(jsonb_build_object('family_id', p.family_id, 'name', p.name, 'role', d.role,
                                               'flagship', p.flagship = 'yes', 'status', d.status)
                            order by p.sort_order), '[]'::jsonb)
  from pc_procedure_devices d join pc_procedures p on p.family_id = d.family_id
  where d.product_code = upper(trim(code))
$$;

create or replace function pc_device_procedures(k text)
returns jsonb language plpgsql stable as $$
declare kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g')); code text;
begin
  select product_code into code from pc_devices where knumber = kn;
  return jsonb_build_object('knumber', kn, 'product_code', code,
                            'procedures', case when code is null then '[]'::jsonb else pc_code_procedures(code) end);
end $$;

-- company pages: procedures where this company (or, in current mode, its family of acquired companies) has 510(k)s in
-- the device categories. Clearance counts only, no dollars. "Recent" uses the same five-year window as the procedure page.
create or replace function pc_vendor_procedures(v text, m text default 'pit')
returns jsonb language sql stable as $$
  with fam as materialized (select vendor_id from pc_vendor_family(v, m) where pc_mode(m) = 'current' or vendor_id = v),
  win as materialized (select pc_data_end() - interval '5 years' as since),
  mine as (
    select p.product_code, count(distinct p.knumber) as clearances_all,
           count(distinct p.knumber) filter (where p.decision_date > w.since) as clearances_recent,
           max(p.decision_date) as latest
    from pc_portfolio_510k p join fam f on f.vendor_id = p.vendor_id cross join win w group by p.product_code),
  cats as (
    select d.family_id, d.role, d.product_code, d.plain_name, m.clearances_all, m.clearances_recent, m.latest
    from pc_procedure_devices d join mine m on m.product_code = d.product_code),
  fams as (
    select pr.family_id, pr.name, pr.sort_order, pr.flagship, pr.data_year,
           (select count(*) from pc_procedure_devices d where d.family_id = pr.family_id) as categories_total,
           count(c.product_code) as categories_with_clearances,
           count(c.product_code) filter (where c.clearances_recent > 0) as categories_recent,
           sum(c.clearances_recent) as clearances_recent, max(c.latest) as latest,
           jsonb_agg(jsonb_build_object('role', c.role, 'product_code', c.product_code, 'plain_name', c.plain_name,
                                        'clearances_all', c.clearances_all, 'clearances_recent', c.clearances_recent,
                                        'latest', c.latest)
                     order by c.clearances_recent desc, c.clearances_all desc, c.product_code) as categories
    from pc_procedures pr join cats c on c.family_id = pr.family_id
    group by pr.family_id, pr.name, pr.sort_order, pr.flagship, pr.data_year)
  select jsonb_build_object(
    'vendor_id', v, 'mode', pc_mode(m),
    'window', (select jsonb_build_object('from', w.since::date, 'to', (w.since + interval '5 years')::date) from win w),
    'procedures', coalesce((select jsonb_agg(jsonb_build_object(
        'family_id', f.family_id, 'name', f.name, 'flagship', f.flagship = 'yes', 'data_year', f.data_year,
        'categories_total', f.categories_total, 'categories_with_clearances', f.categories_with_clearances,
        'categories_recent', f.categories_recent, 'clearances_recent', f.clearances_recent, 'latest', f.latest,
        'categories', f.categories)
      order by f.clearances_recent desc, f.categories_with_clearances desc, f.sort_order) from fams f), '[]'::jsonb),
    'procedures_total', (select count(*) from pc_procedures))
$$;

grant execute on function pc_procedure_notes(), pc_procedure_worksheet(text), pc_code_vendors(text, int), pc_procedure_list(), pc_procedure_asc_summary(text),
  pc_procedure(text, int), pc_code_procedures(text), pc_device_procedures(text), pc_vendor_procedures(text, text)
  to anon, authenticated;
notify pgrst, 'reload schema';

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
