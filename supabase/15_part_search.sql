-- 15_part_search.sql: part-number lookup from FDA GUDID (catalog and version or model numbers).
-- Run this, then import outputs/site_data/pc_catalog_brand.csv into pc_catalog_brand, pc_catalog_company.csv into
-- pc_catalog_company, and each outputs/site_data/pc_catalog_N.csv into pc_catalog (Table Editor, Insert, Import data
-- from CSV), then run `select pc_catalog_after_import();` (it rebuilds the search index, about 25 MB smaller than
-- one built row by row, and returns the counts to check).
-- Safe to run again; after the one-time Phase 9 table change it never deletes rows. To reload after a new GUDID
-- release, run `truncate pc_catalog, pc_catalog_brand, pc_catalog_company;` first, then import the new files.
--
-- Phase 9 (2026-11-24): pc_catalog also holds GUDID part numbers filed under the site's orthopedic product codes that
-- list an FDA number outside the site (n is that number) or no FDA number at all (n is blank; pc and company_id say
-- which product code and company GUDID names, exempt says whether the company marked it premarket exempt). Every row
-- also carries the device-ID count and, when every device ID on the row agrees, units per package, packaged sterile
-- and MRI safety (0 labeling has no MRI safety information, 1 MR Safe, 2 MR Conditional, 3 MR Unsafe, 9 mixed).

create table if not exists pc_catalog_brand (brand_id int primary key, brand text);
create table if not exists pc_catalog_company (company_id int primary key, company text);
-- Phase 9 layout (fixed-width columns first, so rows carry no padding). The first run replaces the old 4-column table;
-- its rows come back with the new import, which has to replace every row anyway because brand IDs change.
do $$ begin
  if to_regclass('public.pc_catalog') is not null and not exists (select 1 from information_schema.columns
       where table_schema = 'public' and table_name = 'pc_catalog' and column_name = 'exempt') then
    drop table pc_catalog;
    truncate pc_catalog_brand;  -- brand IDs change with the new import
  end if;
end $$;
create table if not exists pc_catalog (
  brand_id int, company_id int, n_di smallint, units smallint, mri smallint,
  in_dist boolean, sterile boolean, exempt boolean, ident text not null, n text, pc text);

do $$
declare t text;
begin
  foreach t in array array['pc_catalog', 'pc_catalog_brand', 'pc_catalog_company'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (%s)', t,
      case t when 'pc_catalog' then 'ident is not null' when 'pc_catalog_brand' then 'brand_id is not null'
             else 'company_id is not null' end);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;

-- letters and digits only, upper case: "213-65-05" and "21365 05" find the same part
create or replace function pc_part_key(t text) returns text language sql immutable parallel safe as $$
  select upper(regexp_replace(coalesce(t, ''), '[^A-Za-z0-9]', '', 'g'))
$$;

create index if not exists pc_catalog_key on pc_catalog (pc_part_key(ident) text_pattern_ops);

create or replace function pc_mri_label(m smallint) returns text language sql immutable as $$
  select case m when 0 then 'Labeling has no MRI safety information' when 1 then 'MR Safe'
                when 2 then 'MR Conditional' when 3 then 'MR Unsafe' when 9 then 'Differs across device IDs' end
$$;

-- Exact matches first, then part numbers that start with what was typed. At least 3 letters or digits.
-- Within each, parts listed under an FDA number on the site come first.
-- scope 'site' (the default, what the site called before Phase 9) returns only parts under an FDA number on the site;
-- scope 'all' adds parts under other FDA numbers and parts with no FDA number.
drop function if exists pc_part_search(text, int);
create or replace function pc_part_search(q text, lim int default 25, scope text default 'site')
returns jsonb language sql stable as $$
  with k as (select pc_part_key(q) as key),
  raw as (
    select c.*, pc_part_key(c.ident) = k.key as exact
      from pc_catalog c, k
     where length(k.key) >= 3 and pc_part_key(c.ident) ~>=~ k.key and pc_part_key(c.ident) ~<~ (k.key || '~')
       and (lower(coalesce(scope, 'site')) = 'all' or c.n is not null)
     order by (pc_part_key(c.ident) = k.key) desc, pc_part_key(c.ident)
     limit 1000),
  dev as (
    select distinct on (n) n, device_name, vendor_id, product_code from (
      select p.knumber as n, p.device_name, p.vendor_id, p.product_code, 1 as src
        from pc_portfolio_510k p where p.knumber in (select n from raw)
      union all
      select a.number, a.trade_name, a.vendor_id, a.product_code, 2
        from pc_approvals a where a.number in (select n from raw)) x
     order by n, src, vendor_id),
  hits as (
    select r.*, d.n is not null as on_site, d.device_name, d.vendor_id, coalesce(r.pc, d.product_code) as code
      from raw r left join dev d on d.n = r.n
     where lower(coalesce(scope, 'site')) = 'all' or d.n is not null
     order by r.exact desc, (d.n is not null) desc, r.ident, r.n nulls last
     limit least(greatest(coalesce(lim, 25), 1), 100))
  select jsonb_build_object(
    'query', q, 'key', (select key from k), 'scope', case when lower(coalesce(scope, 'site')) = 'all' then 'all' else 'site' end,
    'note', case when length((select key from k)) < 3 then 'Type at least 3 letters or numbers of the part number.' end,
    'counts', jsonb_build_object(
        'shown', (select count(*) from hits),
        'on_site', (select count(*) from hits where on_site),
        'other_fda_number', (select count(*) from hits where not on_site and n is not null),
        'fda_number_not_found', (select count(*) from hits where n is null)),
    'results', coalesce(jsonb_agg(jsonb_build_object(
        'part_number', h.ident, 'match', case when h.exact then 'exact' else 'starts with' end,
        'number', h.n, 'on_site', h.on_site,
        'fda_number_note', case
            when h.n is null and h.exempt then 'FDA number NOT FOUND in GUDID: the company marked this device premarket exempt.'
            when h.n is null then 'FDA number NOT FOUND in GUDID: the company listed no premarket submission for this device.'
            when not h.on_site then 'GUDID lists FDA number ' || h.n || ', which is outside OrthoParity''s orthopedic set.' end,
        'brand', case when upper(trim(b.brand)) in ('', 'NA', 'N/A', 'NONE', 'UNKNOWN') then null else b.brand end,
        'in_distribution', h.in_dist,
        'device_name', h.device_name, 'company', coalesce(v.display_name, co.company), 'vendor_id', h.vendor_id,
        'product_code', h.code, 'product_code_name', coalesce(pcn.plain_name, pcn.fda_name),
        'device_ids', h.n_di, 'units_per_package', h.units,
        'sterile', case h.sterile when true then 'Packaged sterile' when false then 'Not packaged sterile' end,
        'mri_safety', pc_mri_label(h.mri))
      order by h.exact desc, h.on_site desc, h.ident, h.n nulls last), '[]'::jsonb),
    'source', 'FDA GUDID: catalog and version or model numbers for every device filed under an orthopedic product code '
              || 'on the site or listing an FDA number on the site. Units, sterile and MRI safety show only when every '
              || 'device ID on the row agrees.')
  from hits h left join pc_catalog_brand b on b.brand_id = h.brand_id
    left join pc_catalog_company co on co.company_id = h.company_id
    left join pc_vendors v on v.vendor_id = h.vendor_id
    left join pc_product_codes pcn on pcn.product_code = h.code
$$;
grant execute on function pc_part_key(text), pc_mri_label(smallint), pc_part_search(text, int, text) to anon, authenticated;

-- After importing the CSVs: blank FDA numbers and product codes become null (the dashboard importer can load an empty
-- cell as empty text), the search index is rebuilt compactly, and the counts come back for checking.
create or replace function pc_catalog_after_import()
returns jsonb language plpgsql volatile security definer set search_path = public as $$
declare fixed int;
begin
  update pc_catalog set n = nullif(btrim(n), ''), pc = nullif(btrim(pc), '') where n = '' or pc = '';
  get diagnostics fixed = row_count;
  execute 'reindex index pc_catalog_key';
  analyze pc_catalog;
  if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if;
  return jsonb_build_object('rows', (select count(*) from pc_catalog),
    'with_fda_number', (select count(*) from pc_catalog where n is not null),
    'no_fda_number', (select count(*) from pc_catalog where n is null),
    'brands', (select count(*) from pc_catalog_brand), 'companies', (select count(*) from pc_catalog_company),
    'blank_cells_fixed', fixed,
    'part_tables_mb', round((pg_total_relation_size('pc_catalog') + pg_total_relation_size('pc_catalog_brand')
                             + pg_total_relation_size('pc_catalog_company')) / 1048576.0, 1),
    'database_mb', round(pg_database_size(current_database()) / 1048576.0, 1));
end $$;
revoke execute on function pc_catalog_after_import() from public, anon, authenticated;

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
