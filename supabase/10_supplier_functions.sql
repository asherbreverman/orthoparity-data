-- OrthoParity: supplier record for the company page (manufacturing sites, FDA inspections, warning letters,
-- recalls and adverse event reports in one place). Read-only. Run after 09_maude_functions.sql.
--
-- Facts only. Nothing here scores or grades a company. A site, an inspection result or a warning letter is a
-- public FDA record; the page shows what it says and links to the source.

-- Page cache (Phase 4). The heavy page functions below keep a copy of each answer in pc_cache, so a repeat visit
-- reads one row instead of recomputing. Every SQL file in this folder empties the cache when it finishes, and so
-- does 07_after_import.sql, so the cache never outlives the data or the rules that made it. It holds at most 8,000 answers (about
-- 100 MB) to stay well inside the Supabase Free plan's 500 MB; past that, pages still work, just uncached.
create table if not exists pc_cache (
  fn text not null, arg text not null, payload jsonb not null, made timestamptz not null default now(),
  primary key (fn, arg));
alter table pc_cache enable row level security;
revoke all on pc_cache from anon, authenticated;

create or replace function pc_supplier_notes() returns jsonb language sql immutable as $$
  select jsonb_build_array(
    'Sites come from FDA establishment registration and listing, current registrations only. A site counts when it lists at least one of the company''s 510(k)s.',
    'Company sites are registered to an owner/operator whose name matches this company or a company it owns. Partner sites belong to other firms (contract manufacturers, sterilizers, importers, relabelers, specification developers) that list this company''s products.',
    'Inspection results and warning letters come from the FDA Data Dashboard, device inspections only, fiscal year 2009 on. State inspections, pre-approval inspections and inspections waiting for a final action are not included.',
    'An inspection classification describes what FDA found at one site on one visit: NAI (no action indicated), VAI (voluntary action indicated) or OAI (official action indicated). It is not a rating of products.',
    'Partner site results describe the partner firm''s own site. They are shown because the site handles this company''s products, not because the company was inspected there.',
    'Sites of other device companies that list some of this company''s 510(k)s are counted separately. This usually means a product line changed hands; those sites are not treated as this company''s sites or partners.'
  );
$$;

create or replace function pc_vendor_supplier_live(v text, m text default 'current') returns jsonb
language sql stable as $$
  with fam as (
    select p.knumber from pc_portfolio_510k p
    where p.vendor_id in (select f.vendor_id from pc_vendor_family(v, pc_mode(m)) f)),
  me as (select coalesce(pc_vendor_parent(v), v) as parent),
  lk as (
    select l.fei_number, l.knumber, l.activities, l.makes_device
    from pc_establishment_510k l join fam using (knumber)),
  asof as (select max(end_date) d_insp from pc_inspection),
  win as (select (coalesce((select d_insp from asof), current_date) - interval '5 years')::date since),
  insp as (  -- one row per inspection: the most serious classification across its device project areas
    select i.fei_number, i.inspection_id, max(i.end_date) end_date,
           case max(case when i.classification like '%(OAI)%' then 3 when i.classification like '%(VAI)%' then 2 else 1 end)
             when 3 then 'OAI' when 2 then 'VAI' else 'NAI' end cls
    from pc_inspection i where i.product_type = 'Devices' and i.fei_number in (select fei_number from lk)
    group by 1, 2),
  wl as (
    select a.* from pc_compliance_action a
    where a.product_type = 'Devices' and a.fei_number in (select fei_number from lk)),
  site as (
    select e.fei_number, e.name, e.city, e.state, e.country, e.owner_operator_name,
           coalesce(e.company_vendor_id = (select parent from me), false) own,
           (coalesce(e.company_vendor_id, '') not in ('', (select parent from me))) other_co, e.company_vendor_id,
           string_agg(distinct a.act, '; ' order by a.act) activities,
           bool_or(lk.makes_device) makes, count(distinct lk.knumber) products
    from lk join pc_establishment e using (fei_number)
    left join lateral unnest(string_to_array(lk.activities, '; ')) a(act) on true
    group by e.fei_number, e.name, e.city, e.state, e.country, e.owner_operator_name, e.company_vendor_id),
  site_x as (
    select s.*,
      (select jsonb_build_object('date', x.end_date, 'classification', x.cls) from insp x
        where x.fei_number = s.fei_number order by x.end_date desc limit 1) last_inspection,
      (select count(*) from insp x where x.fei_number = s.fei_number and x.end_date >= (select since from win)) insp5,
      (select count(*) from insp x where x.fei_number = s.fei_number and x.end_date >= (select since from win) and x.cls = 'OAI') oai5,
      (select count(distinct w.case_id) from wl w where w.fei_number = s.fei_number and w.action_type = 'Warning Letter'
        and w.action_date >= (select since from win)) wl5
    from site s),
  tot as (
    select
      count(*) filter (where own) company_sites,
      count(*) filter (where own and makes) company_making,
      count(*) filter (where not own and not other_co) partner_sites,
      count(*) filter (where not own and not other_co and makes) partner_making,
      count(*) filter (where other_co) other_company_sites,
      count(distinct country) filter (where own) company_countries
    from site),
  insp_own as (select x.* from insp x join site s using (fei_number) where s.own and x.end_date >= (select since from win)),
  insp_own_all as (select x.* from insp x join site s using (fei_number) where s.own),
  insp_partner as (select x.* from insp x join site s using (fei_number) where not s.own and not s.other_co and x.end_date >= (select since from win)),
  wl_own as (select w.*, s.name site, s.city, s.country from wl w join site s using (fei_number) where s.own),
  wl_partner as (select w.*, s.name site, s.city, s.country from wl w join site s using (fei_number) where not s.own and not s.other_co),
  cit as (
    select c.cfr, max(c.short_description) short_description, count(distinct c.inspection_id) n
    from pc_inspection_citation c join insp_own x using (inspection_id) where c.program_area = 'Devices' group by c.cfr
    order by n desc, c.cfr limit 8),
  recall as (select pc_recall_card_vendor(v, m) r),
  maude as (select pc_vendor_maude(v, m, 1) j)
  select jsonb_build_object(
    'vendor_id', v,
    'since', (select since from win),
    'inspections_through', (select d_insp from asof),
    'sites', (select to_jsonb(tot) from tot),
    'countries', coalesce((select jsonb_agg(jsonb_build_object('country', country, 'sites', n) order by n desc, country)
                  from (select country, count(*) n from site where own group by country) c), '[]'::jsonb),
    'inspections_last5', (select jsonb_build_object('inspections', count(*), 'nai', count(*) filter (where cls = 'NAI'),
                            'vai', count(*) filter (where cls = 'VAI'), 'oai', count(*) filter (where cls = 'OAI'),
                            'sites_inspected', count(distinct fei_number)) from insp_own),
    'inspections_all', (select jsonb_build_object('inspections', count(*), 'nai', count(*) filter (where cls = 'NAI'),
                            'vai', count(*) filter (where cls = 'VAI'), 'oai', count(*) filter (where cls = 'OAI'),
                            'first', min(end_date), 'latest', max(end_date)) from insp_own_all),
    'partner_inspections_last5', (select jsonb_build_object('inspections', count(*), 'oai', count(*) filter (where cls = 'OAI'))
                            from insp_partner),
    'warning_letters', jsonb_build_object(
       'company_last5', (select count(distinct case_id) from wl_own where action_type = 'Warning Letter' and action_date >= (select since from win)),
       'company_all', (select count(distinct case_id) from wl_own where action_type = 'Warning Letter'),
       'partner_last5', (select count(distinct case_id) from wl_partner where action_type = 'Warning Letter' and action_date >= (select since from win)),
       'company_rows', coalesce((select jsonb_agg(jsonb_build_object('date', action_date, 'type', action_type, 'site', site,
                          'city', city, 'country', country, 'case_id', case_id) order by action_date desc)
                          from (select distinct action_date, action_type, site, city, country, case_id from wl_own) z), '[]'::jsonb)),
    'top_citations', coalesce((select jsonb_agg(to_jsonb(cit)) from cit), '[]'::jsonb),
    'company_sites', coalesce((select jsonb_agg(jsonb_build_object('fei', fei_number, 'name', name, 'city', city, 'state', state,
                       'country', country, 'activities', activities, 'makes', makes, 'products', products,
                       'last_inspection', last_inspection, 'inspections_last5', insp5, 'oai_last5', oai5,
                       'warning_letters_last5', wl5) order by products desc, name)
                       from site_x where own), '[]'::jsonb),
    'partner_sites', coalesce((select jsonb_agg(jsonb_build_object('fei', fei_number, 'name', name, 'owner', owner_operator_name,
                       'city', city, 'state', state, 'country', country, 'activities', activities, 'makes', makes,
                       'products', products, 'last_inspection', last_inspection, 'inspections_last5', insp5,
                       'oai_last5', oai5, 'warning_letters_last5', wl5) order by products desc, name)
                       from (select * from site_x where not own and not other_co order by products desc, name limit 40) p), '[]'::jsonb),
    'other_company_sites', coalesce((select jsonb_agg(jsonb_build_object('company', coalesce(x.display_name, o.company_vendor_id),
                       'vendor_id', o.company_vendor_id, 'sites', o.n, 'products', o.products) order by o.products desc)
                       from (select company_vendor_id, count(*) n, sum(products) products from site where other_co group by 1) o
                       left join pc_vendors x on x.vendor_id = o.company_vendor_id), '[]'::jsonb),
    'recalls', (select jsonb_build_object('figs', r->'figs', 'badge', r->'badge') from recall),
    'maude_last5', (select j->'last5' from maude),
    'sources', jsonb_build_object(
       'sites', 'https://open.fda.gov/apis/device/registrationlisting/',
       'inspections', 'https://datadashboard.fda.gov/oii/cd/inspections.htm',
       'compliance', 'https://datadashboard.fda.gov/oii/cd/complianceactions.htm',
       'warning_letters', 'https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters'),
    'notes', pc_supplier_notes());
$$;

grant execute on function pc_supplier_notes() to anon, authenticated;
grant execute on function pc_vendor_supplier_live(text, text) to anon, authenticated;

-- Product page: the registered sites that list this 510(k), with their device inspections and warning letters.
create or replace function pc_device_supplier(k text) returns jsonb language sql stable as $$
  with me as (
    select coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) parent
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id where p.knumber = k),
  asof as (select max(end_date) d from pc_inspection),
  win as (select (coalesce((select d from asof), current_date) - interval '5 years')::date since),
  lk as (select * from pc_establishment_510k where knumber = k),
  insp as (
    select i.fei_number, i.inspection_id, max(i.end_date) end_date,
           case max(case when i.classification like '%(OAI)%' then 3 when i.classification like '%(VAI)%' then 2 else 1 end)
             when 3 then 'OAI' when 2 then 'VAI' else 'NAI' end cls
    from pc_inspection i where i.product_type = 'Devices' and i.fei_number in (select fei_number from lk)
    group by 1, 2),
  site as (
    select e.fei_number, e.name, e.city, e.state, e.country, e.owner_operator_name, lk.activities, lk.makes_device makes,
           case when e.company_vendor_id = (select parent from me) then 'company'
                when coalesce(e.company_vendor_id, '') = '' then 'partner' else 'other company' end as relation,
           (select jsonb_build_object('date', x.end_date, 'classification', x.cls) from insp x
             where x.fei_number = e.fei_number order by x.end_date desc limit 1) last_inspection,
           (select count(*) from insp x where x.fei_number = e.fei_number and x.end_date >= (select since from win)) insp5,
           (select count(*) from insp x where x.fei_number = e.fei_number and x.end_date >= (select since from win)
              and x.cls = 'OAI') oai5,
           (select count(distinct a.case_id) from pc_compliance_action a where a.fei_number = e.fei_number
              and a.product_type = 'Devices' and a.action_type = 'Warning Letter' and a.action_date >= (select since from win)) wl5
    from lk join pc_establishment e using (fei_number))
  select jsonb_build_object(
    'knumber', k, 'since', (select since from win), 'inspections_through', (select d from asof),
    'sites', (select count(*) from site),
    'making_sites', (select count(*) from site where makes),
    'company_sites', (select count(*) from site where relation = 'company'),
    'partner_sites', (select count(*) from site where relation = 'partner'),
    'other_company_sites', (select count(*) from site where relation = 'other company'),
    'partner_making', coalesce((select jsonb_agg(distinct name) from site where relation = 'partner' and makes), '[]'::jsonb),
    'countries_making', coalesce((select jsonb_agg(distinct country) from site where makes and country <> ''), '[]'::jsonb),
    'inspections_last5', (select coalesce(sum(insp5), 0) from site),
    'oai_last5', (select coalesce(sum(oai5), 0) from site),
    'warning_letters_last5', (select coalesce(sum(wl5), 0) from site),
    'flagged_sites', coalesce((select jsonb_agg(name order by name) from site where oai5 > 0 or wl5 > 0), '[]'::jsonb),
    'rows', coalesce((select jsonb_agg(jsonb_build_object('fei', fei_number, 'name', name, 'city', city, 'state', state,
              'country', country, 'owner', owner_operator_name, 'relation', relation, 'activities', activities,
              'makes', makes, 'last_inspection', last_inspection, 'inspections_last5', insp5, 'oai_last5', oai5,
              'warning_letters_last5', wl5) order by (relation = 'company') desc, makes desc, name) from site), '[]'::jsonb),
    'sources', jsonb_build_object(
       'sites', 'https://open.fda.gov/apis/device/registrationlisting/',
       'inspections', 'https://datadashboard.fda.gov/oii/cd/inspections.htm',
       'compliance', 'https://datadashboard.fda.gov/oii/cd/complianceactions.htm'),
    'notes', pc_supplier_notes());
$$;

grant execute on function pc_device_supplier(text) to anon, authenticated;

-- pc_vendor_supplier: cached front door for pc_vendor_supplier_live (same name and arguments the website already calls).
create or replace function pc_vendor_supplier(v text, m text default 'current')
returns jsonb language plpgsql volatile security definer set search_path = public as $$
declare r jsonb; ck text := coalesce(v, '') || '|' || coalesce(m, 'current');
begin
  select c.payload into r from pc_cache c where c.fn = 'pc_vendor_supplier' and c.arg = ck;
  if found then return r; end if;
  r := pc_vendor_supplier_live(v, m);
  if r is not null and (select count(*) from pc_cache) < 8000 and exists (select 1 from pc_vendors x where x.vendor_id = v) then
    begin
      insert into pc_cache (fn, arg, payload) values ('pc_vendor_supplier', ck, r) on conflict do nothing;
    exception when others then null;  -- read-only call or a race: skip the save, still answer
    end;
  end if;
  return r;
end $$;
revoke execute on function pc_vendor_supplier_live(text, text) from public, anon, authenticated;
grant execute on function pc_vendor_supplier(text, text) to anon, authenticated;

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
