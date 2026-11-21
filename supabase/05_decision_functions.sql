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

-- non-empty questions, in order, as a JSON array
create or replace function pc_asks(variadic q text[]) returns jsonb language sql immutable as $$
  select coalesce(jsonb_agg(x), '[]'::jsonb) from unnest(q) x where nullif(trim(x), '') is not null
$$;

-- whole dollars with thousands separators ($27,892)
create or replace function pc_usd(x numeric) returns text language sql immutable as $$
  select case when x is null then null
              when x = round(x) then '$' || to_char(x, 'FM999,999,999,990')
              else '$' || to_char(x, 'FM999,999,999,990.00') end
$$;

-- a payment range, or one amount when the range is a single DRG ($19,439, or $27,892 to $104,193)
create or replace function pc_pay_range(lo numeric, hi numeric, compact boolean default false) returns text language sql immutable as $$
  select case when lo is null then null
              when round(lo) = round(hi) then case when compact then pc_money(lo::double precision) else pc_usd(round(lo)) end
              when compact then pc_money(lo::double precision) || ' to ' || pc_money(hi::double precision)
              else pc_usd(round(lo)) || ' to ' || pc_usd(round(hi)) end
$$;

-- a device name cut at its first comma or semicolon ("OPTETRAK TOTAL KNEE SYSTEM, HI-FLEX ..." -> "OPTETRAK TOTAL KNEE SYSTEM")
create or replace function pc_short_name(n text) returns text language sql immutable as $$
  select nullif(trim(split_part(split_part(coalesce(n, ''), ';', 1), ',', 1)), '')
$$;

-- a count with its noun (1 death, 2 deaths)
create or replace function pc_count(n numeric, one text, many text) returns text language sql immutable as $$
  select pc_num(coalesce(n, 0)) || ' ' || case when coalesce(n, 0) = 1 then one else many end
$$;

-- countries as names for the questions (two-letter FDA codes; unknown codes stay as codes)
create or replace function pc_country(c text) returns text language sql immutable as $$
  select case upper(c) when 'US' then 'the United States' when 'IE' then 'Ireland' when 'CH' then 'Switzerland'
    when 'DE' then 'Germany' when 'FR' then 'France' when 'GB' then 'the United Kingdom' when 'NL' then 'the Netherlands'
    when 'IT' then 'Italy' when 'CN' then 'China' when 'KR' then 'South Korea' when 'TW' then 'Taiwan' when 'JP' then 'Japan'
    when 'CR' then 'Costa Rica' when 'MX' then 'Mexico' when 'PR' then 'Puerto Rico' when 'CA' then 'Canada'
    when 'BE' then 'Belgium' when 'SE' then 'Sweden' when 'DK' then 'Denmark' when 'AU' then 'Australia' when 'IN' then 'India'
    when 'IL' then 'Israel' when 'MY' then 'Malaysia' when 'SG' then 'Singapore' when 'PL' then 'Poland' when 'AT' then 'Austria'
    when 'ES' then 'Spain' when 'BR' then 'Brazil' when 'TR' then 'Turkey' when 'HK' then 'Hong Kong'
    when 'AE' then 'the United Arab Emirates' when 'AR' then 'Argentina' when 'BG' then 'Bulgaria' when 'BM' then 'Bermuda'
    when 'CL' then 'Chile' when 'CO' then 'Colombia' when 'CZ' then 'the Czech Republic' when 'DO' then 'the Dominican Republic'
    when 'EC' then 'Ecuador' when 'EE' then 'Estonia' when 'EG' then 'Egypt' when 'FI' then 'Finland' when 'GR' then 'Greece'
    when 'GT' then 'Guatemala' when 'HN' then 'Honduras' when 'HU' then 'Hungary' when 'ID' then 'Indonesia' when 'IS' then 'Iceland'
    when 'KH' then 'Cambodia' when 'LT' then 'Lithuania' when 'LV' then 'Latvia' when 'MT' then 'Malta' when 'NI' then 'Nicaragua'
    when 'NZ' then 'New Zealand' when 'PA' then 'Panama' when 'PE' then 'Peru' when 'PH' then 'the Philippines' when 'PK' then 'Pakistan'
    when 'PT' then 'Portugal' when 'RO' then 'Romania' when 'RU' then 'Russia' when 'SK' then 'Slovakia' when 'SM' then 'San Marino'
    when 'SV' then 'El Salvador' when 'TH' then 'Thailand' when 'UA' then 'Ukraine' when 'VN' then 'Vietnam' when 'WS' then 'Samoa'
    when 'ZA' then 'South Africa' else upper(c) end
$$;

-- What is it cleared to treat? This 510(k)'s Indications for Use and how closely the wording matches its primary
-- predicate's (trigram similarity on the extracted text; a wording comparison, not a clinical judgment)
create or replace function pc_device_indications(k text) returns jsonb language sql stable as $$
  with me as (select ifu_text, page from pc_ifu where knumber = k and coalesce(ifu_text, '') <> ''),
  pred as (
    select e.predicate, d.device_name, i.ifu_text
    from pc_edges e left join pc_devices d on d.knumber = e.predicate
    left join pc_ifu i on i.knumber = e.predicate and coalesce(i.ifu_text, '') <> ''
    where e.child = k
    order by (e.role = 'primary') desc, e.list_order nulls last, e.predicate limit 1)
  select jsonb_build_object(
    'knumber', k,
    'found', exists (select 1 from me),
    'ifu_text', (select ifu_text from me), 'page', (select page from me),
    'predicate', (select jsonb_build_object('knumber', predicate, 'device_name', device_name, 'ifu_text', ifu_text) from pred),
    'similarity', (select round(similarity(lower(me.ifu_text), lower(pred.ifu_text))::numeric, 2) from me, pred
                   where pred.ifu_text is not null))
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
  c_ind jsonb; c_own jsonb; c_rec jsonb; c_ae jsonb; c_sup jsonb; c_med jsonb; c_add jsonb;
  bl text; crowd text;
  ind jsonb; sim numeric; own jsonb; mau jsonb; sup jsonb; addon jsonb; procs jsonb;
  fam_id text; fam_name text; fam_status text; n_fam int; drg_n int; drg_min numeric; drg_max numeric; fam_avg numeric;
  fam_dis numeric; sup30 numeric; sup50 numeric; data_yr int; n_nct int; nct_ids text; pred_recalls int;
  n_peers int; n_code int; r5 int; d5 int; i5 int; m5 int; partners text; countries text; flagged text;
  ntap_amt numeric; ntap_name text; tpt_code text; cat_tech text;
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
  c_alt := pc_card('alternatives', 'What else does the job?', crowd, case when n_alt < 5 then 'attention' else 'info' end,
    case when n_alt > 0 then n_alt || ' other compan' || case when n_alt = 1 then 'y' else 'ies' end || ' cleared ' || plain
           || ' devices in the last five years of data, including ' || alt_names || '.'
         else 'No other company cleared a ' || plain || ' device in the last five years of data.' end,
    case when n_alt >= 20 then 'Plenty of substitutes. Standardizing on fewer vendors in this category is realistic.'
         when n_alt >= 5 then 'Several substitutes exist, so a head-to-head comparison is practical.'
         when n_alt >= 1 then 'Few substitutes. Supply continuity and backup options matter more.'
         else 'Little recent competition. Supply continuity matters more.' end,
    case when n_alt >= 5 then 'How does it compare with products from ' || alt_names || ' on outcomes, instrument sets and total cost per case?'
         else 'If supply is interrupted, what is the backup?' end,
    'alternatives');

  -- 3. Financial ties (CMS Open Payments, payments naming this 510(k) or its brand)
  select sum(amount), sum(amount) filter (where nature_group = 'royalty'), sum(amount) filter (where nature_group = 'consulting'),
         min(year), max(year)
    into tot, roy, cons, yr_min, yr_max
    from pc_op_product where knumber = kn;
  c_pay := pc_card('payments', 'What are the financial ties for this product?',
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
  c_ev := pc_card('evidence', 'What clinical evidence exists?',
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
  c_cat := pc_card('catalog', 'What will it take to stock on the shelf?',
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
  c_nov := c_nov || jsonb_build_object('short', 'New', 'figs', pc_figs(
             pc_fig(pc_num(n_same), 'of ' || company || '''s own devices'),
             pc_fig(pc_num(n_direct - n_same), 'from other companies'),
             pc_fig(pc_num(gens), 'generations on record'),
             pc_fig(lin->'ends_at'->>'decision_year', 'earliest predicate on record')));
  c_alt := c_alt || jsonb_build_object('short', 'Alternatives', 'figs', pc_figs(
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

  -- what the cards below ask (several questions per card where the data supports them; the first is the card's ask)
  n_peers := nullif(b->'peers'->>'total', '')::int;
  n_code := nullif(b->'category'->>'total', '')::int;
  c_nov := c_nov || jsonb_build_object('asks', pc_asks(c_nov->>'ask',
             case when coalesce(n_peers, 0) > 0 then pc_num(n_peers) || ' other device' || case when n_peers = 1 then ' was' else 's were' end
                  || ' cleared on the same predicates. How does this one differ from them?' end));
  c_alt := c_alt || jsonb_build_object('asks', pc_asks(c_alt->>'ask',
             case when coalesce(n_code, 0) >= 5 then pc_num(n_code) || ' 510(k)s share product code ' || code
                  || '. What separates this device from the others in the code, beyond what its 510(k) summary says?' end));
  c_pay := c_pay || jsonb_build_object('asks', pc_asks(c_pay->>'ask',
             'Which surgeons at our hospital receive royalties or consulting fees from ' || company || ', and what hourly consulting rate do you pay?',
             case when coalesce(tot, 0) > 0 then 'Explain the ' || pc_money(tot) || ' in industry payments that name this product: how much was royalties, consulting, education, travel and meals?' end));
  select count(distinct ct_gov_id) filter (where coalesce(ct_gov_id, '') <> ''),
         string_agg(distinct ct_gov_id, ', ') filter (where coalesce(ct_gov_id, '') <> '')
    into n_nct, nct_ids
    from pc_op_research where ('|' || coalesce(knumbers, '') || '|') like '%|' || kn || '|%' and coalesce(ortho, true);
  c_ev := jsonb_set(c_ev, '{ask}', to_jsonb(case when n_st > 0
             then 'Share the results of the ' || n_st || ' industry-funded stud' || case when n_st = 1 then 'y that names' else 'ies that name' end
                  || ' this product, including any not yet published.'
             else 'No industry-funded studies name this product. What clinical data supports it, or why is none needed beyond its predicates?' end));
  c_ev := c_ev || jsonb_build_object('asks', pc_asks(c_ev->>'ask',
             case when n_nct > 0 then 'Which of these studies have results posted on ClinicalTrials.gov (' || nct_ids || ')?' end,
             case when n_st > 0 then 'What clinical data exists for this device itself, as opposed to its predicates?' end));
  c_cat := c_cat || jsonb_build_object('asks', pc_asks(
             case when coalesce(skus, 0) > 0 then 'GUDID lists ' || pc_num(skus) || ' catalog items under this 510(k). Can you confirm the full part-number list we would load, and explain any part numbers not in GUDID?' end,
             c_cat->>'ask'));
  c_cat := jsonb_set(c_cat, '{ask}', c_cat->'asks'->0);

  -- 2. What is it cleared to treat?
  ind := pc_device_indications(kn);
  sim := nullif(ind->>'similarity', '')::numeric;
  c_ind := pc_card('indications', 'What is it cleared to treat?',
    case when not (ind->>'found')::boolean then 'Not on file'
         when sim is null then 'On file'
         when sim >= 0.9 then 'Same wording as predicate'
         when sim >= 0.6 then 'Close to predicate'
         else 'Differs from predicate' end,
    case when not (ind->>'found')::boolean then 'attention' else 'info' end,
    case when not (ind->>'found')::boolean then 'NOT FOUND: the Indications for Use could not be read from the 510(k) summary. The FDA PDF has it.'
         else 'Cleared for: ' || left(ind->>'ifu_text', 260) || case when length(ind->>'ifu_text') > 260 then '…' else '' end
              || case when sim is not null then ' The wording is ' || round(sim * 100) || '% similar to its primary predicate, '
                        || coalesce(ind->'predicate'->>'device_name', 'name not on file') || ' (' || (ind->'predicate'->>'knumber') || ').'
                      when ind->'predicate'->>'knumber' is not null then ' The primary predicate''s Indications for Use are not on file, so the two can''t be compared.'
                      else '' end end,
    'A device is cleared for specific uses. Use outside them is off-label and can change coverage, consent and liability.',
    case when not (ind->>'found')::boolean then 'Can you provide the cleared Indications for Use for this 510(k)?'
         else 'Which of the cleared indications will our surgeons use it for, and is any planned use outside them?' end,
    'indications');
  c_ind := c_ind || jsonb_build_object('short', 'Indications',
    'headline', case when not (ind->>'found')::boolean then 'Indications not on file.' else 'Indications on file.' end,
    'figs', pc_figs(case when sim is not null then pc_fig(round(sim * 100) || '%', 'wording similarity to the primary predicate') end,
                    pc_fig(ind->'predicate'->>'knumber', 'primary predicate')),
    'asks', pc_asks(c_ind->>'ask',
      case when sim is not null and sim < 0.9 then 'The indications wording is ' || round(sim * 100) || '% similar to its primary predicate, '
           || (ind->'predicate'->>'knumber') || '. What changed, and what data supports any new use?' end));

  -- 3. Who sells it today?
  own := pc_device_owner(kn);
  c_own := pc_card('owner', 'Who sells it today?',
    case when coalesce((own->>'divested')::boolean, false) or coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
         then 'Now ' || coalesce(own->>'owner_name', 'NOT FOUND') else 'Same company' end,
    case when coalesce((own->>'divested')::boolean, false) then 'attention' else 'info' end,
    'FDA cleared it for ' || rtrim(coalesce(own->>'filer', company), '.') || '. '
      || case when coalesce((own->>'divested')::boolean, false) or coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
              then coalesce(own->>'explanation', 'It is now part of ' || coalesce(own->>'owner_name', 'NOT FOUND') || '.')
              else 'The same company, ' || coalesce(own->>'owner_name', company) || ', sells it today.' end,
    'The contract, pricing, instrument sets and rep coverage come from whoever owns the product line now.',
    case when coalesce((own->>'divested')::boolean, false) or coalesce(own->>'owner_vendor_id', '') <> coalesce(own->>'filer_vendor_id', '')
         then coalesce(own->>'owner_name', 'The new owner') || ' now sells this product line. Do our contract, pricing and instrument sets carry over, and who supports revisions of implants already in patients?'
         else 'Is any sale, spin-off or change in distribution planned for this product line?' end,
    'owner');
  c_own := c_own || jsonb_build_object('short', 'Owner', 'headline', c_own->>'badge' || '.',
    'figs', pc_figs(pc_fig(coalesce(own->>'filer', company), '510(k) holder at clearance'), pc_fig(own->>'owner_name', 'sells it today')),
    'asks', pc_asks(c_own->>'ask'));

  -- 9. Any recalls? (card from 04_recall_functions.sql, with a question about its predicates)
  if to_regclass('public.pc_recalls') is not null then
    c_rec := pc_recall_card_product(kn, company);
    select nullif(f->>'value', '')::int into pred_recalls from jsonb_array_elements(c_rec->'figs') f
      where f->>'label' = 'on its direct predicates';
    c_rec := c_rec || jsonb_build_object('asks', pc_asks(c_rec->>'ask',
      case when coalesce(pred_recalls, 0) > 0 then 'FDA lists ' || pred_recalls || ' recall event' || case when pred_recalls = 1 then '' else 's' end
           || ' on its direct predicates. Were those problems designed out of this device?' end));
  end if;

  -- 10. Any adverse events? (MAUDE, 09_maude_functions.sql)
  if to_regprocedure('pc_device_maude(text)') is not null then
    mau := pc_device_maude(kn);
    r5 := (mau->'last5'->>'reports')::int; d5 := (mau->'last5'->>'deaths')::int;
    i5 := (mau->'last5'->>'injuries')::int; m5 := (mau->'last5'->>'malfunctions')::int;
    c_ae := pc_card('adverse_events', 'Any adverse events?',
      case when not coalesce((mau->>'has_reports')::boolean, false) then 'None reported'
           when coalesce(r5, 0) = 0 then pc_num((mau->>'reports')::numeric) || ', none recent'
           else pc_num(r5) || ' in five years' end,
      'info',
      case when not coalesce((mau->>'has_reports')::boolean, false)
             then 'No FDA adverse event report (MAUDE) names this 510(k) number.'
                  || coalesce(' In product code ' || code || ', ' || pc_num((mau->'category'->>'with_reports')::numeric) || ' of '
                     || pc_num((mau->'category'->>'clearances')::numeric) || ' clearances have reports.', '')
           else pc_num((mau->>'reports')::numeric) || ' MAUDE reports name this 510(k)' || coalesce(' since ' || (mau->>'first_year'), '')
                || case when coalesce(r5, 0) > 0 then '; ' || pc_num(r5) || ' in the last five years (' || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ').' else ', none in the last five years.' end
                || coalesce(' In product code ' || code || ', the median for clearances with recent reports is '
                            || pc_num((mau->'category'->>'median_last5_with_reports')::numeric) || '.', '') end,
      'A report is not proof that the device caused an event, and counts are not rates: widely used products get more reports. A report counts only when it names the 510(k) number.',
      case when coalesce(r5, 0) > 0
           then 'FDA received ' || pc_num(r5) || ' adverse event reports naming this product in the last five years (' || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || '). What failure modes drive them, and what changed in response?'
           when coalesce((mau->>'has_reports')::boolean, false)
           then 'What drove the ' || pc_num((mau->>'reports')::numeric) || ' earlier adverse event reports, and were those issues resolved in the current design?'
           else 'No adverse event reports name this 510(k) number. Are complaints for this product reported to FDA under another 510(k)?' end,
      'maude');
    c_ae := c_ae || jsonb_build_object('short', 'Adverse events',
      'headline', case when not coalesce((mau->>'has_reports')::boolean, false) then 'No reports name it.'
                       else pc_num(coalesce(r5, 0)) || ' reports in five years.' end,
      'figs', pc_figs(pc_fig(pc_num(coalesce(r5, 0)), 'reports, last five years'),
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(d5), 'deaths') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(i5), 'injuries') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(m5), 'malfunctions') end,
                      pc_fig(pc_num(coalesce((mau->>'reports')::numeric, 0)), 'reports, all years')));
    c_ae := c_ae || jsonb_build_object('asks', pc_asks(c_ae->>'ask'));
  end if;

  -- 11. What is the vendor's supplier record? (sites listing this 510(k), 10_supplier_functions.sql)
  if to_regprocedure('pc_device_supplier(text)') is not null then
    sup := pc_device_supplier(kn);
    select string_agg(x, ', ') into partners from (select jsonb_array_elements_text(sup->'partner_making') x limit 3) z;
    select string_agg(pc_country(x), ', ') into countries from jsonb_array_elements_text(sup->'countries_making') x where x <> 'US';
    select string_agg(x, ', ') into flagged from (select jsonb_array_elements_text(sup->'flagged_sites') x limit 3) z;
    c_sup := pc_card('supplier', 'What is the vendor''s supplier record?',
      case when (sup->>'sites')::int = 0 then 'No sites on file'
           when (sup->>'warning_letters_last5')::int > 0 then (sup->>'warning_letters_last5') || ' warning letter' || case when (sup->>'warning_letters_last5')::int = 1 then '' else 's' end
           when (sup->>'oai_last5')::int > 0 then (sup->>'oai_last5') || ' OAI inspection' || case when (sup->>'oai_last5')::int = 1 then '' else 's' end
           else (sup->>'sites') || ' site' || case when (sup->>'sites')::int = 1 then '' else 's' end end,
      case when (sup->>'warning_letters_last5')::int > 0 or (sup->>'oai_last5')::int > 0 then 'attention' else 'info' end,
      case when (sup->>'sites')::int = 0 then 'No FDA establishment registration lists this 510(k) number, so its manufacturing sites are not on file.'
           else (sup->>'sites') || ' FDA-registered site' || case when (sup->>'sites')::int = 1 then ' lists' else 's list' end || ' this 510(k): '
                || array_to_string(array_remove(array[
                     case when (sup->>'company_sites')::int > 0 then (sup->>'company_sites') || ' of the company''s own' end,
                     case when (sup->>'partner_sites')::int > 0 then (sup->>'partner_sites') || ' partner firm' || case when (sup->>'partner_sites')::int = 1 then '' else 's' end
                          || coalesce(' (makers or sterilizers: ' || partners || ')', '') end,
                     case when (sup->>'other_company_sites')::int > 0 then (sup->>'other_company_sites') || ' of another device company, usually because the product line changed hands' end], null), '; ')
                || '. In the last five years FDA inspected these sites '
                || (sup->>'inspections_last5') || ' time' || case when (sup->>'inspections_last5')::int = 1 then '' else 's' end
                || ' for devices (' || (sup->>'oai_last5') || ' classified OAI) and issued ' || (sup->>'warning_letters_last5')
                || ' warning letter' || case when (sup->>'warning_letters_last5')::int = 1 then '' else 's' end || '.' end,
      'Shows who makes and handles the product and what FDA found at those sites. An inspection result describes one visit to one site, not the product.',
      case when (sup->>'sites')::int = 0 then 'Which FDA-registered site makes this product, and what is its FEI number?'
           else 'Which site makes this product, and what is your backup if that site stops shipping?' end,
      'supplier');
    c_sup := c_sup || jsonb_build_object('short', 'Supplier record',
      'headline', case when (sup->>'sites')::int = 0 then 'No sites on file.' else (sup->>'sites') || ' registered sites.' end,
      'figs', pc_figs(pc_fig(sup->>'sites', 'sites list this 510(k)'), pc_fig(sup->>'making_sites', 'make or sterilize it'),
                      pc_fig(sup->>'inspections_last5', 'device inspections, last five years'), pc_fig(sup->>'oai_last5', 'classified OAI'),
                      pc_fig(sup->>'warning_letters_last5', 'warning letters, last five years')),
      'asks', pc_asks(c_sup->>'ask',
        case when partners is not null then partners || case when jsonb_array_length(sup->'partner_making') = 1
               then ' makes or sterilizes this product for you. How much buffer stock do you hold if that partner stops shipping?'
               else ' make or sterilize this product for you. How much buffer stock do you hold if one of them stops shipping?' end end,
        case when countries is not null then 'This product is made at sites in ' || countries || '. How do you manage import holds, tariffs and shipping delays?' end,
        case when flagged is not null then 'FDA classified an inspection OAI or issued a warning letter at ' || flagged
             || ' in the last five years. Which corrective actions are complete, and did any affect this product?' end));
  end if;

  -- 12. What does Medicare pay for procedures that use it? (08_procedure_functions.sql)
  if to_regprocedure('pc_device_procedures(text)') is not null then
    procs := coalesce(pc_device_procedures(kn)->'procedures', '[]'::jsonb);
    n_fam := jsonb_array_length(procs);
    select x->>'family_id', x->>'name', x->>'status' into fam_id, fam_name, fam_status
      from jsonb_array_elements(procs) x order by (x->>'flagship')::boolean desc nulls last, x->>'name' limit 1;
    select count(*), min(medicare_pays), max(medicare_pays) into drg_n, drg_min, drg_max from pc_procedure_drg where family_id = fam_id;
    select medicare_pays, discharges, supply_total_30, supply_total_50, data_year into fam_avg, fam_dis, sup30, sup50, data_yr
      from pc_procedures where family_id = fam_id;
    c_med := pc_card('medicare', 'What does Medicare pay for procedures that use it?',
      case when fam_id is null then 'No procedure match' else pc_pay_range(drg_min, drg_max, true) || ' per case' end,
      'info',
      case when fam_id is null then 'NOT FOUND: product code ' || coalesce(code, 'none') || ' is not mapped to a Medicare procedure family.'
           else 'Used in ' || lower(fam_name) || ': ' || drg_n || ' MS-DRG' || case when drg_n = 1 then '' else 's' end || ', '
                || pc_num(fam_dis) || ' Medicare discharges in ' || data_yr || '. Medicare paid ' || pc_pay_range(drg_min, drg_max)
                || ' on average per case' || case when drg_n > 1 then ', depending on the DRG (' || pc_usd(round(fam_avg)) || ' across the family)' else '' end || '. '
                || 'This pays for the whole stay and every implant in it, not this product alone.'
                || case when sup30 is not null then ' Published cost studies put all implants at 30% to 50% of the case payment, about '
                          || pc_usd(round(sup30)) || ' to ' || pc_usd(round(sup50)) || '.' else '' end
                || case when n_fam > 1 then ' It is also mapped to ' || (n_fam - 1) || ' other procedure famil' || case when n_fam = 2 then 'y.' else 'ies.' end else '' end
                || ' The link from product code ' || code || ' to this procedure is ' || coalesce(fam_status, 'draft') || '.' end,
      'The DRG payment is fixed per case, so the implant cost has to fit inside it with the room, the operating room and the nursing. Which DRG a case falls into depends on the approach, levels and complications.',
      case when fam_id is null then 'Which inpatient and outpatient procedures is this product used in?'
           else 'Medicare pays ' || pc_pay_range(drg_min, drg_max) || ' per case for ' || lower(fam_name)
                || '. What will the full implant construct cost per case at our volume?' end,
      'procedures');
    c_med := c_med || jsonb_build_object('short', 'Medicare payment',
      'headline', case when fam_id is null then 'No procedure match.' else pc_money(round(fam_avg)) || ' average per case.' end,
      'figs', pc_figs(pc_fig(pc_num(drg_n), 'MS-DRGs in ' || coalesce(lower(fam_name), 'the family')),
                      pc_fig(pc_usd(round(drg_min)), 'lowest DRG average'), pc_fig(pc_usd(round(drg_max)), 'highest DRG average'),
                      pc_fig(pc_num(fam_dis), 'Medicare discharges, ' || coalesce(data_yr::text, '')),
                      pc_fig(fam_status, 'mapping status')),
      'asks', pc_asks(c_med->>'ask',
        case when fam_id is not null then 'Which other implants complete the construct in a typical ' || lower(fam_name) || ' case, and are they on the same contract?' end));
  end if;

  -- 13. Any Medicare add-on payments? (11_add_on_functions.sql)
  if to_regprocedure('pc_device_add_on(text)') is not null then
    addon := pc_device_add_on(kn);
    select max((x->>'max_payment')::numeric) filter (where x->>'program' = 'NTAP' and x->>'status' <> 'discontinued'),
           (array_agg(x->>'technology') filter (where x->>'program' = 'NTAP' and x->>'status' <> 'discontinued'))[1],
           string_agg(x->>'hcpcs', ', ') filter (where x->>'program' = 'TPT')
      into ntap_amt, ntap_name, tpt_code from jsonb_array_elements(addon->'items') x;
    select string_agg(distinct x->>'technology', '; ') into cat_tech from jsonb_array_elements(addon->'category') x;
    c_add := pc_card('add_on', 'Any Medicare add-on payments?',
      case when ntap_amt is not null and tpt_code is not null then 'NTAP and pass-through'
           when ntap_amt is not null then 'NTAP up to ' || pc_money(ntap_amt)
           when tpt_code is not null then 'Pass-through ' || tpt_code
           when jsonb_array_length(addon->'items') > 0 then 'NTAP ended'
           else 'None' end,
      'info',
      case when jsonb_array_length(addon->'items') = 0
             then 'No current Medicare add-on payment names this product line: no FY 2027 inpatient NTAP and no CY 2027 outpatient pass-through code.'
                  || coalesce(' In product code ' || code || ': ' || cat_tech || '.', '')
           else (select string_agg(case when x->>'program' = 'NTAP' then
                   x->>'technology' || ': inpatient NTAP, ' || case x->>'status' when 'new' then 'new for FY 2027' when 'continued' then 'continues in FY 2027' else 'ended for FY 2027' end
                   || ', up to ' || pc_usd((x->>'max_payment')::numeric) || ' per case.'
                 else x->>'technology' || ': outpatient pass-through, HCPCS ' || (x->>'hcpcs')
                   || case when x->>'pass_through_ends' = 'during CY 2027' then ', expires during 2027.' else ', continues in CY 2027.' end end, ' ')
                 from jsonb_array_elements(addon->'items') x) end,
      'Medicare pays the hospital or ASC extra for a limited time when a qualifying new technology is used. It is a payment rule for Original Medicare, not a clinical endorsement or a price.',
      case when ntap_amt is not null then 'Medicare adds up to ' || pc_usd(ntap_amt) || ' per inpatient case for this product in FY 2027. Do you provide coding guidance for the ICD-10-PCS codes CMS requires, and when does the add-on end?'
           when tpt_code is not null then 'Outpatient claims can bill HCPCS ' || tpt_code || ' for pass-through payment. Do you provide billing guidance for hospital outpatient departments and ASCs?'
           when cat_tech is not null then cat_tech || case when cat_tech like '%;%' then ' have Medicare add-on payments' else ' has a Medicare add-on payment' end
                || ' in the same product code. How does your product compare on total cost to the hospital?'
           else 'Is an NTAP or outpatient pass-through application planned for this product?' end,
      'addon');
    c_add := c_add || jsonb_build_object('short', 'Add-on payments',
      'headline', case when jsonb_array_length(addon->'items') = 0 then 'No add-on payment.' else c_add->>'badge' || '.' end,
      'figs', pc_figs(case when ntap_amt is not null then pc_fig(pc_usd(ntap_amt), 'most NTAP per inpatient case, FY 2027') end,
                      case when tpt_code is not null then pc_fig(tpt_code, 'outpatient pass-through code, CY 2027') end,
                      pc_fig(pc_num(jsonb_array_length(addon->'category')), 'others in product code ' || coalesce(code, ''))),
      'asks', pc_asks(c_add->>'ask',
        case when ntap_amt is not null and tpt_code is not null then 'Outpatient claims can also bill HCPCS ' || tpt_code || ' for pass-through payment. Do you provide billing guidance for that too?' end));
  end if;
  cards := pc_figs(c_nov, c_ind, c_own, c_alt, c_pay, c_ev, c_cat, c_rec, c_ae, c_sup, c_med, c_add);

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
  c_rec jsonb; c_ae jsonb; c_sup jsonb; c_med jsonb; c_add jsonb; mau jsonb; sup jsonb; vaddon jsonb; vprocs jsonb;
  top_fam text; top_name text; n_fam int; drg_min numeric; drg_max numeric; data_yr int; rec5 int;
  r5 int; d5 int; i5 int; m5 int; top_prod text; countries text; n_nct int; first_yr int;
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
  -- current owner, if another company: the latest open-ended ownership change (buyers need not be vendors;
  -- product-line sales and planned separations don't count)
  select coalesce(p.display_name, l.parent), l.valid_from into acquired_by, acquired_on
    from pc_vendor_lineage l left join pc_vendors p on p.vendor_id = l.parent
    where l.vendor_id = v and l.parent <> v and l.valid_to is null
      and l.relation ~* '(acquired by|merged into|owned by|sold to|spun off|became part of)'
      and l.relation !~* '(business sold|planned)' and coalesce(l.note, '') !~* 'history note'
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
    pc_card('ownership', 'Have any acquisitions or mergers occurred?',
      case when acquired_by is not null then 'Acquired' when n_acq > 0 then 'Recent acquisitions'
           when jsonb_array_length(acq) > 0 then 'No recent changes' else 'No changes on record' end,
      case when acquired_by is not null or n_acq > 0 then 'attention' else 'info' end,
      case when acquired_by is not null then 'Acquired by ' || acquired_by || coalesce(' on ' || to_char(acquired_on, 'Mon DD, YYYY'), '') || '.'
           when n_acq > 0 then 'Acquired ' || acq_names || '.'
           when jsonb_array_length(acq) > 0 then 'No acquisitions or ownership changes in the last five years. Earlier on record: '
                || (select string_agg((x->>'name') || coalesce(' (' || to_char((x->>'date')::date, 'Mon YYYY') || ')', ''), ', ')
                      from jsonb_array_elements(acq) x) || '.'
           else 'No acquisitions or ownership changes in OrthoParity''s reviewed registry.' end,
      case when acquired_by is not null or n_acq > 0 then 'Acquisitions consolidate product lines. Contract pricing, instrument sets and rep coverage can change.'
           else 'The registry covers major orthopedic deals since 2018, so smaller transactions may be missing.' end,
      case when acquired_by is not null or n_acq > 0 then 'Which product lines will continue, and how will pricing, instrument sets and rep coverage change?'
           else 'Are any ownership or financing changes planned that could affect supply or support?' end,
      'ownership'),
    pc_card('payments', 'What are the financial ties for this vendor?',
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
    pc_card('evidence', 'Are they building clinical evidence?',
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
                                                        when n_acq > 0 then 'Recent acquisitions.'
                                                        when jsonb_array_length(acq) > 0 then 'No recent ownership changes.'
                                                        else 'No ownership changes on record.' end));
  cards := jsonb_set(cards, '{3,headline}', to_jsonb(case when coalesce(tot, 0) > 0 then pc_money(tot) || ' in ' || latest || '.'
                                                        else 'No payments in scope.' end));
  cards := jsonb_set(cards, '{4,headline}', to_jsonb(case when coalesce(n_st, 0) > 0 then n_st || case when n_st = 1 then ' study' else ' studies' end || ' since 2019.'
                                                        else 'No studies reported.' end));
  cards := jsonb_set(cards, '{5,headline}', to_jsonb(case when coalesce(n_disc, 0) > 0 then n_disc || ' brand' || case when n_disc = 1 then '' else 's' end || ' discontinued.'
                                                        else 'All brands in distribution.' end));
  cards := jsonb_set(cards, '{0}', (cards->0) || jsonb_build_object('short', 'Competition', 'figs', pc_figs(
             pc_fig(pc_num(n_codes), 'product codes'), pc_fig(pc_num(n_active), 'with clearances in the last five years'),
             pc_fig(pc_num(n_top3), 'categories as a top-3 filer'))));
  cards := jsonb_set(cards, '{1}', (cards->1) || jsonb_build_object('short', 'Investment', 'figs', pc_figs(
             pc_fig(pc_num(v_last5), 'clearances, last five years'), pc_fig(pc_num(v_prior5), 'the five years before'))));
  cards := jsonb_set(cards, '{2}', (cards->2) || jsonb_build_object('short', 'Acquisitions', 'figs', pc_figs(
             pc_fig(pc_num(n_acq), 'acquisitions, last five years'),
             pc_fig(pc_num(jsonb_array_length(acq)), 'acquisitions on record, all years'),
             case when acquired_by is not null then pc_fig(to_char(acquired_on, 'YYYY'), 'acquired by ' || acquired_by) end)));
  cards := jsonb_set(cards, '{3}', (cards->3) || jsonb_build_object('short', 'Financial ties', 'figs', case when coalesce(tot, 0) > 0 then pc_figs(
             pc_fig(pc_money(tot), 'reported payments in ' || latest), pc_fig(pc_num(recips), 'recipients in ' || latest),
             pc_fig(round((100 * coalesce(roy_share, 0))::numeric) || '%', 'royalties since 2019'),
             case when coalesce(cons_r, 0) > 0 then pc_fig(pc_num(cons_r), 'consultants paid in ' || latest) end)
           else pc_figs(pc_fig('0', 'orthopedic-scope payments, 2019 to 2025')) end));
  cards := jsonb_set(cards, '{4}', (cards->4) || jsonb_build_object('short', 'Evidence', 'figs', pc_figs(
             case when n_st > 0 then pc_fig(pc_money(st_amt), 'industry-funded research since 2019') end,
             pc_fig(pc_num(coalesce(n_st, 0)), 'studies'), case when n_st > 0 then pc_fig(st_last::text, 'latest year') end)));
  cards := jsonb_set(cards, '{5}', (cards->5) || jsonb_build_object('short', 'Distribution', 'figs', pc_figs(
             pc_fig(pc_num(coalesce(n_disc, 0)), 'brands with no devices in distribution'), pc_fig(pc_num(n_brands), 'orthopedic brands in GUDID'))));
  -- questions for the six cards above (the first is each card's ask)
  first_yr := ven.first_clearance_year;
  if to_regprocedure('pc_vendor_procedures(text,text)') is not null then
    vprocs := coalesce(pc_vendor_procedures(v, md)->'procedures', '[]'::jsonb);
    n_fam := jsonb_array_length(vprocs);
    select x->>'family_id', x->>'name' into top_fam, top_name from jsonb_array_elements(vprocs) x
      order by (select coalesce(sum((c->>'clearances_recent')::int), 0) from jsonb_array_elements(x->'categories') c) desc,
               (x->>'flagship')::boolean desc nulls last, x->>'name' limit 1;
  end if;
  select count(distinct ct_gov_id) filter (where coalesce(ct_gov_id, '') <> '') into n_nct from pc_op_research r
    where ((md = 'pit' and r.vendor_pit = v) or (md = 'current' and r.vendor_current = v)) and coalesce(r.ortho, true);
  cards := jsonb_set(cards, '{0,asks}', pc_asks(cards->0->>'ask',
             case when top_name is not null then 'In ' || lower(top_name) || ', which of your products make a complete construct, and which parts would we buy from another vendor?' end,
             case when first_yr >= extract(year from data_end)::int - 10 then 'You filed your first orthopedic 510(k) in ' || first_yr || '. How will you guarantee supply, instrument sets and field support as our volume grows?' end));
  cards := jsonb_set(cards, '{1,asks}', pc_asks(cards->1->>'ask',
             case when trend in ('Fewer recent clearances', 'No recent clearances') then 'Which product lines are you no longer developing, and how long will you support implants and instruments for them?' end));
  cards := jsonb_set(cards, '{2,asks}', pc_asks(cards->2->>'ask'));
  cards := jsonb_set(cards, '{3,asks}', pc_asks(cards->3->>'ask',
             'What hourly rate do you pay surgeon consultants, and how is it set?',
             case when coalesce(tot, 0) > 0 then 'Explain the ' || pc_money(tot) || ' in ' || latest || ' payments: how much was royalties, consulting, education, travel and meals?' end));
  cards := jsonb_set(cards, '{4,asks}', pc_asks(cards->4->>'ask',
             case when coalesce(n_nct, 0) > 0 then n_nct || ' of your funded studies have ClinicalTrials.gov numbers. Which have results posted, and can you share any that are not yet published?' end));
  cards := jsonb_set(cards, '{5,asks}', pc_asks(cards->5->>'ask'));

  -- Any recalls? (04_recall_functions.sql)
  if to_regclass('public.pc_recalls') is not null then
    c_rec := pc_recall_card_vendor(v, md) || jsonb_build_object('question', 'Any recalls?', 'short', 'Recalls');
    select nullif(f->>'value', '')::int into rec5 from jsonb_array_elements(c_rec->'figs') f where f->>'label' = 'recall events, last five years';
    c_rec := c_rec || jsonb_build_object('asks', pc_asks(c_rec->>'ask',
      case when coalesce(rec5, 0) > 0 then 'Explain the ' || rec5 || ' recall event' || case when rec5 = 1 then '' else 's' end
           || ' in the last five years: what caused ' || case when rec5 = 1 then 'it' else 'them' end || ', and what changed in design, manufacturing or labeling?' end));
  end if;

  -- Any adverse events? (09_maude_functions.sql)
  if to_regprocedure('pc_vendor_maude(text,text,integer)') is not null then
    mau := pc_vendor_maude(v, md, 3);
    r5 := (mau->'last5'->>'reports')::int; d5 := (mau->'last5'->>'deaths')::int;
    i5 := (mau->'last5'->>'injuries')::int; m5 := (mau->'last5'->>'malfunctions')::int;
    top_prod := pc_short_name(mau->'top_products'->0->>'device_name');
    c_ae := pc_card('adverse_events', 'Any adverse events?',
      case when coalesce((mau->>'reports')::int, 0) = 0 then 'None reported' else pc_num(coalesce(r5, 0)) || ' in five years' end,
      'info',
      case when coalesce((mau->>'reports')::int, 0) = 0 then 'No FDA adverse event report (MAUDE) names any of this company''s orthopedic 510(k)s.'
           else pc_num((mau->>'reports')::numeric) || ' MAUDE reports name ' || pc_num((mau->>'products_with_reports')::numeric) || ' of its '
                || pc_num((mau->>'products')::numeric) || ' orthopedic 510(k)s; ' || pc_num(coalesce(r5, 0)) || ' in the last five years ('
                || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ')'
                || coalesce(', most for ' || top_prod, '') || '.' end,
      'A report is not proof that a device caused an event, and counts are not rates: companies with more products in use get more reports. A report counts only when it names the 510(k) number.',
      case when coalesce(r5, 0) > 0 then 'FDA received ' || pc_num(r5) || ' adverse event reports naming your 510(k)s in the last five years ('
                || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ')'
                || coalesce(', most for ' || top_prod, '') || '. What failure modes drive them, and what changed in response?'
           else 'How do you report complaints to FDA, and under which 510(k) numbers?' end,
      'maude');
    c_ae := c_ae || jsonb_build_object('short', 'Adverse events',
      'headline', case when coalesce((mau->>'reports')::int, 0) = 0 then 'No reports name its 510(k)s.' else pc_num(coalesce(r5, 0)) || ' reports in five years.' end,
      'figs', pc_figs(pc_fig(pc_num(coalesce(r5, 0)), 'reports, last five years'),
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(d5), 'deaths') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(i5), 'injuries') end,
                      case when coalesce(r5, 0) > 0 then pc_fig(pc_num(m5), 'malfunctions') end,
                      pc_fig(pc_num(coalesce((mau->>'products_with_reports')::numeric, 0)), '510(k)s with reports')),
      'asks', pc_asks(case when coalesce(r5, 0) > 0 then 'FDA received ' || pc_num(r5) || ' adverse event reports naming your 510(k)s in the last five years ('
                || pc_count(d5, 'death', 'deaths') || ', ' || pc_count(i5, 'injury', 'injuries') || ', ' || pc_count(m5, 'malfunction', 'malfunctions') || ')'
                || coalesce(', most for ' || top_prod, '') || '. What failure modes drive them, and what changed in response?'
           else 'How do you report complaints to FDA, and under which 510(k) numbers?' end,
        'How do you share complaint and adverse event trends with hospital customers?'));
  end if;

  -- What is the vendor's supplier record? (10_supplier_functions.sql)
  if to_regprocedure('pc_vendor_supplier(text,text)') is not null then
    sup := pc_vendor_supplier(v, md);
    select string_agg(pc_country(x->>'country'), ', ') into countries
      from jsonb_array_elements(sup->'countries') x where x->>'country' not in ('US', '');
    c_sup := pc_card('supplier', 'What is the vendor''s supplier record?',
      case when (sup->'warning_letters'->>'company_last5')::int > 0 then (sup->'warning_letters'->>'company_last5') || ' warning letter'
                || case when (sup->'warning_letters'->>'company_last5')::int = 1 then '' else 's' end || ' in five years'
           when (sup->'inspections_last5'->>'oai')::int > 0 then (sup->'inspections_last5'->>'oai') || ' OAI inspection'
                || case when (sup->'inspections_last5'->>'oai')::int = 1 then '' else 's' end || ' in five years'
           when (sup->'sites'->>'company_sites')::int = 0 then 'No company sites on file'
           else pc_count((sup->'sites'->>'company_sites')::numeric, 'company site', 'company sites') end,
      case when (sup->'warning_letters'->>'company_last5')::int > 0 or (sup->'inspections_last5'->>'oai')::int > 0 then 'attention' else 'info' end,
      case when (sup->'sites'->>'company_sites')::int = 0 and (sup->'sites'->>'partner_sites')::int = 0
             then 'No FDA establishment registration lists this company''s orthopedic 510(k)s, so its sites are not on file.'
           else (sup->'sites'->>'company_sites') || ' company site' || case when (sup->'sites'->>'company_sites')::int = 1 then '' else 's' end
                || ' (' || (sup->'sites'->>'company_making') || case when (sup->'sites'->>'company_making')::int = 1 then ' makes' else ' make' end
                || ' devices) in ' || (sup->'sites'->>'company_countries') || ' countr'
                || case when (sup->'sites'->>'company_countries')::int = 1 then 'y' else 'ies' end
                || case when (sup->'sites'->>'partner_sites')::int > 0 then ', plus ' || (sup->'sites'->>'partner_sites') || ' partner site'
                        || case when (sup->'sites'->>'partner_sites')::int = 1 then '' else 's' end else '' end
                || '. In the last five years FDA inspected company sites ' || (sup->'inspections_last5'->>'inspections') || ' time'
                || case when (sup->'inspections_last5'->>'inspections')::int = 1 then '' else 's' end || ' for devices ('
                || (sup->'inspections_last5'->>'nai') || ' NAI, ' || (sup->'inspections_last5'->>'vai') || ' VAI, ' || (sup->'inspections_last5'->>'oai')
                || ' OAI). ' || case when (sup->'warning_letters'->>'company_all')::int = 0 then 'FDA has issued no device warning letters to company sites since fiscal 2009.'
                   else pc_count((sup->'warning_letters'->>'company_last5')::numeric, 'warning letter', 'warning letters') || ' in the last five years, '
                        || (sup->'warning_letters'->>'company_all') || ' since fiscal 2009.' end end,
      'Shows where the company makes its products and what FDA found there. An inspection result describes one visit to one site, not the company''s products.',
      'Which sites make the products you are proposing, and what is your backup if one stops shipping?',
      'supplier');
    c_sup := c_sup || jsonb_build_object('short', 'Supplier record',
      'headline', c_sup->>'badge' || '.',
      'figs', pc_figs(pc_fig(sup->'sites'->>'company_sites', 'company sites'), pc_fig(sup->'sites'->>'company_countries', 'countries'),
                      pc_fig(sup->'inspections_last5'->>'inspections', 'device inspections, last five years'),
                      pc_fig(sup->'inspections_last5'->>'oai', 'classified OAI'),
                      pc_fig(sup->'warning_letters'->>'company_last5', 'warning letters, last five years'),
                      pc_fig(sup->'sites'->>'partner_sites', 'partner sites')),
      'asks', pc_asks(c_sup->>'ask',
        case when (sup->'warning_letters'->>'company_last5')::int > 0 or (sup->'inspections_last5'->>'oai')::int > 0
             then 'FDA issued ' || (sup->'warning_letters'->>'company_last5') || ' warning letter' || case when (sup->'warning_letters'->>'company_last5')::int = 1 then '' else 's' end
                  || ' and classified ' || (sup->'inspections_last5'->>'oai') || ' inspection' || case when (sup->'inspections_last5'->>'oai')::int = 1 then '' else 's' end
                  || ' OAI at your sites in the last five years. Which corrective actions are complete, and did any affect products you are proposing?' end,
        case when (sup->'sites'->>'partner_making')::int > 0 then 'Which contract manufacturers and sterilizers make the products you are proposing, and do you have a second source for each?' end,
        case when countries is not null then 'Your products are made at sites in ' || countries || '. How do you manage tariffs, import holds and shipping delays?' end));
  end if;

  -- What does Medicare pay for procedures that use their products? (08_procedure_functions.sql)
  if vprocs is not null then
    select min(medicare_pays), max(medicare_pays) into drg_min, drg_max from pc_procedure_drg where family_id = top_fam;
    select data_year into data_yr from pc_procedures where family_id = top_fam;
    c_med := pc_card('medicare', 'What does Medicare pay for procedures that use their products?',
      case when top_fam is null then 'No procedure match' else pc_pay_range(drg_min, drg_max, true) || ' per case' end,
      'info',
      case when top_fam is null then 'NOT FOUND: none of this company''s product codes is mapped to a Medicare procedure family.'
           else 'Its products map to ' || n_fam || ' Medicare procedure famil' || case when n_fam = 1 then 'y' else 'ies' end
                || '. The family with its most recent clearances is ' || lower(top_name) || ', where Medicare paid ' || pc_pay_range(drg_min, drg_max)
                || ' on average per case in ' || data_yr || '. That pays for the whole stay and every implant in it.' end,
      'The procedure payment is fixed per case, so implant cost has to fit inside it. Product-code-to-procedure links are reviewed by hand; see the procedure section for each family''s status.',
      case when top_fam is null then 'Which inpatient and outpatient procedures are your products used in?'
           else 'Medicare pays ' || pc_pay_range(drg_min, drg_max) || ' per case for ' || lower(top_name)
                || '. What will your implants cost per case for the constructs you are proposing?' end,
      'procedures');
    c_med := c_med || jsonb_build_object('short', 'Medicare payment',
      'headline', case when top_fam is null then 'No procedure match.' else c_med->>'badge' || '.' end,
      'figs', pc_figs(pc_fig(pc_num(n_fam), 'procedure families'), pc_fig(pc_usd(round(drg_min)), 'lowest DRG average, ' || coalesce(lower(top_name), '')),
                      pc_fig(pc_usd(round(drg_max)), 'highest DRG average')),
      'asks', pc_asks(c_med->>'ask'));
  end if;

  -- Any Medicare add-on payments? (11_add_on_functions.sql)
  if to_regprocedure('pc_vendor_add_on(text,text)') is not null then
    vaddon := pc_vendor_add_on(v, md);
    c_add := pc_card('add_on', 'Any Medicare add-on payments?',
      case when jsonb_array_length(vaddon->'items') = 0 then 'None'
           else array_to_string(array_remove(array[
                  case when (vaddon->>'ntap')::int > 0 then (vaddon->>'ntap') || ' NTAP' end,
                  case when (vaddon->>'pass_through')::int > 0 then (vaddon->>'pass_through') || ' pass-through' end], null), ', ')
                || case when (vaddon->>'ntap')::int = 0 and (vaddon->>'pass_through')::int = 0 then 'NTAP ended' else '' end end,
      'info',
      case when jsonb_array_length(vaddon->'items') = 0
             then 'None of this company''s technologies has a current Medicare add-on payment (FY 2027 inpatient NTAP or CY 2027 outpatient pass-through).'
           else (select string_agg(x->>'technology' || case when x->>'program' = 'NTAP'
                   then ' (NTAP, ' || case x->>'status' when 'discontinued' then 'ended for FY 2027' else 'up to ' || pc_usd((x->>'max_payment')::numeric) || ' per case' end || ')'
                   else ' (pass-through ' || (x->>'hcpcs') || ')' end, '; ') from jsonb_array_elements(vaddon->'items') x) || '.' end,
      'Medicare pays the hospital or ASC extra for a limited time when a qualifying new technology is used. It is a payment rule for Original Medicare, not a clinical endorsement or a price.',
      case when jsonb_array_length(vaddon->'items') > 0 then 'Which of the products you are proposing carry a Medicare add-on payment, and do you provide coding and billing guidance for them?'
           else 'Do you plan NTAP or outpatient pass-through applications for any product you are proposing?' end,
      'addon');
    c_add := c_add || jsonb_build_object('short', 'Add-on payments',
      'headline', case when jsonb_array_length(vaddon->'items') = 0 then 'No add-on payments.' else c_add->>'badge' || '.' end,
      'figs', pc_figs(pc_fig(vaddon->>'ntap', 'inpatient NTAP, FY 2027'), pc_fig(vaddon->>'pass_through', 'outpatient pass-through codes, CY 2027')),
      'asks', pc_asks(c_add->>'ask'));
  end if;
  cards := cards || pc_figs(c_rec, c_ae, c_sup, c_med, c_add);

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
