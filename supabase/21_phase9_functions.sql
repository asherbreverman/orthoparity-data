-- 21_phase9_functions.sql: Phase 9 functions. No new tables; everything reads data that is already loaded.
--   pc_search_groups(q)          product search grouped by brand and today's parent company (backlog S16)
--   pc_code_sites(code)          where a product code's devices are made: registered sites by country (S18)
--   pc_vendor_compare_many(ids)  compare 2 to 5 companies by product code and Open Payments totals (S20)
--   pc_cache_warm()              pre-fill the page cache after an update (live review #19, first-load speed)
-- Run after 01 to 20 (it uses pc_co from 05 and pc_vendor_family from 03). Safe to run again.

-- ---------------------------------------------------------------- S16: search grouped by brand and owner
-- Whole-word matches in the FDA device name or the GUDID brand, grouped by today's parent company. The largest group
-- carries the brand name; other companies' groups say whose records they are. Matches inside a longer word (for
-- example "Personalized" for "Persona") form one more group. Records keep the company name exactly as filed with FDA.
create or replace function pc_search_groups(q text, lim int default 50)
returns jsonb language sql stable as $$
  with t as (select trim(regexp_replace(coalesce(q, ''), '\s+', ' ', 'g')) as term),
  rx as (select term, lower(term) as lt,
                '\m' || regexp_replace(regexp_replace(term, '([.*+?^${}()|\[\]\\])', '\\\1', 'g'), ' ', '\s+', 'g') || '\M' as w
           from t where length(regexp_replace(term, '[^A-Za-z0-9]', '', 'g')) >= 3),
  recs as (
    select p.knumber, p.device_name, p.applicant, p.product_code, p.decision_date, p.gudid_brand,
           coalesce(pc_vendor_parent(p.vendor_id), p.vendor_id) as owner_id,
           (coalesce(p.device_name, '') ~* rx.w or coalesce(p.gudid_brand, '') ~* rx.w) as whole
      from pc_portfolio_510k p, rx
     where lower(coalesce(p.device_name, '') || ' ' || coalesce(p.gudid_brand, '')) like '%' || rx.lt || '%'),
  g as (
    select owner_id, count(*) as n, min(decision_date) as first, max(decision_date) as latest,
           row_number() over (order by count(*) desc, owner_id) as rk
      from recs where whole group by owner_id),
  grp as (
    select g.*, v.display_name as owner_name,
           (select b from (select btrim(regexp_replace(r.gudid_brand, '[®™]', '', 'g')) as b, count(*) as c from recs r
                            where r.owner_id = g.owner_id and r.whole and r.gudid_brand ~* (select w from rx)
                            group by 1 order by 2 desc, 1 limit 1) x) as top_brand
      from g left join pc_vendors v on v.vendor_id = g.owner_id)
  select jsonb_build_object(
    'query', q,
    'note', case when not exists (select 1 from rx) then 'Type at least 3 letters or numbers.' end,
    'total', (select count(*) from recs),
    'whole_word', (select count(*) from recs where whole),
    'inside_word', (select count(*) from recs where not whole),
    'groups', coalesce((select jsonb_agg(jsonb_build_object(
        'label', case when grp.rk = 1 then coalesce(grp.top_brand, (select term from rx))
                      else coalesce(grp.owner_name, 'Other') || ' records that name "' || (select term from rx) || '"' end,
        'kind', case when grp.rk = 1 then 'brand' else 'owner' end,
        'owner_id', grp.owner_id, 'owner_name', grp.owner_name, 'records', grp.n,
        'first', grp.first, 'latest', grp.latest,
        'product_codes', (select jsonb_agg(c order by c) from (select distinct r.product_code as c from recs r
                           where r.owner_id = grp.owner_id and r.whole and r.product_code is not null) x),
        'filed_as', (select jsonb_agg(jsonb_build_object('name', nm, 'records', c) order by c desc, nm) from (
                       select pc_co(r.applicant) as nm, count(*) as c from recs r
                        where r.owner_id = grp.owner_id and r.whole group by 1) x),
        'gudid_brands', (select jsonb_agg(b order by c desc, b) from (
                           select r.gudid_brand as b, count(*) as c from recs r
                            where r.owner_id = grp.owner_id and r.whole and coalesce(r.gudid_brand, '') <> ''
                            group by 1 order by 2 desc, 1 limit 10) x),
        'gudid_brand_count', (select count(distinct r.gudid_brand) from recs r
                               where r.owner_id = grp.owner_id and r.whole and coalesce(r.gudid_brand, '') <> ''),
        'items', (select jsonb_agg(jsonb_build_object('number', knumber, 'device_name', device_name,
                     'filer', applicant, 'decision_date', decision_date, 'product_code', product_code)
                     order by decision_date desc nulls last, knumber) from (
                   select * from recs r where r.owner_id = grp.owner_id and r.whole
                    order by r.decision_date desc nulls last, r.knumber limit greatest(coalesce(lim, 50), 1)) x))
        order by grp.rk) from grp), '[]'::jsonb),
    'inside_word_group', case when exists (select 1 from recs where not whole) then jsonb_build_object(
        'label', '"' || (select term from rx) || '" inside another word',
        'records', (select count(*) from recs where not whole),
        'by_owner', (select jsonb_agg(jsonb_build_object('owner_id', owner_id, 'owner_name', owner_name, 'records', c)
                       order by c desc, owner_name) from (
                       select r.owner_id, v.display_name as owner_name, count(*) as c from recs r
                         left join pc_vendors v on v.vendor_id = r.owner_id where not r.whole group by 1, 2) x),
        'items', (select jsonb_agg(jsonb_build_object('number', knumber, 'device_name', device_name,
                     'filer', applicant, 'decision_date', decision_date, 'product_code', product_code)
                     order by decision_date desc nulls last, knumber) from (
                   select * from recs r where not r.whole
                    order by r.decision_date desc nulls last, r.knumber limit greatest(coalesce(lim, 50), 1)) x)) end,
    'notes', jsonb_build_array(
      'Groups use the brand in the FDA device name or GUDID brand and today''s parent company. Records keep the company '
      'name exactly as filed with FDA.',
      'A brand word shared by two companies stays in two groups: the same word on different companies'' records says '
      'nothing about whether the products are related.'),
    'source', 'FDA 510(k), De Novo, PMA and HDE databases; FDA GUDID brand names; OrthoParity vendor registry.')
$$;

-- ---------------------------------------------------------------- S18: where a product code's devices are made
-- Every registered establishment that lists at least one FDA record under the code, counted by country. "Makes"
-- means the site registers to manufacture, contract-manufacture, remanufacture or sterilize that record.
create or replace function pc_code_sites(code text)
returns jsonb language sql stable as $$
  with c as (select upper(trim(code)) as pc),
  recs as (select p.knumber from pc_portfolio_510k p, c where p.product_code = c.pc),
  links as (select l.fei_number, bool_or(l.makes_device) as makes, count(distinct l.knumber) as records
              from pc_establishment_510k l join recs r on r.knumber = l.knumber group by 1),
  s as (select e.fei_number, coalesce(nullif(upper(e.country), ''), '??') as cc, l.makes, l.records
          from links l join pc_establishment e on e.fei_number = l.fei_number),
  by_c as (select cc, count(*) as sites, count(*) filter (where makes) as making, sum(records) as record_links
             from s group by cc)
  select jsonb_build_object(
    'product_code', (select pc from c),
    'records_under_code', (select count(*) from recs),
    'records_with_a_site', (select count(distinct l.knumber) from pc_establishment_510k l join recs r using (knumber)),
    'sites', (select count(*) from s),
    'countries', (select count(*) from by_c where cc <> '??'),
    'making_sites', (select count(*) from s where makes),
    'by_country', coalesce((select jsonb_agg(jsonb_build_object(
        'country_code', case when cc = '??' then null else cc end,
        'country', case when cc = '??' then 'Country NOT FOUND in the registration'
                        else regexp_replace(pc_country(cc), '^the ', '') end,
        'sites', sites, 'making_sites', making) order by sites desc, making desc, cc) from by_c), '[]'::jsonb),
    'notes', jsonb_build_array(
      'FDA establishment registrations, current year only. A registration says a site handles a product; it doesn''t '
      'say how much it makes or whether it supplies the US.',
      '"Make or sterilize" counts sites that register to manufacture, contract-manufacture, remanufacture or sterilize '
      'at least one record under this code. The rest design, relabel, import, distribute or handle complaints.',
      'A site is counted once per country however many records it lists.'),
    'source', 'openFDA device registration and listing (FDA establishment registrations).')
$$;

-- ---------------------------------------------------------------- S20: compare 2 to 5 companies
-- Product codes each company holds FDA records under, how many of the chosen companies share each code, and each
-- company's Open Payments totals for the latest year every one of them has. Counts only: no recipient is named.
create or replace function pc_vendor_compare_many(ids text[], m text default 'pit')
returns jsonb language plpgsql stable as $$
declare
  md text := pc_mode(m);
  vs text[]; k int; latest int; codes jsonb; vendors jsonb; n_all int; n_some int; n_one int; shared_all int;
begin
  select array_agg(x order by o) into vs from (
    select distinct on (x) x, o from unnest(ids) with ordinality as u(x, o)
     where x in (select vendor_id from pc_vendors) order by x, o) d;
  k := coalesce(array_length(vs, 1), 0);
  if k < 2 or coalesce(array_length(ids, 1), 0) > 5 then
    return jsonb_build_object('found', false, 'note',
      case when coalesce(array_length(ids, 1), 0) > 5 then 'Compare up to 5 companies at a time.'
           else 'Pick at least 2 companies OrthoParity has on file.' end);
  end if;

  with fam as (select v as vendor_id, f.vendor_id as member from unnest(vs) v, pc_vendor_family(v, md) f
                where md = 'current' or f.vendor_id = v),
  per as (
    select f.vendor_id, p.product_code, count(*) as n
      from pc_portfolio_510k p join fam f on f.member = p.vendor_id
     where p.product_code is not null group by 1, 2),
  code as (
    select product_code, count(distinct vendor_id) as held_by,
           jsonb_object_agg(vendor_id, n) as counts, sum(n) as total
      from per group by 1)
  select coalesce(jsonb_agg(jsonb_build_object('product_code', c.product_code, 'plain_name', pcn.plain_name,
           'fda_name', pcn.fda_name, 'anatomy', pcn.anatomy, 'kind', pcn.kind, 'held_by', c.held_by, 'counts', c.counts)
           order by c.held_by desc, c.total desc, c.product_code), '[]'::jsonb),
         count(*) filter (where c.held_by = k), count(*) filter (where c.held_by > 1 and c.held_by < k),
         count(*) filter (where c.held_by = 1)
    into codes, n_all, n_some, n_one
    from code c left join pc_product_codes pcn on pcn.product_code = c.product_code;

  select min(y) into latest from (select max(year) as y from pc_op_vendor_profile
                                   where mode = md and year > 0 and vendor_id = any(vs) group by vendor_id) x;
  if (select count(distinct vendor_id) from pc_op_vendor_profile where mode = md and year > 0 and vendor_id = any(vs)) < k then
    latest := null;  -- at least one company has no Open Payments profile, so no year covers all of them
  end if;

  with fam as (select v as vendor_id, f.vendor_id as member from unnest(vs) v, pc_vendor_family(v, md) f
                where md = 'current' or f.vendor_id = v)
  select jsonb_agg(jsonb_build_object(
      'vendor_id', v.vendor_id, 'display_name', v.display_name,
      'product_codes', (select count(distinct p.product_code) from pc_portfolio_510k p join fam f
                          on f.member = p.vendor_id where f.vendor_id = v.vendor_id and p.product_code is not null),
      'records', (select count(*) from pc_portfolio_510k p join fam f on f.member = p.vendor_id
                   where f.vendor_id = v.vendor_id),
      'no_code', (select count(*) from pc_portfolio_510k p join fam f on f.member = p.vendor_id
                   where f.vendor_id = v.vendor_id and p.product_code is null),
      'payments', (select to_jsonb(op) - 'mode' - 'vendor_id' from pc_op_vendor_profile op
                    where op.vendor_id = v.vendor_id and op.mode = md and op.year = latest),
      'payment_mix', (select coalesce(jsonb_agg(jsonb_build_object('nature_group', nature_group, 'amount', s) order by s desc), '[]'::jsonb)
                        from (select nature_group, sum(amount) as s from pc_op_vendor_year
                               where vendor_id = v.vendor_id and mode = md and year = latest group by 1) x))
      order by array_position(vs, v.vendor_id))
    into vendors from pc_vendors v where v.vendor_id = any(vs);

  select count(*) into shared_all from (
    select rkey from pc_op_relationship where mode = md and vendor_id = any(vs)
     group by rkey having count(distinct vendor_id) = k) s;

  return jsonb_build_object(
    'found', true, 'mode', md, 'companies', k, 'vendors', vendors, 'codes', codes,
    'codes_held_by_all', n_all, 'codes_held_by_some', n_some, 'codes_held_by_one', n_one,
    'summary', 'By FDA records, not sales: ' || n_all || ' product code' || case when n_all = 1 then ' is' else 's are' end
               || case when k = 2 then ' held by both, and ' || n_one || ' by one of them only.'
                       else ' held by all ' || k || ', ' || n_some || ' by more than one but not all, and ' || n_one
                            || ' by one company only.' end,
    'payments_year', latest,
    'payments_note', case when latest is null then 'At least one of these companies has no Open Payments records, so no year covers all of them.'
                          else 'Open Payments totals for ' || latest || ', the latest year every company here reported.' end,
    'shared_recipients', jsonb_build_object('all_years', shared_all,
        'definition', 'Recipients with consulting, royalty, speaking or services payments from every company here, 2019 to 2025. Meals and travel do not count. Counts only; no one is named.'),
    'notes', jsonb_build_array(
      'Each company counts with the companies it owns today when the page shows today''s ownership, and on its own when it shows ownership at the time of each record.',
      'A shared product code means both hold FDA records under it. It doesn''t show that the products are interchangeable.'),
    'source', 'FDA 510(k), De Novo, PMA and HDE databases; CMS Open Payments 2019 to 2025; OrthoParity vendor registry.');
end $$;

-- ---------------------------------------------------------------- First-load speed (live review #19)
-- Every SQL file empties the page cache, so after an update each page's first visit runs cold on the Free plan's
-- small database server. This fills the cache for the largest companies' pages (today's ownership, as the site shows
-- them) and the newest products in the product codes with the most records. Run it once after the last SQL file of
-- an update, when the site is quiet: `select pc_cache_warm();` It can take a few minutes; nothing breaks if it stops.
create or replace function pc_cache_warm(n_vendors int default 25, n_products int default 100)
returns jsonb language plpgsql volatile security definer set search_path = public as $$
declare v text; k text; nv int := 0; np int := 0; t0 timestamptz := clock_timestamp();
begin
  for v in select x.vendor_id from pc_vendors x
            where coalesce(x.rolls_up_to, x.vendor_id) = x.vendor_id and coalesce(x.clearances, 0) > 0
            order by x.clearances desc, x.vendor_id limit greatest(coalesce(n_vendors, 25), 0) loop
    perform pc_vendor_brief(v, 'current');
    perform pc_vendor_signals(v, 'current');
    if to_regprocedure('pc_vendor_supplier(text,text)') is not null then
      execute 'select pc_vendor_supplier($1, ''current'')' using v;
    end if;
    nv := nv + 1;
  end loop;
  for k in select r.knumber from (
             select p.knumber, row_number() over (partition by p.product_code order by p.decision_date desc, p.knumber) as rn,
                    count(*) over (partition by p.product_code) as code_size
               from pc_portfolio_510k p where p.product_code is not null) r
            order by r.rn, r.code_size desc, r.knumber limit greatest(coalesce(n_products, 100), 0) loop
    perform pc_brief(k);
    perform pc_signals(k);
    np := np + 1;
  end loop;
  return jsonb_build_object('companies', nv, 'products', np, 'cached_answers', (select count(*) from pc_cache),
                            'seconds', round(extract(epoch from clock_timestamp() - t0)::numeric, 1));
end $$;
revoke execute on function pc_cache_warm(int, int) from public, anon, authenticated;

grant execute on function pc_search_groups(text, int), pc_code_sites(text), pc_vendor_compare_many(text[], text)
  to anon, authenticated;

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
