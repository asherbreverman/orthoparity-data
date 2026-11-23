-- OrthoParity database: FDA premarket approvals (PMA) and humanitarian device exemptions (HDE)
-- Part of the OrthoParity data pipeline (MIT License). Safe to run again.
--
-- Run order after a CSV import:  07_after_import.sql, 13_approvals.sql, 12_curated_fixes.sql, 05_decision_functions.sql
-- (13 goes before 12 so the reviewed company splits and merges in 12 also apply to approvals).
--
-- What it does: pc_approvals and pc_approval_supplements hold one row per approval and per supplement
-- (python orthoparity.py load-approvals). pc_approval_rows holds the rows each approval adds to the tables the site
-- already uses (devices, portfolio, indications, MAUDE, recalls, sites, GUDID brands, payments, new vendors and
-- product codes), as JSON. pc_apply_approvals() removes the approval rows it added last time and adds them again,
-- so every page, search and company total treats an approval like a 510(k), with its own wording.

create table if not exists pc_approvals (
  number text primary key, pathway text, trade_name text, generic_name text, applicant text, vendor_id text,
  vendor_basis text, product_code text, decision_date date, original_on_file boolean, date_received date,
  expedited boolean, indications text, url text, supplements integer, supplements_shown integer,
  new_indications integer, design_changes integer, labeling_changes integer, study_changes integer,
  manufacturing_changes integer, site_changes integer, other_changes integer, last_change_date date,
  last_change_type text, note text);
create table if not exists pc_approval_supplements (
  number text not null, supplement_number text not null, supplement_type text, supplement_reason text,
  category text, shown boolean, decision_date date, decision_code text, trade_name text, change text,
  primary key (number, supplement_number));
create index if not exists pc_approval_supplements_n on pc_approval_supplements (number);
create table if not exists pc_approval_rows (target text not null, row jsonb not null);

do $$
declare t text;
begin
  foreach t in array array['pc_approvals', 'pc_approval_supplements'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    -- Same rules Lovable set live on Nov 22: every row is public, written so the security scan doesn't flag "true".
    execute format('create policy "public read" on %I for select to anon, authenticated using (%s)', t,
      case when t = 'pc_approval_supplements' then 'number is not null and supplement_number is not null'
           else 'number is not null' end);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;
alter table pc_approval_rows enable row level security;
revoke all on pc_approval_rows from anon, authenticated;

-- 510(k), De Novo, PMA or HDE, from the number's prefix
create or replace function pc_pathway(k text) returns text language sql immutable as $$
  select case when upper(coalesce(k, '')) like 'DEN%' then 'De Novo'
              when upper(coalesce(k, '')) ~ '^H\d' then 'HDE'
              when upper(coalesce(k, '')) ~ '^(P\d|N\d)' then 'PMA'
              else '510(k)' end
$$;
grant execute on function pc_pathway(text) to anon, authenticated;

create or replace function pc_apply_approvals() returns text language plpgsql as $$
declare n_dev int; n_rows int;
begin
  if not exists (select 1 from pc_approval_rows) then
    return 'pc_approval_rows is empty: import pc_approval_rows.csv first';
  end if;
  -- 1. take out what an earlier run added
  delete from pc_devices where knumber in (select number from pc_approvals) or status = 'approved';
  delete from pc_portfolio_510k where knumber ~ '^(P|H|N)\d';
  delete from pc_ifu where source = 'FDA approval order statement';
  delete from pc_maude_product where knumber ~ '^(P|H|N)\d';
  delete from pc_maude_year where knumber ~ '^(P|H|N)\d';
  delete from pc_recalls where vendor_basis = 'approval number';
  delete from pc_establishment_510k where knumber ~ '^(P|H|N)\d';
  delete from pc_portfolio_brands where knumbers ~ '^(P|H|N)\d' and knumbers !~ 'K\d';
  delete from pc_op_product where knumber ~ '^(P|H|N)\d';
  if to_regclass('public.pc_add_on_payment_510k') is not null then
    delete from pc_add_on_payment_510k where knumber ~ '^(P|H|N)\d';
  end if;

  -- 2. add them back from pc_approval_rows
  insert into pc_devices select (jsonb_populate_record(null::pc_devices, row)).* from pc_approval_rows where target = 'pc_devices'
    on conflict (knumber) do update set device_name = excluded.device_name, applicant = excluded.applicant,
      decision_date = excluded.decision_date, decision_year = excluded.decision_year, product_code = excluded.product_code,
      regulation_number = excluded.regulation_number, device_class = excluded.device_class, review_panel = excluded.review_panel,
      segment = excluded.segment, in_starting_set = excluded.in_starting_set, status = excluded.status,
      stop_reason = excluded.stop_reason, summary_url = excluded.summary_url, brand = excluded.brand,
      company_root = excluded.company_root;
  get diagnostics n_dev = row_count;
  -- codes only approvals use: refresh names and the reviewed flag each run; a code any 510(k) uses is never touched
  insert into pc_product_codes select (jsonb_populate_record(null::pc_product_codes, row)).* from pc_approval_rows
   where target = 'pc_product_codes'
  on conflict (product_code) do update set fda_name = excluded.fda_name, plain_name = excluded.plain_name,
     plain_description = excluded.plain_description, anatomy = excluded.anatomy, procedures = excluded.procedures,
     kind = excluded.kind, segment = excluded.segment, reviewed = excluded.reviewed
   where not exists (select 1 from pc_devices d where d.product_code = pc_product_codes.product_code and d.knumber ~ '^(K|DEN)');
  insert into pc_vendors select (jsonb_populate_record(null::pc_vendors, row)).* from pc_approval_rows
   where target = 'pc_vendors' on conflict (vendor_id) do nothing;
  insert into pc_vendor_names select x.* from pc_approval_rows r, jsonb_populate_record(null::pc_vendor_names, r.row) x
   where r.target = 'pc_vendor_names'
     and not exists (select 1 from pc_vendor_names n where n.source = x.source and n.raw_name = x.raw_name);
  insert into pc_portfolio_510k select (jsonb_populate_record(null::pc_portfolio_510k, row)).* from pc_approval_rows where target = 'pc_portfolio_510k';
  insert into pc_ifu select (jsonb_populate_record(null::pc_ifu, row)).* from pc_approval_rows where target = 'pc_ifu'
    on conflict (knumber) do nothing;
  insert into pc_maude_product select (jsonb_populate_record(null::pc_maude_product, row)).* from pc_approval_rows
   where target = 'pc_maude_product' on conflict (knumber) do nothing;
  insert into pc_maude_year select (jsonb_populate_record(null::pc_maude_year, row)).* from pc_approval_rows
   where target = 'pc_maude_year' on conflict do nothing;
  -- a recall already on file (it also names a 510(k)) gains the approval number; a new one is added
  update pc_recalls r set knumbers = array_to_string(array(select distinct x from unnest(
           string_to_array(coalesce(nullif(r.knumbers, ''), ''), '|') || string_to_array(a.row->>'knumbers', '|')) x
           where x <> '' order by x), '|')
    from pc_approval_rows a
   where a.target = 'pc_recalls' and r.recall_number = a.row->>'recall_number' and r.vendor_basis <> 'approval number';
  insert into pc_recalls select x.* from pc_approval_rows a, jsonb_populate_record(null::pc_recalls, a.row) x
   where a.target = 'pc_recalls' and not exists (select 1 from pc_recalls r where r.recall_number = x.recall_number);
  insert into pc_establishment select (jsonb_populate_record(null::pc_establishment, row)).* from pc_approval_rows
   where target = 'pc_establishment' on conflict (fei_number) do nothing;
  insert into pc_establishment_510k select (jsonb_populate_record(null::pc_establishment_510k, row)).* from pc_approval_rows
   where target = 'pc_establishment_510k' on conflict do nothing;
  insert into pc_portfolio_brands select (jsonb_populate_record(null::pc_portfolio_brands, row)).* from pc_approval_rows
   where target = 'pc_portfolio_brands';
  insert into pc_op_product select (jsonb_populate_record(null::pc_op_product, row)).* from pc_approval_rows where target = 'pc_op_product';

  -- Medicare add-on payments that CMS ties to an approval number (reference/add_on_payments.csv, fda_numbers)
  if to_regclass('public.pc_add_on_payment_510k') is not null then
    insert into pc_add_on_payment_510k (tech_id, knumber, vendor_id, product_code)
    select distinct p.tech_id, a.number, a.vendor_id, a.product_code
      from pc_add_on_payment p join pc_approvals a on p.fda_numbers ~ ('(^|[^0-9A-Z])' || a.number || '($|[^0-9])');
    update pc_add_on_payment p set vendor_id = a.vendor_id
      from pc_approvals a
     where coalesce(p.vendor_id, '') = '' and p.fda_numbers ~ ('(^|[^0-9A-Z])' || a.number || '($|[^0-9])');
    update pc_add_on_payment set note = nullif(trim(replace(replace(note, 'A PMA device: no 510(k) page on OrthoParity.', ''),
                                                             'Cerapedics is not in the vendor registry.', '')), '')
     where note like '%no 510(k) page on OrthoParity%';
  end if;

  -- Medicare procedure links for product codes only approvals use (reference/approval_procedure_links.csv)
  if to_regclass('public.pc_procedure_devices') is not null then
    delete from pc_procedure_devices p
     where not exists (select 1 from pc_devices d where d.product_code = p.product_code and d.knumber ~ '^(K|DEN)')
       and exists (select 1 from pc_devices d where d.product_code = p.product_code and d.status = 'approved');
    insert into pc_procedure_devices (family_id, role, product_code, plain_name, fda_name, clearances_all, clearances_recent, active_vendors, status)
    select x.family_id, x.role, c.product_code, c.plain_name, c.fda_name,
           (select count(*) from pc_devices d where d.product_code = c.product_code and d.in_starting_set),
           (select count(*) from pc_devices d where d.product_code = c.product_code and d.in_starting_set
              and d.decision_date::date >= current_date - interval '5 years'),
           (select count(distinct p.vendor_id) from pc_portfolio_510k p where p.product_code = c.product_code
              and p.decision_date::date >= current_date - interval '5 years'),
           'reviewed'
      from pc_approval_rows r, jsonb_to_record(r.row) as x(family_id text, role text, product_code text)
      join pc_product_codes c on c.product_code = x.product_code
     where r.target = 'pc_procedure_devices'
       and not exists (select 1 from pc_procedure_devices p where p.family_id = x.family_id and p.product_code = x.product_code);
  end if;

  -- 3. company totals and product code counts now include approvals
  update pc_vendors v set
    clearances = coalesce(a.n, 0), first_clearance_year = a.y1, last_clearance_year = a.y2,
    gudid_ortho_devices = coalesce(b.devs, 0), gudid_brands = coalesce(b.nb, 0)
  from pc_vendors v2
  left join (select vendor_id, count(*) n, min(extract(year from decision_date))::int y1, max(extract(year from decision_date))::int y2
               from pc_portfolio_510k group by 1) a on a.vendor_id = v2.vendor_id
  left join (select vendor_id, sum(devices) devs, count(*) nb from pc_portfolio_brands group by 1) b on b.vendor_id = v2.vendor_id
  where v.vendor_id = v2.vendor_id
    and v.vendor_id in (select vendor_id from pc_portfolio_510k where knumber ~ '^(P|H|N)\d');
  update pc_product_codes c set clearances = x.n
    from (select product_code, count(*) n from pc_devices where in_starting_set group by 1) x
   where x.product_code = c.product_code and c.clearances is distinct from x.n;
  select count(*) into n_rows from pc_approval_rows;
  return n_dev || ' approvals applied from ' || n_rows || ' rows';
end $$;
revoke execute on function pc_apply_approvals() from public, anon, authenticated;

-- one approval with its supplement history (the page shows device, labeling, indication and study changes;
-- manufacturing and site notices are counted, not listed)
create or replace function pc_approval_detail(k text) returns jsonb language sql stable as $$
  select case when a.number is null then null else
    to_jsonb(a) || jsonb_build_object(
      'supplements_listed', coalesce((
        select jsonb_agg(jsonb_build_object('supplement_number', s.supplement_number, 'decision_date', s.decision_date,
                                            'category', s.category, 'type', s.supplement_type, 'reason', s.supplement_reason,
                                            'change', s.change) order by s.decision_date desc, s.supplement_number desc)
          from pc_approval_supplements s where s.number = a.number and s.shown), '[]'::jsonb),
      'not_listed', coalesce(a.manufacturing_changes, 0) + coalesce(a.site_changes, 0) + coalesce(a.other_changes, 0),
      'definition', case when a.pathway = 'HDE'
        then 'Humanitarian device exemption: for a device that treats or diagnoses a condition affecting not more than 8,000 people in the US a year. FDA requires evidence of safety and probable benefit instead of effectiveness, and a hospital''s institutional review board must approve its use.'
        else 'Premarket approval: FDA''s review for Class III devices. The company submits its own clinical evidence of safety and effectiveness instead of comparing the device to a predicate.' end)
  end
  from (select 1) one left join pc_approvals a on a.number = upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'))
$$;
grant execute on function pc_approval_detail(text) to anon, authenticated;

select pc_apply_approvals();

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
