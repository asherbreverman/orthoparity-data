-- OrthoParity database: FDA adverse event reports (MAUDE) for products and companies
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.
--
-- Counts come from pipeline/fetch_maude.py. A report counts toward a 510(k) only when it names that 510(k)
-- number, so counts are a floor. A report is a fact about a filing, not proof that the device caused the event.
-- Counts are not rates: FDA publishes no count of devices in use.

create or replace function pc_maude_notes() returns jsonb language sql immutable as $$
  select jsonb_build_array(
    'A MAUDE report records what a manufacturer, hospital, clinician or patient told FDA. It is not proof that the device caused the event.',
    'Counts are not rates. FDA publishes no count of devices implanted, so a widely used product will have more reports.',
    'A report counts only when it names the 510(k) number. Reports with a missing or wrong number are not matched, so these counts are a floor. About half of the reports filed under orthopedic product codes name a matching 510(k).',
    'Manufacturers must report deaths, serious injuries and malfunctions they learn of. Reporting practices differ by company, and lawsuits or recalls can bring a wave of reports.',
    'Most orthopedic injury reports describe a revision surgery or another operation.')
$$;

-- one product: its own reports, by type and year, with its product code for context
create or replace function pc_device_maude(k text)
returns jsonb language plpgsql stable as $$
declare
  kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'));
  m pc_maude_product%rowtype; code text; ctx jsonb; asof date;
begin
  select * into m from pc_maude_product where knumber = kn;
  select product_code into code from pc_devices where knumber = kn;
  select max(data_through) into asof from pc_maude_product;
  select jsonb_build_object('product_code', code,
           'clearances', (select count(*) from pc_devices d where d.product_code = code and d.in_starting_set),
           'with_reports', count(*),
           'reports_last5', coalesce(sum(p.reports_last5), 0),
           'median_last5_with_reports', percentile_cont(0.5) within group (order by p.reports_last5)
                                          filter (where p.reports_last5 > 0))
    into ctx from pc_maude_product p join pc_devices d on d.knumber = p.knumber where d.product_code = code;
  return jsonb_build_object(
    'knumber', kn, 'has_reports', coalesce(m.reports, 0) > 0,
    'reports', coalesce(m.reports, 0), 'deaths', coalesce(m.deaths, 0), 'injuries', coalesce(m.injuries, 0),
    'malfunctions', coalesce(m.malfunctions, 0), 'other', coalesce(m.other, 0),
    'last5', jsonb_build_object('reports', coalesce(m.reports_last5, 0), 'deaths', coalesce(m.deaths_last5, 0),
                                'injuries', coalesce(m.injuries_last5, 0), 'malfunctions', coalesce(m.malfunctions_last5, 0),
                                'other', coalesce(m.other_last5, 0), 'since', m.window_start),
    'first_year', m.first_year, 'last_year', m.last_year,
    'by_year', (select coalesce(jsonb_agg(jsonb_build_object('year', y.year, 'reports', y.reports) order by y.year), '[]'::jsonb)
                from pc_maude_year y where y.knumber = kn),
    'category', ctx, 'data_through', asof,
    'source', 'FDA MAUDE adverse event reports via openFDA, matched on the 510(k) number each report names',
    'maude_url', 'https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/search.cfm',
    'tplc_url', case when code is not null then 'https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfTPLC/tplc.cfm?id=' || code end,
    'notes', pc_maude_notes());
end $$;

-- one company: every 510(k) in its family (parent company and everything it owns, with product-line sales
-- following the buyer), the same family the portfolio and recalls use
create or replace function pc_vendor_maude(v text, m text default 'pit', lim int default 10)
returns jsonb language sql stable as $$
  with fam as (
    select p.knumber, p.device_name, p.product_code from pc_portfolio_510k p
    where p.vendor_id in (select f.vendor_id from pc_vendor_family(v, pc_mode(m)) f where pc_mode(m) = 'current' or f.vendor_id = v)),
  hit as (select f.knumber, f.device_name, f.product_code, q.reports, q.deaths, q.injuries, q.malfunctions, q.other,
                 q.reports_last5, q.deaths_last5, q.injuries_last5, q.malfunctions_last5, q.other_last5
          from fam f join pc_maude_product q on q.knumber = f.knumber),
  tot as (
    select count(*) filter (where reports > 0) with_reports,
           coalesce(sum(reports), 0) reports, coalesce(sum(deaths), 0) deaths, coalesce(sum(injuries), 0) injuries,
           coalesce(sum(malfunctions), 0) malfunctions, coalesce(sum(other), 0) other,
           coalesce(sum(reports_last5), 0) r5, coalesce(sum(deaths_last5), 0) d5, coalesce(sum(injuries_last5), 0) i5,
           coalesce(sum(malfunctions_last5), 0) m5, coalesce(sum(other_last5), 0) o5
    from hit),
  asof as (select max(data_through) data_through, max(window_start) since from pc_maude_product)
  select jsonb_build_object(
    'vendor_id', v, 'products', (select count(*) from fam), 'products_with_reports', t.with_reports,
    'reports', t.reports, 'deaths', t.deaths, 'injuries', t.injuries, 'malfunctions', t.malfunctions, 'other', t.other,
    'last5', jsonb_build_object('reports', t.r5, 'deaths', t.d5, 'injuries', t.i5, 'malfunctions', t.m5, 'other', t.o5,
                                'since', a.since),
    'by_year', (select coalesce(jsonb_agg(jsonb_build_object('year', s.year, 'reports', s.n) order by s.year), '[]'::jsonb) from (
                  select y.year, sum(y.reports) n from fam f join pc_maude_year y on y.knumber = f.knumber
                  group by y.year) s),
    'top_products', (select coalesce(jsonb_agg(to_jsonb(x) order by x.reports_last5 desc, x.reports desc), '[]'::jsonb) from (
                  select h.knumber, h.device_name, h.product_code, h.reports, h.reports_last5, h.deaths_last5,
                         h.injuries_last5, h.malfunctions_last5
                  from hit h where h.reports > 0 order by h.reports_last5 desc, h.reports desc limit lim) x),
    'data_through', a.data_through,
    'source', 'FDA MAUDE adverse event reports via openFDA, matched on the 510(k) number each report names',
    'maude_url', 'https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/search.cfm',
    'notes', pc_maude_notes())
  from tot t, asof a
$$;

grant execute on function pc_maude_notes(), pc_device_maude(text), pc_vendor_maude(text, text, int) to anon, authenticated;
