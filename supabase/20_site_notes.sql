-- 20_site_notes.sql: the public corrections log and the data release notes (Phase 7).
-- This file holds its own rows. To add a correction or a release, add a row here (newest first is not required),
-- then run the whole file in Supabase. Safe to run again.
--
-- A correction is a change to something the site showed that was wrong or misleading. Wording polish and new
-- features are release notes, not corrections.

create table if not exists pc_corrections (
  id text primary key, corrected_on date not null, area text, what_was_wrong text, what_changed text,
  pages_affected text, source text);
create table if not exists pc_release_notes (
  id text primary key, released_on date not null, title text, summary text, data_release text, url text);

do $$ declare t text; begin
  foreach t in array array['pc_corrections', 'pc_release_notes'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "public read" on %I', t);
    execute format('create policy "public read" on %I for select to anon, authenticated using (id is not null)', t);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
end $$;

delete from pc_corrections;
insert into pc_corrections (id, corrected_on, area, what_was_wrong, what_changed, pages_affected, source) values
  ('2026-11-20-product-codes', '2026-11-20', 'Product code names',
   '21 of 254 plain-English product code names did not match FDA''s definitions. For example, HSX and HRY read as total knee only, SJA read as a heat nerve treatment, QHG read as a cartilage tool, and OSF and OJP read as spine guidance.',
   'All 254 names were reviewed against FDA''s classification definitions; 21 were rewritten (HSX and HRY: partial or total knee; SJA: cold nerve treatment; QHG: spinal disc device; OSF and OJP: hip and knee guidance).',
   'Every product and company page that shows those codes', 'CHANGELOG, Draft labels cleared'),
  ('2026-11-20-procedure-links', '2026-11-20', 'Medicare procedure links',
   'Product code OJP was linked to lumbar and cervical fusion, but its clearances are hip and knee robots. Product code KWI (radial head) was linked to shoulder and elbow replacement, but MS-DRG 483 covers elbow joint replacement, not radius replacement. Anterior cervical staples (PHQ) had no procedure link.',
   'OJP and KWI links removed; PHQ linked to cervical fusion.', 'Medicare box on OJP, KWI and PHQ products; fusion and shoulder procedure pages',
   'CHANGELOG, Draft labels cleared'),
  ('2026-11-22-ownership', '2026-11-22', 'Company ownership',
   '24 companies appeared twice under different IDs (same FDA address), some acquired companies rolled up to the wrong parent (for example Pioneer Surgical), and some headers read "X, now part of X".',
   'Duplicates merged, roll-ups corrected against SEC filings, company releases or trade press, and self-referencing headers removed.',
   'Affected company pages and every product page that names their owner', 'CHANGELOG, Full-site scan fixes'),
  ('2026-11-22-distribution', '2026-11-22', 'Distribution box',
   'Companies with no brand in FDA''s GUDID read "Every brand is in distribution" (about 1,300 company records).',
   'Those companies now read NOT FOUND, with the reason (GUDID starts in 2014 and some products sell under another company''s label).',
   'About 1,300 company pages', 'CHANGELOG, Full-site scan fixes'),
  ('2026-11-22-predicate-only', '2026-11-22', 'Out-of-scope pages',
   '4,284 510(k)s that are on file only as predicates of orthopedic devices received a full decision brief, as if they were orthopedic products.',
   'They no longer get a full brief; they stay visible in predicate chains.', '4,284 product pages', 'CHANGELOG, Full-site scan fixes'),
  ('2026-11-22-evidence-label', '2026-11-22', 'Industry studies box',
   'The box asked "What clinical evidence exists?" and could read "None in Open Payments", which reviewers took to mean no clinical evidence at all. It only counts industry-funded studies reported in Open Payments.',
   'The product box now asks "What industry-funded studies name it?" and the company box "Are they funding clinical studies?".',
   'Every product and company page', 'CHANGELOG, Evidence box renamed'),
  ('2026-11-22-empirical-spine', '2026-11-22', 'Company ownership',
   'LimiFlex (P220031, K253374) was shown under Enovis because a name pattern for Empi, Inc. matched "Empirical".',
   'Empirical Spine is its own company.', 'LimiFlex product pages; Enovis and Empirical Spine company pages', 'CHANGELOG, Phase 5 review'),
  ('2026-11-22-approval-dates', '2026-11-22', 'FDA approval dates',
   '7 approvals whose original record is missing from FDA''s PMA and HDE databases showed their earliest supplement date as the approval date.',
   'Those pages read "Approval date not on file" (NOT FOUND).', '7 approval pages', 'CHANGELOG, Phase 5 review'),
  ('2026-11-22-approval-class', '2026-11-22', 'Device class',
   '30 PMAs in product codes FDA later reclassified read "Class III".', 'They say the code was reclassified and no longer read Class III.',
   '30 approval pages', 'CHANGELOG, Phase 5 review'),
  ('2026-11-22-approval-payments', '2026-11-22', 'Payments on approval pages',
   'Approval pages read only the orthopedic-scope payment set (Synvisc showed none) and picked up brand-name payments that belong to 510(k) pages (Trident, the Osteonics constrained insert, BHR).',
   'Approval pages read every Open Payments record linked to them, and brands shared with 510(k)s stay on the 510(k) pages.',
   'Approval pages with payments', 'CHANGELOG, Phase 5 review'),
  ('2026-11-22-approval-codes', '2026-11-22', 'Product code names',
   '4 of the 37 product code names added with FDA approvals were inaccurate (QGP, OJZ, NOX, MPW).', 'Corrected against FDA''s definitions.',
   'Approval pages in those codes', 'CHANGELOG, Phase 5 review'),
  ('2026-11-23-compare-null', '2026-11-23', 'Company compare',
   'Products with no FDA product code on file showed as a "null" row (Alphatec Spine, K243461).',
   'They are left out of the code lists and counted in a note instead.', 'Company compare pages', 'CHANGELOG, Phase 6'),
  ('2026-11-23-compare-mix', '2026-11-23', 'Company compare payments',
   'The payment mix summed 2019 to 2025 under a single-year heading (Globus royalties read 71.8%; the 2025 figure is 70.2%).',
   'The mix uses the same year as the payment totals next to it.', 'Company compare pages', 'CHANGELOG, Phase 6');

delete from pc_release_notes;
insert into pc_release_notes (id, released_on, title, summary, data_release, url) values
  ('2026-11-20', '2026-11-20', 'Adverse events, supplier record, add-on payments and question boxes',
   'MAUDE adverse event reports, manufacturing sites and FDA inspections, Medicare NTAP and pass-through payments, and 12 product and 11 company question boxes.',
   'data-2026-11-20', 'https://github.com/asherbreverman/orthoparity-data/releases/tag/data-2026-11-20'),
  ('2026-11-22', '2026-11-22', 'FDA approvals (PMA and HDE)',
   '131 orthopedic PMAs and HDEs with 2,554 supplements, each with a full product page.', '', ''),
  ('2026-11-23', '2026-11-23', 'Medicare ASC rates and part-number search',
   'CY 2027 ASC rates and device portions for 12 key procedure codes, and part-number lookup from FDA GUDID (993,975 numbers).', '', ''),
  ('2026-11-24', '2026-11-24', 'TEAM, registered trials and category directories',
   'Medicare''s TEAM episode model (trigger codes, CMS 2026 and 2027 regional target prices, 721 participating hospitals), registered trials from ClinicalTrials.gov, and a complete directory of every orthopedic FDA record by product code.',
   '', '');

grant select on pc_corrections, pc_release_notes to anon, authenticated;
