# Data dictionary

This covers the three databases the build uses and the website tables it writes.

## Predicate database

Database: `data/predicate_chain.db` (SQLite). Tables 1-3 hold reference data loaded by `load-fda`. Tables 4-10 hold extraction results and review work. Every extraction table is keyed by `parser_version`, so re-running a newer parser adds rows and keeps the old ones.

### 1. clearances: the starting set (18,224 rows)
One row per orthopedic clearance from the starting-set workbook.

| Column | Meaning |
|---|---|
| knumber | 510(k) or De Novo number (primary key) |
| applicant, contact, street1, street2, city, state, country_code, zip, postal_code | Applicant as printed at clearance. ZIP and postal code are text. |
| date_received, decision_date | ISO dates (YYYY-MM-DD) |
| decision_year | Year of decision_date |
| decision | FDA decision code (for example SESE) |
| review_advise_comm | FDA review panel (OR = Orthopedic) |
| product_code | 510(k) product code; blank for 88 rows |
| device, regulation_description, regulation_number, device_class, life_sustaining, implant | Product code classification fields from the workbook |
| stateorsumm | "Summary", "Statement", or blank |
| classadvisecomm, sspindicator, type, thirdparty, expeditedreview | FDA fields as released |
| devicename | Device name as cleared |
| unofficial_segment, unofficial_sub_segment | **Unofficial**: assigned by Claude, not FDA |
| submission_category, inclusion_basis, source_file | Workbook bookkeeping columns |
| loaded_from, loaded_at_utc | Provenance of the load |

### 2. fda_master: every FDA 510(k) and De Novo record (176,747 rows)
Same fields as FDA's release files, all review panels. `review_panel` is FDA's REVIEWADVISECOMM. `source_file` names the release file each row came from.

### 3. product_codes: FDA product code classification (7,105 rows)
`product_code` (key), `review_panel`, `medical_specialty`, `device_name`, `device_class`, `regulation_number`, `definition`, implant and life-sustaining flags, and the other classification fields.

### 4. documents: one row per number per parser version
Where the Summary PDF came from and what the parser saw.

| Column | Meaning |
|---|---|
| fetch_outcome | downloaded, cache hit, copied from previous run, not found, skipped |
| url, url_source | PDF address and how it was found (detail page link or URL pattern) |
| detail_page_url, detail_page_status, detail_page_link, detail_page_label | The FDA clearance detail page request and the Summary/Statement link on it |
| http_status, sha256, bytes, retrieved_at_utc, download_seconds | Download provenance |
| file_source | "downloaded" or "copied from previous run" |
| cache_path | Location in `cache/pdfs/` |
| page_count, text_method, text_chars | text layer, OCR, needs OCR, or unreadable |
| pdf_own_knumber | The number the PDF says it belongs to |
| predicate_sections | Number of predicate sections used |
| parse_status | CLEAN, AMBIGUOUS, or NOT PARSED |
| parse_notes | Free-text notes (for example "summary status unknown") |

### 5. edges: one row per predicate cited
The child is the device whose Summary was read; the predicate is the device it cites.

| Column | Meaning |
|---|---|
| child_knumber | Subject device |
| predicate_number, predicate_base, predicate_kind | Cited number (K, DEN, P, or blank when none was printed); base drops a PMA supplement |
| list_order | Order of first appearance |
| role, role_basis | primary or reference, and why |
| printed_label | Label printed in the PDF (primary predicate, additional predicates, reference device) |
| family_of | Head number for "including ..." family members |
| printed_name, printed_company | Text printed near the number, kept only for cross-checking |
| fda_applicant, fda_device_name, fda_decision_date, fda_product_code, fda_review_panel | Identity from FDA records by number |
| identity_source, identity_retrieved_at_utc | starting set, FDA master, openFDA, FDA web database, or not found |
| name_match_score, company_match | Cross-check results (0-1 score; 1/0 company match) |
| in_predicate_section, section_heading | Whether the number sat in a labeled predicate or substantial-equivalence section |
| confidence | HIGH, MEDIUM, or LOW; NO NUMBER for a predicate named without an FDA number (rule D) |
| page, evidence | PDF page and a verbatim snippet of at most 300 characters |

### 6. node_status: one stop reason (or none) per node per parser version
`status` is "continues" (has numbered predicates) or "stopped". `stop_reason` is one of the reasons in METHODOLOGY section 9. `distance` is generations from the nearest starting device in the run that found it; `discovered_from` is the child that cited it. TRUNCATED is computed in the chain view, not stored here.

### 7. flags
One row per cross-check finding: `flag_type` (mentioned, not classified; name mismatch; partial name match; probable misread number; wrong file; PMA predicate), `number`, `detail`, `page`, `evidence`.

### 8. review_queue
Items for a second look: LOW edges (`item_type` edge, `ref_id` = edge_id), wrong-file and misread flags (`item_type` flag, `ref_id` = flag_id), and AMBIGUOUS documents (`item_type` document). `status` starts as "open".

### 9. review_decisions
Review decisions. Never overwrites parser output. `decision_source` is "parser", "Claude review", or "human review"; `reasoning` and `evidence_page` back each decision.

### 10. run_log_index
One row per run: phase, parser version, log file name, start and end time, counts, and how it ended. The full action log is in `logs/run_log_YYYY-MM-DD.jsonl`.

### Helper tables
- **run_targets:** target lists for runs (pilot sample with its stratum, later the full run and the frontier).
- **external_lookups:** identity answers from openFDA or the FDA web database, cached so each number is looked up once.

### Log file (`logs/run_log_YYYY-MM-DD.jsonl`)
One JSON object per line: `ts_utc`, `run_id`, `parser_version`, `action` (lookup, download, cache hit, parse, ocr, cross-check, flag, stop, review decision, load, run, copy), `knumber`, `depth`, `url`, `http_status`, `result`, `reason`.

## Payments database

Database: `data/payments.duckdb` (DuckDB). Built by the `payments` steps; the main tables are `gudid_devices`,
`gudid_identifiers` and `gudid_submissions` (GUDID index), `op_general`, `op_research`, `op_ownership` and
`op_products` (Open Payments rows from in-scope payers, no recipient names), `vendors`, `vendor_entities` and
`vendor_lineage` (the registry), `op_product_match` and `op_product_k` (product links), and `pay_fact` plus the
`agg_*` tables that become the website's payment tables. The recipient NPI is used only to build the anonymous key
and never leaves this database.

## Website tables (`outputs/site_data/*.csv`, Supabase)

The build writes one CSV per table, and `supabase/01_tables.sql` creates the tables. `mode` is `pit` (as owned at the time) or `current` (current owner with history). A 510(k) list inside one cell is separated by `|`.

### pc_devices
One row per device: the orthopedic starting set plus every ancestor. Identity from FDA records by number.

Columns: `knumber`, `device_name`, `applicant`, `decision_date`, `decision_year`, `product_code`, `regulation_number`, `device_class`, `review_panel`, `segment`, `in_starting_set`, `status`, `stop_reason`, `summary_url`, `brand`, `company_root`

### pc_edges
One row per predicate link, as the lookup uses it (current parser, review decisions applied).

Columns: `edge_id`, `child`, `predicate`, `number_as_printed`, `role`, `confidence`, `review_decision`, `review_source`, `page`, `printed_label`, `evidence`, `list_order`

### pc_flags
Parser flags on each document (misread numbers, wrong files and similar).

Columns: `flag_id`, `knumber`, `flag_type`, `number`, `detail`, `review_decision`

### pc_meta
Export time, parser version, counts and the limitations text the site shows.

Columns: `key`, `value`

### pc_product_codes
One row per orthopedic product code, with FDA's name and the plain-English name (reviewed or draft).

Columns: `product_code`, `fda_name`, `regulation_number`, `device_class`, `fda_definition`, `plain_name`, `plain_description`, `anatomy`, `procedures`, `kind`, `segment`, `clearances`, `reviewed`

### pc_ifu
Indications for Use text from each Summary PDF, verbatim, about 1,500 characters at most.

Columns: `knumber`, `ifu_text`, `page`, `source`, `found`

### pc_vendors
One row per listed vendor: name, current parent, segment, clearance counts, GUDID counts, payment kind.

Columns: `vendor_id`, `display_name`, `current_parent`, `segment`, `basis`, `reviewed`, `note`, `clearances`, `first_clearance_year`, `last_clearance_year`, `gudid_ortho_devices`, `gudid_brands`, `payment_kind`, `rolls_up_to`

### pc_vendor_names
Every raw name (payer, applicant, labeler) and the vendor it belongs to, with the basis.

Columns: `vendor_id`, `source`, `raw_name`, `basis`

### pc_vendor_lineage
Dated ownership changes, each with a source link.

Columns: `vendor_id`, `parent`, `relation`, `valid_from`, `valid_to`, `source_url`, `note`, `reviewed`

### pc_portfolio_brands
GUDID brands per vendor with their product codes, 510(k)s and device counts.

Columns: `vendor_id`, `brand`, `product_codes`, `knumbers`, `devices`, `in_distribution`, `implantable`

### pc_portfolio_510k
Every orthopedic 510(k) with its vendor, GUDID brand and catalog size.

Columns: `vendor_id`, `knumber`, `device_name`, `applicant`, `product_code`, `decision_date`, `gudid_brand`, `gudid_devices`, `gudid_in_distribution`

### pc_op_vendor_year
Open Payments by vendor, year and nature group, in both roll-ups (mode).

Columns: `mode`, `vendor_id`, `year`, `nature_group`, `transactions`, `amount`, `recipients`

### pc_op_vendor_profile
One row per vendor and year (year 0 = all years): totals, recipients, concentration, specialty buckets.

Columns: `mode`, `vendor_id`, `year`, `total`, `transactions`, `to_entities`, `equity_forms`, `acquisitions`, `debt_forgiveness`, `to_teaching_hospitals`, `recipients`, `physicians`, `food_r`, `travel_r`, `consulting_r`, `royalty_r`, `top1pct_share`, `top10_share`, `median_per_recipient`, `bucket_json`

### pc_op_entity
Payments by reporting entity (payer ID) under each vendor.

Columns: `vendor_pit`, `vendor_current`, `payer_id`, `payer_name`, `year`, `amount`, `recipients`, `royalty`, `food`

### pc_op_product
Payments linked to each 510(k), by tier, year and nature group.

Columns: `knumber`, `tier`, `year`, `nature_group`, `brand`, `vendor_pit`, `transactions`, `amount`, `recipients`

### pc_op_product_top
Each vendor's top 50 products by payments.

Columns: `mode`, `vendor_id`, `brand`, `amount`, `transactions`, `royalty`, `engagement`, `rank`

### pc_op_research
Research payments by study, with the 510(k)s named and the orthopedic scope flag.

Columns: `vendor_entity`, `vendor_pit`, `vendor_current`, `year`, `study_name`, `ct_gov_id`, `amount`, `payments`, `preclinical`, `knumbers`, `ortho`

### pc_op_relationship
One row per vendor, anonymous surgeon key and year: amount and relationship types. No names or NPIs.

Columns: `mode`, `vendor_id`, `rkey`, `year`, `bucket`, `consulting`, `royalty`, `speaking_services`, `amount`

### pc_op_ownership
Physician ownership and investment interests by vendor and year (counts and amounts).

Columns: `vendor_pit`, `vendor_current`, `year`, `holders`, `invested`, `value`

### pc_recalls
One row per recalled product: recall number, event, dates, FDA class, product code, 510(k)s, vendor link and basis.

Columns: `recall_number`, `event_id`, `initiated`, `posted`, `terminated`, `status`, `recall_class`, `product_code`, `knumbers`, `recalling_firm`, `vendor_id`, `vendor_basis`, `product`, `reason`, `root_cause`, `quantity`
