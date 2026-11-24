-- 19_trials.sql: registered clinical trials from ClinicalTrials.gov (Phase 7).
-- Tables are filled from outputs/site_data/pc_trial.csv, pc_trial_device.csv and pc_trial_vendor.csv
-- (python orthoparity.py fetch-trials). Safe to run again. Run before 05: the industry studies boxes call
-- pc_device_trials and pc_vendor_trials when they exist.
--
-- Links are exact. A trial is linked to a device only when the registry record writes the device's FDA number, or when
-- an Open Payments research record names both the 510(k) and the trial. A trial is linked to a company only through
-- its lead sponsor's name, and company counts cover trials whose conditions fall under musculoskeletal MeSH terms.
-- A registered trial is a fact about a study's design and status, not evidence that a device works or doesn't.

create table if not exists pc_trial (
  nct text primary key, title text, status text, study_type text, phase text, sponsor text, sponsor_class text,
  start_date text, primary_completion text, completion_date text, has_results boolean, enrollment int,
  primary_outcome text, primary_timeframe text, allocation text, purpose text, conditions text, devices text,
  musculoskeletal boolean, last_update text, url text);
create table if not exists pc_trial_device (nct text not null, number text not null, basis text, context text);
create table if not exists pc_trial_vendor (nct text not null, vendor_id text, owner_id text, sponsor text, basis text);
create index if not exists pc_trial_device_n on pc_trial_device (number);
create index if not exists pc_trial_vendor_o on pc_trial_vendor (owner_id);
create index if not exists pc_trial_vendor_v on pc_trial_vendor (vendor_id);

do $$ declare t text; begin
  foreach t in array array['pc_trial', 'pc_trial_device', 'pc_trial_vendor'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (nct is not null)', t);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;

-- the trial fields the site shows, as JSON
create or replace function pc_trial_json(t pc_trial) returns jsonb language sql immutable as $$
  select jsonb_build_object('nct', t.nct, 'title', t.title, 'status', t.status, 'study_type', t.study_type,
    'phase', nullif(t.phase, ''), 'sponsor', t.sponsor, 'start_date', nullif(t.start_date, ''),
    'primary_completion', nullif(t.primary_completion, ''), 'has_results', t.has_results, 'enrollment', t.enrollment,
    'primary_outcome', nullif(t.primary_outcome, ''), 'primary_timeframe', nullif(t.primary_timeframe, ''),
    'allocation', nullif(t.allocation, ''), 'devices', nullif(t.devices, ''), 'conditions', nullif(t.conditions, ''),
    'last_update', nullif(t.last_update, ''), 'url', t.url)
$$;

create or replace function pc_trial_notes() returns jsonb language sql stable as $$
  select jsonb_build_array(
    'Registered trials come from ClinicalTrials.gov, every study with a device intervention. A trial is linked to a '
      || 'product only when its registry record writes the product''s FDA number, or when an Open Payments research record '
      || 'names both. Most registry records name no FDA number, so a product with no linked trial may still have been studied.',
    'Company counts use the trial''s lead sponsor and include companies it has since acquired. They cover trials whose '
      || 'conditions fall under musculoskeletal diseases, bone fractures or limb injuries (MeSH), so a diversified company''s '
      || 'other trials stay out. Investigator-led trials that use a company''s device are not counted.',
    '"Results posted" means the sponsor posted summary results on ClinicalTrials.gov. Published papers are not included.',
    'A registered trial describes a study''s design and status. It is not evidence that a device works or doesn''t.')
$$;

-- one product: trials whose record names its FDA number
create or replace function pc_device_trials(k text) returns jsonb language sql stable as $$
  with n as (select upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g')) as v),
  l as (select d.nct, string_agg(distinct d.basis, '; ') as basis, max(nullif(d.context, '')) as context
          from pc_trial_device d where d.number = (select v from n) group by d.nct)
  select jsonb_build_object(
    'number', (select v from n),
    'total', (select count(*) from l),
    'with_results', (select count(*) from l join pc_trial t using (nct) where t.has_results),
    'active', (select count(*) from l join pc_trial t using (nct)
                where t.status in ('Recruiting', 'Not yet recruiting', 'Active, not recruiting', 'Enrolling by invitation')),
    'trials', coalesce((select jsonb_agg(pc_trial_json(t) || jsonb_build_object('basis', l.basis, 'context', l.context)
                                         order by t.start_date desc nulls last, t.nct)
                          from l join pc_trial t using (nct)), '[]'::jsonb),
    'notes', pc_trial_notes(),
    'source', 'ClinicalTrials.gov (U.S. National Library of Medicine), device-intervention studies; CMS Open Payments research records.')
$$;

-- one company (today's parent): musculoskeletal device trials it or a company it acquired leads
create or replace function pc_vendor_trials(v text, lim int default 200) returns jsonb language sql stable as $$
  with o as (select coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) as id from pc_vendors x where x.vendor_id = v),
  l as (select distinct on (tv.nct) tv.nct, tv.sponsor, tv.vendor_id from pc_trial_vendor tv
         where tv.owner_id = (select id from o) order by tv.nct, tv.vendor_id),
  t as (select pc.*, l.vendor_id as sponsor_vendor from l join pc_trial pc using (nct))
  select jsonb_build_object(
    'vendor_id', (select id from o),
    'total', (select count(*) from t),
    'with_results', (select count(*) from t where has_results),
    'active', (select count(*) from t where status in ('Recruiting', 'Not yet recruiting', 'Active, not recruiting', 'Enrolling by invitation')),
    'completed', (select count(*) from t where status = 'Completed'),
    'completed_with_results', (select count(*) from t where status = 'Completed' and has_results),
    'stopped', (select count(*) from t where status in ('Terminated', 'Withdrawn', 'Suspended')),
    'started_last5', (select count(*) from t where left(start_date, 4) ~ '^\d{4}$'
                        and left(start_date, 4)::int >= extract(year from current_date)::int - 5),
    'by_status', coalesce((select jsonb_agg(jsonb_build_object('status', status, 'n', n) order by n desc, status)
                             from (select status, count(*) n from t group by status) s), '[]'::jsonb),
    'sponsors', coalesce((select jsonb_agg(jsonb_build_object('sponsor', sponsor, 'vendor_id', sponsor_vendor, 'n', n) order by n desc, sponsor)
                            from (select sponsor, sponsor_vendor, count(*) n from t group by sponsor, sponsor_vendor) s), '[]'::jsonb),
    'trials', coalesce((select jsonb_agg(pc_trial_json(p) || jsonb_build_object('sponsor_vendor', x.sponsor_vendor)
                                         order by p.start_date desc nulls last, p.nct)
                          from (select nct, sponsor_vendor from t order by start_date desc nulls last, nct
                                 limit greatest(1, least(coalesce(lim, 200), 1000))) x
                          join pc_trial p using (nct)), '[]'::jsonb),
    'notes', pc_trial_notes(),
    'source', 'ClinicalTrials.gov (U.S. National Library of Medicine), device-intervention studies with musculoskeletal conditions.')
$$;

-- one trial by NCT number (Packet check). Only trials OrthoParity stores; the site checks ClinicalTrials.gov live for others.
create or replace function pc_trial_lookup(nct text) returns jsonb language sql stable as $$
  with n as (select upper(regexp_replace(coalesce(nct, ''), '[^0-9A-Za-z]', '', 'g')) as v)
  select case when (select v from n) !~ '^NCT\d{8}$'
              then jsonb_build_object('found', false, 'note', 'An NCT number is NCT followed by 8 digits, for example NCT04821154.')
              when not exists (select 1 from pc_trial where pc_trial.nct = (select v from n))
              then jsonb_build_object('found', false, 'stored', false, 'nct', (select v from n),
                     'note', 'Not among the trials OrthoParity stores (orthopedic device trials and trials linked to an orthopedic product).')
              else (select pc_trial_json(t) || jsonb_build_object('found', true, 'stored', true,
                       'products', coalesce((select jsonb_agg(jsonb_build_object('number', d.number, 'basis', d.basis)) from pc_trial_device d where d.nct = t.nct), '[]'::jsonb),
                       'companies', coalesce((select jsonb_agg(distinct jsonb_build_object('vendor_id', tv.owner_id, 'name', x.display_name))
                                                from pc_trial_vendor tv join pc_vendors x on x.vendor_id = tv.owner_id where tv.nct = t.nct), '[]'::jsonb))
                    from pc_trial t where t.nct = (select v from n)) end
$$;

grant execute on function pc_trial_json(pc_trial), pc_trial_notes(), pc_device_trials(text), pc_vendor_trials(text, int),
  pc_trial_lookup(text) to anon, authenticated;
