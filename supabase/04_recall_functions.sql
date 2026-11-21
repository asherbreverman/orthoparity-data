-- OrthoParity database: recall lookups and the recall cards used by the decision briefs
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.

-- one row per recall event (a single event can cover many catalog numbers); the most serious class wins
create or replace function pc_recall_event_rows(ids text[], lim int default 50)
returns jsonb language sql stable as $$
  select coalesce(jsonb_agg(e order by e.initiated desc nulls last), '[]'::jsonb) from (
    select r.event_id, min(r.initiated) as initiated, max(r.terminated) as terminated,
           case when bool_or(r.status ilike 'open%') then 'Open' when bool_or(r.status = 'Completed') then 'Completed' else 'Terminated' end as status,
           case when bool_or(r.recall_class = 'Class I') then 'Class I' when bool_or(r.recall_class = 'Class II') then 'Class II'
                when bool_or(r.recall_class = 'Class III') then 'Class III' else 'Not classified in openFDA' end as recall_class,
           count(*) as products, (array_agg(r.product order by r.recall_number))[1] as product,
           (array_agg(r.reason order by r.recall_number))[1] as reason, max(r.root_cause) as root_cause,
           max(r.recalling_firm) as recalling_firm, (array_agg(r.recall_number order by r.recall_number))[1] as recall_number,
           string_agg(distinct nullif(r.knumbers, ''), '|') as knumbers
    from pc_recalls r where r.event_id = any(ids) group by r.event_id
    order by min(r.initiated) desc nulls last limit lim) e
$$;

-- recalls that name a 510(k) directly, and recalls that name any of its direct predicates
create or replace function pc_device_recalls(k text)
returns jsonb language plpgsql stable as $$
declare
  kn text := upper(regexp_replace(coalesce(k, ''), '[\s\-]', '', 'g'));
  preds text[]; own text[]; pred_ev text[]; code text; ctx jsonb;
begin
  select array_agg(distinct event_id) into own from pc_recalls where string_to_array(knumbers, '|') @> array[kn];
  select array_agg(distinct e.predicate) into preds from pc_edges e where e.child = kn and e.predicate like 'K%';
  select array_agg(distinct event_id) into pred_ev from pc_recalls
    where string_to_array(knumbers, '|') && coalesce(preds, '{}') and not (event_id = any(coalesce(own, '{}')));
  select product_code into code from pc_devices where knumber = kn;
  select jsonb_build_object('product_code', code,
           'events_last5', count(distinct event_id) filter (where initiated > current_date - interval '5 years'),
           'companies_last5', count(distinct coalesce(vendor_id, recalling_firm)) filter (where initiated > current_date - interval '5 years'),
           'class1_last5', count(distinct event_id) filter (where initiated > current_date - interval '5 years' and recall_class = 'Class I'))
    into ctx from pc_recalls where product_code = code;
  return jsonb_build_object('knumber', kn, 'device', pc_recall_event_rows(coalesce(own, '{}'), 50),
                            'predicates', pc_recall_event_rows(coalesce(pred_ev, '{}'), 50),
                            'predicate_knumbers', to_jsonb(coalesce(preds, '{}')), 'category', ctx,
                            'source', 'FDA recall database via openFDA, 2002 to present');
end $$;

create or replace function pc_vendor_recalls(v text, m text default 'pit', lim int default 50)
returns jsonb language plpgsql stable as $$
declare md text := pc_mode(m); ids text[]; ids5 text[];
begin
  select array_agg(distinct event_id), array_agg(distinct event_id) filter (where initiated > current_date - interval '5 years')
    into ids, ids5
    from pc_recalls where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v);
  return jsonb_build_object(
    'events_all', coalesce(array_length(ids, 1), 0), 'events_last5', coalesce(array_length(ids5, 1), 0),
    'by_year', (select coalesce(jsonb_agg(jsonb_build_object('year', y, 'events', n) order by y), '[]'::jsonb) from (
                  select extract(year from min(initiated))::int y, count(*) n from (
                    select event_id, min(initiated) initiated from pc_recalls where event_id = any(coalesce(ids, '{}')) group by 1) e
                  where initiated is not null group by extract(year from initiated)) s),
    'events', pc_recall_event_rows(coalesce(ids, '{}'), lim),
    'source', 'FDA recall database via openFDA, 2002 to present');
end $$;

-- decision cards (called by pc_signals and pc_vendor_signals in 05_decision_functions.sql)
create or replace function pc_recall_card_product(kn text, company text)
returns jsonb language plpgsql stable as $$
declare d jsonb := pc_device_recalls(kn); n_own int; n_pred int; c1 boolean; open_n int; latest date; cls text; cat jsonb;
begin
  n_own := jsonb_array_length(d->'device'); n_pred := jsonb_array_length(d->'predicates'); cat := d->'category';
  select bool_or(e->>'recall_class' = 'Class I'), count(*) filter (where e->>'status' = 'Open'), max((e->>'initiated')::date),
         (array_agg(e->>'recall_class' order by e->>'initiated' desc))[1]
    into c1, open_n, latest, cls from jsonb_array_elements(d->'device') e;
  return pc_card('recalls', 'Any recalls?',
    case when coalesce(c1, false) then 'Class I recall' when n_own > 0 then n_own || ' recall' || case when n_own = 1 then '' else 's' end
         when n_pred > 0 then 'None on this device' else 'None on record' end,
    case when n_own > 0 then 'attention' else 'info' end,
    case when n_own > 0 then 'FDA lists ' || n_own || ' recall event' || case when n_own = 1 then '' else 's' end || ' naming this 510(k)'
                             || ', the latest in ' || to_char(latest, 'Mon YYYY') || ' (' || cls || ')'
                             || case when open_n > 0 then '; ' || open_n || ' still listed as open by FDA' else '; none still open' end || '.'
         else 'No FDA recall names this 510(k).' end
    || case when n_pred > 0 then ' Recalls name ' || n_pred || ' event' || case when n_pred = 1 then '' else 's' end || ' on its direct predicates.'
            when n_own = 0 then ' None name its direct predicates either.' else '' end
    || coalesce(' Across this product code, ' || (cat->>'events_last5') || ' recall events in the last five years involved '
                || (cat->>'companies_last5') || ' companies.', ''),
    case when n_own > 0 then 'Recalls show what went wrong and how the company responded. Most orthopedic recalls are Class II, and many cover labeling or specific lots.'
         else 'A clean record helps, though newer devices have had less time on the market. FDA records start in 2002.' end,
    case when n_own > 1 then 'What caused the ' || n_own || ' recalls, are the corrections complete, and are any affected lots in our inventory?'
         when n_own = 1 then 'What caused the recall, is the correction complete, and are any affected lots in our inventory?'
         else 'Has FDA or the company issued field safety notices or corrections for this device or its predicates outside FDA''s recall list?' end,
    'recalls')
    || jsonb_build_object('headline', case when n_own > 0 then n_own || ' recall' || case when n_own = 1 then '' else 's' end || ' on this device.'
                                           when n_pred > 0 then 'No recalls on this device.' else 'No recalls on record.' end,
                          'short', 'Recalls',
                          'figs', jsonb_build_array(
                             jsonb_build_object('value', n_own::text, 'label', 'recall events naming it'),
                             jsonb_build_object('value', n_pred::text, 'label', 'on its direct predicates'),
                             jsonb_build_object('value', coalesce(cat->>'events_last5', '0'), 'label', 'in this product code, last five years')));
end $$;

create or replace function pc_recall_card_vendor(v text, md text)
returns jsonb language plpgsql stable as $$
declare n5 int; c1 int; open_n int; cause text; n_all int;
begin
  with ev as (
    select event_id, min(initiated) initiated, bool_or(recall_class = 'Class I') is_c1, bool_or(status ilike 'open%') is_open,
           max(root_cause) root_cause
    from pc_recalls where vendor_id in (select vendor_id from pc_vendor_family(v, md) where md = 'current' or vendor_id = v)
    group by event_id)
  select count(*) filter (where initiated > current_date - interval '5 years'),
         count(*) filter (where initiated > current_date - interval '5 years' and is_c1),
         count(*) filter (where is_open), count(*),
         (select root_cause from ev e2 where e2.initiated > current_date - interval '5 years' and root_cause is not null
            group by root_cause order by count(*) desc limit 1)
    into n5, c1, open_n, n_all, cause from ev;
  return pc_card('recalls', 'What is their recall history?',
    case when open_n > 0 then open_n || ' listed open' when n5 > 0 then n5 || ' in five years' else 'None in five years' end,
    case when c1 > 0 or open_n > 0 then 'attention' else 'info' end,
    case when n_all = 0 then 'No FDA recalls linked to this vendor since 2002.'
         else n5 || ' recall event' || case when n5 = 1 then '' else 's' end || ' in the last five years'
              || case when c1 > 0 then ' (' || c1 || ' Class I)' else '' end
              || ', ' || n_all || ' since 2002; ' || open_n || ' still listed as open by FDA.'
              || coalesce(' Most common recent cause in FDA''s records: ' || lower(cause) || '.', '') end,
    'Recall counts reflect product issues and how readily a company reports and corrects them, and larger portfolios usually have more. Read the reasons, not just the count.',
    'Which recalls affect products we use or are evaluating, and are all corrective actions complete?',
    'recalls')
    || jsonb_build_object('headline', case when n5 > 0 then n5 || ' recall' || case when n5 = 1 then '' else 's' end || ' in five years.'
                                           when n_all > 0 then 'No recalls in five years.' else 'No recalls on record.' end,
                          'short', 'Recalls',
                          'figs', jsonb_build_array(
                             jsonb_build_object('value', n5::text, 'label', 'recall events, last five years'),
                             jsonb_build_object('value', c1::text, 'label', 'Class I, last five years'),
                             jsonb_build_object('value', open_n::text, 'label', 'listed as open by FDA'),
                             jsonb_build_object('value', n_all::text, 'label', 'since 2002')));
end $$;

grant execute on function pc_recall_event_rows(text[], int), pc_device_recalls(text), pc_vendor_recalls(text, text, int),
  pc_recall_card_product(text, text), pc_recall_card_vendor(text, text) to anon, authenticated;
