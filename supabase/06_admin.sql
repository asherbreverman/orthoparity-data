-- OrthoParity database: maintenance functions and connection settings
-- Part of the OrthoParity data pipeline (MIT License). Run the files in this folder in number order in the
-- Supabase SQL Editor (or psql). Every file is safe to run again. See supabase/README.md.

-- The dashboard importer can store empty cells as empty text. Run  select pc_clean_blanks();  once after each
-- import to turn them into NULL, which the lookup functions expect.
create or replace function pc_clean_blanks()
returns text language plpgsql as $$
declare r record; n bigint; total bigint := 0;
begin
  for r in select c.table_name, c.column_name from information_schema.columns c
            where c.table_schema = 'public' and c.table_name like 'pc\_%' and c.data_type = 'text'
  loop
    execute format('update %I set %I = null where %I = ''''', r.table_name, r.column_name, r.column_name);
    get diagnostics n = row_count; total := total + n;
  end loop;
  return total || ' empty cells set to NULL';
end $$;
revoke execute on function pc_clean_blanks() from public, anon, authenticated;

-- research studies in orthopedic scope. Open Payments research rows from diversified companies include
-- cardiac, neurovascular, neuromodulation and other non-orthopedic trials. pc_refresh_research_scope() marks each
-- row: out if the study name is clearly non-orthopedic; in if it names an orthopedic 510(k), an orthopedic topic,
-- or one of the vendor's top orthopedic brands; otherwise in only for vendors whose payments are mostly orthopedic.
-- Run it again after re-importing pc_op_research (07_after_import.sql does).
create or replace function pc_refresh_research_scope()
returns text language plpgsql as $$
declare n_in bigint; n_out bigint;
begin
  with cls as (
    select r.ctid as rid,
      case when r.study_name ~* ('(\mSCS\M|spinal cord stim|neurostim|neuromodulat|\m10 ?kHz|\mHF10\M|deep brain|implanted electrode'
                 || '|glycemic|diabet|insulin|\mDPN\M|aneurysm|thrombectom|stroke|neurovascular|cardi|atrial|\mAF\M|\mLAA\M|aortic|endovascular'
                 || '|\mTAVR|valve|hypertens|pacing|pacemaker|breast|hernia|bariatric|reflux|cystoscop|kidney|renal|nephrolith|urolog|fetal|dental'
                 || '|\mDFU|venous|wound (care|dressing|healing|matrix)|\mburn)') then false
           when exists (select 1 from unnest(string_to_array(coalesce(r.knumbers, ''), '|')) k
                        join pc_portfolio_510k p on p.knumber = k)
             or r.study_name ~* ('(orthop|spine|spinal|lumbar|cervical|thoracic|sacr|scolio|deformit|kyphopl|vertebr|\mdisc|fusion'
                 || '|\m[atpxo]lif\M|laminect|stenosis|spondyl|knee|\mhip|shoulder|elbow|wrist|\mhand|ankle|\mfoot|femor|tibi|humer|pelvi'
                 || '|fractur|trauma|fixation|arthro|joint|menisc|cartilage|rotator|tendon|ligament|\mACL\M|osteo|\mbone|avascular necrosis'
                 || '|nonunion|sports med)') then true
           when exists (select 1 from pc_op_product_top t where t.mode = 'pit' and t.vendor_id = r.vendor_pit
                          and length(t.brand) >= 4 and position(lower(t.brand) in lower(r.study_name)) > 0) then true
           when exists (select 1 from pc_vendors x where x.vendor_id = r.vendor_pit and x.payment_kind = 'dedicated') then true
           else false end as keep
    from pc_op_research r)
  update pc_op_research r set ortho = cls.keep from cls where r.ctid = cls.rid;
  select count(*) filter (where ortho), count(*) filter (where not ortho) into n_in, n_out from pc_op_research;
  return n_in || ' research rows in orthopedic scope, ' || n_out || ' out of scope';
end $$;
revoke execute on function pc_refresh_research_scope() from public, anon, authenticated;

-- ---------------------------------------------------------------- connection settings
-- Give public page requests more time on a cold database. Supabase's default limit for the anon role is short;
-- a first visit after a quiet period can exceed it while the database warms up.
alter role anon set statement_timeout = '15s';
alter role authenticated set statement_timeout = '15s';
notify pgrst, 'reload config';
