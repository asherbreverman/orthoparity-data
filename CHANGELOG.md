# Changelog

## Phase 5 review: every approval page checked (2026-11-22)

A review of all 131 PMA and HDE pages, their company pages and search, against FDA's PMA and HDE databases.

- **Payments:** approval pages now read every Open Payments record that links to them, not only the orthopedic-scope
  set (Synvisc went from none to $94K). Brands shared with 510(k)s are no longer counted on approval pages (Trident,
  the Osteonics constrained insert and BHR had picked up brand-name payments that belong to 510(k) pages). Records that name a product without a device ID or a GUDID
  brand are not counted, and the box says so.
- **Empirical Spine:** LimiFlex (P220031, K253374) belonged to Enovis because the pattern for Empi, Inc. matched
  "Empirical". It is its own company now.
- **Dates:** 7 approvals whose original is missing from FDA's database read NOT FOUND for the approval date instead of
  showing the earliest supplement as the approval. Dates drop the leading zero ("Aug 8", not "Aug 08") site-wide.
- **Reclassified codes:** 30 PMAs in codes FDA later moved to Class II say so, and no longer read "Class III".
- **Text:** FDA's ALL CAPS indications and supplement descriptions read in sentence case; stray Windows characters
  ("Infuse\x99") fixed.
- **Adverse events:** boxes with no recent report say newer reports often leave the FDA number blank.
- **Sites:** a company's own registered site no longer reads as a partner when FDA lists it under another company
  name (Genzyme for Sanofi Genzyme).
- **Company pages:** 510(k) wording on company pages that include approvals (MAUDE, momentum, "no recent
  clearances"), and a pointer from the payments box to product-level payments.
- **Names and Medicare links:** the 37 draft product code names reviewed (QGP, OJZ, NOX and MPW corrected) and 21
  Medicare procedure links added, by Claude at the project owner's direction, pending professional review.
- **Tests:** casing, character cleanup and site ownership (`tests/test_approvals.py`, 133 pass).

SQL to run: re-import the three approval CSVs (truncate first), then `13`, `02`, `12` and `05`.

## FDA approvals: PMA and HDE (Phase 5, 2026-11-22)

Class III orthopedic devices are on the site now, with one page per approval.

- **131 approvals:** 116 PMAs (including hyaluronic acid knee injections and bone growth stimulators) and 15
  humanitarian device exemptions (HDEs), from openFDA's PMA dataset and FDA's HDE database, advisory committee
  Orthopedic.
- **Supplements:** 2,554 on file. Each page lists new indications, design, labeling and post-approval study changes
  (914) and counts manufacturing and site notices. Every supplement is in `pc_approval_supplements.csv`.
- **Every box hooked in:** GUDID catalog items, Open Payments, recalls, MAUDE reports, FDA-registered sites, Medicare
  add-on payments (Infuse, PearlMatrix, TOPS and TOUCH CMC 1 now show on their own pages) and company totals.
- **Wording:** approval pages say approved, PMA or HDE, explain what each pathway means, and drop the predicate
  questions. The "Is it new?" box shows the supplement history instead of a predicate chain.
- **Alternatives:** an approval counts as active in its product code when FDA approved it or a supplement to it in
  the last five years. Company pages count 510(k)s and approvals separately.
- **New companies and product codes:** 25 applicants FDA names that the registry did not have, and 37 product codes
  with draft plain-English names (`reference/approval_product_codes.csv`) awaiting review. The new codes are not yet
  mapped to Medicare procedure families.
- **Search:** P, H and N numbers open their page.
- **Tests:** supplement categories, indications text and record building (`tests/test_approvals.py`).

SQL to run: `13` (creates three tables), import `pc_approvals.csv`, `pc_approval_supplements.csv` and
`pc_approval_rows.csv`, then `13` again, `02`, `12` and `05`.

## Full-site scan fixes, reviewed ownership and page cache (Phases 2 to 4, 2026-11-21 to 2026-11-22)

A scan of every product page since 1996 and every company page, read the way a value analysis committee would.

- **Out-of-scope pages:** 510(k)s on file only as predicates no longer get a full brief (4,284 pages).
- **Wording:** zero counts, singular and plural ("1 device ID"), supplier and MAUDE text, form labels left in
  indications text, and companies whose names an automatic title case mangled.
- **Ownership:** 24 duplicate company IDs merged (same FDA address), wrong roll-ups fixed (for example Pioneer
  Surgical), product-line sales worded as such, and headers that read "X, now part of X".
- **Kyocera:** the record for Kyocera Corporation, Kyocera Medical Corporation and Kyocera Medical Technologies is named
  "Kyocera" (it read "Kyocera Medical, Inc.", a name no filing uses).
- **Medicare:** procedure family picked from the indications when the product code allows several; the "varies by
  procedure" card narrowed to the company's segments.
- **Distribution card:** companies with no GUDID brand now read NOT FOUND instead of "Every brand is in distribution"
  (about 1,300 company records).
- **Ties:** same-day clearances and equal counts break ties the same way every time.
- **Page cache:** the five heaviest page functions keep their answers in `pc_cache`; repeat visits read one row.
- **Tests:** "instrument" added to the allowed roles for procedure links.
- **Procedure links:** 30 product codes added to revision hip and knee (21), hip replacement for hip fracture (7) and
  primary hip and knee (2), from 54 candidates an AI crosswalk flagged, each checked against the CMS MS-DRG v41/v41.1
  code lists (`C:\OrthoData\Reviews\Procedure_Links_Phase4_DECISIONS.xlsx`, outside the repo). The revision family
  is picked from a device's name only for revision words; "semi-constrained" and "non-constrained" no longer count.
- **Outpatient status:** the 6 procedure codes that read NOT FOUND now carry their CY 2024 status from CMS's OPPS
  final rule Addenda B and E (lumbar fusion 22612, 22630, 22633: APC 5116; ACDF 22551: APC 5115; revision hip and
  knee: inpatient only). The other rows now cite the same CMS file instead of secondary summaries.

SQL to run: `02`, `03`, `10`, `12`, then `05`; after the link review, `12` and `05` again. No CSV import.

## Draft labels cleared (2026-11-20)

The project owner reviewed every hand-made entry the site labeled as draft (`Reviews/OrthoParity_Draft_Review_EASY.xlsx`,
outside the repo).

- Plain-English product code dictionary: all 254 codes reviewed (`reviews/Product_Code_Dictionary_REVIEW.xlsx`).
  233 approved as drafted, 21 corrected against FDA's definitions. Examples: HSX and HRY now say "partial or total
  knee" (most of their clearances are partial knees); SJA is a cold, not heat, nerve treatment; QHG is the Barricaid
  spinal disc tray, not a cartilage tool; OSF and OJP are hip and knee guidance, not spine; NOV is a facial anchor.
- Product-code-to-procedure links: 134 approved, 3 removed (OJP from lumbar and cervical fusion: its clearances
  are hip and knee robots; KWI radial head from shoulder and elbow replacement: DRG 483 lists elbow joint
  replacement, not replacement of the radius), 1 added (PHQ anterior cervical staple to cervical fusion). Total
  ankle and total wrist stay unlinked: CMS pays them under the hip-knee and shoulder-elbow DRGs, but the family
  names would mislabel them.
- The 7 procedure families added on 2026-11-19 are approved.

CSVs to re-import: `pc_product_codes.csv`, `pc_procedure_devices.csv`. No SQL changes.

## Question boxes and vendor questions (2026-11-20)

**Product pages ask 12 questions; vendor pages ask 11.** Every box is phrased as a question, shows even when the
answer is "none", and carries a short label for the tab bar. Each card now has `asks`, a list of questions for the
vendor that the data triggers (the first is still `ask`), so the "Questions for the vendor" list grows to about 16
to 22 per page. Changes in `supabase/05_decision_functions.sql`; new `pc_device_supplier` in `10_supplier_functions.sql`.

- Product boxes: Is it new? · What is it cleared to treat? (new) · Who sells it today? (new) · What else does the
  job? · What are the financial ties for this product? · What clinical evidence exists? · What will it take to
  stock on the shelf? · Any recalls? · Any adverse events? (new) · What is the vendor's supplier record? (new) ·
  What does Medicare pay for procedures that use it? (new) · Any Medicare add-on payments? (new)
- Vendor boxes: Where do they compete? · Are they still investing? · Have any acquisitions or mergers occurred?
  (reworded) · What are the financial ties for this vendor? (reworded) · Are they building clinical evidence? ·
  Is the portfolio in distribution? · Any recalls? · Any adverse events? (new) · What is the vendor's supplier
  record? (new) · What does Medicare pay for procedures that use their products? (new) · Any Medicare add-on
  payments? (new)
- New questions cover devices cleared on the same predicates and in the same product code, surgeon royalties and
  consulting rates at the asking hospital, the payments that name a product, study results and ClinicalTrials.gov
  postings, the GUDID part-number list, recalls on predicates, adverse event counts by type, manufacturing sites,
  contract manufacturers, foreign sites, OAI inspections and warning letters, construct cost against the Medicare
  payment, and add-on payment coding.
- The Medicare box is procedure-level: it names the procedure family, its DRGs and the payment range per case, and
  says the payment covers the whole stay and every implant in it.
- The indications box compares wording with the primary predicate's (trigram similarity); it is not a judgment of
  clinical scope.

SQL files to run: `04`, `05`, `10`. No new tables.

## Medicare add-on payments: NTAP and device pass-through (2026-11-20)

**Which orthopedic technologies get extra Medicare payment.** New step `load-add-on-payments` and new group `addon`.
It reads two CMS files, FY 2027 MAC Implementation File 8 (inpatient NTAP) and CY 2027 OPPS Addendum B (outpatient
device pass-through), and checks the new human-reviewed file `reference/add_on_payments.csv` against them. New tables
`pc_add_on_payment` and `pc_add_on_payment_510k`; new functions `pc_device_add_on` and `pc_vendor_add_on` in
`supabase/11_add_on_functions.sql`.

- 12 orthopedic NTAP technologies for FY 2027: 3 new (CMORE CT System, Infuse Bone Graft for TLIF, PearlMatrix
  P-15), 8 continued (VADER Pedicle System, 4WEB Ankle Truss System, aprevo-C, CERAMENT G for open fractures, EUROPA
  Posterior Cervical Fusion System, iFuse TORQ TNT, MY01, restor3d TIDAL Fusion Cage) and 1 discontinued (TOPS).
- 6 orthopedic device pass-through codes for CY 2027: C1737 (iFuse Bedrock Granite, expires during 2027), C1741
  (RemeOs), C1742 (MY01), C1608 (TOUCH CMC 1), C1609 (TOPS) and C1610 (TIDAL Fusion Cage, new January 1, 2027).
- They link to 25 starting-set 510(k)s. PMA devices show on company pages only.
- The step stops if any reviewed name, status, code or expiration flag disagrees with CMS, and its report lists
  every CMS technology the reference file leaves out (61 NTAP technologies and 13 pass-through codes; on review,
  none is orthopedic).

Tables to re-import: `pc_add_on_payment`, `pc_add_on_payment_510k` (new). SQL files to run: `01`, `07`, `11`.

## Supplier record: manufacturing sites, inspections and warning letters (2026-11-20)

**Who makes the product, and what FDA found there.** New steps `fetch-establishments` and `load-fda-compliance`
and new group `supplier`. The first downloads FDA establishment registrations from openFDA for the 254 orthopedic
product codes and links each site (FEI number) to the starting-set 510(k)s it lists. The second reads three FDA Data
Dashboard exports (inspections, Form 483 citations, compliance actions) and keeps the rows for those sites. New
tables `pc_establishment`, `pc_establishment_510k`, `pc_inspection`, `pc_inspection_citation` and
`pc_compliance_action`; new function `pc_vendor_supplier` in `supabase/10_supplier_functions.sql`.

- 2,944 sites list devices under the orthopedic codes; 981 list at least one starting-set 510(k), covering 11,661
  of 18,224 clearances. 612 of the 981 make, contract-make, remanufacture or sterilize.
- Each site gets a company only when its owner/operator's name matches a name the company files under. Logistics
  firms, distributors and contract manufacturers stay unmatched and show as partner sites. Sites of other device
  companies that list a company's older 510(k)s (usually a product line that changed hands) are counted
  separately.
- Kept for those sites: 6,529 inspection rows (fiscal year 2009 through Nov 6, 2026), 5,983 citation rows and 139
  compliance actions (all warning letters).
- The company page gets one place for recalls, MAUDE reports, inspections, 483 citations and warning letters.
  Facts only: nothing scores or grades a company.
- Contact people, US agents and official correspondents from the registrations are never kept.
- Some FDA site and case numbers happen to pass the NPI check digit. `check` now skips columns that hold FDA
  identifiers (`fei_number`, `registration_number`, `owner_operator_number`, `inspection_id`, `case_id`) and lists
  them as a note; every other column is still scanned.

Tables to re-import: the five new tables above. SQL files to run: `01`, `07`, `10`.

## Adverse event reports (MAUDE) (2026-11-20)

**MAUDE counts per 510(k).** New step `fetch-maude` and new group `maude`. It counts FDA adverse event reports
from openFDA for every clearance in the starting set, matched on the 510(k) number each report names: all
reports by event type, the last five years by event type, and reports by year received. It writes
`pc_maude_product` and `pc_maude_year`; new functions `pc_device_maude` and `pc_vendor_maude` in
`supabase/09_maude_functions.sql`. Company counts add up every 510(k) in the company's family, the same family
the portfolio and recalls use.

- 649,641 reports matched to 7,484 of 18,224 orthopedic 510(k)s (1,093 deaths, 443,643 injuries, 200,304
  malfunctions, 4,601 other or not answered), openFDA data through Nov 11, 2026. That equals about 48% of the
  1,341,166 reports filed under the 254 orthopedic product codes.
- FDA's data stores some 510(k) numbers with a leading P (PK140881 for K140881). Both forms count.
- A free openFDA API key goes in `.env` (or `.env.txt`) in the project folder; both are excluded from git, and
  `check` now flags an openFDA key in any published file.
- Limitations and the site's notes say plainly that a report is not proof of cause, counts are not rates, and
  counts are a floor.

Tables to re-import: `pc_maude_product`, `pc_maude_year` (new). SQL files to run: `01`, `07`, `09`.

## Medicare procedure view and parent-company benchmarking (2026-11-19)

**Medicare payments by procedure.** New step `load-medicare-hospitals` and new group `medicare`. It reads the CMS
Medicare Inpatient and Outpatient Hospitals by Provider and Service files (data year 2024) and writes six tables:
`pc_procedures`, `pc_procedure_drg`, `pc_procedure_apc`, `pc_procedure_outpatient`, `pc_procedure_devices` and
`pc_supply_evidence`. New functions in `supabase/08_procedure_functions.sql`.

- 15 procedure families, 58 surgical DRGs. The first 8 (fusion, joint replacement, revision, fracture fixation)
  carry 83% of Medicare's 2024 musculoskeletal inpatient payments; 7 more cover the other surgical DRGs with
  reported hospitals, for 88% in all.
- Payments split three ways: Medicare pays, patient and other payers, total.
- DRG titles now come from the CMS MS-DRG v41.1 Definitions Manual (`reference/drg_titles.csv`), complete and in
  sentence case. DRG lists sort by number.
- A hospital spread needs at least 5 reporting hospitals (`SPREAD_MIN_HOSPITALS`); otherwise it reads NOT FOUND
  with the count. The supply range appears only for the 8 families a published study covers; the rest read NOT
  FOUND with the reason.
- Outpatient status rows not confirmed from an official CMS list now say so in plain words.
- Device categories for the 7 added families were checked against public manufacturer coding guides and the CMS
  MS-DRG v41.1 manual. 28 links are marked reviewed and 10 without a clear source were removed (navigation and AR
  guidance from spine without fusion, the collagen meniscus implant, which Medicare doesn't cover, and 7 more).
  Antibiotic-eluting bone void filler moved from knee surgery to debridement, biopsy and amputation. Sources are in
  `reviews/Procedure_Families_Added_REVIEW.xlsx`.
- Limitations now note the October 2026 DRG renumbering (MS-DRG v44).

**Parent companies.** A vendor now always means the parent company with every company it owns.

- `pc_vendor_resolve` redirects a company another company owns to its parent, with an explanation and sources.
  `pc_vendor_search` returns parents only, with the owned company that matched; its 510(k) count includes every
  owned company. `pc_device_owner` gives a product's filer and its parent today. `pc_vendor_coverage` gives the
  home page counts (1,895 parent companies with clearances).
- Product-line sales follow the business by FDA product code (`reference/vendor_divestitures.csv`, new table
  `pc_vendor_divestitures`). Five sales, including Stryker's U.S. spine business to VB Spine (2025-04-01), 4WEB's
  osteotomy and ankle truss lines to Stryker (2024-09-11), and EBI's spine lines to Highridge with the ZimVie
  spine sale.
- Ownership grew from 25 dated events to 83 dated links, each with a source. Every claim checked is in
  `reference/ownership_sources.csv` with its status; 3 are not applied. Business and trade press now count as
  sources alongside SEC filings and company releases. 29 same-company name variants were merged.
- The "as owned at the time" switch is gone from the site. The dated roll-up still drives "Is it new?".
- Recalls were re-linked to the new vendor list: 141 of 8,096 remain unlinked.

**Tables to re-import:** `pc_vendors`, `pc_vendor_names`, `pc_vendor_lineage`, `pc_vendor_divestitures`,
`pc_portfolio_510k`, `pc_portfolio_brands`, `pc_recalls`, the eight `pc_op_*` tables, and the six procedure tables.

## 0.4.1: company matching and ownership wording (2026-11-18)

- "Is it new?" now treats two predicates as the same company when both applicants belong to vendors with the same
  owner on the clearance date, not only when the printed names match. Example: ATTUNE (K140881, "Depuy(Ireland)")
  citing "DePuy Orthopaedics, Inc." predicates was labeled a competitive entry; it is a line extension. Across the
  11,995 starting-set devices with predicates on file, about 1,490 (12%) changed label, nearly all toward line
  extension (1,060 now read as line extensions).
  New functions: `pc_applicant_vendor`, `pc_owner_at`, `pc_same_company`; `pc_direct` and `pc_compare` use them.
- Vendor ownership card: a vendor with acquisitions older than five years now reads "No recent changes" and lists
  them, where it read "No changes on record" beside "2 acquisitions on record". A vendor bought by a company outside
  the vendor list (for example ZB Spine, now owned by H.I.G. Capital) now shows that owner.
- New index on `pc_vendor_names (raw_name, source)`.

## 0.4.0: clean public repository (2026-11-18)

The project moved from a working folder to a clean, documented repository for open-source release. The code that
builds the data is the same apart from the fixes below; `outputs/site_data/` CSVs rebuilt from the same databases
match the live site except where listed.

- The website moved to its own domain: https://www.orthoparity.com. The FDA download user agent names it.

**Layout**

- One command, `python orthoparity.py <step>`, replaces about 20 `.bat` files and root scripts. `run.bat` sets up
  Python and runs it. Steps run in groups: `predicates`, `payments`, `recalls`, `all`.
- Build steps moved to `pipeline/`, tools to `tools/`, docs to `docs/`.
- Human review decisions moved from `outputs/` (not published) to `reviews/` (published), so a rebuild reproduces
  the live site. `config.ini` gains `REVIEW_DIR` and `SITE_DATA_DIR`.
- Website CSVs are written to `outputs/site_data/` (was `outputs/lovable/`).
- `supabase/` holds seven numbered SQL files that replace eight files written as the site grew. Built side by side
  in Postgres 16, the two schemas matched (`pg_dump --schema-only`) except one comment. `load_csv.sh` loads every CSV
  with psql.
- The Lovable prompts, setup guides and design references stay in the old working folder; they described how the
  site was built step by step and aren't needed to run or audit it.

**Fixes found while checking the rebuild**

- Brand words and company keys fold accents and drop trademark signs and apostrophes, so the restored names
  ("Medos International Sàrl", "E3D™-C", "PIT’Stop®") give the same keys as before the 2026-11-18 text repair.
- Export files are sorted and ties broken by name, so two runs write identical CSVs. The brand shown for a 510(k) is
  its most common GUDID brand by distinct device ID, ties to the first alphabetically (389 of 18,224 rows changed).
- `pc_devices.csv` now carries the restored names (1,254 device names, 6 applicants) and `pc_product_codes.csv` all
  254 plain-English names, so the v9 and text-repair patches aren't needed for a new database.
- `tools/check_before_publish.py` (`python orthoparity.py check`) blocks the salt, databases, keys, NPI-shaped
  numbers and person-level column headers before anything is pushed or released.
- GitHub Actions runs the tests and the check on Windows and Linux.

**Old file to new file**

| Before | Now |
|---|---|
| `setup_phase0.py` | `pipeline/load_fda.py` (`load-fda`) |
| `run_full_extraction.py`, `run_full_extraction.bat` | `pipeline/extract_predicates.py` (`extract-predicates`) |
| `run_frontier.py`, `run_frontier.bat` | `pipeline/walk_ancestors.py` (`walk-ancestors`) |
| `import_review.py`, `apply_review.bat` | `pipeline/import_review.py` (`import-review`) |
| `extract_ifu.py` | `pipeline/extract_ifu.py` |
| `product_dictionary.py`, `lovable/product_code_dictionary_draft.py` | `pipeline/product_dictionary.py`, `pipeline/product_code_drafts.py` |
| `export_lovable.py` | `pipeline/export_predicates.py` (`export-predicates`) |
| `build_gudid_index.py`, `run_payments_phase_a.*` | `pipeline/index_gudid.py` (`index-gudid`) |
| `load_open_payments.py` | `pipeline/load_open_payments.py` |
| `build_vendor_registry.py`, `match_products.py`, `run_payments_phase_b.bat` | `pipeline/` (same names) |
| `build_payment_aggregates.py`, `validate_payments.py`, `export_payments.py`, `run_payments_phase_c.bat` | `pipeline/` (same names) |
| `repair_text.py`, `run_text_repair.bat` | `pipeline/repair_text.py` (`repair-text`) |
| `fetch_recalls.py`, `run_recalls.bat` | `pipeline/fetch_recalls.py` (`fetch-recalls`) |
| `lookup.py`, `app.py`, `run_lookup.bat` | `tools/lookup.py`, `tools/lookup_app.py` (`lookup`, `lookup-app`) |
| `review_packet.py`, `import_handcheck.py`, `run_pilot.py`, `pilot_report.py`, `make_validation.py`, `accuracy_report.py` | `tools/` |
| `export_master.py`, `make_lineage_trees.py`, `make_segment_visuals.py`, `reparse_offline.py` | `tools/` |
| `apply_rule_d.py`, `apply_rule_d.bat` | retired: a one-time migration to rule D; a fresh build applies rule D directly |
| `lovable/supabase_*.sql` | `supabase/01_tables.sql` to `07_after_import.sql` |

# History before 0.4.0

Entries below use the old file names (see the table above).

## Reliability fixes (2026-11-18)

- `lovable/supabase_v12_timeouts.sql`: raises the anon and authenticated statement timeout to 15 seconds; a cold first visit on the live site timed out.
- `pc_device_recalls` reads direct predicates straight from `pc_edges` rather than building a full `pc_brief`, so a product page no longer builds the brief three times. The recall card badge reads "None on this device" (was "Predicate recalls") when only the predicates have recalls.
- `lovable/LOVABLE_PROMPT_V12_FIXES.md`: friendly retry on slow loads, seven-tile layout, small design fixes.

## Rebuild design (2026-11-18)

- Cards in `pc_signals` and `pc_vendor_signals` (and the recall cards) gain `short` (rail label) and `figs` (two to four stat tiles, each `{value, label}`), so the rebuild design runs on live data. Vendor "Where do they compete?" now counts all 510(k)s, including the few with no product code, with thousands separators.
- `lovable/design_reference/`: the friend's static prototype (`OrthoParity_Rebuild.html`) and six reference screenshots.
- `lovable/LOVABLE_PROMPT_V11_REBUILD.md`: adopt the design with live data, keeping the logo mark, recalls chapter, current footer and limitations.

## Card headlines (2026-11-18)

- `pc_signals` and `pc_vendor_signals` cards gain a `headline` field: a short statement for the chapter title ("An update to its own line.", "92 other companies make one.", "No recalls on this device."). Recall cards get one too. The vendor bottom line now says "a top-3 filer in N categories".
- `lovable/LOVABLE_PROMPT_V10_POLISH.md`: hero cleanup, "At a glance" tiles, headline field, home-page examples.

## Recalls (2026-11-18)

- `fetch_recalls.py` and `run_recalls.bat` download FDA device recalls for all 254 orthopedic product codes from openFDA (recall endpoint, plus FDA recall class from the enforcement endpoint) into `outputs/lovable/pc_recalls.csv`: 8,096 recalled products in 2,537 events, 2002 to Nov 14, 2026. Vendor links: 6,309 by 510(k) number, 1,646 by firm name, 141 not linked. Impossible dates in openFDA (2) are left blank. Report: `outputs/Recalls_Report.txt`. Tests in `tests/test_recalls.py`.
- `lovable/supabase_v10_recalls.sql`: table `pc_recalls`; functions `pc_device_recalls`, `pc_vendor_recalls` and the recall decision cards, which `supabase_v6_decision.sql` now adds to both pages when the table exists.
- `lovable/LOVABLE_PROMPT_V8_RECALLS.md` and `SETUP_GUIDE_V10.md`.

## Plain-English product codes, complete draft (2026-11-18)

- `lovable/product_code_dictionary_draft.py` now drafts all 254 orthopedic product codes (195 added). New kinds: software, non-surgical device. Drafts stay labeled "pending expert review" until marked Y in `Product_Code_Dictionary_REVIEW.xlsx`.
- `lovable/supabase_v9_product_names.sql` fills the new names on the live site without re-importing; it never overwrites a reviewed name.

## Text repair (2026-11-18)

- `repair_text.py` and `run_text_repair.bat` restore characters the starting-set workbook lost (registered and trademark signs, dashes, accented letters) from the FDA release files, in clearances, predicate edges and the vendor registry. A value changes only when the FDA value for the same 510(k) matches it character for character; the dry run on the live database matched all 7,796 affected values (1,254 device names) and left none. Writes `outputs/Text_Repair_Report.txt` and `outputs/lovable/supabase_text_repair.sql` so Supabase needs no re-import. `setup_phase0.py` now runs the same repair on every load. Tests in `tests/test_textrepair.py`.

## Website v6: decision briefs (2026-11-18)

- `lovable/supabase_v6_decision.sql`: `pc_signals(k)` and `pc_vendor_signals(v, mode)` turn each product and vendor page into a bottom line plus decision cards (finding, why it matters, what to ask). Product cards: is it new, alternatives in the product code (last five years, by current owner), financial ties, evidence, catalog size from GUDID. Vendor cards: where they compete (rank and share by product code), clearance momentum, ownership changes, financial relationships, research, discontinued brands. Fixed rules, tested on 300 random devices and 300 random vendor and mode pairs.
- `lovable/supabase_v4_vendor.sql`: research rows get an `ortho` flag from `pc_refresh_research_scope()`, which drops clearly non-orthopedic studies (neuromodulation, cardiac, neurovascular, wound care and similar) for companies with large non-orthopedic businesses. 4,675 of 7,698 research rows stay in scope.
- `lovable/LOVABLE_PROMPT_V6.md` and `SETUP_GUIDE_V6.md`: decision-first layout, evidence in collapsible sections, Analyst detail view, working PDF via print.
- Known gap, for the next pipeline run: about 1,256 510(k) device names lost their ® or ™ symbol when first read in.

## Benchmark a Vendor, Phase D and E: website v4 (2026-11-17)

- `lovable/supabase_v4_vendor.sql`: 13 new tables (vendors, names, lineage, portfolio, payments by year and nature, payment profiles, reporting entities, product payments, research, anonymous relationships, ownership) with public read, and functions `pc_vendor_search`, `pc_vendor_brief` (portfolio, category footprint, payments, peers, entities, top products, research, ownership, rule-based vendor questions), `pc_vendor_portfolio` (filterable), `pc_vendor_compare` (shared and unique product codes, payments side by side, shared surgeon count) and `pc_product_payments` (device-ID and brand-name payments for one 510(k)). `pc_brief` is unchanged. `pc_clean_blanks()` now covers every `pc_` table. Tested on PostgreSQL 16 against the full export (under 0.05 s per call).
- `lovable/LOVABLE_PROMPT_V4.md` and `lovable/SETUP_GUIDE_V4.md`: two modes (Benchmark a product, Benchmark a vendor), ownership toggle, vendor comparison, industry payments on the device brief, new limitations. No recipient is named anywhere.

## Benchmark a Vendor, Phases A to C (2026-11-17)

- Phase A: `build_gudid_index.py` (5,258,157 GUDID records, 1,607,467 with a 510(k)) and `load_open_payments.py` (CMS Open Payments 2019 to 2025: general, research, ownership; no recipient names loaded). Launcher `run_payments_phase_a.bat`. Settings in the `[payments]` section of config.ini.
- Phase B: `build_vendor_registry.py` (vendor registry from Open Payments payers, 510(k) applicants and GUDID labelers; curated families and dated ownership events in `reference/`; review workbook `Vendor_Registry_REVIEW.xlsx`, answers kept on re-run) and `match_products.py` (tier 1 device ID, tier 2 brand of the same vendor, tier 3 unmatched). Launcher `run_payments_phase_b.bat`.
- Phase C: `build_payment_aggregates.py` (orthopedic scope, point-in-time and current-owner roll-ups, anonymous surgeon keys), `validate_payments.py` (`outputs/payments_validation.md`) and `export_payments.py` (`outputs/lovable/pc_*.csv`, 24.6 MB). Launcher `run_payments_phase_c.bat`.
- Only vendors with at least one orthopedic 510(k) are listed (Asher's rule, 2026-11-17).

## Website v3: Open Ortho Benchmark (2026-11-17)

- Rebrand to Open Ortho Benchmark, single page. `lovable/LOVABLE_PROMPT_V3.md` removes Compare and Batch from the site, adds the logo and a "Step 1: Identify an orthopedic device to benchmark" search, and groups the vendor questions.
- `lovable/supabase_v3_vac_questions.sql`: `pc_brief` also returns `vac_questions`, 16 standard value analysis questions in five topics (17 for line extensions), tailored with the device's procedures, predicates and product kind. Also folded into `supabase_v2_brief.sql`.
- `lovable/brand/`: logo mark and lockups (SVG and PNG).

## Website v2: Device Brief (2026-11-17)

- `lovable/supabase_v2_brief.sql`: new tables `pc_product_codes` and `pc_ifu`, and functions `pc_brief` (plain-English category, FDA-cleared use, pattern badge, direct predicates, primary technology line, peers, category context, rule-based vendor questions), `pc_compare`, `pc_batch` (up to 50), plus helpers `pc_direct`, `pc_peers`, `pc_category`, `pc_primary_lineage`. `pc_clean_blanks()` now covers the new tables. Tested on PostgreSQL 16 against the full export (about 0.2 s per brief).
- `extract_ifu.py`: reads the Indications for Use from cached Summary PDFs into `outputs/ifu/ifu.jsonl` (13,645 of 13,986 found).
- `product_dictionary.py` and `lovable/product_code_dictionary_draft.py`: plain-English product-code dictionary. Claude drafted the top 59 codes; `Product_Code_Dictionary_REVIEW.xlsx` holds them for expert review, and reviewed answers override drafts.
- `export_lovable.py` also writes `pc_product_codes.csv` and `pc_ifu.csv`.
- `company_root` drops one-letter tokens and spaces, so "Nu Vasive, Incorporated" and "NuVasive, Inc." match. Still no parent-company roll-up.
- `lovable/LOVABLE_PROMPT_V2.md` and `lovable/SETUP_GUIDE_V2.md`: the redesign prompt and upgrade steps.

## Website kit (2026-11-17)

- `export_lovable.py` writes `outputs/lovable/` (devices, edges with review decisions applied, flags, meta) for Supabase.
- `lovable/supabase_setup.sql`: tables, read-only public access, and the lookup functions `pc_search`, `pc_brand_family`, `pc_lookup` (same chain logic as the PC app; tested on PostgreSQL 16 against the full export, K241487 returns the same 715 devices). `pc_clean_blanks()` tidies the dashboard import.
- `lovable/LOVABLE_PROMPT.md` and `lovable/SETUP_GUIDE.md`: the prompt for Lovable and step-by-step setup.

## Phase 6 tools and master outputs (2026-11-17)

- `make_validation.py`: fresh seeded sample of 40 clearances (10 per era, 1996 to 2026, no pilot devices) and `Validation_HandCheck_[date].xlsx`, showing what the tool reports today (review decisions applied). Columns 1 to 22 match the pilot hand-check, so `import_handcheck.py` reads both.
- `accuracy_report.py`: edge and device error rates by confidence tier and era with 95% Wilson intervals, plus a plain statement of what a 40-device sample can and cannot support.
- `export_master.py`: CSV exports and `Corpus_Summary.xlsx` (aggregates only).

## Phase 5 lookup tool (2026-11-17)

- `run_lookup.bat` opens the Streamlit app (`app.py`): search by K-number, product name or company (partial and close-spelling matches), single clearance or brand family by the same applicant (other-company matches listed as excluded, with the reason), Benchmark table, interactive tree (primary predicates only or full chain), flags, stop reasons, edges, and downloads.
- `lookup.py`: the same lookup from the command line; writes the workbook and both trees to `outputs/lookups/`.
- `predicate_chain/lookup_core.py` and `lookup_workbook.py`: chain, benchmark rows, tree drawing (Graphviz, else networkx plus matplotlib), and the 10-tab workbook. Summary counts are Excel formulas over the Benchmark and Edges tabs.
- `build_chain` accepts a list of subject K-numbers (brand families).

## Phase 4 tools (2026-11-17)

- `review_decisions` gains `predicate_number`, `corrected_number` and `parser_version` (added automatically to older databases), so a decision follows the printed number across parser versions.
- Lookup layer (`chains.py`): `review_overrides` applies review decisions without changing parser rows. "own number" and "not a predicate" leave the edge out; "corrected" follows the number the document meant; "confirmed" makes a LOW edge usable. `build_chain` and `pending_nodes` both use it, so corrected numbers get extracted like any other ancestor.
- `import_review.py` / `apply_review.bat`: record a batch's decisions, close its queue items, write `outputs/review/Review_Log.csv`, then extract any corrected numbers and their chains.
- `make_lineage_trees.py` applies review decisions too.

## Parser 1.3.1 (2026-11-17, rule D refinements before Phase 4 review)

- The OCR safeguard now also accepts a number when FDA's device name or company appears anywhere in the 300-character evidence around it, or when FDA's applicant is the same company as the document's own submitter.
- A number found in no FDA record that sits in a "510(k) Number" field, or is within two characters of the document's own number, is the document's own number misread (a fax stamp, page header or Indications for Use form). The edge is dropped and an informational "own number misread" flag records it.
- On 150 queued documents from real PDFs, 59 more became CLEAN (149 AMBIGUOUS to 90).
- `review_packet.py`: writes the next Phase 4 review batch, ranked by impact, with candidate numbers one character away for misread numbers.

## 0.3.0, parser 1.3.0 (2026-11-17, review rule D)

- `REVIEW_RULE = D`, the project owner's common-sense rules: ignore predicates named without a number; the FDA number decides identity (name mismatches never block); any other K-number or DEN number in a Summary is a predicate. Review keeps only numbers not found in FDA records, wrong files, and OCR-read numbers that match neither the FDA device name nor the company. See METHODOLOGY.md.
- `apply_rule_d.bat` / `apply_rule_d.py`: re-parses every cached PDF offline with parser 1.3.0, then downloads the ancestors that rule D newly reaches and walks their chains. Parser 1.2.0 rows are kept. Writes `outputs/RuleD_Summary.txt`.
- On a 50-document sample from real PDFs, AMBIGUOUS documents fell from 33 to 5.

## Phase 3 (2026-11-17)

- Gate 2 approved. `run_frontier.bat` / `run_frontier.py`: walks every predicate chain from the starting set, generation by generation up to `MAX_GENERATIONS`, and extracts each ancestor not yet extracted for the current parser version. Ancestors only. Writes `outputs/progress_frontier.txt` and `outputs/Phase3_Summary.txt` (ancestors by generation, stop reasons, FDA review panel). Resumable like Phase 2.
- Runner: chain-walk progress now counts down within each generation instead of overstating the remaining work.
- `make_lineage_trees.py`: primary lineages for every starting-set device traced to the earliest ancestor on record, one tree per unofficial segment, plus earliest-on-record and most-cited tables. LOW-confidence edges are left out until reviewed. Writes `outputs/Lineage_Trees_by_Segment.html` and `outputs/lineage/`.

## 0.2.0, parser 1.2.0 (2026-11-16, Phase 2)

- Gate 1 approved. Review rule C (`REVIEW_RULE = C` in config.ini): "PMA predicate" flags are informational; "mentioned, not classified" keeps a document AMBIGUOUS only when it has no HIGH predicate from a labeled section. Parser logic is otherwise the same as 1.1.0; the version changes because parse status is computed differently, and 1.1.0 rows are kept.
- `run_full_extraction.bat` / `run_full_extraction.py`: Phase 2 runner for all starting-set clearances, newest first. Runs in its own minimized window, keeps the PC awake, writes `outputs/progress_full.txt`, a checkpoint file every 100 documents (`outputs/checkpoint_full.json`) and `outputs/Phase2_Summary.txt` at the end. Closing the window stops after the current document; the next run resumes.

## Visuals (2026-11-16)

- `make_segment_visuals.py`: primary-lineage trees per unofficial segment, with ancestors shaded by how many device chains in the segment include them, plus most-shared-ancestor and cross-segment tables. Writes `outputs/Predicate_Trees_by_Segment.html` and `outputs/visuals/*.svg`. Uses the pilot devices by default; `--all` for every starting-set device after Phase 2.

## Gate 1 decisions (2026-11-16)

- Approved stop rule "No summary on file (pre-1991)": blank STATEORSUMM, decided 1990 or earlier, no request.
- Approved stop rule "No summary on file (1991-1995)": STATEORSUMM Summary or blank, decided 1991-1995, no request.
- `PDF_URL_STRATEGY = pattern_first` (1,655 of 1,656 pilot detail-page links matched the pattern).
- Pilot nodes decided in 1995 or earlier were re-stamped with the new stop reasons. 2 of those 219 nodes had a PDF online; neither listed a predicate.

## 0.1.1, parser 1.1.0 (2026-11-16, from pilot findings)

Re-run offline on the cached pilot PDFs; parser 1.0.0 results are kept in the database.

- Table rows that end in a role word ("... MAX, OVD Primary" / "Additional") now set the printed label.
- eSTAR summaries: the header "(Primary Predicate is listed first)" is read as an instruction, not as a label.
- OCR uses Tesseract page-layout mode 4, which reads boxed eSTAR form rows; when a predicate heading is read but no number, it retries once in mode 6.
- OCR text is cached by PDF hash (`cache/ocr_text/`), so offline re-parsing skips OCR.
- Scrambled text layers are detected. Some PDFs embed fonts with a broken character map, so "The results" is stored as "7KHUHVXOWV" (every character 29 code points low) or as symbol soup. Such pages are repaired by un-shifting when that yields English; pages that stay unreadable, or whose repaired text has no spaces, are sent to OCR. About 1% of pilot PDFs were affected (including K162496 and K200002, which previously showed "no predicate found").
- A STOP file in `outputs/` ends a run cleanly (for background runs).
- Headings preceded by OCR-mangled bullets (". Predicate Devices:", "e Predicate ...") are recognized.
- New headings: "Equivalence to Marketed Product", "Substantially Equivalent Devices(s);", "Equivalent Device Identification:", "Legally marketed device(s) to which ... equivalence is claimed", "Table 5-1 Predicate Devices", OCR's "Substantial Eguivalence", and headings behind a table border ("| Legally Marketed Predicate Devices").
- A column-header line right under a predicate heading ("Intended Use/Design/Technology") no longer ends the section.
- "(reference device)" printed after a number on the same table row marks that row as a reference device.
- OCR-split numbers are read ("K9335 18", "K(002783", "K91 2735") and marked as normalized.
- The PDF's own number comes only from FDA's "Re:" line or the Indications-for-Use form field and tolerates OCR noise ("Re: KI 11572"); a "510(k) number" column in a predicate table no longer triggers a false "wrong file".
- A run of numbers separated only by punctuation ("K143628/K140454/K143375 Medtronic Navigated Instruments") shares one text window for name matching.
- FDA clearance-letter pages are left out of section finding (their boilerplate mentions "legally marketed predicate device").
- Numbers inside a sentence that claims substantial equivalence ("... is based on ... Premise Cup (K912426) and Ultima Cup (K924115)") count as a labeled predicate context.
- A device named in such a sentence without any number becomes a "Predicate has no FDA number" edge; generic claims ("equivalent to other commercially available devices") do not.
- Several numbers listed one after another under one device name are family members of the first.
- Wrapped paragraph lines that start in lower case are never headings.
- Name matching scores long FDA names segment by segment; company matching handles split or joined names ("Nu Vasive" / "NuVasive").
- HTTP 400 from FDA's detail page means the record cannot be served; it now counts as "no PDF" instead of a retryable error.

## 0.1.0, parser 1.0.0 (2026-11-16)

Fresh start. Nothing reused from earlier versions (no `predicate-chain_old/cache/pdfs` existed, so 0 PDFs were copied).

- Starting set extended to 1976-2026 (18,224 orthopedic clearances, 20 De Novo).
- New `fda_master` table built from FDA's five 510(k) release files (176,747 records, all panels) for local identity lookups of any predicate, including non-orthopedic ones.
- New `product_codes` table (7,105 FDA product codes).
- `MAX_GENERATIONS` raised from 5 to 10 and moved to `config.ini`.
- Every input file name and expected count lives in `config.ini`. Phase 0 stops if a count differs.
- Extraction layer: PDF cache with SHA-256, parser version stored on every row, old versions kept on re-extraction, offline re-parse (`reparse_offline.py`).
- Two stop reasons added beyond the original list, each needed so that every node gets exactly one: "Summary parsed, no predicate found" and "Wrong file (PDF is for another number)".
- Download errors (HTTP 403, 5xx after three retries, timeouts) never become a stop reason. The node stays pending and the next run retries it. Ten errors in a row pause the run.
- Phase 1 pilot runner (`run_pilot.bat`), resumable, with a progress file.
- Unit tests for number patterns, the role rule, stop rules, control-character stripping, cross-check flags, and an end-to-end extraction from a synthetic PDF.
