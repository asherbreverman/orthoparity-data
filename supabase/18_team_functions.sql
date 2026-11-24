-- 18_team_functions.sql: Medicare TEAM model functions (Phase 7). Reads the tables 17_team_data.sql fills.
-- Safe to run again. Run after 17, then run 05 (the Medicare box calls pc_team_family_note when it exists).
--
-- TEAM facts shown here are CMS's own: which codes start an episode (42 CFR 512.525(d)), CMS's preliminary target
-- price for each MS-DRG and census division, and which hospitals take part. A target price is a regional benchmark
-- in CMS standardized dollars for all Medicare spending in the episode (the stay plus 30 days after discharge), not a
-- price for any device and not what a hospital will be paid. CMS doesn't publish hospital-specific target prices or
-- which track each hospital chose.

create or replace function pc_team_notes() returns jsonb language sql stable as $$
  select jsonb_build_array(
    'TEAM (Transforming Episode Accountability Model) is Medicare''s mandatory episode model for selected hospitals, '
      || 'January 2026 through December 2030. An episode covers the hospital stay or outpatient procedure plus 30 days '
      || 'after discharge, and CMS compares all Medicare spending in it with a target price.',
    'Target prices here are CMS''s preliminary regional prices: one per MS-DRG and census division, in standardized '
      || 'dollars, before CMS adjusts them for each hospital''s patients. They cover every Medicare service in the episode, '
      || 'so they are benchmarks, not device prices or payments.',
    'In 2027 every participating hospital must take Track 3 (upside and downside risk, 20% stop-gain and stop-loss) '
      || 'except safety-net, rural, Medicare Dependent, Sole Community and Essential Access Community hospitals, which may '
      || 'choose lower-risk tracks; safety-net hospitals may stay upside-only through 2028 (CMS Participation Tracks fact '
      || 'sheet). Which track a hospital chose is not public: NOT FOUND.',
    'Outpatient procedures that start an episode are priced under the MS-DRG CMS assigns them '
      || '(42 CFR 512.540): 27447 and 27130 under 470, 27702 under 469, 22551 and 22554 under 473, 22612 and 22630 under 451, 22633 under 402.',
    'The participant list is CMS''s list as of ' || coalesce((select to_char(max(as_of), 'FMMonth FMDD, YYYY') from pc_team_participant), 'NOT FOUND')
      || '; CMS updates it quarterly.')
$$;

-- MS-DRG titles: OrthoParity's reviewed titles (2024 numbering). Newer MS-DRGs have no title on file yet.
create or replace function pc_drg_title_lookup(d text) returns table (title text) language plpgsql stable as $$
begin
  if to_regclass('public.pc_procedure_drg') is not null then
    return query select max(x.drg_desc)::text from pc_procedure_drg x where x.drg = d;
  else
    return query select null::text;
  end if;
end $$;

-- Target prices for a set of MS-DRGs in one performance year: per MS-DRG, the regional range and every region.
create or replace function pc_team_prices(drgs text[], p_py int default 2) returns jsonb language sql stable as $$
  with g as (
    select t.drg, max(t.year) as year, round(min(t.target_price)) as mn, round(max(t.target_price)) as mx,
           round(percentile_cont(0.5) within group (order by t.target_price)::numeric) as med,
           jsonb_agg(jsonb_build_object('region', t.region, 'region_name', t.region_name,
                                        'target_price', round(t.target_price), 'benchmark_price', round(t.benchmark_price),
                                        'trend_factor', t.trend_factor, 'discount_factor', t.discount_factor)
                     order by t.region) as regions
      from pc_team_target_price t
     where t.py = p_py and t.drg = any(drgs)
     group by t.drg
  )
  select coalesce(jsonb_agg(jsonb_build_object('drg', g.drg, 'title', (select title from pc_drg_title_lookup(g.drg)),
                                               'year', g.year, 'min', g.mn, 'max', g.mx, 'median', g.med, 'regions', g.regions)
                            order by g.drg), '[]'::jsonb)
    from g
$$;

-- One procedure family: is it a TEAM episode, which codes start it, and CMS's target prices for 2026 and 2027.
create or replace function pc_team_family(fam text) returns jsonb language sql stable as $$
  with f as (select * from pc_team_family where family_id = fam),
  t as (select * from pc_team_trigger where category_id = (select category_id from f)),
  drgs as (select string_to_array(nullif((select price_drgs from f), ''), '|') as a)
  select case
    when not exists (select 1 from f) then jsonb_build_object('family_id', fam, 'is_team', false, 'checked', false,
      'note', 'This procedure family is not one of the families checked against TEAM''s episode codes.')
    when (select coalesce(category_id, '') from f) = '' then jsonb_build_object('family_id', fam, 'is_team', false, 'checked', true,
      'note', (select note from f), 'basis', (select basis from f))
    else jsonb_build_object(
      'family_id', fam, 'is_team', true, 'checked', true,
      'category_id', (select category_id from f), 'category', (select max(category) from t),
      'note', (select note from f), 'basis', (select basis from f),
      'family_drgs_not_in_team', (select nullif(family_drgs_not_in_team, '') from f),
      'triggers', (select jsonb_agg(jsonb_build_object('code_type', code_type, 'code', code, 'price_drg', price_drg,
                                                       'setting', setting, 'note', nullif(note, ''))
                                    order by code_type desc, code) from t
                    where code_type = 'HCPCS' and price_drg = any(array(select unnest(a) from drgs))
                       or code_type = 'MS-DRG' and code = any(array(select unnest(a) from drgs))),
      'prices_2027', pc_team_prices((select a from drgs), 2),
      'prices_2026', pc_team_prices((select a from drgs), 1),
      'range_2027', (select jsonb_build_object('min', round(min(target_price)), 'max', round(max(target_price)))
                       from pc_team_target_price where py = 2 and drg = any(array(select unnest(a) from drgs))),
      'participants', (select count(*) from pc_team_participant),
      'participants_as_of', (select max(as_of) from pc_team_participant),
      'notes', pc_team_notes(),
      'sources', jsonb_build_array(
        jsonb_build_object('name', 'CMS TEAM model page (target prices, participant list, DRG mapping)', 'url',
                           'https://www.cms.gov/priorities/innovation/innovation-models/team-model'),
        jsonb_build_object('name', 'CMS Participation Tracks in TEAM fact sheet', 'url',
                           'https://www.cms.gov/files/document/team-participation-tracks-fact-sheet.pdf'),
        jsonb_build_object('name', '42 CFR 512.525(d), episode categories', 'url',
                           'https://www.ecfr.gov/current/title-42/chapter-IV/subchapter-H/part-512/subpart-E/section-512.525')))
  end
$$;

-- TEAM Episode Check: does an MS-DRG or HCPCS code start a TEAM episode?
create or replace function pc_team_code(code text) returns jsonb language sql stable as $$
  with c as (select upper(regexp_replace(coalesce(code, ''), '[^0-9A-Za-z]', '', 'g')) as v),
  k as (select case when (select v from c) ~ '^\d{1,3}$' then lpad((select v from c), 3, '0') else (select v from c) end as v),
  hit as (select * from pc_team_trigger where code = (select v from k))
  select case when (select v from k) = '' then jsonb_build_object('found', false, 'note', 'Type an MS-DRG (for example 470) or a HCPCS code (for example 27447).')
    when not exists (select 1 from hit) then jsonb_build_object('found', false, 'code', (select v from k),
      'note', (select v from k) || ' does not start a TEAM episode under 42 CFR 512.525(d). Only the MS-DRGs and HCPCS codes listed there do.')
    else (select jsonb_build_object('found', true, 'code', h.code, 'code_type', h.code_type, 'category', h.category,
            'category_id', h.category_id, 'setting', h.setting, 'price_drg', h.price_drg, 'note', nullif(h.note, ''),
            'families', coalesce((select jsonb_agg(jsonb_build_object('family_id', f.family_id, 'name', p.name))
                                    from pc_team_family f join pc_procedures p on p.family_id = f.family_id
                                   where h.price_drg = any(string_to_array(f.price_drgs, '|'))), '[]'::jsonb),
            'prices_2027', pc_team_prices(array[h.price_drg], 2),
            'source', h.source, 'source_url', h.source_url)
          from hit h limit 1) end
$$;

-- TEAM Lookup: participating hospitals by name, city or CBSA, CCN or state, with their region's 2027 prices.
create or replace function pc_team_hospital(q text, lim int default 25) returns jsonb language sql stable as $$
  with s as (select trim(coalesce(q, '')) as v),
  m as (
    select p.*, (select t.region from pc_team_target_price t where t.py = 2 and t.region_name ~ ('\m' || p.state || '\M') limit 1) as region,
           (select t.region_name from pc_team_target_price t where t.py = 2 and t.region_name ~ ('\m' || p.state || '\M') limit 1) as region_name
      from pc_team_participant p, s
     where length(s.v) >= 2
       and (p.ccn = lpad(regexp_replace(s.v, '\D', '', 'g'), 6, '0') and s.v ~ '^\s*\d{5,6}\s*$'
            or (length(s.v) = 2 and upper(s.v) = p.state)
            or lower(p.hospital || ' ' || coalesce(p.cbsa_name, '')) like '%' || lower(s.v) || '%')
     order by p.hospital limit greatest(1, least(coalesce(lim, 25), 200))
  )
  select jsonb_build_object(
    'query', (select v from s),
    'results', coalesce((select jsonb_agg(jsonb_build_object(
        'ccn', ccn, 'hospital', hospital, 'participation', participation, 'cbsa', cbsa, 'cbsa_name', cbsa_name,
        'state', state, 'start_date', start_date, 'end_date', end_date, 'region', region, 'region_name', region_name,
        'track', 'NOT FOUND: CMS does not publish which track a hospital chose.',
        'prices_2027', (select jsonb_agg(jsonb_build_object('category', tt.category, 'drg', t.drg, 'target_price', round(t.target_price))
                                         order by tt.category, t.drg)
                          from pc_team_target_price t join pc_team_trigger tt on tt.code = t.drg and tt.code_type = 'MS-DRG'
                         where t.py = 2 and t.region = m.region and tt.category_id in ('LEJR', 'SHFFT', 'SPINE')))
        order by hospital) from m), '[]'::jsonb),
    'note', case when length((select v from s)) < 2 then 'Type at least 2 characters: a hospital name, a city, a two-letter state or a 6-digit CCN.'
                 when not exists (select 1 from m) then 'NOT FOUND on CMS''s TEAM participant list as of '
                      || (select to_char(max(as_of), 'FMMonth FMDD, YYYY') from pc_team_participant)
                      || '. A hospital not on the list is not in TEAM for now; CMS updates the list quarterly.' end,
    'as_of', (select max(as_of) from pc_team_participant),
    'total', (select count(*) from pc_team_participant),
    'source_url', 'https://www.cms.gov/team-model-participant-list',
    'prices_note', 'Orthopedic preliminary target prices for 2027 in the hospital''s census division, before CMS adjusts them for the hospital''s own patients.')
$$;

-- The TEAM sentence, figure and question for the product page's Medicare box (05 calls this when it exists).
create or replace function pc_team_family_note(fam text) returns jsonb language sql stable as $$
  with f as (select pc_team_family(fam) as j)
  select case when not ((select j from f)->>'is_team')::boolean then
      case when ((select j from f)->>'checked')::boolean
           then jsonb_build_object('text', ' ' || ((select j from f)->>'note'), 'is_team', false) end
    else jsonb_build_object(
      'is_team', true,
      'category', (select j from f)->>'category',
      'text', ' Medicare''s TEAM model treats this procedure as a ' || lower((select j from f)->>'category')
        || ' episode at the ' || pc_num(((select j from f)->>'participants')::numeric) || ' hospitals in TEAM. CMS''s preliminary 2027 target prices for '
        || 'these episodes run ' || pc_usd((((select j from f)->'range_2027'->>'min'))::numeric) || ' to '
        || pc_usd((((select j from f)->'range_2027'->>'max'))::numeric)
        || ' across MS-DRGs and regions, for all Medicare spending from the stay through 30 days after discharge.',
      'fig', pc_fig(pc_usd((((select j from f)->'range_2027'->>'min'))::numeric) || ' to ' || pc_usd((((select j from f)->'range_2027'->>'max'))::numeric),
                    'TEAM 2027 target prices, ' || lower((select j from f)->>'category')),
      'ask', 'Is our hospital in TEAM, and which costs inside the 30-day episode (length of stay, discharge to a facility, readmissions) would this product change?')
  end
$$;

grant execute on function pc_team_notes(), pc_team_prices(text[], int), pc_drg_title_lookup(text), pc_team_family(text),
  pc_team_code(text), pc_team_hospital(text, int), pc_team_family_note(text) to anon, authenticated;
