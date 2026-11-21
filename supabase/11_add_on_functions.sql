-- OrthoParity: Medicare add-on payments (inpatient NTAP and outpatient device pass-through) for product and company
-- pages. Read-only. Run after 10_supplier_functions.sql.
--
-- An add-on payment is a Medicare payment rule for hospitals, set by CMS for a limited time. It is not a clinical
-- endorsement and not a price. Every row links to the CMS file and the FDA record it came from.

create or replace function pc_add_on_notes() returns jsonb language sql immutable as $$
  select jsonb_build_array(
    'NTAP (new technology add-on payment) adds to the hospital''s inpatient MS-DRG payment when a case uses the technology and the case costs more than the DRG pays. The amount shown is the most Medicare adds per case; most cases get less. FY 2027 runs October 1, 2026 to September 30, 2027.',
    'Device pass-through pays hospital outpatient departments and ASCs separately for the device, on top of the procedure payment, for two to three years. CMS sets it by HCPCS device code (C-code); the code covers any device that fits its description.',
    'Both go to the hospital or ASC, not the manufacturer, and both apply to Original Medicare. Commercial payers set their own rules.',
    'CMS names technologies, not 510(k) numbers. OrthoParity links each technology to the 510(k)s for that product line, listed with an FDA source. A PMA device has no 510(k) page here.',
    'An add-on payment is a payment rule, not a finding about safety, effectiveness or price.'
  );
$$;

-- Product page: add-on payments that name this 510(k)'s product line, and others in the same product code.
create or replace function pc_device_add_on(k text) returns jsonb language sql stable as $$
  with mine as (
    select t.* from pc_add_on_payment t join pc_add_on_payment_510k l using (tech_id) where l.knumber = k),
  code as (select product_code from pc_devices where knumber = k),
  peers as (
    select distinct on (t.tech_id) t.*, l.knumber example_knumber
    from pc_add_on_payment t join pc_add_on_payment_510k l using (tech_id)
    where l.product_code = (select product_code from code) and l.knumber <> k
      and t.tech_id not in (select tech_id from mine)
    order by t.tech_id, l.knumber desc)
  select jsonb_build_object(
    'knumber', k,
    'has_add_on', exists (select 1 from mine),
    'items', coalesce((select jsonb_agg(to_jsonb(m) order by m.program, m.status) from mine m), '[]'::jsonb),
    'product_code', (select product_code from code),
    'category', coalesce((select jsonb_agg(to_jsonb(p)
                  order by p.program, p.technology) from peers p), '[]'::jsonb),
    'notes', pc_add_on_notes());
$$;

-- Company page: add-on payments for technologies whose 510(k)s belong to this company, or that CMS names for it.
create or replace function pc_vendor_add_on(v text, m text default 'current') returns jsonb language sql stable as $$
  with fam as (select f.vendor_id from pc_vendor_family(v, pc_mode(m)) f),
  hit as (
    select t.*, (select count(*) from pc_add_on_payment_510k l where l.tech_id = t.tech_id
                   and l.vendor_id in (select vendor_id from fam)) products
    from pc_add_on_payment t
    where t.vendor_id in (select vendor_id from fam)
       or exists (select 1 from pc_add_on_payment_510k l where l.tech_id = t.tech_id
                  and l.vendor_id in (select vendor_id from fam)))
  select jsonb_build_object(
    'vendor_id', v,
    'items', coalesce((select jsonb_agg(to_jsonb(h)
               order by h.program, h.status, h.technology) from hit h), '[]'::jsonb),
    'ntap', (select count(*) from hit where program = 'NTAP' and status <> 'discontinued'),
    'pass_through', (select count(*) from hit where program = 'TPT'),
    'notes', pc_add_on_notes());
$$;

grant execute on function pc_add_on_notes() to anon, authenticated;
grant execute on function pc_device_add_on(text) to anon, authenticated;
grant execute on function pc_vendor_add_on(text, text) to anon, authenticated;
