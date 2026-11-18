-- OrthoParity database: decision briefs (the product and vendor signal cards)
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.
-- Turns the data behind each product and vendor page into a short list of signals, each with a finding, why it
-- matters and what to ask. Fixed rules only: same input, same output.

create or replace function pc_money(x double precision) returns text language sql immutable as $$
  select case when x is null then null
              when abs(x) >= 1e9 then '$' || trim(to_char(x / 1e9, 'FM999990.0')) || 'B'
              when abs(x) >= 1e6 then '$' || trim(to_char(x / 1e6, 'FM999990.0')) || 'M'
              when abs(x) >= 1e4 then '$' || trim(to_char(x / 1e3, 'FM999990')) || 'K'
              when abs(x) >= 1e3 then '$' || trim(to_char(x / 1e3, 'FM990.0')) || 'K'
              else '$' || trim(to_char(x, 'FM999990')) end
$$;

-- latest clearance date in the data; "last five years" is measured back from here
create or replace function pc_data_end() returns date language sql stable as $$
  select max(decision_date) from pc_portfolio_510k
$$;

create or replace function pc_card(key text, question text, badge text, tone text, finding text, why text, ask text,
                                   evidence text default null)
returns jsonb language sql immutable as $$
  select jsonb_build_object('key', key, 'question', question, 'badge', badge, 'tone', tone,
                            'finding', finding, 'why', why, 'ask', ask, 'evidence', evidence)
$$;

create or replace function pc_fig(v text, label text) returns jsonb language sql immutable as $$
  select case when v is null then null else jsonb_build_object('value', v, 'label', label) end
$$;

create or replace function pc_num(n numeric) returns text language sql immutable as $$
  select case when n is null then null else to_char(n, 'FM999,999,999,990') end
$$;

-- array of non-null tiles
create or replace function pc_figs(variadic f jsonb[]) returns jsonb language sql immutable as $$
  select coalesce(jsonb_agg(x), '[]'::jsonb) from unnest(f) x where x is not null
$$;

create or replace function pc_signals(k text)
returns jsonb language plpgsql stable as $$
declare
  kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'));
  b jsonb; dev jsonb; pcode jsonb; lin jsonb;
  pattern text; company text; code text; plain text; vend text; owner text; owner_name text;
  n_direct int; n_same int; others text; prim text; gens int; lin_end text;
  data_end date; n_alt int; alts jsonb; alt_names text;
  tot double precision; roy double precision; cons double precision; yr_min int; yr_max int;
  n_st int; st_amt double precision; st_last int;
  skus int; skus_in int; med_skus double precision;
  cards jsonb := '[]'::jsonb; c_nov jsonb; c_alt jsonb; c_pay jsonb; c_ev jsonb; c_cat jsonb;
  bl text; crowd text;
begin
  b := pc_brief(kn);
  if not coalesce((b->>'found')::boolean, false) then
    return jsonb_build_object('found', false, 'knumber', kn);
  end if;
  dev := b->'device'; pcode := b->'product_code'; lin := b->'lineage';
  pattern := b->>'pattern';
  company := dev->>'applicant';
  code := dev->>'product_code';
  plain := coalesce(pcode->>'plain_name', pcode->>'fda_name', code);
  data_end := pc_data_end();

  select p.vendor_id, coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) into vend, owner
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id where p.knumber = kn;
  select display_name into owner_name from pc_vendors where vendor_id = owner;
  select coalesce(display_name, company) into company from pc_vendors where vendor_id = vend;
  company := coalesce(company, dev->>'applicant');

  -- 1. Is it new?
  select count(*), count(*) filter (where (e->>'same_company')::boolean),
         (array_agg(coalesce(e->>'device_name', '') || ' (' || (e->>'predicate') || ')') filter (where e->>'role' = 'primary'))[1],
         string_agg(distinct rtrim(e->>'applicant', '.'), ', ') filter (where not (e->>'same_company')::boolean)
    into n_direct, n_same, prim, others
    from jsonb_array_elements(coalesce(b->'direct_predicates', '[]'::jsonb)) e;
  gens := nullif(lin->>'generations', '')::int;
  if coalesce(gens, 0) > 1 then
    lin_end := ' The predicate record goes back ' || gens || ' generations to ' || coalesce(lin->'ends_at'->>'device_name', 'an earlier device')
               || ' (' || coalesce(lin->'ends_at'->>'applicant', 'unknown company') || ', ' || coalesce(lin->'ends_at'->>'decision_year', 'year unknown') || ').';
  else
    lin_end := '';
  end if;
  c_nov := case pattern
    when 'line extension' then pc_card('novelty', 'Is it new?', 'Line extension', 'info',
      'Cleared as equivalent to ' || n_direct || ' of ' || company || '''s own earlier device' || case when n_direct = 1 then '' else 's' end
        || coalesce(', led by ' || prim, '') || '.' || lin_end,
      'An update to a product line the company already sells. It often fits an existing contract tier rather than a new line item.',
      'What changed clinically or technically from the earlier version, and will the earlier version stay available and on contract?',
      'predicates')
    when 'competitive entry' then pc_card('novelty', 'Is it new?', 'Competitive entry', 'info',
      'Cleared as equivalent to devices from ' || coalesce(others, 'other companies') || '.' || lin_end,
      'The company is entering a category where other vendors'' devices set the benchmark. Compare it with what you already use.',
      'Which product on our shelf would this replace, and what does it do better?',
      'predicates')
    when 'mixed' then pc_card('novelty', 'Is it new?', 'Builds on own and others'' devices', 'info',
      'Cleared against ' || n_same || ' of ' || company || '''s own devices and ' || (n_direct - n_same) || ' from other companies ('
        || coalesce(others, 'not named') || ').' || lin_end,
      'Builds on the company''s own line and on features cleared for other vendors'' devices.',
      'Which features came from the other companies'' devices, and what evidence supports them?',
      'predicates')
    else pc_card('novelty', 'Is it new?', 'Predicate not on file', 'attention',
      'We could not read a predicate 510(k) number in the FDA record for this clearance.',
      'Novelty can''t be judged from the FDA record alone.',
      'Which devices did FDA clear it against, with their 510(k) numbers?',
      'predicates') end;

  -- 2. What else does this job? (other companies, same product code, last five years; grouped by current owner)
  with recent as (
    select coalesce(nullif(x.rolls_up_to, ''), x.vendor_id) as grp, p.knumber, p.device_name, p.decision_date
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id
    where p.product_code = code and p.decision_date > data_end - interval '5 years'),
  g as (
    select r.grp, count(*) as clearances,
           (array_agg(r.knumber order by r.decision_date desc))[1] as latest_knumber,
           (array_agg(r.device_name order by r.decision_date desc))[1] as latest_device,
           max(r.decision_date) as latest_date
    from recent r where r.grp is distinct from owner group by r.grp)
  select count(*),
         coalesce(jsonb_agg(jsonb_build_object('vendor_id', g.grp, 'company', v.display_name, 'clearances', g.clearances,
                                               'latest_knumber', g.latest_knumber, 'latest_device', g.latest_device,
                                               'latest_date', g.latest_date)
                            order by g.clearances desc, g.latest_date desc), '[]'::jsonb),
         (array_to_string((array_agg(rtrim(v.display_name, '.') order by g.clearances desc, g.latest_date desc))[1:3], ', '))
    into n_alt, alts, alt_names
    from g join pc_vendors v on v.vendor_id = g.grp;
  crowd := case when n_alt >= 20 then 'Crowded' when n_alt >= 5 then 'Competitive' when n_alt >= 1 then 'Few alternatives'
                else 'No recent alternatives' end;
  c_alt := pc_card('alternatives', 'What else does this job?', crowd, case when n_alt < 5 then 'attention' else 'info' end,
    case when n_alt > 0 then n_alt || ' other compan' || case when n_alt = 1 then 'y' else 'ies' end || ' cleared ' || plain
           || ' devices in the last five years of data, including ' || alt_names || '.'
         else 'No other company cleared a ' || plain || ' device in the last five years of data.' end,
    case when n_alt >= 20 then 'Plenty of substitutes. Standardizing on fewer vendors in this category is realistic.'
         when n_alt >= 5 then 'Several substitutes exist, so a head-to-head comparison is practical.'
         when n_alt >= 1 then 'Few substitutes. Supply continuity and backup options matter more.'
         else 'Little recent competition. Supply continuity matters more.' end,
    case when n_alt >= 5 then 'Which products we already contract for would this replace, and why this one?'
         else 'If supply is interrupted, what is the backup?' end,
    'alternatives');

  -- 3. Financial ties (CMS Open Payments, payments naming this 510(k) or its brand)
  select sum(amount), sum(amount) filter (where nature_group = 'royalty'), sum(amount) filter (where nature_group = 'consulting'),
         min(year), max(year)
    into tot, roy, cons, yr_min, yr_max
    from pc_op_product where knumber = kn;
  c_pay := pc_card('payments', 'Who has a financial tie to it?',
    case when coalesce(roy, 0) > 0 then 'Royalties paid' when coalesce(tot, 0) > 0 then 'Payments named' else 'None named' end,
    case when coalesce(roy, 0) > 0 then 'attention' else 'info' end,
    case when coalesce(tot, 0) > 0 then
           pc_money(tot) || ' in reported payments named this product' || case when yr_min = yr_max then ' in ' || yr_min
                                                                               else ' from ' || yr_min || ' to ' || yr_max end
           || case when coalesce(roy, 0) > 0 and coalesce(cons, 0) > 0 then ', including ' || pc_money(roy) || ' in royalties and ' || pc_money(cons) || ' in consulting.'
                   when coalesce(roy, 0) > 0 then ', including ' || pc_money(roy) || ' in royalties.'
                   when coalesce(cons, 0) > 0 then ', including ' || pc_money(cons) || ' in consulting. No royalties named it.'
                   else '. No royalties or consulting named it.' end
         else 'No Open Payments records from 2019 to 2025 name this 510(k) or its brand.' end,
    case when coalesce(roy, 0) > 0 then 'Device royalties typically go to inventors and design surgeons. Your conflict-of-interest review should know if a requesting surgeon is one.'
         when coalesce(tot, 0) > 0 then 'Shows the company''s spending tied to this product. It says nothing about any one surgeon.'
         else 'Payments may still exist under the company without a product named.' end,
    'Does the requesting surgeon have a consulting, royalty, ownership or research relationship with ' || company || '?',
    'payments');

  -- 4. Evidence (industry-funded research in Open Payments that names this 510(k))
  select count(distinct study_name), sum(amount), max(year) into n_st, st_amt, st_last
    from pc_op_research
    where ('|' || coalesce(knumbers, '') || '|') like '%|' || kn || '|%' and coalesce(ortho, true);
  c_ev := pc_card('evidence', 'What evidence exists?',
    case when n_st > 0 then n_st || ' stud' || case when n_st = 1 then 'y' else 'ies' end else 'None linked' end,
    case when n_st > 0 then 'info' else 'attention' end,
    case when n_st > 0 then n_st || ' industry-funded research stud' || case when n_st = 1 then 'y names' else 'ies name' end
                            || ' this 510(k) (' || pc_money(st_amt) || ' reported, latest ' || st_last || ').'
         else 'No industry-funded research in Open Payments names this 510(k).' end,
    case when n_st > 0 then 'The company is collecting data on this device. Ask for results, not just enrollment.'
         else 'Evidence may rest on predicate devices or on studies outside Open Payments.' end,
    'What clinical data exists for this device itself, as opposed to its predicates?',
    'research');

  -- 5. Catalog size (FDA GUDID device IDs that cite this 510(k))
  select gudid_devices, gudid_in_distribution into skus, skus_in from pc_portfolio_510k where knumber = kn;
  select percentile_cont(0.5) within group (order by gudid_devices) into med_skus
    from pc_portfolio_510k where product_code = code and gudid_devices > 0;
  c_cat := pc_card('catalog', 'What will it take to stock?',
    case when coalesce(skus, 0) = 0 then 'Not in GUDID'
         when skus_in < skus then (skus - skus_in) || ' discontinued'
         else skus || ' catalog items' end,
    case when coalesce(skus, 0) = 0 or skus_in < skus then 'attention' else 'info' end,
    case when coalesce(skus, 0) > 0 then
           'FDA''s GUDID lists ' || skus || ' device IDs (catalog items) under this 510(k), ' || skus_in || ' in commercial distribution.'
           || coalesce(' The median for this category is ' || round(med_skus)::int || '.', '')
         else 'No GUDID device IDs cite this 510(k). Its labels may cite a later or earlier 510(k).' end,
    'Each device ID is a line in your item master. Larger catalogs mean more items to load, more trays and more inventory.',
    case when coalesce(skus, 0) > 0 then 'How many trays per case, and are sets loaner, consigned or sterile-packed?'
         else 'Is every item listed in GUDID with a UDI-DI we can load into our item master?' end,
    'catalog');

  -- short statement headlines for the page design (one per card)
  c_nov := c_nov || jsonb_build_object('headline', case pattern
             when 'line extension' then 'An update to its own line.'
             when 'competitive entry' then 'A new entry against other companies'' devices.'
             when 'mixed' then 'Built on its own and other companies'' designs.'
             else 'No predicate on file.' end);
  c_alt := c_alt || jsonb_build_object('headline', case when n_alt > 0
             then n_alt || ' other compan' || case when n_alt = 1 then 'y makes' else 'ies make' end || ' one.'
             else 'No recent competitors.' end);
  c_pay := c_pay || jsonb_build_object('headline', case
             when coalesce(roy, 0) > 0 then pc_money(tot) || ' in payments, including royalties.'
             when coalesce(tot, 0) > 0 then pc_money(tot) || ' in payments. No royalties.'
             else 'No payments name it.' end);
  c_ev := c_ev || jsonb_build_object('headline', case when n_st > 0
             then n_st || case when n_st = 1 then ' study names it.' else ' studies name it.' end
             else 'No studies name it.' end);
  c_cat := c_cat || jsonb_build_object('headline', case when coalesce(skus, 0) > 0
             then skus || ' catalog items.' else 'Not listed in GUDID.' end);
  -- stat tiles and short labels for the page design
  c_nov := c_nov || jsonb_build_object('short', 'Is it new?', 'figs', pc_figs(
             pc_fig(pc_num(n_same), 'of ' || company || '''s own devices'),
             pc_fig(pc_num(n_direct - n_same), 'from other companies'),
             pc_fig(pc_num(gens), 'generations on record'),
             pc_fig(lin->'ends_at'->>'decision_year', 'earliest predicate on record')));
  c_alt := c_alt || jsonb_build_object('short', 'What else does this job?', 'figs', pc_figs(
             pc_fig(pc_num(n_alt), 'other companies, last five years'),
             pc_fig(pc_num((b->'peers'->>'total')::numeric), 'peers on the same predicates'),
             pc_fig(pc_num((b->'category'->>'total')::numeric), 'clearances in ' || code)));
  c_pay := c_pay || jsonb_build_object('short', 'Financial ties', 'figs', case when coalesce(tot, 0) > 0 then pc_figs(
             pc_fig(pc_money(tot), 'in payments naming it, ' || yr_min || ' to ' || yr_max),
             case when coalesce(roy, 0) > 0 then pc_fig(pc_money(roy), 'royalties') end,
             case when coalesce(cons, 0) > 0 then pc_fig(pc_money(cons), 'consulting') end)
           else pc_figs(pc_fig('0', 'Open Payments records naming it, 2019 to 2025')) end);
  c_ev := c_ev || jsonb_build_object('short', 'Evidence', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(n_st, 0)), 'industry-funded studies naming it'),
             case when n_st > 0 then pc_fig(pc_money(st_amt), 'reported research payments') end,
             case when n_st > 0 then pc_fig(st_last::text, 'latest year') end));
  c_cat := c_cat || jsonb_build_object('short', 'Stocking', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(skus, 0)), 'catalog items in GUDID'),
             case when skus > 0 then pc_fig(pc_num(skus_in), 'in commercial distribution') end,
             pc_fig(pc_num(round(med_skus::numeric)), 'category median')));
  cards := jsonb_build_array(c_nov, c_alt, c_pay, c_ev, c_cat);
  -- recall card (04_recall_functions.sql) when the recall table exists
  if to_regclass('public.pc_recalls') is not null then
    cards := cards || jsonb_build_array(pc_recall_card_product(kn, company));
  end if;

  bl := case pattern
          when 'line extension' then 'A line extension of ' || company || '''s own product line'
          when 'competitive entry' then 'A competitive entry against ' || coalesce(others, 'other companies'') devices')
          when 'mixed' then 'Builds on ' || company || '''s own devices and other companies'''
          else 'A clearance with no predicate on file' end
        || case when n_alt >= 20 then ' in a crowded category (' || n_alt || ' other companies in five years). '
                when n_alt >= 5 then ' in a competitive category (' || n_alt || ' other companies in five years). '
                when n_alt >= 1 then ' in a category with few alternatives (' || n_alt || ' other compan' || case when n_alt = 1 then 'y' else 'ies' end || ' in five years). '
                else ' in a category with no other recent clearances. ' end
        || case when coalesce(roy, 0) > 0 then 'Royalties are paid on it. '
                when coalesce(tot, 0) > 0 then 'Industry payments name it. ' else '' end
        || case when coalesce(n_st, 0) = 0 then 'No industry-funded studies name it.' else n_st || ' industry-funded stud' || case when n_st = 1 then 'y names' else 'ies name' end || ' it.' end;

  return jsonb_build_object(
    'found', true, 'knumber', kn,
    'header', jsonb_build_object('device_name', dev->>'device_name', 'company', company, 'owner', owner_name,
                                 'plain_name', plain, 'fda_name', pcode->>'fda_name', 'product_code', code,
                                 'cleared', dev->>'decision_date', 'device_class', dev->>'device_class',
                                 'procedures', pcode->>'procedures', 'anatomy', pcode->>'anatomy', 'kind', pcode->>'kind',
                                 'summary_url', dev->>'summary_url', 'pattern', pattern),
    'bottom_line', bl, 'cards', cards,
    'alternatives', jsonb_build_object('window', 'Clearances after ' || to_char(data_end - interval '5 years', 'Mon DD, YYYY'),
                                       'companies', n_alt, 'rows', alts),
    'notes', jsonb_build_array(
      'Signals come from fixed rules on public FDA and CMS data. They frame questions and are not a judgment of the device or the company.',
      'Alternatives group companies by current owner and count clearances in the same FDA product code. A product code is broad, so not every alternative is a direct substitute.',
      'Catalog counts are the GUDID device IDs that cite this 510(k). A system sold under several 510(k)s spreads its items across them.'));
end $$;

create or replace function pc_vendor_signals(v text, m text default 'pit')
returns jsonb language plpgsql stable as $$
declare
  md text := pc_mode(m);
  ven pc_vendors;
  data_end date;
  n_cl int; n_codes int; n_active int; n_top3 int; top3_names text;
  v_last5 int; v_prior5 int; trend text;
  acq jsonb; n_acq int; acq_names text; acquired_by text; acquired_on date;
  latest int; tot double precision; recips int; cons_r int; roy_share double precision; max_holders int;
  n_st int; st_amt double precision; st_last int;
  n_brands int; n_disc int; disc_names text;
  comp jsonb; cards jsonb; bl text; breadth text;
begin
  select * into ven from pc_vendors where vendor_id = v;
  if ven.vendor_id is null then return jsonb_build_object('found', false, 'vendor_id', v); end if;
  data_end := pc_data_end();

  -- where they compete: every product code in the portfolio, ranked against other companies in the last five years
  with fam as (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v),
  allp as (
    select p.product_code, p.decision_date,
           case when p.vendor_id in (select vendor_id from fam) then v
                when md = 'current' then coalesce(nullif(x.rolls_up_to, ''), x.vendor_id)
                else x.vendor_id end as grp
    from pc_portfolio_510k p join pc_vendors x on x.vendor_id = p.vendor_id
    where p.product_code in (select distinct product_code from pc_portfolio_510k where vendor_id in (select vendor_id from fam))),
  per as (
    select product_code, grp, count(*) as all_time,
           count(*) filter (where decision_date > data_end - interval '5 years') as last5
    from allp group by 1, 2),
  ranked as (
    select per.*, sum(last5) over (partition by product_code) as code_last5,
           count(*) filter (where last5 > 0) over (partition by product_code) as active_cos,
           case when last5 > 0 then rank() over (partition by product_code order by last5 desc) end as rnk
    from per)
  select coalesce(jsonb_agg(jsonb_build_object(
           'product_code', r.product_code, 'plain_name', c.plain_name, 'fda_name', c.fda_name, 'anatomy', c.anatomy, 'kind', c.kind,
           'clearances', r.all_time, 'last5', r.last5, 'code_last5', r.code_last5,
           'share_last5_pct', round((100.0 * r.last5 / nullif(r.code_last5, 0))::numeric, 1),
           'rank_last5', r.rnk, 'competitors_last5', r.active_cos - case when r.last5 > 0 then 1 else 0 end,
           'position', case when r.last5 = 0 then 'No recent clearances'
                            when r.rnk <= 3 and r.last5::numeric / nullif(r.code_last5, 0) >= 0.1 then 'Top 3'
                            else 'Active' end)
           order by r.last5 desc, r.all_time desc), '[]'::jsonb),
         sum(r.all_time), count(*), count(*) filter (where r.last5 > 0),
         count(*) filter (where r.rnk <= 3 and r.last5::numeric / nullif(r.code_last5, 0) >= 0.1),
         array_to_string((array_agg(coalesce(c.plain_name, c.fda_name, r.product_code) order by r.last5 desc)
                          filter (where r.rnk <= 3 and r.last5::numeric / nullif(r.code_last5, 0) >= 0.1))[1:3], '; ')
    into comp, n_cl, n_codes, n_active, n_top3, top3_names
    from ranked r left join pc_product_codes c on c.product_code = r.product_code
    where r.grp = v;

  -- all clearances, including the few with no product code on record
  select count(*) into n_cl from pc_portfolio_510k
    where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);

  -- momentum
  select count(*) filter (where decision_date > data_end - interval '5 years'),
         count(*) filter (where decision_date <= data_end - interval '5 years' and decision_date > data_end - interval '10 years')
    into v_last5, v_prior5
    from pc_portfolio_510k where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);
  trend := case when v_prior5 = 0 and v_last5 > 0 then 'New entrant'
                when v_last5 = 0 then 'No recent clearances'
                when v_last5 >= 1.2 * v_prior5 then 'More recent clearances'
                when v_last5 <= 0.8 * v_prior5 then 'Fewer recent clearances'
                else 'Steady' end;

  -- ownership changes
  select coalesce(jsonb_agg(jsonb_build_object('vendor_id', l.vendor_id, 'name', c.display_name, 'date', l.valid_from,
                                               'relation', l.relation, 'source_url', l.source_url) order by l.valid_from desc), '[]'::jsonb),
         count(*) filter (where l.valid_from > current_date - interval '5 years'),
         string_agg(c.display_name || ' (' || to_char(l.valid_from, 'Mon YYYY') || ')', ', ' order by l.valid_from desc)
           filter (where l.valid_from > current_date - interval '5 years')
    into acq, n_acq, acq_names
    from pc_vendor_lineage l join pc_vendors c on c.vendor_id = l.vendor_id
    where l.parent = v and l.vendor_id <> v;
  select p.display_name, l.valid_from into acquired_by, acquired_on
    from pc_vendor_lineage l join pc_vendors p on p.vendor_id = l.parent
    where l.vendor_id = v and l.parent <> v and l.relation ~* '(acquired|merged|owned)'
    order by l.valid_from desc nulls last limit 1;

  -- payments
  select max(year) into latest from pc_op_vendor_profile where vendor_id = v and mode = md and year > 0;
  select total, recipients, consulting_r into tot, recips, cons_r from pc_op_vendor_profile where vendor_id = v and mode = md and year = latest;
  select sum(amount) filter (where nature_group = 'royalty') / nullif(sum(amount), 0) into roy_share
    from pc_op_vendor_year where vendor_id = v and mode = md;
  select max(h) into max_holders from (select year, sum(holders) h from pc_op_ownership o
    where (md = 'pit' and o.vendor_pit = v) or (md = 'current' and o.vendor_current = v) group by year) s;

  -- evidence
  select count(distinct study_name), sum(amount), max(year) into n_st, st_amt, st_last
    from pc_op_research r
    where ((md = 'pit' and r.vendor_pit = v) or (md = 'current' and r.vendor_current = v)) and coalesce(r.ortho, true);

  -- supply
  select count(*), count(*) filter (where devices > 0 and in_distribution = 0),
         array_to_string((array_agg(brand order by devices desc) filter (where devices > 0 and in_distribution = 0))[1:5], ', ')
    into n_brands, n_disc, disc_names
    from pc_portfolio_brands where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);

  breadth := case when n_codes >= 12 then 'Broad portfolio' when n_codes <= 3 then 'Focused' else 'Moderate breadth' end;

  cards := jsonb_build_array(
    pc_card('breadth', 'Where do they compete?', breadth, 'info',
      coalesce(pc_num(n_cl), '0') || ' orthopedic 510(k)' || case when n_cl = 1 then '' else 's' end || ' across ' || coalesce(n_codes, 0)
        || ' product code' || case when n_codes = 1 then '' else 's' end || ', with clearances in '
        || coalesce(n_active, 0) || ' of them in the last five years.'
        || case when n_top3 > 0 then ' A top-3 filer in ' || n_top3 || ' categor' || case when n_top3 = 1 then 'y' else 'ies' end
                                     || coalesce(', including ' || top3_names, '') || '.' else '' end,
      case when n_codes >= 12 then 'A broad portfolio makes a portfolio or bundled agreement possible.'
           when n_codes <= 3 then 'A specialist. Compare it category by category rather than as a portfolio.'
           else 'Large enough to bundle a few categories, focused enough to compare category by category.' end,
      case when n_codes >= 12 then 'Which categories would you include in a portfolio agreement, and what pricing applies if we consolidate?'
           else 'Where is your portfolio headed in the next two years?' end,
      'competition'),
    pc_card('momentum', 'Are they still investing?', trend,
      case when trend = 'No recent clearances' then 'attention' else 'info' end,
      coalesce(v_last5, 0) || ' orthopedic clearances in the last five years of data, versus ' || coalesce(v_prior5, 0) || ' in the five years before.',
      case trend when 'More recent clearances' then 'The company is adding new and updated products faster than before.'
                 when 'Fewer recent clearances' then 'Fewer new clearances can reflect a maturing portfolio or fewer, larger projects. Roadmap and long-term support are worth confirming.'
                 when 'No recent clearances' then 'No new clearances in five years. Long-term support and revision parts matter more.'
                 when 'New entrant' then 'A newer company in orthopedics. Supply capacity and field support matter more.'
                 else 'A steady pace of new and updated products.' end,
      'What is launching in the next 12 months, and what is being retired?',
      'portfolio'),
    pc_card('ownership', 'Has ownership changed?',
      case when acquired_by is not null then 'Acquired' when n_acq > 0 then 'Recent acquisitions' else 'No changes on record' end,
      case when acquired_by is not null or n_acq > 0 then 'attention' else 'info' end,
      case when acquired_by is not null then 'Acquired by ' || acquired_by || coalesce(' on ' || to_char(acquired_on, 'Mon DD, YYYY'), '') || '.'
           when n_acq > 0 then 'Acquired ' || acq_names || '.'
           else 'No acquisitions or ownership changes in OrthoParity''s reviewed registry.' end,
      case when acquired_by is not null or n_acq > 0 then 'Acquisitions consolidate product lines. Contract pricing, instrument sets and rep coverage can change.'
           else 'The registry covers major orthopedic deals since 2018, so smaller transactions may be missing.' end,
      case when acquired_by is not null or n_acq > 0 then 'Which product lines will continue, and how will pricing, instrument sets and rep coverage change?'
           else 'Are any ownership or financing changes planned that could affect supply or support?' end,
      'ownership'),
    pc_card('payments', 'What financial relationships exist?',
      case when coalesce(tot, 0) = 0 then 'None in scope' when roy_share > 0.5 then 'Royalty-led' else 'Mixed' end, 'info',
      case when coalesce(tot, 0) > 0 then
             pc_money(tot) || ' in reported payments in ' || latest || ' to ' || to_char(recips, 'FM999,999,999') || ' recipients. Royalties are '
             || round((100 * coalesce(roy_share, 0))::numeric) || '% of payments since 2019'
             || case when coalesce(cons_r, 0) > 0 then '; ' || cons_r || ' consultants were paid in ' || latest else '' end
             || case when coalesce(max_holders, 0) > 0 then '; up to ' || max_holders || ' physicians a year reported ownership' else '' end || '.'
           else 'No orthopedic-scope Open Payments records for this vendor from 2019 to 2025.' end,
      'Royalties go mostly to inventors and design surgeons; consulting goes to surgeons who advise, train or develop products. These relationships are normal in device development, and committees track them for disclosure.',
      'Which of your consultants or royalty holders practice at our facility, and are those relationships disclosed to our committee?',
      'payments'),
    pc_card('evidence', 'Are they building evidence?',
      case when coalesce(n_st, 0) > 0 then n_st || ' stud' || case when n_st = 1 then 'y' else 'ies' end else 'None reported' end,
      case when coalesce(n_st, 0) > 0 then 'info' else 'attention' end,
      case when coalesce(n_st, 0) > 0 then pc_money(st_amt) || ' in industry-funded orthopedic research across ' || n_st || ' studies since 2019, latest in ' || st_last || '.'
           else 'No industry-funded orthopedic research in Open Payments from 2019 to 2025.' end,
      case when coalesce(n_st, 0) > 0 then 'Shows where the company is building evidence. Results matter more than spend.'
           else 'Evidence may come from predicate devices, published literature or studies outside Open Payments.' end,
      'Which studies cover the products you are proposing, and when will results be published?',
      'research'),
    pc_card('supply', 'Is the portfolio in distribution?',
      case when coalesce(n_disc, 0) > 0 then n_disc || ' brand' || case when n_disc = 1 then '' else 's' end || ' discontinued' else 'All in distribution' end,
      case when coalesce(n_disc, 0) > 0 then 'attention' else 'info' end,
      case when coalesce(n_disc, 0) > 0 then n_disc || ' of ' || n_brands || ' orthopedic brands in GUDID list no devices in commercial distribution'
                                              || coalesce(' (' || disc_names || ')', '') || '.'
           else 'Every orthopedic brand in GUDID lists devices in commercial distribution.' end,
      'Discontinued lines can strand instrument sets and leave revision patients without parts.',
      'Is every line you are proposing in full distribution, and what is your end-of-life policy for revision parts?',
      'brands'));
  cards := jsonb_set(cards, '{0,headline}', to_jsonb(coalesce(n_codes, 0) || ' product code' || case when n_codes = 1 then '.' else 's.' end));
  cards := jsonb_set(cards, '{1,headline}', to_jsonb(coalesce(v_last5, 0) || ' clearance' || case when v_last5 = 1 then '' else 's' end || ' in five years.'));
  cards := jsonb_set(cards, '{2,headline}', to_jsonb(case when acquired_by is not null then 'Now part of ' || acquired_by || '.'
                                                        when n_acq > 0 then 'Recent acquisitions.' else 'No ownership changes on record.' end));
  cards := jsonb_set(cards, '{3,headline}', to_jsonb(case when coalesce(tot, 0) > 0 then pc_money(tot) || ' in ' || latest || '.'
                                                        else 'No payments in scope.' end));
  cards := jsonb_set(cards, '{4,headline}', to_jsonb(case when coalesce(n_st, 0) > 0 then n_st || case when n_st = 1 then ' study' else ' studies' end || ' since 2019.'
                                                        else 'No studies reported.' end));
  cards := jsonb_set(cards, '{5,headline}', to_jsonb(case when coalesce(n_disc, 0) > 0 then n_disc || ' brand' || case when n_disc = 1 then '' else 's' end || ' discontinued.'
                                                        else 'All brands in distribution.' end));
  cards := jsonb_set(cards, '{0}', (cards->0) || jsonb_build_object('short', 'Where they compete', 'figs', pc_figs(
             pc_fig(pc_num(n_codes), 'product codes'), pc_fig(pc_num(n_active), 'with clearances in the last five years'),
             pc_fig(pc_num(n_top3), 'categories as a top-3 filer'))));
  cards := jsonb_set(cards, '{1}', (cards->1) || jsonb_build_object('short', 'Still investing', 'figs', pc_figs(
             pc_fig(pc_num(v_last5), 'clearances, last five years'), pc_fig(pc_num(v_prior5), 'the five years before'))));
  cards := jsonb_set(cards, '{2}', (cards->2) || jsonb_build_object('short', 'Ownership', 'figs', pc_figs(
             pc_fig(pc_num(jsonb_array_length(acq)), 'acquisitions on record'),
             case when acquired_by is not null then pc_fig(to_char(acquired_on, 'YYYY'), 'acquired by ' || acquired_by) end)));
  cards := jsonb_set(cards, '{3}', (cards->3) || jsonb_build_object('short', 'Financial relationships', 'figs', case when coalesce(tot, 0) > 0 then pc_figs(
             pc_fig(pc_money(tot), 'reported payments in ' || latest), pc_fig(pc_num(recips), 'recipients in ' || latest),
             pc_fig(round((100 * coalesce(roy_share, 0))::numeric) || '%', 'royalties since 2019'),
             case when coalesce(cons_r, 0) > 0 then pc_fig(pc_num(cons_r), 'consultants paid in ' || latest) end)
           else pc_figs(pc_fig('0', 'orthopedic-scope payments, 2019 to 2025')) end));
  cards := jsonb_set(cards, '{4}', (cards->4) || jsonb_build_object('short', 'Evidence', 'figs', pc_figs(
             case when n_st > 0 then pc_fig(pc_money(st_amt), 'industry-funded research since 2019') end,
             pc_fig(pc_num(coalesce(n_st, 0)), 'studies'), case when n_st > 0 then pc_fig(st_last::text, 'latest year') end)));
  cards := jsonb_set(cards, '{5}', (cards->5) || jsonb_build_object('short', 'Distribution', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(n_disc, 0)), 'brands with no devices in distribution'), pc_fig(pc_num(n_brands), 'orthopedic brands in GUDID'))));
  if to_regclass('public.pc_recalls') is not null then
    cards := cards || jsonb_build_array(pc_recall_card_vendor(v, md));
  end if;

  bl := ven.display_name || ': ' || lower(breadth) || ' (' || coalesce(n_codes, 0) || ' product code' || case when n_codes = 1 then '' else 's' end
        || case when n_top3 > 0 then ', a top-3 filer in ' || n_top3 || ' categor' || case when n_top3 = 1 then 'y' else 'ies' end else '' end || '), '
        || case trend when 'More recent clearances' then 'more clearances than the five years before'
                      when 'Fewer recent clearances' then 'fewer clearances than the five years before'
                      when 'Steady' then 'a steady clearance pace'
                      when 'New entrant' then 'a new entrant' else 'no recent clearances' end
        || case when acquired_by is not null then ', now part of ' || acquired_by
                when n_acq > 0 then ', with recent acquisitions' else '' end
        || '. ' || case when coalesce(tot, 0) = 0 then 'No orthopedic-scope payments on record.'
                        when roy_share > 0.5 then 'Payments are royalty-led.' else 'Payments are a mix of royalties and field engagement.' end;

  return jsonb_build_object(
    'found', true, 'mode', md, 'vendor', to_jsonb(ven), 'bottom_line', bl, 'cards', cards,
    'competition', comp, 'acquisitions', acq,
    'notes', jsonb_build_array(
      'Signals come from fixed rules on public FDA and CMS data. They frame questions and are not a judgment of the company.',
      'Rank and share count 510(k) clearances in each product code over the last five years of data, by company. Clearances measure product activity, not sales.',
      'Research is limited to studies in orthopedic scope by rule; some broad research programs may still include non-orthopedic work.'));
end $$;

grant execute on function pc_fig(text, text), pc_num(numeric), pc_figs(jsonb[]), pc_money(double precision), pc_data_end(), pc_card(text, text, text, text, text, text, text, text),
  pc_signals(text), pc_vendor_signals(text, text) to anon, authenticated;
