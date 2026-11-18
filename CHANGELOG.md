# Changelog

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
