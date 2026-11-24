-- 16_directory.sql: category directories (Phase 7). Every orthopedic 510(k), De Novo, PMA and HDE in the database,
-- grouped by FDA product code and by the reviewed segment in the product code dictionary.
-- Reads existing tables only (pc_product_codes, pc_portfolio_510k, pc_vendors, pc_procedure_devices, pc_procedures).
-- Safe to run again. Run it after 05 (it uses pc_short_name and pc_data_end from 05).
--
-- What a directory is: a complete list of FDA records, the same for everyone. It lists identity facts only (number,
-- name, filer, today's owner, decision date, GUDID brand and listing counts). It does not rank products, judge
-- compatibility or show current availability. Recalls and adverse events stay on each product page, because those
-- links are partial (many reports and recalls leave the FDA number blank) and a sortable count would read as a score.

-- FDA's device class codes as words: 1, 2 and 3 stay numbers; f is a humanitarian (HDE) device type, U unclassified,
-- N not classified. Pages show "Class <n>" only for 1 to 3.
create or replace function pc_class_label(c text) returns text language sql immutable as $$
  select case upper(coalesce(c, '')) when '1' then '1' when '2' then '2' when '3' then '3' when 'F' then 'HDE'
              when 'U' then 'Unclassified' when 'N' then 'Not classified' when '' then 'NOT FOUND' else c end
$$;

-- One row per product: the base the two functions below share.
create or replace function pc_directory_rows(code text)
returns table (number text, pathway text, product text, device_name text, filer text, owner_id text, owner_name text,
               decision_date date, gudid_brand text, gudid_devices int, gudid_in_distribution int)
language sql stable as $$
  select p.knumber,
         case when p.knumber like 'DEN%' then 'De Novo' when p.knumber ~ '^H\d' then 'HDE'
              when p.knumber ~ '^(P|N)\d' then 'PMA' else '510(k)' end,
         coalesce(pc_short_name(p.device_name), p.device_name),
         p.device_name,
         coalesce(pc_co(p.applicant), p.applicant),
         o.vendor_id, o.display_name,
         p.decision_date, nullif(p.gudid_brand, ''), p.gudid_devices, p.gudid_in_distribution
    from pc_portfolio_510k p
    left join pc_vendors v on v.vendor_id = p.vendor_id
    left join pc_vendors o on o.vendor_id = coalesce(nullif(v.rolls_up_to, ''), v.vendor_id)
   where p.product_code = upper(trim(code))
$$;

-- The directory home: every segment and product code with its counts.
create or replace function pc_directory_index()
returns jsonb language sql stable as $$
  with e as (select pc_data_end() as d),
  a as (
    select p.product_code, p.knumber, p.decision_date, p.gudid_in_distribution,
           coalesce(nullif(v.rolls_up_to, ''), v.vendor_id) as owner_id
      from pc_portfolio_510k p left join pc_vendors v on v.vendor_id = p.vendor_id
  ),
  r as (select a.* from a where a.product_code is not null and a.product_code <> ''),
  seg as (
    select coalesce(x.segment, 'Not assigned') as segment, count(distinct r.owner_id) as companies
      from r join pc_product_codes x on x.product_code = r.product_code group by 1
  ),
  c as (
    select pc.product_code, pc.plain_name, pc.fda_name, pc_class_label(pc.device_class) as device_class, coalesce(pc.segment, 'Not assigned') as segment,
           pc.anatomy, pc.kind,
           count(r.knumber) as products,
           count(r.knumber) filter (where r.knumber ~ '^(P|H|N)\d') as approvals,
           count(distinct r.owner_id) as companies,
           count(distinct r.owner_id) filter (where r.decision_date > (select d from e) - interval '5 years') as companies_last5,
           count(r.knumber) filter (where r.gudid_in_distribution > 0) as listed_in_distribution,
           max(r.decision_date) as latest,
           (select jsonb_agg(distinct jsonb_build_object('family_id', d.family_id, 'name', f.name))
              from pc_procedure_devices d join pc_procedures f on f.family_id = d.family_id
             where d.product_code = pc.product_code) as procedures
      from pc_product_codes pc left join r on r.product_code = pc.product_code
     group by pc.product_code, pc.plain_name, pc.fda_name, pc.device_class, pc.segment, pc.anatomy, pc.kind
    having count(r.knumber) > 0
  )
  select jsonb_build_object(
    'segments', (select jsonb_agg(s order by s->>'segment') from (
        select jsonb_build_object(
                 'segment', segment,
                 'product_codes', count(*),
                 'products', sum(products),
                 'companies', (select seg.companies from seg where seg.segment = c.segment),
                 'codes', jsonb_agg(jsonb_build_object(
                     'product_code', product_code, 'plain_name', plain_name, 'fda_name', fda_name,
                     'device_class', device_class, 'anatomy', anatomy, 'kind', kind,
                     'products', products, 'approvals', approvals, 'companies', companies,
                     'companies_last5', companies_last5, 'listed_in_distribution', listed_in_distribution,
                     'latest', latest, 'procedures', coalesce(procedures, '[]'::jsonb))
                   order by products desc, product_code)) as s
          from c group by segment) t),
    'totals', jsonb_build_object('products', (select count(*) from r), 'product_codes', (select count(*) from c),
                                 'companies', (select count(distinct owner_id) from r), 'data_end', (select d from e),
                                 'no_product_code', (select count(*) from a where coalesce(a.product_code, '') = '')),
    'note', 'Every orthopedic 510(k), De Novo, PMA and HDE in OrthoParity that has an FDA product code, grouped by that '
            'code. Segments come '
            'from the OrthoParity product code dictionary (every code reviewed). Companies are counted by today''s '
            'parent company. A listing is an FDA record; it does not show that a product is sold today, that parts '
            'fit together or that one product is better than another.',
    'source', 'FDA 510(k), De Novo, PMA and HDE databases; FDA GUDID; OrthoParity product code dictionary and vendor registry.'
  )
$$;

-- One product code: its dictionary entry, its companies and every product under it.
create or replace function pc_directory(code text)
returns jsonb language sql stable as $$
  with e as (select pc_data_end() as d),
  pc as (select * from pc_product_codes where product_code = upper(trim(code))),
  r as (select * from pc_directory_rows(code)),
  co as (
    select owner_id, max(owner_name) as owner_name, count(*) as products,
           count(*) filter (where decision_date > (select d from e) - interval '5 years') as last5,
           count(*) filter (where gudid_in_distribution > 0) as listed_in_distribution,
           min(decision_date) as first, max(decision_date) as latest
      from r group by owner_id
  )
  select case when not exists (select 1 from pc) then jsonb_build_object('found', false, 'product_code', upper(trim(code)),
      'note', 'NOT FOUND: ' || upper(trim(code)) || ' is not an orthopedic product code in OrthoParity.')
  else jsonb_build_object(
    'found', true,
    'product_code', (select to_jsonb(pc) - 'reviewed' - 'clearances' || jsonb_build_object('device_class', pc_class_label(pc.device_class),
                                                                                        'device_class_code', pc.device_class) from pc),
    'procedures', coalesce((select jsonb_agg(distinct jsonb_build_object('family_id', d.family_id, 'name', f.name, 'role', d.role))
                              from pc_procedure_devices d join pc_procedures f on f.family_id = d.family_id
                             where d.product_code = upper(trim(code))), '[]'::jsonb),
    'totals', jsonb_build_object(
        'products', (select count(*) from r),
        'clearances', (select count(*) from r where pathway in ('510(k)', 'De Novo')),
        'approvals', (select count(*) from r where pathway in ('PMA', 'HDE')),
        'companies', (select count(*) from co),
        'companies_last5', (select count(*) from co where last5 > 0),
        'listed_in_distribution', (select count(*) from r where gudid_in_distribution > 0),
        'no_gudid', (select count(*) from r where coalesce(gudid_devices, 0) = 0),
        'first', (select min(decision_date) from r), 'latest', (select max(decision_date) from r),
        'data_end', (select d from e)),
    'companies', coalesce((select jsonb_agg(to_jsonb(co) order by products desc, owner_name) from co), '[]'::jsonb),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'number', number, 'pathway', pathway, 'product', product, 'device_name', device_name, 'filer', filer,
        'owner_id', owner_id, 'owner_name', owner_name,
        'decision_date', decision_date, 'gudid_brand', gudid_brand, 'gudid_devices', coalesce(gudid_devices, 0),
        'gudid_in_distribution', coalesce(gudid_in_distribution, 0))
        order by decision_date desc nulls last, number) from r), '[]'::jsonb),
    'notes', jsonb_build_array(
        'This list holds every record OrthoParity has under this FDA product code, from FDA''s own databases. '
        'It is complete for that code; products filed under other codes (for example a component cleared on its own) '
        'appear under those codes.',
        'Filer is the company named on the FDA record. Owner is today''s parent company, from SEC filings, company '
        'releases or trade press.',
        'GUDID brand and listing counts are what companies report to FDA''s device identifier database. "Listed in '
        'distribution" means at least one GUDID entry for that FDA number is not marked as out of commercial '
        'distribution. It does not show that a product is sold today, and older products often have no GUDID entry.',
        'Recalls, adverse event reports, payments and Medicare data are on each product''s page.',
        'A listing is a regulatory fact. It does not rank products, show that parts fit together or suit a patient.'),
    'source', 'FDA 510(k), De Novo, PMA and HDE databases; FDA GUDID; OrthoParity product code dictionary and vendor registry.'
  ) end
$$;

grant execute on function pc_class_label(text), pc_directory_rows(text), pc_directory_index(), pc_directory(text) to anon, authenticated;
