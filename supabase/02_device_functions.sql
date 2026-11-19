-- OrthoParity database: device lookup, predicate chains and the device brief
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.

-- K-number: exact match on any device. Otherwise every word must appear in the device name or applicant
-- (orthopedic starting set only), newest first. If that finds fewer than 5, close spellings are added.
create or replace function pc_search(q text, lim int default 50)
returns table (knumber text, device_name text, applicant text, decision_date text, segment text,
               in_starting_set boolean, match text)
language sql stable
as $$
  with k as (
    select upper(regexp_replace(coalesce(q, ''), '[\s\-]', '', 'g')) as kn
  ),
  exact as (
    select d.knumber, d.device_name, d.applicant, d.decision_date, d.segment, d.in_starting_set, 'exact'::text as match
    from pc_devices d, k
    where k.kn ~ '^(K|DEN)\d{6}$' and d.knumber = k.kn
  ),
  w as (
    select array_remove(regexp_split_to_array(lower(trim(coalesce(q, ''))), '\s+'), '') as words
  ),
  partial as (
    select d.knumber, d.device_name, d.applicant, d.decision_date, d.segment, d.in_starting_set, 'partial'::text
    from pc_devices d, w
    where d.in_starting_set
      and not exists (select 1 from exact)
      and cardinality(w.words) > 0
      and (select bool_and(lower(coalesce(d.device_name, '') || ' ' || coalesce(d.applicant, '')) like '%' || x || '%')
           from unnest(w.words) x)
    order by d.decision_date desc nulls last
    limit lim
  ),
  fuzzy as (
    select d.knumber, d.device_name, d.applicant, d.decision_date, d.segment, d.in_starting_set,
           'close spelling'::text
    from pc_devices d, w
    where d.in_starting_set
      and not exists (select 1 from exact)
      and (select count(*) from partial) < 5
      and length(trim(coalesce(q, ''))) >= 3
      and (select bool_and(word_similarity(x, lower(coalesce(d.device_name, '') || ' ' || coalesce(d.applicant, ''))) >= 0.45)
           from unnest(w.words) x where length(x) >= 3)
      and d.knumber not in (select p.knumber from partial p)
    order by word_similarity(lower(q), lower(coalesce(d.device_name, '') || ' ' || coalesce(d.applicant, ''))) desc
    limit 20
  )
  select * from exact
  union all select * from partial
  union all select * from fuzzy
$$;

-- All starting-set clearances whose device name contains the brand word, split into the same applicant
-- (family) and other companies (excluded, with the reason). No parent-company roll-up.
create or replace function pc_brand_family(k text)
returns jsonb
language sql stable
as $$
  with me as (
    select brand, company_root from pc_devices where knumber = upper(trim(k)) and in_starting_set
  ),
  same_brand as (
    select d.* from pc_devices d, me
    where me.brand is not null and d.in_starting_set
      and d.device_name ~* ('\m' || me.brand || '\M')
  )
  select jsonb_build_object(
    'brand', (select brand from me),
    'family', coalesce((select jsonb_agg(jsonb_build_object('knumber', s.knumber, 'device_name', s.device_name,
                         'applicant', s.applicant, 'decision_date', s.decision_date) order by s.decision_date)
                        from same_brand s, me where s.company_root = me.company_root), '[]'::jsonb),
    'excluded', coalesce((select jsonb_agg(jsonb_build_object('knumber', s.knumber, 'device_name', s.device_name,
                           'applicant', s.applicant, 'decision_date', s.decision_date,
                           'reason', 'same brand word ''' || me.brand || ''', different applicant (' || s.applicant || ')')
                           order by s.decision_date)
                          from same_brand s, me where s.company_root is distinct from me.company_root), '[]'::jsonb)
  )
$$;

-- Breadth-first walk of ancestors from one or more subject K-numbers. Each device appears once, at its nearest
-- generation. Returns {nodes, edges, flags, max_gen}. Ancestors only.
create or replace function pc_lookup(roots text[], max_gen int default 10)
returns jsonb
language plpgsql stable
as $$
declare
  r_up     text[];
  frontier text[];
  seen     text[];
  gen_of   int[];
  g        int := 0;
  result   jsonb;
begin
  select coalesce(array_agg(distinct upper(trim(x))), '{}') into r_up from unnest(roots) x where trim(x) <> '';
  frontier := r_up;
  seen := r_up;
  gen_of := array_fill(0, array[coalesce(array_length(r_up, 1), 0)]);
  while g < max_gen and coalesce(array_length(frontier, 1), 0) > 0 loop
    g := g + 1;
    select coalesce(array_agg(distinct e.predicate), '{}') into frontier
      from pc_edges e
     where e.child = any(frontier) and not (e.predicate = any(seen));
    seen := seen || frontier;
    gen_of := gen_of || array_fill(g, array[coalesce(array_length(frontier, 1), 0)]);
  end loop;

  with c as (
    select t.knumber, t.generation from unnest(seen, gen_of) as t(knumber, generation)
  ),
  ce as (
    select e.*, c.generation + 1 as generation
      from pc_edges e join c on c.knumber = e.child
     where c.generation < max_gen
  ),
  inbound as (
    select ce.predicate,
           array_agg(distinct ce.role) as roles,
           max(case ce.confidence when 'HIGH' then 3 when 'MEDIUM' then 2 when 'LOW' then 1 else 0 end) as conf,
           bool_or(ce.review_source <> 'parser') as reviewed
      from ce join c on c.knumber = ce.predicate and c.generation = ce.generation
     group by ce.predicate
  ),
  nodes as (
    select c.knumber, c.generation, d.device_name, d.applicant, d.decision_date, d.product_code,
           d.regulation_number, d.device_class, d.review_panel,
           coalesce(d.segment, case when coalesce(d.in_starting_set, false) then null else 'outside orthopedic set' end) as segment,
           coalesce(d.in_starting_set, false) as in_starting_set, d.summary_url,
           case
             when c.knumber = any(r_up) then 'subject (vendor device)'
             when i.roles = array['primary'] then 'primary predicate'
             when i.roles = array['reference'] then 'reference predicate'
             when i.roles is not null then 'primary + reference'
             else 'predicate'
           end as role,
           case when c.knumber = any(r_up) then null
                else (array['n/a', 'LOW', 'MEDIUM', 'HIGH'])[coalesce(i.conf, 0) + 1] end as confidence,
           case when c.knumber = any(r_up) then null
                when i.reviewed then 'Claude review' else 'parser' end as review_source,
           coalesce(
             d.stop_reason,
             case when d.knumber is null or d.status = 'not extracted' then 'Not yet extracted' end,
             case when c.generation >= max_gen and exists (select 1 from pc_edges x where x.child = c.knumber)
                  then 'TRUNCATED (generation limit reached with more predicates available)' end
           ) as stop
      from c
      left join pc_devices d on d.knumber = c.knumber
      left join inbound i on i.predicate = c.knumber
  )
  select jsonb_build_object(
    'max_gen', max_gen,
    'roots', to_jsonb(r_up),
    'nodes', coalesce((select jsonb_agg(to_jsonb(n) order by n.generation, n.knumber) from nodes n), '[]'::jsonb),
    'edges', coalesce((select jsonb_agg(jsonb_build_object(
                 'generation', ce.generation, 'child', ce.child, 'predicate', ce.predicate,
                 'number_as_printed', ce.number_as_printed, 'role', ce.role, 'confidence', ce.confidence,
                 'review_decision', ce.review_decision, 'review_source', ce.review_source, 'page', ce.page,
                 'printed_label', ce.printed_label, 'evidence', ce.evidence)
               order by ce.generation, ce.child, ce.list_order) from ce), '[]'::jsonb),
    'flags', coalesce((select jsonb_agg(to_jsonb(f) order by f.knumber) from pc_flags f
                        where f.knumber = any(seen)), '[]'::jsonb)
  ) into result;
  return result;
end
$$;

-- Direct predicates of one clearance with identity and same-company / same-code markers.
-- Same company? Applicant names as printed at clearance can differ for one company ("DePuy Orthopaedics, Inc."
-- and "Depuy(Ireland)"), and companies change hands. Two clearances count as the same company when their cleaned
-- names match, or when both applicants belong to vendors with the same owner on the given date. The owner follows
-- the same dated roll-up rules as the payment totals (acquired by, merged into, owned by, asset purchases).
create or replace function pc_applicant_vendor(name text)
returns text
language sql stable
as $$
  select min(vendor_id) from pc_vendor_names where source = 'applicant' and raw_name = name
$$;

create or replace function pc_owner_at(v text, d date)
returns text
language sql stable
as $$
  with recursive up(vid, depth) as (
    select v, 0 where v is not null
    union all
    select l.parent, up.depth + 1
      from up join pc_vendor_lineage l on l.vendor_id = up.vid
     where up.depth < 3
       and l.parent <> up.vid
       and l.relation in ('acquired by', 'merged into', 'owned by', 'hardware and biologics assets acquired by')
       and exists (select 1 from pc_vendors p where p.vendor_id = l.parent)
       and coalesce(l.valid_from, date '1900-01-01') <= coalesce(d, current_date)
       and coalesce(l.valid_to, date '2999-12-31') >= coalesce(d, current_date)
  )
  select vid from up order by depth desc limit 1
$$;

create or replace function pc_same_company(a_applicant text, a_root text, b_applicant text, b_root text, d date)
returns boolean
language sql stable
as $$
  select (a_root is not null and a_root = b_root)
      or coalesce(pc_owner_at(pc_applicant_vendor(a_applicant), d) = pc_owner_at(pc_applicant_vendor(b_applicant), d), false)
$$;

create or replace function pc_direct(k text)
returns table (predicate text, role text, confidence text, review_source text, number_as_printed text,
               device_name text, applicant text, decision_year text, product_code text, kind text,
               same_company boolean, same_code boolean, list_order int)
language sql stable
as $$
  with me as (select * from pc_devices where knumber = upper(trim(k)))
  select e.predicate, e.role, e.confidence, e.review_source, e.number_as_printed,
         d.device_name, d.applicant, d.decision_year, d.product_code,
         case when e.predicate like 'P%' then 'PMA' when e.predicate like 'DEN%' then 'De Novo' else '510(k)' end,
         pc_same_company(d.applicant, d.company_root, me.applicant, me.company_root, nullif(me.decision_date, '')::date),
         (d.product_code is not null and d.product_code = me.product_code),
         min(e.list_order)
    from pc_edges e
    cross join me
    left join pc_devices d on d.knumber = e.predicate
   where e.child = me.knumber
   group by e.predicate, e.role, e.confidence, e.review_source, e.number_as_printed, d.device_name, d.applicant,
            d.decision_year, d.product_code, d.company_root, me.company_root, me.product_code, me.applicant,
            me.decision_date
   order by (e.role = 'primary') desc, min(e.list_order)
$$;

create or replace function pc_category(code text)
returns jsonb
language sql stable
as $$
  with c as (
    select d.*, nullif(d.decision_year, '')::int as yr
      from pc_devices d where d.in_starting_set and d.product_code = code
  ),
  latest as (select coalesce(max(yr), 0) as y from c),
  co as (
    select company_root, max(applicant) as applicant, count(*) as n,
           count(*) filter (where yr > (select y from latest) - 5) as n5
      from c group by company_root
  )
  select jsonb_build_object(
    'product_code', code,
    'total', (select count(*) from c),
    'latest_year', (select y from latest),
    'last5_clearances', (select count(*) from c where yr > (select y from latest) - 5),
    'last5_companies', (select count(*) from co where n5 > 0),
    'by_year', coalesce((select jsonb_agg(jsonb_build_object('year', yr, 'n', n) order by yr)
                           from (select yr, count(*) n from c where yr is not null group by yr) t), '[]'::jsonb),
    'top_companies', coalesce((select jsonb_agg(jsonb_build_object('applicant', applicant, 'clearances', n,
                                 'last5', n5) order by n desc, applicant)
                                 from (select * from co order by n desc, applicant limit 10) t), '[]'::jsonb),
    'top_companies_last5', coalesce((select jsonb_agg(jsonb_build_object('applicant', applicant, 'clearances', n5)
                                       order by n5 desc, applicant)
                                       from (select * from co where n5 > 0 order by n5 desc, applicant limit 10) t),
                                    '[]'::jsonb)
  )
$$;

-- Other orthopedic clearances that cite at least one of this clearance's direct predicates.
create or replace function pc_peers(k text, lim int default 50)
returns jsonb
language sql stable
as $$
  with me as (select * from pc_devices where knumber = upper(trim(k))),
  preds as (select distinct e.predicate from pc_edges e, me where e.child = me.knumber),
  p as (
    select e.child, array_agg(distinct e.predicate order by e.predicate) as shared
      from pc_edges e join preds on preds.predicate = e.predicate
     where e.child <> (select knumber from me)
     group by e.child
  ),
  rows as (
    select p.child as knumber, d.device_name, d.applicant, d.decision_year, d.product_code, p.shared,
           cardinality(p.shared) as n_shared,
           (d.company_root is not null and d.company_root = me.company_root) as same_company,
           (d.product_code = me.product_code) as same_code
      from p join pc_devices d on d.knumber = p.child and d.in_starting_set
      cross join me
  )
  select jsonb_build_object(
    'total', (select count(*) from rows),
    'other_companies', (select count(distinct r.applicant) from rows r where not r.same_company),
    'same_code', (select count(*) from rows where same_code),
    'peers', coalesce((select jsonb_agg(to_jsonb(r) order by r.n_shared desc, r.same_code desc, r.decision_year desc nulls last)
                         from (select * from rows order by n_shared desc, same_code desc, decision_year desc nulls last
                               limit lim) r), '[]'::jsonb)
  )
$$;

-- Follows one predicate per generation (the primary one, else the first listed) back to where the record stops.
create or replace function pc_primary_lineage(k text, max_gen int default 10)
returns jsonb
language plpgsql stable
as $$
declare
  cur text := upper(trim(k));
  nxt text;
  g int := 0;
  path jsonb := '[]'::jsonb;
  seen text[] := array[upper(trim(k))];
begin
  loop
    select e.predicate into nxt
      from pc_edges e
     where e.child = cur
     order by (e.role = 'primary') desc, e.list_order
     limit 1;
    exit when nxt is null or g >= max_gen or nxt = any(seen);
    g := g + 1;
    seen := seen || nxt;
    path := path || (select jsonb_build_object('generation', g, 'knumber', nxt, 'device_name', d.device_name,
                       'applicant', d.applicant, 'decision_year', d.decision_year, 'stop', d.stop_reason)
                       from (select 1) one left join pc_devices d on d.knumber = nxt);
    cur := nxt;
  end loop;
  return jsonb_build_object(
    'path', path,
    'generations', g,
    'oldest_year', (select min(x->>'decision_year') from jsonb_array_elements(path) x where x->>'decision_year' ~ '^\d{4}$'),
    'ends_at', case when jsonb_array_length(path) = 0 then null else path->-1 end,
    'stopped_by_limit', g >= max_gen and nxt is not null
  );
end
$$;

-- Includes the standard value analysis committee questions (key: vac_questions).
create or replace function pc_brief(k text)
returns jsonb
language plpgsql stable
as $$
declare
  kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'));
  dev pc_devices;
  pcode pc_product_codes;
  ifu pc_ifu;
  direct jsonb;
  n_direct int;
  n_same int;
  n_low int;
  pattern text;
  lineage jsonb;
  peers jsonb;
  cat jsonb;
  q jsonb := '[]'::jsonb;
  vq jsonb := '[]'::jsonb;
  pred_list text;
  pred_phrase text;
  proc text;
  own_list text;
  other_cos text;
  oldest int;
begin
  select * into dev from pc_devices where knumber = kn;
  if dev.knumber is null then
    return jsonb_build_object('found', false, 'knumber', kn);
  end if;
  select * into pcode from pc_product_codes where product_code = dev.product_code;
  select * into ifu from pc_ifu where knumber = kn;

  select coalesce(jsonb_agg(to_jsonb(x) order by x.role = 'primary' desc, x.list_order), '[]'::jsonb),
         count(*), count(*) filter (where x.same_company),
         count(*) filter (where x.confidence = 'LOW' and x.review_source = 'parser')
    into direct, n_direct, n_same, n_low
    from pc_direct(kn) x;

  pattern := case
    when n_direct = 0 then 'no numbered predicate'
    when n_same = n_direct then 'line extension'
    when n_same = 0 then 'competitive entry'
    else 'mixed' end;

  lineage := pc_primary_lineage(kn, 10);
  oldest := nullif(lineage->>'oldest_year', '')::int;

  peers := pc_peers(kn, 50);
  cat := case when dev.product_code is null then null else pc_category(dev.product_code) end;

  -- questions to ask the vendor (fixed rules; same input, same output)
  if pattern = 'no numbered predicate' then
    q := q || to_jsonb('No numbered predicate is on file for this clearance (' || coalesce(dev.stop_reason, 'reason not recorded')
         || '). Ask the vendor which predicate device(s) FDA cleared it against, with their 510(k) numbers.');
  end if;
  if pattern = 'line extension' then
    select string_agg(x.predicate || coalesce(' (' || x.decision_year || ')', ''), ', ') into own_list
      from pc_direct(kn) x where x.same_company;
    q := q || to_jsonb('FDA cleared this as equivalent to the company''s own earlier device(s): ' || own_list
         || '. What changed clinically or technically, and how does that change the value compared with the current product?');
  end if;
  if pattern in ('competitive entry', 'mixed') then
    select string_agg(distinct x.applicant, '; ') into other_cos from pc_direct(kn) x where not x.same_company;
    q := q || to_jsonb('FDA cleared this as equivalent to devices from ' || coalesce(other_cos, 'other companies')
         || '. Which of those devices, or their peers, are already in use or on contract here?');
  end if;
  if coalesce((peers->>'total')::int, 0) > 0 then
    q := q || to_jsonb((peers->>'total') || ' other orthopedic clearance(s) from ' || (peers->>'other_companies')
         || ' other compan' || case when (peers->>'other_companies')::int = 1 then 'y' else 'ies' end
         || ' were cleared against the same predicate(s). How does this device differ from them?');
  end if;
  if cat is not null and coalesce((cat->>'last5_companies')::int, 0) >= 10 then
    q := q || to_jsonb('This is a crowded category: ' || (cat->>'last5_companies') || ' companies cleared '
         || coalesce(pcode.plain_name, dev.product_code) || ' devices in the last five years of data. Consider a competitive comparison.');
  elsif cat is not null and coalesce((cat->>'last5_companies')::int, 0) between 1 and 3 then
    q := q || to_jsonb('Few companies cleared devices in this category recently (' || (cat->>'last5_companies')
         || ' in the last five years of data). Ask about alternatives and supply continuity.');
  end if;
  if oldest is not null and oldest <= 1995 and n_direct > 0 then
    q := q || to_jsonb('The primary predicate line on record goes back to ' || oldest
         || '. What evidence supports any advantage claimed over long-established designs?');
  end if;
  if exists (select 1 from pc_direct(kn) x where x.kind in ('PMA', 'De Novo')) then
    q := q || to_jsonb('A direct predicate is a PMA or De Novo device. Ask what clinical data supports this device.'::text);
  end if;
  if n_low > 0 then
    q := q || to_jsonb(n_low || ' predicate link(s) were read with low confidence and not reviewed. Confirm them in the FDA summary.');
  end if;

  -- standard VAC questions, tailored with this device's predicates, procedures and kind
  select string_agg(y.predicate, ', ') into pred_list
    from (select x.predicate from pc_direct(kn) x order by x.role = 'primary' desc, x.list_order limit 3) y;
  pred_phrase := case when n_direct = 0 then 'its predicates'
                      when n_direct > 3 then 'its predicates (' || pred_list || ' and others)'
                      else 'its predicates (' || pred_list || ')' end;
  proc := coalesce(nullif(pcode.procedures, ''), 'the procedures where this device is used');

  vq := vq || jsonb_build_array(
    jsonb_build_object('topic', 'Coding and reimbursement', 'question',
      'Which CPT, ICD-10-PCS and HCPCS codes, and which MS-DRG (inpatient) or APC (outpatient and ASC), apply to '
      || proc || ' with this device? Does it change the coding we use today?'),
    jsonb_build_object('topic', 'Coding and reimbursement', 'question',
      'How does the device cost compare with what we are paid for the procedure at each site of service (inpatient, outpatient, ASC)?'),
    jsonb_build_object('topic', 'Coding and reimbursement', 'question',
      'Does it qualify for a new technology add-on payment (NTAP) or transitional pass-through (TPT) payment? If yes, until when?'),
    jsonb_build_object('topic', 'Total procedure cost', 'question',
      'What is the total supply cost of a typical case: implants, instruments, orthobiologics, enabling technology (navigation, robotics, imaging) and disposables?'),
    jsonb_build_object('topic', 'Total procedure cost', 'question',
      'Which other products does the procedure require or typically use with this device? Are any of them proprietary or sold only as a system?'),
    jsonb_build_object('topic', 'Total procedure cost', 'question',
      'Does it change OR time, length of stay, or site of service? What data shows that?'),
    jsonb_build_object('topic', 'Clinical value', 'question',
      'Is the requesting surgeon already using one of ' || pred_phrase
      || ' or a peer device? Which product would this one replace, and would we keep both?'),
    jsonb_build_object('topic', 'Clinical value', 'question',
      'What specific features does this device have that its predicates lack, and what evidence shows those features change outcomes, complications or revisions?'),
    jsonb_build_object('topic', 'Clinical value', 'question',
      'What clinical data exists for this device itself, as opposed to data from its predicates?'));
  if pattern = 'line extension' then
    vq := vq || jsonb_build_array(jsonb_build_object('topic', 'Clinical value', 'question',
      'If this replaces the company''s earlier version, will the earlier version stay available and on contract, and for how long?'));
  end if;
  vq := vq || jsonb_build_array(
    jsonb_build_object('topic', 'Pricing and contracting', 'question',
      'How does pricing compare with its predicates and the peer devices already on contract here?'),
    jsonb_build_object('topic', 'Pricing and contracting', 'question',
      'Is it on our GPO or IDN agreement? Will it price into an existing category tier, or does it need a new line item?'),
    jsonb_build_object('topic', 'Pricing and contracting', 'question',
      case when pcode.kind = 'capital equipment'
           then 'What is the acquisition model (purchase, lease, placement or per-procedure fee), and what are the service, software and disposable costs over the term?'
           else 'Does it need any capital, software or dedicated instruments? If yes, how are they priced?' end),
    jsonb_build_object('topic', 'Supply, quality and disclosure', 'question',
      'How are sets supplied (consigned, loaner or sterile-packed), how many trays per case, and what are the lead times and rep coverage?'),
    jsonb_build_object('topic', 'Supply, quality and disclosure', 'question',
      'Is every item listed in FDA''s GUDID with a UDI-DI, so we can load it into our item master?'),
    jsonb_build_object('topic', 'Supply, quality and disclosure', 'question',
      'Have this device or its predicates had recalls, field safety notices or adverse-event trends?'),
    jsonb_build_object('topic', 'Supply, quality and disclosure', 'question',
      'Does the requesting surgeon have a financial relationship with the company (consulting, royalties, ownership or research funding)? CMS Open Payments shows reported payments.'));

  return jsonb_build_object(
    'found', true,
    'device', to_jsonb(dev),
    'product_code', to_jsonb(pcode),
    'ifu', to_jsonb(ifu),
    'pattern', pattern,
    'direct_predicates', direct,
    'lineage', lineage,
    'peers', peers,
    'category', cat,
    'questions', q,
    'vac_questions', vq
  );
end
$$;

create or replace function pc_compare(a text, b text)
returns jsonb
language plpgsql stable
as $$
declare
  ka text := upper(regexp_replace(coalesce(a, ''), '[\s\-]', '', 'g'));
  kb text := upper(regexp_replace(coalesce(b, ''), '[\s\-]', '', 'g'));
  la jsonb;
  lb jsonb;
  shared jsonb;
  direct_shared jsonb;
  da pc_devices;
  db pc_devices;
  verdict text;
begin
  select * into da from pc_devices where knumber = ka;
  select * into db from pc_devices where knumber = kb;
  la := pc_lookup(array[ka], 10);
  lb := pc_lookup(array[kb], 10);
  with na as (select n->>'knumber' k, (n->>'generation')::int g from jsonb_array_elements(la->'nodes') n),
       nb as (select n->>'knumber' k, (n->>'generation')::int g from jsonb_array_elements(lb->'nodes') n)
  select coalesce(jsonb_agg(jsonb_build_object('knumber', na.k, 'gen_a', na.g, 'gen_b', nb.g,
                    'device_name', d.device_name, 'applicant', d.applicant, 'decision_year', d.decision_year)
                    order by greatest(na.g, nb.g), na.g + nb.g, na.k), '[]'::jsonb)
    into shared
    from na join nb on nb.k = na.k
    left join pc_devices d on d.knumber = na.k
   where na.k not in (ka, kb);
  select coalesce(jsonb_agg(x), '[]'::jsonb) into direct_shared
    from (select s from jsonb_array_elements(shared) s where (s->>'gen_a')::int = 1 and (s->>'gen_b')::int = 1) t(x);
  verdict := case
    when ka = any(array(select n->>'knumber' from jsonb_array_elements(lb->'nodes') n)) then kb || ' traces back to ' || ka || '.'
    when kb = any(array(select n->>'knumber' from jsonb_array_elements(la->'nodes') n)) then ka || ' traces back to ' || kb || '.'
    when jsonb_array_length(direct_shared) > 0 then 'Both were cleared against the same predicate(s): '
         || (select string_agg(x->>'knumber', ', ') from jsonb_array_elements(direct_shared) x) || '.'
    when jsonb_array_length(shared) > 0 then 'They share ancestry: nearest common ancestor '
         || (shared->0->>'knumber') || ' (' || (shared->0->>'gen_a') || ' generation(s) back for ' || ka || ', '
         || (shared->0->>'gen_b') || ' for ' || kb || ').'
    else 'No shared ancestry on record within 10 generations.' end;
  return jsonb_build_object(
    'a', to_jsonb(da), 'b', to_jsonb(db),
    'same_product_code', da.product_code is not null and da.product_code = db.product_code,
    'same_company', pc_same_company(da.applicant, da.company_root, db.applicant, db.company_root,
                                    greatest(nullif(da.decision_date, '')::date, nullif(db.decision_date, '')::date)),
    'verdict', verdict,
    'direct_shared', direct_shared,
    'shared_ancestors', shared,
    'shared_count', jsonb_array_length(shared)
  );
end
$$;

create or replace function pc_batch(ks text[])
returns jsonb
language sql stable
as $$
  with input as (
    select distinct on (kn) kn, ord
      from (select upper(regexp_replace(x, '[\s\-]', '', 'g')) kn, ord
              from unnest(ks) with ordinality t(x, ord) where trim(x) <> '') s
     order by kn, ord
     limit 50
  )
  select coalesce(jsonb_agg(jsonb_build_object(
    'knumber', i.kn,
    'found', d.knumber is not null,
    'device_name', d.device_name,
    'applicant', d.applicant,
    'decision_year', d.decision_year,
    'product_code', d.product_code,
    'plain_name', pc.plain_name,
    'pattern', case when d.knumber is null then 'not in database'
                    when s.n = 0 or s.n is null then 'no numbered predicate'
                    when s.n_same = s.n then 'line extension'
                    when s.n_same = 0 then 'competitive entry' else 'mixed' end,
    'direct_predicates', coalesce(s.n, 0),
    'primary_predicate', s.primary_pred,
    'stop_reason', d.stop_reason,
    'summary_url', d.summary_url
  ) order by i.ord), '[]'::jsonb)
  from input i
  left join pc_devices d on d.knumber = i.kn
  left join pc_product_codes pc on pc.product_code = d.product_code
  left join lateral (
    select count(*) n, count(*) filter (where x.same_company) n_same,
           (select y.predicate || ' ' || coalesce(y.device_name, '') || ' (' || coalesce(y.applicant, '?') || ', '
                   || coalesce(y.decision_year, '?') || ')'
              from pc_direct(i.kn) y order by (y.role = 'primary') desc, y.list_order limit 1) primary_pred
      from pc_direct(i.kn) x
  ) s on true
$$;

grant execute on function pc_search(text, int), pc_brand_family(text), pc_lookup(text[], int) to anon, authenticated;
grant execute on function pc_direct(text), pc_category(text), pc_peers(text, int), pc_primary_lineage(text, int), pc_brief(text),
  pc_compare(text, text), pc_batch(text[]) to anon, authenticated;
grant execute on function pc_brief(text) to anon, authenticated;
