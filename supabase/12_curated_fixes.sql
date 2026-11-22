-- 12_curated_fixes.sql  (Phase 2, Nov 2026)
-- Run AFTER every CSV import and 07_after_import.sql, then rerun 05. Safe to run more than once.
-- Every ownership fact below carries its public source. Nothing here is a guess: where no source
-- confirmed a parent, the parent stays empty and the site says the company isn't reviewed yet.
--
--   A. Split vendors the pipeline merged because their names share one generic word
--      (L&K Biomed vs Q Biomed, N Spine vs US Spine vs L&K Spine, A&E Medical vs R&R Medical, ...)
--   B. Merge spelling variants of one company (GLW) and roll subsidiaries into their parent
--   C. Ownership changes and divestitures (lineage), with sources
--   D. Parents for public companies, with sources
--   E. Segments derived from each company's own FDA product codes
--   F. Medicare procedure mappings for product codes that had none
--   G. Recount vendor totals

begin;

-- ---------------------------------------------------------------------------------------------
-- helper: move one company's records out of a merged vendor into its own vendor id
-- ---------------------------------------------------------------------------------------------
create or replace function pg_temp.op_split(old_id text, new_id text, new_name text, rx text, move_brands boolean default false)
returns void language plpgsql as $$
declare moved text[];
begin
  if not exists (select 1 from pc_vendors where vendor_id = old_id) then return; end if;
  insert into pc_vendors (vendor_id, display_name, basis, reviewed, note, rolls_up_to)
  select new_id, new_name, 'own name', true,
         'Split from ' || old_id || ' in Phase 2 review: the pipeline had merged different companies whose names share one generic word',
         new_id
  where not exists (select 1 from pc_vendors where vendor_id = new_id);

  update pc_vendor_names set vendor_id = new_id where vendor_id = old_id and raw_name ~* rx;
  select array_agg(knumber) into moved from pc_portfolio_510k where vendor_id = old_id and applicant ~* rx;
  update pc_portfolio_510k set vendor_id = new_id where vendor_id = old_id and applicant ~* rx;
  update pc_recalls set vendor_id = new_id
   where vendor_id = old_id and (recalling_firm ~* rx or string_to_array(replace(coalesce(knumbers, ''), ' ', ''), '|') && coalesce(moved, '{}'));
  update pc_establishment set company_vendor_id = new_id where company_vendor_id = old_id and (name ~* rx or owner_operator_name ~* rx);
  if move_brands then
    update pc_portfolio_brands set vendor_id = new_id where vendor_id = old_id;
  end if;
end $$;

-- helper: rename a vendor only while it still holds the company the name belongs to
create or replace function pg_temp.op_rename(vid text, new_name text, rx text)
returns void language sql as $$
  update pc_vendors set display_name = new_name
   where vendor_id = vid and exists (select 1 from pc_vendor_names n where n.vendor_id = vid and n.raw_name ~* rx);
$$;

-- ---------------------------------------------------------------------------------------------
-- A. Splits (source: the FDA 510(k) applicant and GUDID labeler names themselves)
-- ---------------------------------------------------------------------------------------------
-- L&K Biomed: drop the Q BIOMED payer alias, which matched only because both names end in "Biomed"
delete from pc_vendor_names where vendor_id = 'n_biomed' and raw_name ~* '^q\s*biomed';
select pg_temp.op_rename('n_biomed', 'L&K Biomed Co., Ltd.', '^l\s*(&|and)\s*k\s+biomed');

-- n_spine held N Spine (applicant), US Spine (applicant) and L&K Spine (payer)
select pg_temp.op_split('n_spine', 'n_usspine', 'US Spine', '^u\.?\s*s\.?\s+spine$');
select pg_temp.op_split('n_spine', 'n_lkspine', 'L&K Spine Inc', '^l\s*(&|and)\s*k\s+spine');
-- every Open Payments record under n_spine was paid by L&K Spine (checked Nov 2026); runs only while that holds
do $do$ begin
if exists (select 1 from pc_vendor_names where vendor_id = 'n_lkspine' and source = 'payer')
   and not exists (select 1 from pc_op_entity where vendor_current = 'n_spine' and payer_name !~* '^l\s*&\s*k') then
update pc_op_entity        set vendor_pit = 'n_lkspine' where vendor_pit = 'n_spine';
update pc_op_entity        set vendor_current = 'n_lkspine' where vendor_current = 'n_spine';
update pc_op_product       set vendor_pit = 'n_lkspine' where vendor_pit = 'n_spine';
update pc_op_vendor_year   set vendor_id = 'n_lkspine' where vendor_id = 'n_spine';
update pc_op_vendor_profile set vendor_id = 'n_lkspine' where vendor_id = 'n_spine';
update pc_op_relationship  set vendor_id = 'n_lkspine' where vendor_id = 'n_spine';
update pc_op_product_top   set vendor_id = 'n_lkspine' where vendor_id = 'n_spine';
update pc_op_research      set vendor_pit = 'n_lkspine' where vendor_pit = 'n_spine';
update pc_op_research      set vendor_current = 'n_lkspine' where vendor_current = 'n_spine';
update pc_op_research      set vendor_entity = 'n_lkspine' where vendor_entity = 'n_spine';
update pc_op_ownership     set vendor_pit = 'n_lkspine' where vendor_pit = 'n_spine';
update pc_op_ownership     set vendor_current = 'n_lkspine' where vendor_current = 'n_spine';
end if;
end $do$;
update pc_vendors set payment_kind = 'no payments' where vendor_id = 'n_spine' and not exists (select 1 from pc_op_vendor_year where vendor_id = 'n_spine');
select pg_temp.op_rename('n_spine', 'N Spine, Inc.', '^n[\s-]*spine');
update pc_vendors set payment_kind = 'dedicated' where vendor_id = 'n_lkspine';

-- n_medical held seven unrelated "<letters> Medical" companies; A & E Medical keeps the id
select pg_temp.op_split('n_medical', 'n_rrmedical',      'R&R Medical, Inc.',       '^r\s*&\s*r\s+medical');
select pg_temp.op_split('n_medical', 'n_rdmedical',      'R and D Medical, LLC',    '^r\s*(and|&)\s*d\s+medical');
select pg_temp.op_split('n_medical', 'n_zmedical',       'Z-Medical GmbH & Co. KG', '^z[\s-]*medical');
select pg_temp.op_split('n_medical', 'n_camedical',      'C.A. Medical, LLC',       '^c\.?\s*a\.?\s+medical');
select pg_temp.op_split('n_medical', 'n_globalmedicalco','Global Medical Co.',      '^global\s+medical\s+co');
select pg_temp.op_split('n_medical', 'n_shmedical',      'S.H. Medical Corporation','^s\.?\s*h\.?\s+medical');
select pg_temp.op_rename('n_medical', 'A & E Medical Corporation', '^a\s*&\s*e\s+medical');

-- n_surgical: G Surgical, LLC keeps the id. G Surgical Co., Ltd. stays separate: no source ties the two.
select pg_temp.op_split('n_surgical', 'n_amsurgical',     'A.M. Surgical, Inc.',   '^a\.?\s*m\.?\s+surgical');
select pg_temp.op_split('n_surgical', 'n_esurgical',      'E Surgical, LLC',       '^e\s+surgical');
select pg_temp.op_split('n_surgical', 'n_nssurgical',     'N S Surgical Company',  '^n\.?\s*s\.?\s+surgical');
select pg_temp.op_split('n_surgical', 'n_gsurgicalcoltd', 'G Surgical Co., Ltd.',  '^g\s+surgical\s+co');
select pg_temp.op_rename('n_surgical', 'G Surgical, LLC', '^g\s+surgical,?\s+llc');

-- n_medicalproducts: U.S. Medical Products keeps the id; every GUDID brand here is T.A.G.'s (only labeler)
select pg_temp.op_split('n_medicalproducts', 'n_tagmedicalproducts', 'T.A.G. Medical Products Corporation, Ltd.', '^t\.?\s*a\.?\s*g\.?\s+medical', true);
select pg_temp.op_rename('n_medicalproducts', 'U.S. Medical Products, Inc.', '^u\.?\s*s\.?\s+medical\s+products');

-- n_instruments: H&H Instruments keeps the id; the GUDID brand is J & J Instruments' (only labeler)
select pg_temp.op_split('n_instruments', 'n_jjinstruments', 'J & J Instruments Inc', '^j\s*&\s*j\s+instruments', true);
select pg_temp.op_rename('n_instruments', 'H&H Instruments', '^h\s*&\s*h\s+instruments');

-- integra: the family pattern ^integra also caught two unrelated companies
select pg_temp.op_split('integra', 'n_integratedsurgicalsystems', 'Integrated Surgical Systems, Inc.', '^integrated\s+surgical');
select pg_temp.op_split('integra', 'n_integratedendoscopy',       'Integrated Endoscopy, Inc.',        '^integrated\s+endoscopy');

-- ---------------------------------------------------------------------------------------------
-- B. Same company under spelling variants, and subsidiaries rolled into their parent
-- ---------------------------------------------------------------------------------------------
-- GLW: all three applicant names file from 300 Sylvan Ave., Englewood Cliffs, NJ with the same contact
-- (openFDA 510(k) records K201379, K213005, K200343). The same CREED brand appears under two of them.
update pc_vendors set rolls_up_to = 'n_glw' where vendor_id in ('n_glwmedical', 'n_glwmedicalinnovation');
select pg_temp.op_rename('n_glw', 'GLW Medical', '^glw');

-- Brainlab AG converted to Brainlab SE on 2025-06-24 (same company)
update pc_vendors set rolls_up_to = 'n_brainlab' where vendor_id = 'n_brainlabse';
select pg_temp.op_rename('n_brainlab', 'Brainlab', '^brainlab');

-- Suzhou MicroPort OrthoRecon is a subsidiary of MicroPort Orthopedics. Shanghai MicroPort Orthopedics
-- and MicroPort NaviBot stay separate: no source found that places them under MicroPort Orthopedics.
update pc_vendors set rolls_up_to = 'n_microportorthopedics' where vendor_id = 'n_suzhoumicroportorthorecon';

-- L&K Spine is L&K Biomed's U.S. subsidiary
update pc_vendors set rolls_up_to = 'n_biomed' where vendor_id = 'n_lkspine';

-- ---------------------------------------------------------------------------------------------
-- C. Ownership changes and divestitures
-- ---------------------------------------------------------------------------------------------
delete from pc_vendor_lineage where note like 'Phase 2:%';
insert into pc_vendor_lineage (vendor_id, parent, relation, valid_from, valid_to, source_url, note, reviewed) values
 ('n_brainlabse', 'n_brainlab', 'renamed from', '2025-06-24', null,
  'https://www.brainlab.com/press-releases-landingpage/brainlab-se-conversion-into-european-stock-corporation-completed/',
  'Phase 2: Brainlab AG converted into a European stock corporation (SE)', true),
 ('n_glwmedical', 'n_glw', 'same company as', null, null, 'https://api.fda.gov/device/510k.json?search=applicant:GLW',
  'Phase 2: same address and contact on FDA 510(k) records', true),
 ('n_glwmedicalinnovation', 'n_glw', 'same company as', null, null, 'https://api.fda.gov/device/510k.json?search=applicant:GLW',
  'Phase 2: same address on FDA 510(k) records', true),
 ('n_suzhoumicroportorthorecon', 'n_microportorthopedics', 'subsidiary of', null, null,
  'https://microport.com/news/microport-orthopedics-first-chinese-made-total-hip-arthroplasty-system-receives-nmpa-approval',
  'Phase 2: MicroPort describes Suzhou MicroPort OrthoRecon as a subsidiary of MicroPort Orthopedics', true),
 ('n_lkspine', 'n_biomed', 'subsidiary of', null, null, 'https://www.asiae.co.kr/en/article/2022051815135184965',
  'Phase 2: L&K Biomed''s newly established U.S. subsidiary (2022)', true),
 ('n_pioneersurgicaltechnology', 'surgalign', 'acquired by', '2013-07-16', '2020-07-20',
  'https://www.sec.gov/Archives/edgar/data/0001100441/000119312513295719/d570743dex991.htm',
  'Phase 2: RTI Biologics completed the Pioneer acquisition and renamed itself RTI Surgical (later Surgalign)', true),
 ('n_pioneersurgicaltechnology', 'Montagu Private Equity', 'acquired by', '2020-07-20', null,
  'https://www.businesswire.com/news/home/20200720005679/en/Montagu-Private-Equity-LLP-Completes-Acquisition-of-the-RTI-Surgical-OEM-Business',
  'Phase 2: Montagu bought RTI''s OEM business, which included Pioneer; the Pioneer metals business became Resolve Surgical Technologies (2022, MD+DI) and joined Exalta in Sept 2025 (Medical Design and Outsourcing)', true),
 ('n_corelink', 'n_zavationmedicalproducts', 'acquired by', '2023-06-26', null,
  'https://www.biospace.com/zavation-a-gemspring-capital-portfolio-company-acquires-corelink',
  'Phase 2: Zavation, a Gemspring Capital portfolio company, acquired CoreLink', true),
 ('n_amedica', 'n_ctlmedical', 'spine business acquired by', '2018-10-01', null,
  'https://www.sec.gov/Archives/edgar/data/1269026/000149315219017023/form10-q.htm',
  'Phase 2: Amedica sold its spine business to CTL Medical (CTL-Amedica); Amedica itself renamed SINTX Technologies on 2018-10-30', true),
 ('n_arthrosurface', 'anika', 'acquired by', '2020-02-03', '2024-10-31',
  'https://www.sec.gov/Archives/edgar/data/898437/000117184320000664/exh_991.htm',
  'Phase 2: Anika acquired Arthrosurface', true),
 ('n_arthrosurface', 'Phoenix Brio, Inc.', 'acquired by', '2024-10-31', null,
  'https://www.sec.gov/Archives/edgar/data/898437/000117184326001275/anik20251231_10k.htm',
  'Phase 2: Anika sold Arthrosurface to Phoenix Brio, Inc. (Anika FY2025 10-K)', true),
 ('n_kyoceramedicaltechnologies', 'Kyocera Corporation', 'wholly owned by', null, null,
  'https://www.orthoworld.com/kyocera-to-expand-u-s-business-with-purchase-of-renovis-surgical',
  'Phase 2: Kyocera Medical Technologies is a wholly owned Kyocera subsidiary formed in March 2019 with the Renovis assets', true),
 ('n_choicespine', 'n_zavationmedicalproducts', 'acquired by', '2026-02-26', null,
  'https://orthotw.com/2026/02/zavation-acquires-choicespine-names-derek-kuyper-ceo-of-combined-company',
  'Phase 2: Zavation acquired Choice Spine Holdings, Inc. (press release Feb 26, 2026)', true),
 ('n_vilex', 'Squadron Capital (affiliate Vilex LLC)', 'adult business sold to', '2019-12-31', null,
  'https://www.odtmag.com/?p=15353',
  'Phase 2: OrthoPediatrics kept the pediatric business (Vilex in Tennessee) and sold the adult business to Vilex LLC', true);

-- CoreLink now counts toward its acquirer's company page; Amedica's spine products toward CTL.
-- Pioneer stays on its own page: it left RTI/Surgalign with the OEM business in 2020.
update pc_vendors set rolls_up_to = 'n_pioneersurgicaltechnology' where vendor_id = 'n_pioneersurgicaltechnology';
update pc_vendors set rolls_up_to = 'n_zavationmedicalproducts' where vendor_id in ('n_corelink', 'n_choicespine');
update pc_vendors set rolls_up_to = 'n_ctlmedical'              where vendor_id = 'n_amedica';

-- Surgalign sold its hardware and biologics business to Xtant (SEC 8-K)
delete from pc_vendor_divestitures where note like 'Phase 2:%';
insert into pc_vendor_divestitures (seller, buyer, effective, product_codes, decided_before, source_url, note)
select 'surgalign', 'xtant', '2023-08-10',
       (select string_agg(distinct p.product_code, '|' order by p.product_code) from pc_portfolio_510k p
         where p.vendor_id = 'surgalign'),
       null, 'https://www.sec.gov/Archives/edgar/data/1453593/000149315223027585/ex99-1.htm',
       'Phase 2: Xtant acquired Surgalign''s hardware and biologics business';

-- ---------------------------------------------------------------------------------------------
-- D. Parents, each from a listing, filing or company statement
-- ---------------------------------------------------------------------------------------------
update pc_vendors v set current_parent = x.parent, reviewed = true,
       note = trim(both '; ' from coalesce(nullif(v.note, ''), '') || '; parent source: ' || x.src)
from (values
 ('n_medacta',                  'Medacta Group (public, SIX: MOVE)',               'https://www.six-group.com/de/newsroom/news/the-swiss-stock-exchange/2019/medacta.html'),
 ('n_medartis',                 'Medartis Holding (public, SIX: MED)',             'https://www.six-group.com/en/newsroom/archive/2018/20180323-ipo-medartis.html'),
 ('n_medartismedizinprodukteundforschung', 'Medartis Holding (public, SIX: MED)', 'https://www.six-group.com/en/newsroom/archive/2018/20180323-ipo-medartis.html'),
 ('n_kurosbiosciences',         'Kuros Biosciences (public, SIX: KURN)',           'https://kurosbio.gcs-web.com/ir-resources/investor-faqs'),
 ('n_carlsmed',                 'Carlsmed (public, Nasdaq: CARL)',                 'https://www.mofo.com/resources/news/250724-mofo-advises-carlsmed-on-initial'),
 ('n_treacemedicalconcepts',    'Treace Medical Concepts (public, Nasdaq: TMCI)',  'https://www.sec.gov/Archives/edgar/data/1630627/000095017025029029/0000950170-25-029029-index.html'),
 ('n_sibone',                   'SI-BONE (public, Nasdaq: SIBN)',                  'https://sec.gov/Archives/edgar/data/1459839/000145983924000034/sibn1231202310-kasfiled.pdf'),
 ('n_orthopediatrics',          'OrthoPediatrics (public, Nasdaq: KIDS)',          'https://orthopediatricscorp.gcs-web.com/static-files/75ffaf60-00d2-4e93-adb4-da3e52583051'),
 ('n_materialise',              'Materialise (public, Nasdaq: MTLS)',              'https://investors.materialise.com/static-files/620d7efc-7ed1-43e8-aa95-7fb00c8ab305'),
 ('n_unitedorthopedic',         'United Orthopedic (public, Taipei Exchange: 4129)','https://stockanalysis.com/quote/tpex/4129/company'),
 ('n_corentec',                 'Corentec Co., Ltd. (public, KOSDAQ: 104540)',     'https://stockanalysis.com/quote/kosdaq/104540/company'),
 ('n_biomed',                   'L&K Biomed (public, KOSDAQ: 156100)',             'https://stockanalysis.com/quote/kosdaq/156100/company'),
 ('n_lkspine',                  'L&K Biomed (public, KOSDAQ: 156100)',             'https://www.asiae.co.kr/en/article/2022051815135184965'),
 ('n_aegisspine',               'L&K Biomed held about 74% (Feb 2021)',            'https://www.asiae.co.kr/en/article/2021021512161063428'),
 ('n_kyoceramedicaltechnologies','Kyocera Corporation (public)',                   'https://www.orthoworld.com/kyocera-to-expand-u-s-business-with-purchase-of-renovis-surgical'),
 ('n_medlineindustries',        'Medline (public, Nasdaq: MDLN since Dec 2025)',   'https://newsroom.medline.com/?p=149856'),
 ('n_brainlab',                 'Brainlab SE (private)',                           'https://www.brainlab.com/press-releases-landingpage/brainlab-se-conversion-into-european-stock-corporation-completed/'),
 ('n_microportorthopedics',     'MicroPort Scientific (public, HKEX: 0853)',       'https://microport.com/news/microport-orthopedics-announces-launch-of-ha-coated-collared-hip-stem-and-cemented-collared-hip-stem-expanding-its-hip-stem-portfolio'),
 ('n_zavationmedicalproducts',  'Gemspring Capital portfolio company',             'https://www.biospace.com/zavation-a-gemspring-capital-portfolio-company-acquires-corelink'),
 ('n_ctlmedical',               'CTL Medical (privately held)',                    'https://www.sec.gov/Archives/edgar/data/1269026/000149315219017023/form10-q.htm'),
 ('n_arthrosurface',            'Phoenix Brio, Inc.',                              'https://www.sec.gov/Archives/edgar/data/898437/000117184326001275/anik20251231_10k.htm'),
 ('n_vilex',                    'Vilex LLC, a Squadron Capital affiliate',         'https://www.odtmag.com/?p=15353'),
 ('n_clariance',                'Clariance SpineVision (Clariance and SpineVision merged, June 2024)', 'https://thespinemarketgroup.com/clariance-and-spinevision-are-pleased-to-announce-their-merger-which-will-strengthen-their-position-in-the-fiercely-competitive-market-for-spine-surgery-medical-devices'),
 ('n_spinevision',              'Clariance SpineVision (Clariance and SpineVision merged, June 2024)', 'https://thespinemarketgroup.com/clariance-and-spinevision-are-pleased-to-announce-their-merger-which-will-strengthen-their-position-in-the-fiercely-competitive-market-for-spine-surgery-medical-devices'),
 ('n_pioneersurgicaltechnology','Exalta, owned by Montagu Private Equity',          'https://www.medicaldesignandoutsourcing.com/montagu-private-equity-exalta-medtech-cdmo-intech-resolve-tyber/'),
 ('n_tybermedical',             'Exalta, owned by Montagu Private Equity',          'https://www.medicaldesignandoutsourcing.com/montagu-private-equity-exalta-medtech-cdmo-intech-resolve-tyber/'),
 ('n_acumed',                   'Colson Medical (Marmon Holdings, a Berkshire Hathaway company)', 'https://www.marmon.com/?p=6164'),
 ('n_microairesurgicalinstruments', 'Colson Medical (Marmon Holdings, a Berkshire Hathaway company)', 'https://www.marmon.com/?p=6164'),
 ('n_lifespine',                'Life Spine (privately held)',                     'https://www.businesswire.com/news/home/20260217738041/en'),
 ('n_corelink',                 'Zavation (Gemspring Capital portfolio company)',  'https://www.biospace.com/zavation-a-gemspring-capital-portfolio-company-acquires-corelink'),
 ('n_choicespine',              'Zavation (Gemspring Capital portfolio company)',  'https://orthotw.com/2026/02/zavation-acquires-choicespine-names-derek-kuyper-ceo-of-combined-company'),
 ('n_amedica',                  'Spine business: CTL Medical since Oct 2018',      'https://www.sec.gov/Archives/edgar/data/1269026/000149315219017023/form10-q.htm'),
 ('n_glw',                      'NOT FOUND: no public ownership record',           'https://api.fda.gov/device/510k.json?search=applicant:GLW')
) as x(vid, parent, src)
where v.vendor_id = x.vid and (v.note is null or v.note not like '%' || x.src || '%');
-- GLW: keep NOT FOUND out of the parent field itself; the site already says "not yet reviewed"
update pc_vendors set current_parent = null where vendor_id = 'n_glw' and current_parent like 'NOT FOUND%';

-- ---------------------------------------------------------------------------------------------
-- E. Segments from each company's own 510(k) product codes (only where no reviewer set one)
-- ---------------------------------------------------------------------------------------------
with s as (
  select p.vendor_id, c.segment, count(*) n
    from pc_portfolio_510k p join pc_product_codes c using (product_code)
   where c.segment not in ('Instruments', 'Other / Non-surgical')
   group by 1, 2),
r as (
  select vendor_id, segment, n::numeric / sum(n) over (partition by vendor_id) sh,
         row_number() over (partition by vendor_id order by n desc, segment) rk from s),
pick as (
  select a.vendor_id,
         case when b.segment is not null and a.sh < 0.6 and b.sh >= 0.2 then a.segment || ' and ' || lower(b.segment)
              else a.segment end seg
    from r a left join r b on b.vendor_id = a.vendor_id and b.rk = 2
   where a.rk = 1)
update pc_vendors v set segment = pick.seg,
       note = trim(both '; ' from coalesce(nullif(v.note, ''), '') || '; segment derived from the FDA product codes of its 510(k)s')
  from pick where v.vendor_id = pick.vendor_id and coalesce(v.segment, '') = '';

update pc_vendors v set segment = 'Instruments',
       note = trim(both '; ' from coalesce(nullif(v.note, ''), '') || '; segment derived from the FDA product codes of its 510(k)s')
 where coalesce(v.segment, '') = ''
   and exists (select 1 from pc_portfolio_510k p join pc_product_codes c using (product_code)
                where p.vendor_id = v.vendor_id and c.segment = 'Instruments');

-- ---------------------------------------------------------------------------------------------
-- F. Medicare mappings
--   OUR/SCY/QSR sacroiliac fusion -> MS-DRG 459/460 (CMS MS-DRG v42 definitions, P0194)
--   KWI radial head, QHE shoulder system -> MS-DRG 483 (CMS MS-DRG v33 P0193, v44 P0209)
--   HSN/OYK total ankle -> MS-DRG 469/470, whose CMS title includes total ankle replacement (v41.1)
-- ---------------------------------------------------------------------------------------------
delete from pc_procedure_devices where (family_id, product_code) in (('thoracolumbar_fusion', 'OUR'), ('thoracolumbar_fusion', 'SCY'),
  ('thoracolumbar_fusion', 'QSR'), ('shoulder_elbow_replacement', 'KWI'), ('shoulder_elbow_replacement', 'QHE'),
  ('hip_knee_replacement', 'HSN'), ('hip_knee_replacement', 'OYK'));
insert into pc_procedure_devices (family_id, role, product_code, plain_name, fda_name, clearances_all, clearances_recent, active_vendors, status)
select m.family_id, m.role, c.product_code, c.plain_name, c.fda_name,
       (select count(*) from pc_devices d where d.product_code = c.product_code),
       (select count(*) from pc_devices d where d.product_code = c.product_code and d.decision_date::date >= current_date - interval '5 years'),
       (select count(distinct p.vendor_id) from pc_portfolio_510k p where p.product_code = c.product_code and p.decision_date::date >= current_date - interval '5 years'),
       'reviewed'
  from (values ('thoracolumbar_fusion', 'implant', 'OUR'), ('thoracolumbar_fusion', 'instrument', 'SCY'),
               ('thoracolumbar_fusion', 'instrument', 'QSR'), ('shoulder_elbow_replacement', 'implant', 'KWI'),
               ('shoulder_elbow_replacement', 'instrument', 'QHE'), ('hip_knee_replacement', 'implant', 'HSN'),
               ('hip_knee_replacement', 'instrument', 'OYK')) m(family_id, role, code)
  join pc_product_codes c on c.product_code = m.code
 where not exists (select 1 from pc_procedure_devices x where x.family_id = m.family_id and x.product_code = m.code);

-- ---------------------------------------------------------------------------------------------
-- G. Recount totals for every vendor touched above
-- ---------------------------------------------------------------------------------------------
update pc_vendors v set
  clearances          = coalesce(a.n, 0),
  first_clearance_year = a.y1,
  last_clearance_year  = a.y2,
  gudid_ortho_devices = coalesce(b.devs, 0),
  gudid_brands        = coalesce(b.nb, 0)
from pc_vendors v2
left join (select vendor_id, count(*) n, min(extract(year from decision_date::date))::int y1, max(extract(year from decision_date::date))::int y2
             from pc_portfolio_510k group by 1) a on a.vendor_id = v2.vendor_id
left join (select vendor_id, sum(devices) devs, count(*) nb from pc_portfolio_brands group by 1) b on b.vendor_id = v2.vendor_id
where v.vendor_id = v2.vendor_id
  and v.vendor_id in ('n_biomed', 'n_spine', 'n_usspine', 'n_lkspine', 'n_medical', 'n_rrmedical', 'n_rdmedical', 'n_zmedical',
                      'n_camedical', 'n_globalmedicalco', 'n_shmedical', 'n_surgical', 'n_amsurgical', 'n_esurgical', 'n_nssurgical',
                      'n_gsurgicalcoltd', 'n_medicalproducts', 'n_tagmedicalproducts', 'n_instruments', 'n_jjinstruments', 'integra',
                      'n_integratedsurgicalsystems', 'n_integratedendoscopy');
update pc_vendors set payment_kind = 'no payments'
 where payment_kind is null and vendor_id in (select vendor_id from pc_vendors where note like 'Split from %');

commit;
