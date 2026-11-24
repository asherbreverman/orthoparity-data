-- 15_part_search.sql: part-number lookup from FDA GUDID (catalog and version or model numbers).
-- Run this once, then import outputs/site_data/pc_catalog_brand.csv into pc_catalog_brand and each
-- outputs/site_data/pc_catalog_N.csv into pc_catalog (Table Editor, Insert, Import data from CSV).
-- Safe to run again; it never deletes rows. To reload after a new GUDID release, run `truncate pc_catalog, pc_catalog_brand;`
-- first, then import the new files.

create table if not exists pc_catalog_brand (brand_id int primary key, brand text);
create table if not exists pc_catalog (ident text not null, n text not null, brand_id int, in_dist boolean);

do $$
declare t text;
begin
  foreach t in array array['pc_catalog', 'pc_catalog_brand'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (%s)', t,
      case when t = 'pc_catalog' then 'ident is not null' else 'brand_id is not null' end);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;

-- letters and digits only, upper case: "213-65-05" and "21365 05" find the same part
create or replace function pc_part_key(t text) returns text language sql immutable parallel safe as $$
  select upper(regexp_replace(coalesce(t, ''), '[^A-Za-z0-9]', '', 'g'))
$$;

create index if not exists pc_catalog_key on pc_catalog (pc_part_key(ident) text_pattern_ops);

-- Exact matches first, then part numbers that start with what was typed. At least 3 letters or digits.
create or replace function pc_part_search(q text, lim int default 25)
returns jsonb language sql stable as $$
  with k as (select pc_part_key(q) as key),
  hits as (
    select c.ident, c.n, c.brand_id, c.in_dist, pc_part_key(c.ident) = k.key as exact
      from pc_catalog c, k
     where length(k.key) >= 3 and pc_part_key(c.ident) ~>=~ k.key and pc_part_key(c.ident) ~<~ (k.key || '~')
     order by (pc_part_key(c.ident) = k.key) desc, c.ident, c.n
     limit least(greatest(coalesce(lim, 25), 1), 100)),
  dev as (select distinct on (p.knumber) p.knumber, p.device_name, p.vendor_id
            from pc_portfolio_510k p where p.knumber in (select n from hits) order by p.knumber, p.vendor_id)
  select jsonb_build_object(
    'query', q, 'key', (select key from k),
    'note', case when length((select key from k)) < 3 then 'Type at least 3 letters or numbers of the part number.' end,
    'results', coalesce(jsonb_agg(jsonb_build_object(
        'part_number', h.ident, 'match', case when h.exact then 'exact' else 'starts with' end,
        'number', h.n, 'brand', case when upper(trim(b.brand)) in ('', 'NA', 'N/A', 'NONE', 'UNKNOWN') then null else b.brand end, 'in_distribution', h.in_dist,
        'device_name', d.device_name, 'company', v.display_name, 'vendor_id', d.vendor_id)
      order by h.exact desc, h.ident, h.n) filter (where h.n is not null), '[]'::jsonb),
    'source', 'FDA GUDID: catalog and version or model numbers listed under each 510(k), De Novo, PMA or HDE number.')
  from hits h left join pc_catalog_brand b on b.brand_id = h.brand_id
    left join dev d on d.knumber = h.n left join pc_vendors v on v.vendor_id = d.vendor_id
$$;
grant execute on function pc_part_key(text), pc_part_search(text, int) to anon, authenticated;
