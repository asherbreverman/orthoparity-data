-- OrthoParity database: vendor search, portfolio, vendor brief, compare and product payments
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.

-- Page cache (Phase 4). The heavy page functions below keep a copy of each answer in pc_cache, so a repeat visit
-- reads one row instead of recomputing. Every SQL file in this folder empties the cache when it finishes, and so
-- does 07_after_import.sql, so the cache never outlives the data or the rules that made it. It holds at most 8,000 answers (about
-- 100 MB) to stay well inside the Supabase Free plan's 500 MB; past that, pages still work, just uncached.
create table if not exists pc_cache (
  fn text not null, arg text not null, payload jsonb not null, made timestamptz not null default now(),
  primary key (fn, arg));
alter table pc_cache enable row level security;
revoke all on pc_cache from anon, authenticated;

-- Benchmark a vendor always means the parent company (current owner, with every acquired or merged company's
-- history). The m argument stays for older callers and is ignored.
create or replace function pc_mode(m text) returns text language sql immutable as
$$ select 'current'::text $$;

-- parent company of any vendor: its current owner after every sourced acquisition, merger or divestiture
create or replace function pc_vendor_parent(v text) returns text language sql stable as $$
  select coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) from pc_vendors x where x.vendor_id = v
$$;

-- one step up the ownership chain, with the sourced event that links them
create or replace function pc_vendor_step(v text) returns jsonb language sql stable as $$
  select jsonb_build_object('vendor_id', l.vendor_id, 'name', c.display_name, 'parent', l.parent, 'parent_name', p.display_name,
                            'relation', l.relation, 'date', l.valid_from, 'source_url', l.source_url)
  from pc_vendor_lineage l join pc_vendors c on c.vendor_id = l.vendor_id join pc_vendors p on p.vendor_id = l.parent
  where l.vendor_id = v and l.valid_to is null
    and l.relation in ('acquired by', 'merged into', 'owned by', 'hardware and biologics assets acquired by', 'became part of')
  order by l.valid_from desc nulls last limit 1
$$;

-- what the site shows when someone opens a company that is part of another: where to go and why
create or replace function pc_vendor_resolve(v text) returns jsonb language plpgsql stable as $$
declare top text := pc_vendor_parent(v); cur text := v; st jsonb; steps jsonb := '[]'::jsonb; msg text := ''; i int := 0;
begin
  if top is null then
    return jsonb_build_object('found', false, 'requested', v);
  end if;
  while cur <> top and i < 4 loop
    st := pc_vendor_step(cur);
    exit when st is null;
    steps := steps || st;
    msg := msg || case when i = 0 then '' else ', which ' end
           || case when i = 0 then (st->>'name') || ' ' else '' end
           || case st->>'relation' when 'acquired by' then 'was acquired by ' when 'merged into' then 'merged into '
                   when 'owned by' then 'is owned by ' when 'became part of' then 'became part of '
                   else 'became part of ' end
           || (st->>'parent_name') || coalesce(' on ' || (st->>'date'), '');
    cur := st->>'parent'; i := i + 1;
  end loop;
  return jsonb_build_object(
    'found', true, 'requested', v, 'requested_name', (select display_name from pc_vendors where vendor_id = v),
    'vendor_id', top, 'name', (select display_name from pc_vendors where vendor_id = top),
    'redirected', top <> v, 'steps', steps, 'event', case when msg <> '' then rtrim(msg, '.') || '.' end,
    'explanation', case when top <> v and msg <> '' then rtrim(msg, '.') || '. OrthoParity benchmarks the parent company, so this page covers '
                                                       || (select display_name from pc_vendors where vendor_id = top) || ' and every company it owns.'
                        when top <> v then (select display_name from pc_vendors where vendor_id = v) || ' is part of '
                                           || (select display_name from pc_vendors where vendor_id = top) || '.' end);
end $$;

-- vendors included under v: itself plus vendors that roll up to it (acquired companies)
create or replace function pc_vendor_family(v text, m text)
returns table (vendor_id text, display_name text, since date, relation text, source_url text)
language sql stable as $$
  select x.vendor_id, x.display_name, null::date, 'self', null from pc_vendors x where x.vendor_id = v
  union all
  select c.vendor_id, c.display_name, l.valid_from, l.relation, l.source_url
  from pc_vendors c left join pc_vendor_lineage l on l.vendor_id = c.vendor_id and l.parent = v
  where c.rolls_up_to = v and c.vendor_id <> v
$$;

create or replace function pc_vendor_search(q text, lim int default 20)
returns jsonb language sql stable as $$
  with term as (select lower(trim(coalesce(q, ''))) as t),
  hits as (
    select v.vendor_id, max(case when lower(v.display_name) = t.t then 3
                                 when lower(v.display_name) like t.t || '%' then 2
                                 when lower(v.display_name) like '%' || t.t || '%' then 1.5
                                 when lower(n.raw_name) like '%' || t.t || '%' then 1
                                 else word_similarity(t.t, lower(n.raw_name)) end) as score,
           (array_agg(n.raw_name order by word_similarity(t.t, lower(n.raw_name)) desc))[1] as matched_name
    from term t, pc_vendors v join pc_vendor_names n on n.vendor_id = v.vendor_id
    where length(t.t) >= 2
      and (lower(v.display_name) like '%' || t.t || '%' or lower(n.raw_name) like '%' || t.t || '%'
           or word_similarity(t.t, lower(n.raw_name)) >= 0.45)
    group by v.vendor_id),
  -- every hit counts for its parent company; keep the best-scoring way in
  by_parent as (
    select distinct on (pc_vendor_parent(h.vendor_id)) pc_vendor_parent(h.vendor_id) as parent, h.vendor_id as via, h.score,
           h.matched_name
    from hits h order by pc_vendor_parent(h.vendor_id), h.score desc, (h.vendor_id = pc_vendor_parent(h.vendor_id)) desc)
  select coalesce(jsonb_agg(jsonb_build_object(
           'vendor_id', v.vendor_id, 'display_name', v.display_name, 'current_parent', v.current_parent,
           'segment', v.segment,
           'clearances', (select coalesce(sum(x.clearances), 0) from pc_vendors x
                           where x.vendor_id = v.vendor_id or x.rolls_up_to = v.vendor_id),
           'matched_name', b.matched_name,
           'via_vendor_id', case when b.via <> b.parent then b.via end,
           'via_name', case when b.via <> b.parent then (select x.display_name from pc_vendors x where x.vendor_id = b.via) end,
           'payments_2025', (select total from pc_op_vendor_profile pr where pr.vendor_id = v.vendor_id and pr.mode = 'current' and pr.year = 2025))
         order by b.score desc, (select coalesce(sum(x.clearances), 0) from pc_vendors x where x.vendor_id = v.vendor_id or x.rolls_up_to = v.vendor_id) desc), '[]'::jsonb)
  from (select * from by_parent order by score desc limit lim) b join pc_vendors v on v.vendor_id = b.parent
$$;

-- product pages: who filed the 510(k) and which parent company owns that product line now
create or replace function pc_device_owner(k text) returns jsonb language plpgsql stable as $$
begin
  -- Phase 3: plpgsql so it can call pc_co (05) for a clean filer name; the raw FDA name stays in filer_raw
  return (
  with d as (select p.knumber, p.applicant, p.vendor_id from pc_portfolio_510k p
             where p.knumber = upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g')) limit 1),
  f as (select d.*, pc_applicant_vendor(d.applicant) as filer_vendor, pc_vendor_parent(d.vendor_id) as owner from d)
  select case when f.knumber is null then jsonb_build_object('found', false) else jsonb_build_object(
    'found', true, 'knumber', f.knumber,
    -- clean filer name; when it names the same company as today's owner (only the legal suffix or casing differs),
    -- use the owner's exact name so the page never prints "X, now part of X"
    'filer', case when regexp_replace(lower(pc_co(f.applicant)), '[^a-z0-9]', '', 'g')
                       = regexp_replace(lower(pc_co((select display_name from pc_vendors where vendor_id = f.owner))), '[^a-z0-9]', '', 'g')
                  then (select display_name from pc_vendors where vendor_id = f.owner)
                  else coalesce(pc_co(f.applicant), f.applicant) end,
    'filer_raw', f.applicant, 'filer_vendor_id', f.filer_vendor,
    'owner_vendor_id', f.owner, 'owner_name', (select display_name from pc_vendors where vendor_id = f.owner),
    'now_part_of', coalesce(f.filer_vendor, f.vendor_id) is distinct from f.owner,
    'divested', f.vendor_id is distinct from coalesce(f.filer_vendor, f.vendor_id),
    'explanation', case when f.vendor_id is distinct from coalesce(f.filer_vendor, f.vendor_id)
                          then (select 'This product line was sold to ' || x.display_name || coalesce(' on ' || dv.effective, '') || '.'
                                from pc_vendors x left join pc_vendor_divestitures dv on dv.buyer = f.vendor_id and dv.seller = f.filer_vendor
                                where x.vendor_id = f.vendor_id limit 1)
                        when coalesce(f.filer_vendor, f.vendor_id) is distinct from f.owner
                          then (pc_vendor_resolve(coalesce(f.filer_vendor, f.vendor_id))->>'event') end,
    'source_url', (select dv.source_url from pc_vendor_divestitures dv where dv.buyer = f.vendor_id and dv.seller = f.filer_vendor limit 1))
  end from (select 1) one left join f on true);
end $$;

create or replace function pc_vendor_portfolio(v text, m text default 'pit', p_anatomy text default null,
                                               p_kind text default null, p_code text default null, lim int default 500)
returns jsonb language sql stable as $$
  with fam as (select vendor_id from pc_vendor_family(v, m) where pc_mode(m) = 'current' or vendor_id = v)
  select coalesce(jsonb_agg(r order by r.decision_date desc), '[]'::jsonb) from (
    select p.knumber, p.device_name, p.applicant, p.product_code, p.decision_date, p.gudid_brand, p.gudid_devices,
           p.gudid_in_distribution, c.plain_name, c.fda_name, c.anatomy, c.kind, c.device_class, c.segment,
           c.reviewed as plain_reviewed, (select x.display_name from pc_vendors x where x.vendor_id = p.vendor_id) as vendor
    from pc_portfolio_510k p join fam f on f.vendor_id = p.vendor_id
    left join pc_product_codes c on c.product_code = p.product_code
    where (p_anatomy is null or c.anatomy ilike '%' || p_anatomy || '%')
      and (p_kind is null or c.kind = p_kind)
      and (p_code is null or p.product_code = upper(p_code))
    order by p.decision_date desc limit lim) r
$$;

create or replace function pc_vendor_brief_live(v text, m text default 'pit')
returns jsonb language plpgsql stable as $$
declare
  md text := pc_mode(m);
  ven pc_vendors;
  latest int;
  fam jsonb; names jsonb; port jsonb; cats jsonb; brands jsonb; recent jsonb;
  years jsonb; mix_all jsonb; mix_latest jsonb; prof_all jsonb; prof_latest jsonb; peers jsonb;
  ents jsonb; prods jsonb; research jsonb; own jsonb; q jsonb := '[]'::jsonb;
  n_codes int; royalty_share double precision; ent_share double precision; max_holders int; discontinued int;
  acq record;
begin
  select * into ven from pc_vendors where vendor_id = v;
  if ven.vendor_id is null then return jsonb_build_object('found', false, 'vendor_id', v); end if;

  select coalesce(jsonb_agg(to_jsonb(f) order by f.since nulls first), '[]'::jsonb) into fam from pc_vendor_family(v, md) f;
  select coalesce(jsonb_agg(jsonb_build_object('source', source, 'name', raw_name) order by source, raw_name), '[]'::jsonb)
    into names from pc_vendor_names n
    where n.vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);

  -- portfolio summary
  with p as (select p.*, c.plain_name, c.fda_name, c.anatomy, c.kind, c.device_class
             from pc_portfolio_510k p left join pc_product_codes c on c.product_code = p.product_code
             where p.vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v))
  select jsonb_build_object('clearances', count(*), 'product_codes', count(distinct product_code),
           'first_year', min(extract(year from decision_date))::int, 'last_year', max(extract(year from decision_date))::int,
           'last5_clearances', count(*) filter (where decision_date >= (select max(decision_date) from pc_portfolio_510k) - interval '5 years')),
         count(distinct product_code)
    into port, n_codes from p;
  with p as (select p.product_code, c.plain_name, c.fda_name, c.anatomy, c.kind, c.device_class, p.decision_date
             from pc_portfolio_510k p left join pc_product_codes c on c.product_code = p.product_code
             where p.vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v)),
       mk as (select product_code, count(*) filter (where decision_date >= (select max(decision_date) from pc_portfolio_510k) - interval '5 years') as all5
               from pc_portfolio_510k group by 1)
  select coalesce(jsonb_agg(x order by x.clearances desc), '[]'::jsonb) into cats from (
    select p.product_code, max(p.plain_name) as plain_name, max(p.fda_name) as fda_name, max(p.anatomy) as anatomy,
           max(p.kind) as kind, max(p.device_class) as device_class, count(*) as clearances,
           max(p.decision_date) as latest,
           count(*) filter (where p.decision_date >= (select max(decision_date) from pc_portfolio_510k) - interval '5 years') as last5,
           round(100.0 * count(*) filter (where p.decision_date >= (select max(decision_date) from pc_portfolio_510k) - interval '5 years')
                 / nullif(max(mk.all5), 0), 1) as share_last5_pct
    from p left join mk on mk.product_code = p.product_code group by p.product_code) x;
  select jsonb_build_object('brands', count(*), 'devices', coalesce(sum(devices), 0),
                            'in_distribution', coalesce(sum(in_distribution), 0)),
         count(*) filter (where devices > 0 and in_distribution = 0)
    into brands, discontinued
    from pc_portfolio_brands where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);
  select coalesce(jsonb_agg(r), '[]'::jsonb) into recent from (
    select p.knumber, p.device_name, p.decision_date, p.product_code, c.plain_name
    from pc_portfolio_510k p left join pc_product_codes c on c.product_code = p.product_code
    where p.vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v)
    order by p.decision_date desc limit 8) r;

  -- payments
  select max(year) into latest from pc_op_vendor_profile where vendor_id = v and mode = md and year > 0;
  select coalesce(jsonb_agg(jsonb_build_object('year', year, 'nature_group', nature_group, 'amount', amount,
                                               'transactions', transactions, 'recipients', recipients) order by year, amount desc), '[]'::jsonb)
    into years from pc_op_vendor_year where vendor_id = v and mode = md;
  select coalesce(jsonb_agg(jsonb_build_object('nature_group', nature_group, 'amount', a, 'transactions', t) order by a desc), '[]'::jsonb)
    into mix_all from (select nature_group, sum(amount) a, sum(transactions) t from pc_op_vendor_year
                       where vendor_id = v and mode = md group by 1) s;
  select coalesce(jsonb_agg(jsonb_build_object('nature_group', nature_group, 'amount', amount, 'transactions', transactions,
                                               'recipients', recipients) order by amount desc), '[]'::jsonb)
    into mix_latest from pc_op_vendor_year where vendor_id = v and mode = md and year = latest;
  select to_jsonb(p) - 'mode' - 'vendor_id' into prof_all from pc_op_vendor_profile p where vendor_id = v and mode = md and year = 0;
  select to_jsonb(p) - 'mode' - 'vendor_id' into prof_latest from pc_op_vendor_profile p where vendor_id = v and mode = md and year = latest;
  select coalesce(jsonb_agg(x order by x.total desc), '[]'::jsonb) into peers from (
    select p.vendor_id, x.display_name, p.total, p.physicians, p.recipients,
           round((p.total / nullif(p.recipients, 0))::numeric, 0) as per_recipient, p.vendor_id = v as is_this
    from pc_op_vendor_profile p join pc_vendors x on x.vendor_id = p.vendor_id
    where p.mode = md and p.year = coalesce(latest, 2025) and (p.vendor_id = v or p.vendor_id in (
      select vendor_id from pc_op_vendor_profile where mode = md and year = coalesce(latest, 2025) order by total desc limit 50))) x;
  select coalesce(jsonb_agg(x order by x.amount desc), '[]'::jsonb) into ents from (
    select e.payer_name, sum(e.amount) as amount, max(e.recipients) as max_recipients_in_a_year,
           min(e.year) as first_year, max(e.year) as last_year,
           round((100 * coalesce(sum(e.royalty), 0) / nullif(sum(e.amount), 0))::numeric, 1) as royalty_pct,
           round((100 * coalesce(sum(e.food), 0) / nullif(sum(e.amount), 0))::numeric, 1) as food_pct,
           case when coalesce(sum(e.royalty), 0) >= 0.5 * sum(e.amount) and coalesce(sum(e.food), 0) < 0.02 * sum(e.amount)
                  then 'Royalty-led'
                when coalesce(sum(e.food), 0) >= 0.2 * sum(e.amount) then 'Field organization'
                else 'Mixed' end as profile
    from pc_op_entity e where (md = 'pit' and e.vendor_pit = v) or (md = 'current' and e.vendor_current = v)
    group by e.payer_name) x;
  select coalesce(jsonb_agg(to_jsonb(t) - 'mode' - 'vendor_id' order by t.rank), '[]'::jsonb) into prods
    from (select * from pc_op_product_top where vendor_id = v and mode = md order by rank limit 10) t;
  select jsonb_build_object(
           'by_year', (select coalesce(jsonb_agg(jsonb_build_object('year', year, 'amount', a) order by year), '[]'::jsonb)
                       from (select year, sum(amount) a from pc_op_research r
                             where ((md = 'pit' and r.vendor_pit = v) or (md = 'current' and r.vendor_current = v))
                               and coalesce(r.ortho, true) group by year) s),
           'top_studies', (select coalesce(jsonb_agg(s order by s.amount desc), '[]'::jsonb) from (
                            select study_name, max(ct_gov_id) as ct_gov_id, sum(amount) as amount, sum(payments) as payments,
                                   min(year) as first_year, max(year) as last_year, bool_or(preclinical) as preclinical,
                                   max(knumbers) as knumbers
                            from pc_op_research r where ((md = 'pit' and r.vendor_pit = v) or (md = 'current' and r.vendor_current = v))
                              and coalesce(r.ortho, true)
                            group by study_name order by sum(amount) desc limit 10) s))
    into research;
  select coalesce(jsonb_agg(jsonb_build_object('year', year, 'holders', h, 'invested', i, 'value', val) order by year), '[]'::jsonb),
         max(h)
    into own, max_holders
    from (select year, sum(holders) h, sum(invested) i, sum(value) val from pc_op_ownership o
          where (md = 'pit' and o.vendor_pit = v) or (md = 'current' and o.vendor_current = v) group by year) s;

  -- rule-based vendor questions
  if n_codes >= 12 then
    q := q || to_jsonb(ven.display_name || ' has orthopedic 510(k)s in ' || n_codes
         || ' product codes. Which categories would you include in a portfolio or bundled agreement, and what pricing applies if we consolidate?');
  end if;
  select sum(amount) filter (where nature_group = 'royalty') / nullif(sum(amount), 0) into royalty_share
    from pc_op_vendor_year where vendor_id = v and mode = md;
  if royalty_share > 0.5 then
    q := q || to_jsonb(round((100 * royalty_share)::numeric) || '% of ' || ven.display_name
         || '''s reported payments since 2019 are royalties. Are any surgeons at our facility royalty holders or design surgeons on the products requested, and how is that handled in our approval process?');
  end if;
  if coalesce((prof_latest ->> 'consulting_r')::int, 0) > 0 then
    q := q || to_jsonb(ven.display_name || ' paid consulting fees to ' || (prof_latest ->> 'consulting_r') || ' recipients in ' || latest
         || '. Which of your consultants practice at our facility, and are those relationships disclosed to our committee?');
  end if;
  ent_share := (prof_all ->> 'to_entities')::double precision / nullif((prof_all ->> 'total')::double precision, 0);
  if ent_share >= 0.2 then
    q := q || to_jsonb(round((100 * ent_share)::numeric) || '% of payments since 2019 went to business entities (LLCs or practices) rather than individuals. Are any of those entities owned by surgeons who practice here?');
  end if;
  if coalesce(max_holders, 0) > 0 then
    q := q || to_jsonb('Up to ' || max_holders || ' physicians in a year reported an ownership or investment interest in ' || ven.display_name
         || '. Do any of them practice at our facility or request its products?');
  end if;
  for acq in select c.display_name, l.valid_from from pc_vendor_lineage l join pc_vendors c on c.vendor_id = l.vendor_id
             where l.parent = v and l.valid_from >= current_date - interval '3 years' order by l.valid_from loop
    q := q || to_jsonb(ven.display_name || ' acquired ' || acq.display_name || ' on ' || to_char(acq.valid_from, 'Mon DD, YYYY')
         || '. Which acquired product lines will continue, and what happens to contract pricing and instrument sets for any that are discontinued?');
  end loop;
  if coalesce(discontinued, 0) > 0 then
    q := q || to_jsonb(discontinued || ' of ' || ven.display_name || '''s orthopedic brands in GUDID list no devices in commercial distribution. Is every line you are proposing in full distribution, and what are the supply commitments?');
  end if;

  return jsonb_build_object(
    'found', true, 'mode', md, 'vendor', to_jsonb(ven), 'family', fam, 'names', names,
    'rolled_into', case when md = 'current' and ven.rolls_up_to is not null and ven.rolls_up_to <> v then
                     jsonb_build_object('vendor_id', ven.rolls_up_to,
                                        'display_name', (select display_name from pc_vendors where vendor_id = ven.rolls_up_to))
                   end,
    'portfolio', port || jsonb_build_object('gudid', brands), 'categories', cats, 'recent_clearances', recent,
    'payments', jsonb_build_object('latest_year', latest, 'by_year', years, 'mix_all_years', mix_all,
                                   'mix_latest', mix_latest, 'profile_all_years', prof_all, 'profile_latest', prof_latest,
                                   'peers_latest', peers, 'entities', ents, 'top_products', prods),
    'research', research, 'ownership', own, 'questions', q);
end $$;

create or replace function pc_vendor_compare(a text, b text, m text default 'pit')
returns jsonb language plpgsql stable as $$
declare
  md text := pc_mode(m);
  va pc_vendors; vb pc_vendors;
  codes jsonb; n_shared int; n_a int; n_b int; pa jsonb; pb jsonb; mixa jsonb; mixb jsonb; latest int;
  shared_all int; shared_latest int; rel_a int; rel_b int; top_shared text;
begin
  select * into va from pc_vendors where vendor_id = a;
  select * into vb from pc_vendors where vendor_id = b;
  if va.vendor_id is null or vb.vendor_id is null then
    return jsonb_build_object('found', false);
  end if;
  with ca as (select p.product_code, count(*) n from pc_portfolio_510k p
              where p.vendor_id in (select vendor_id from pc_vendor_family(a, md) where md = 'current' or vendor_id = a) group by 1),
       cb as (select p.product_code, count(*) n from pc_portfolio_510k p
              where p.vendor_id in (select vendor_id from pc_vendor_family(b, md) where md = 'current' or vendor_id = b) group by 1),
       j as (select coalesce(ca.product_code, cb.product_code) as product_code, coalesce(ca.n, 0) as a_clearances,
                    coalesce(cb.n, 0) as b_clearances,
                    case when ca.n > 0 and cb.n > 0 then 'both' when ca.n > 0 then 'only_a' else 'only_b' end as side
             from ca full join cb on ca.product_code = cb.product_code)
  select coalesce(jsonb_agg(jsonb_build_object('product_code', j.product_code, 'plain_name', c.plain_name,
                                               'fda_name', c.fda_name, 'anatomy', c.anatomy, 'kind', c.kind,
                                               'a_clearances', j.a_clearances, 'b_clearances', j.b_clearances, 'side', j.side)
                            order by j.side, j.a_clearances + j.b_clearances desc), '[]'::jsonb),
         count(*) filter (where side = 'both'), count(*) filter (where side = 'only_a'), count(*) filter (where side = 'only_b'),
         (array_agg(coalesce(c.plain_name, c.fda_name, j.product_code) order by j.a_clearances + j.b_clearances desc)
            filter (where side = 'both'))[1]
    into codes, n_shared, n_a, n_b, top_shared
    from j left join pc_product_codes c on c.product_code = j.product_code;

  select least(max(year) filter (where vendor_id = a), max(year) filter (where vendor_id = b)) into latest
    from pc_op_vendor_profile where mode = md and year > 0 and vendor_id in (a, b);
  select to_jsonb(p) - 'mode' into pa from pc_op_vendor_profile p where vendor_id = a and mode = md and year = latest;
  select to_jsonb(p) - 'mode' into pb from pc_op_vendor_profile p where vendor_id = b and mode = md and year = latest;
  select coalesce(jsonb_agg(jsonb_build_object('nature_group', nature_group, 'amount', s) order by s desc), '[]'::jsonb) into mixa
    from (select nature_group, sum(amount) s from pc_op_vendor_year where vendor_id = a and mode = md group by 1) x;
  select coalesce(jsonb_agg(jsonb_build_object('nature_group', nature_group, 'amount', s) order by s desc), '[]'::jsonb) into mixb
    from (select nature_group, sum(amount) s from pc_op_vendor_year where vendor_id = b and mode = md group by 1) x;

  select count(*) into shared_all from (
    select rkey from pc_op_relationship where mode = md and vendor_id = a
    intersect select rkey from pc_op_relationship where mode = md and vendor_id = b) s;
  select count(*) into shared_latest from (
    select rkey from pc_op_relationship where mode = md and vendor_id = a and year = latest
    intersect select rkey from pc_op_relationship where mode = md and vendor_id = b and year = latest) s;
  select count(distinct rkey) into rel_a from pc_op_relationship where mode = md and vendor_id = a;
  select count(distinct rkey) into rel_b from pc_op_relationship where mode = md and vendor_id = b;

  return jsonb_build_object(
    'found', true, 'mode', md, 'a', to_jsonb(va), 'b', to_jsonb(vb),
    'verdict', case when n_shared = 0 then va.display_name || ' and ' || vb.display_name || ' share no orthopedic product codes.'
                    else 'They overlap in ' || n_shared || ' product code' || case when n_shared = 1 then '' else 's' end
                         || coalesce(', led by ' || top_shared, '') || '. ' || va.display_name || ' also covers ' || n_a
                         || ' code' || case when n_a = 1 then '' else 's' end || ' that ' || vb.display_name || ' doesn''t, and '
                         || vb.display_name || ' covers ' || n_b || ' that ' || va.display_name || ' doesn''t.' end,
    'codes', codes, 'shared_codes', n_shared, 'only_a', n_a, 'only_b', n_b,
    'payments', jsonb_build_object('year', latest, 'a', pa, 'b', pb, 'mix_a', mixa, 'mix_b', mixb),
    'shared_surgeons', jsonb_build_object('all_years', shared_all, 'latest_year', shared_latest,
                                          'a_relationships', rel_a, 'b_relationships', rel_b,
                                          'definition', 'Recipients with consulting, royalty, speaking or services payments from both vendors, 2019 to 2025. Meals and travel do not count.'),
    'questions', jsonb_build_array(
      'If we consolidate in the shared categories, which instrument sets, consignment inventory and surgeon training would change?',
      'How would pricing compare across the ' || coalesce(n_shared, 0) || ' shared product codes if one vendor became primary?'));
end $$;

create or replace function pc_product_payments(k text)
returns jsonb language plpgsql stable as $$
declare
  kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'));
  t1 jsonb; t2 jsonb; tot1 double precision; tot2 double precision; roy double precision; cons double precision;
  roy_r int; cons_r int; studies jsonb; code text; code_ctx jsonb; brand text; q jsonb := '[]'::jsonb;
begin
  select coalesce(jsonb_agg(jsonb_build_object('year', year, 'nature_group', nature_group, 'amount', amount,
                                               'transactions', transactions, 'recipients', recipients) order by year, amount desc), '[]'::jsonb),
         sum(amount)
    into t1, tot1 from pc_op_product where knumber = kn and tier = 1;
  select coalesce(jsonb_agg(jsonb_build_object('year', year, 'nature_group', nature_group, 'amount', amount,
                                               'transactions', transactions, 'recipients', recipients) order by year, amount desc), '[]'::jsonb),
         sum(amount)
    into t2, tot2 from pc_op_product where knumber = kn and tier = 2;
  select max(p.brand) into brand from pc_op_product p where p.knumber = kn;
  select sum(amount) filter (where nature_group = 'royalty'), sum(amount) filter (where nature_group = 'consulting'),
         max(recipients) filter (where nature_group = 'royalty'), max(recipients) filter (where nature_group = 'consulting')
    into roy, cons, roy_r, cons_r from pc_op_product where knumber = kn;
  select coalesce(jsonb_agg(s order by s.amount desc), '[]'::jsonb) into studies from (
    select study_name, max(ct_gov_id) as ct_gov_id, sum(amount) as amount, min(year) as first_year, max(year) as last_year
    from pc_op_research where ('|' || coalesce(knumbers, '') || '|') like '%|' || kn || '|%' and coalesce(ortho, true) group by study_name
    order by sum(amount) desc limit 200) s;
  select product_code into code from pc_devices where knumber = kn;
  if code is not null then
    with codek as (select knumber from pc_devices where product_code = code),
         per as (select p.knumber, sum(p.amount) a, sum(p.amount) filter (where p.nature_group = 'royalty') r
                 from pc_op_product p join codek using (knumber) where p.tier = 1 group by 1)
    select jsonb_build_object('product_code', code, 'products_with_payments', count(*),
                              'median_amount', percentile_cont(0.5) within group (order by a),
                              'royalty_pct', round((100 * sum(r) / nullif(sum(a), 0))::numeric, 1))
      into code_ctx from per;
  end if;
  if coalesce(roy, 0) > 0 then
    q := q || to_jsonb('Royalties are paid on this product (' || to_char(roy, 'FM$999,999,999,990') || ' since 2019, reported by the manufacturer). Are any requesting surgeons royalty recipients or design surgeons on it?');
  end if;
  if coalesce(cons, 0) > 0 then
    q := q || to_jsonb('Consulting fees name this product (' || to_char(cons, 'FM$999,999,999,990') || ' since 2019). Do any requesting surgeons consult for the company on it?');
  end if;
  return jsonb_build_object(
    'knumber', kn, 'brand', brand,
    'exact', jsonb_build_object('total', coalesce(tot1, 0), 'rows', t1,
                                'label', 'Payments whose device ID resolves to this 510(k) in GUDID (2021 to 2025)'),
    'brand_match', jsonb_build_object('total', coalesce(tot2, 0), 'rows', t2,
                                      'label', 'Payments naming this product''s brand without a device ID (mostly 2019 and 2020); shared with every 510(k) under the brand'),
    'royalty', coalesce(roy, 0), 'consulting', coalesce(cons, 0), 'royalty_recipients_max_year', roy_r,
    'consulting_recipients_max_year', cons_r, 'research', studies, 'code_context', code_ctx, 'questions', q,
    'note', 'A payment counts in full for every product it names, so product totals overlap. Payments with no product named are not included.');
end $$;

-- home page counts: parent companies with 510(k) clearances (a company another company owns counts under its parent)
create or replace function pc_vendor_coverage()
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'parent_companies', count(*) filter (where coalesce(rolls_up_to, vendor_id) = vendor_id),
    'filer_companies', count(*),
    'first_year', min(first_clearance_year), 'last_year', max(last_clearance_year))
  from pc_vendors where coalesce(clearances, 0) > 0
$$;

grant execute on function pc_vendor_parent(text), pc_vendor_step(text), pc_vendor_resolve(text), pc_device_owner(text),
  pc_vendor_coverage() to anon, authenticated;
grant execute on function pc_mode(text), pc_vendor_family(text, text), pc_vendor_search(text, int),
  pc_vendor_portfolio(text, text, text, text, text, int), pc_vendor_brief_live(text, text), pc_vendor_compare(text, text, text),
  pc_product_payments(text) to anon, authenticated;

-- pc_vendor_brief: cached front door for pc_vendor_brief_live (same name and arguments the website already calls).
create or replace function pc_vendor_brief(v text, m text default 'pit')
returns jsonb language plpgsql volatile security definer set search_path = public as $$
declare r jsonb; ck text := coalesce(v, '') || '|' || coalesce(m, 'pit');
begin
  select c.payload into r from pc_cache c where c.fn = 'pc_vendor_brief' and c.arg = ck;
  if found then return r; end if;
  r := pc_vendor_brief_live(v, m);
  if r is not null and (select count(*) from pc_cache) < 8000 and exists (select 1 from pc_vendors x where x.vendor_id = v) then
    begin
      insert into pc_cache (fn, arg, payload) values ('pc_vendor_brief', ck, r) on conflict do nothing;
    exception when others then null;  -- read-only call or a race: skip the save, still answer
    end;
  end if;
  return r;
end $$;
revoke execute on function pc_vendor_brief_live(text, text) from public, anon, authenticated;
grant execute on function pc_vendor_brief(text, text) to anon, authenticated;

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
