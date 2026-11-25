# Methodology

This document describes exactly how OrthoParity turns public FDA and CMS data into the numbers on the site.
Parts 1 to 13 cover predicate chains (parser version **1.3.1**). Parts 14 to 17 cover vendors, industry payments,
recalls and the decision briefs. `docs/LIMITATIONS.md` lists what the data can't support.

## 1. Data sources, in priority order

| # | Source | Used for |
|---|---|---|
| 1 | Starting-set workbook (`STARTING_SET_FILE` in `config.ini`), sheet "510K Clearances" | The 18,224 orthopedic clearances to extract, plus their FDA fields and the unofficial segment labels |
| 2 | FDA 510(k) release files, all panels, 1976 to present (`FDA_MASTER_FILES`) | Identity (applicant, device name, decision date, product code, review panel) of any predicate by number |
| 3 | FDA product code classification (`PRODUCT_CODE_FILE`) | Device name, class, regulation number, and review panel of any product code |
| 4 | openFDA 510(k) API | Identity of numbers missing from sources 1 and 2 (for example, clearances after the release-file date). Field names are checked on the first call and logged. |
| 5 | FDA 510(k) web database (clearance detail page) | Last-resort identity lookup, and the link to each Summary PDF |
| 6 | The Summary PDF for each clearance | The predicates the submitter cited |

Every fact carries its source and a UTC timestamp: `loaded_at_utc` for file loads, `retrieved_at_utc` for downloads and web lookups.

## 2. Load and verification (`load-fda`)

The loader strips stray control characters (keeping tabs and line breaks), splits FDA release files on line feeds only so a stray carriage return cannot split a record, and stops if any count in `[expected_counts]` differs. Verified on 2026-11-16:

- Starting set: 18,224 rows, 0 duplicates, 20 De Novo, 88 blank product codes, decision dates 1976-07-20 to 2026-11-13.
- STATEORSUMM by era: 1976-1990 blank 1,781; 1991-1995 Summary 534, Statement 549, blank 457; 1996 on Summary 14,373, Statement 336, blank 194.
- FDA master: 176,747 unique records across five files; 464 lines had control characters stripped.
- Product codes: 7,105.
- Every starting-set K-number exists in the FDA master, and every non-blank starting-set product code exists in the classification file.

## 3. Extraction rules (per number)

1. **De Novo (DEN)** and **PMA (P number)** numbers stop immediately. No download.
2. **STATEORSUMM = Statement**: stop with "Statement only, no predicate data". No download.
3. **No summary on file (approved at Gate 1).** STATEORSUMM blank and decided in 1990 or earlier: stop with "No summary on file (pre-1991)", no request (`PRE1991_BLANK_RULE = stop`). STATEORSUMM Summary or blank and decided 1991-1995: stop with "No summary on file (1991-1995)", no request (`EARLY1990S_RULE = stop`). Evidence: in the pilot, 0 of 27 pre-1991 devices and 0 of 17 devices from 1991-1995 had a Summary PDF online; across all 219 pilot nodes decided in 1995 or earlier, 2 had a PDF and neither listed a predicate.
4. **STATEORSUMM blank, decided 1996 or later**: recorded as "summary status unknown"; the tool tries the PDF.
5. **Finding the PDF.** With `PDF_URL_STRATEGY = pattern_first` (approved at Gate 1) the tool tries the URL pattern first and reads the detail page only when the pattern fails. With `detail_first` the tool reads the FDA clearance detail page (`pmn.cfm?ID=...`), takes the link labeled Summary (or Statement), and downloads it. If there is no link, it tries the URL pattern `cdrh_docs/{folder}/{K}.pdf`, where folder is `pdf{YY}` for 2002 on (`pdf2` ... `pdf9`, `pdf10` ...) and `pdf` before that. The pilot records which route worked so the pattern can be verified.
6. **Caching.** Each PDF is saved once to `cache/pdfs/{K}.pdf` with its SHA-256, size, URL, retrieval time, and download time. A later run uses the cached file.
7. **Text.** The PDF text layer is read with pypdfium2. Pages with fewer than 40 letters or digits count as image-only. A page whose text layer is scrambled (a font with a broken character map, which stores "The" as "7KH", or symbol soup) is repaired by shifting characters back 29 code points when that produces English; a page that stays unreadable, or whose repaired text has no spaces, is treated as image-only. If Tesseract is installed, those pages are OCR'd (200 dpi, first 15 such pages, page-layout mode 4, which reads boxed eSTAR form rows; if a predicate heading is read but no number, mode 6 is tried once). OCR text is cached by PDF hash in `cache/ocr_text/`, so re-parsing never OCRs a page twice. If not, the document is marked "Needs OCR" when the text layer holds no predicate data, and the run continues.
8. **Download errors** (HTTP 403, 5xx after three retries, timeouts) are logged and never turned into a stop reason. The number stays pending for the next run. HTTP 400 and 404 are permanent answers and count as "no PDF".

## 4. Finding the predicate section

The parser walks the text line by line and recognizes headings at the start of a line (after optional numbering such as "5." or "VI."):

- **Tier 1, predicate headings:** "Predicate Device(s)", "Primary/Additional Predicate", "Legally Marketed (Predicate) Device(s)", "Device(s) to which equivalence is claimed", "Equivalent Device(s):".
- **Tier 2:** "Substantial Equivalence" (and variants such as "Statement of Substantial Equivalence").
- **Tier 3:** "Comparison", "Technological Characteristics", "Device Description".
- **Reference devices:** "Reference Device(s)" is tracked as its own section.

A section ends at the next recognized heading (Device Description, Indications for Use, Performance Data, Conclusion, and similar) or after 4,000 characters. Sentences that claim substantial equivalence ("is substantially equivalent to", "equivalent to", or mention "predicate") count as Tier 2 as well, so a narrative summary that names "Premise Cup (K912426)" in such a sentence is read as a predicate claim.

The parser uses Tier 1 sections when they hold numbers, and adds any Tier 2 section or sentence that brings new numbers (the document then has more than one predicate section and is marked AMBIGUOUS for review). Without Tier 1 it uses Tier 2, then Tier 3. If none holds a number, it falls back to numbers within 300 characters of "predicate", "substantially equivalent", or "equivalence" (these edges are never HIGH).

FDA's clearance-letter pages are excluded from section finding, because their boilerplate mentions "legally marketed predicate device". A line counts as a heading only when it is short (60 characters or fewer) or the key phrase is followed by a colon, and never when it starts with a lowercase word (wrapped paragraph text). OCR-mangled bullets in front of headings (".", "°", "e ") are allowed.

## 5. Number patterns

- **K numbers:** `K` + six digits, with an optional space or hyphen after K. Inside the six digits, O/o/I/l/| are read as 0 or 1 (common OCR confusions) if at least four real digits remain; such numbers are marked as normalized.
- **DEN numbers:** `DEN` + six digits.
- **P numbers:** `P` + six digits, with an optional supplement `/S###`.
- The subject device's own number is never a predicate.

## 6. Role rule

- One predicate listed: **primary**.
- Several listed, one labeled primary: that one is **primary**, the others **reference**.
- Several listed, none labeled: the **first listed** is primary, the others reference.
- Family members are separate edges that **inherit** their head's role: "K111111, including K222222 and K333333"; several numbers inside one parenthesis after one device name; or several numbers listed one after another (separated only by commas or "and") under one named device. A bare list of numbers with no device name ("Predicates: K111111, K222222") is not a family.
- A device named in a substantial-equivalence sentence with no number at all ("substantially equivalent to the OMNIFIT Femoral Stem") becomes an edge with no number. Generic claims ("equivalent to other commercially available devices") do not.
- Devices under a "Reference Device(s)" label are **reference**.
- A predicate described without any K, DEN, or P number becomes an edge with no number, and that branch stops with "Predicate has no FDA number".

The printed label, the reason for the role (`role_basis`), and the family head are stored on each edge.

## 7. Predicate identity

Company and device name come from FDA records by number, never from the PDF text. Lookup order: starting set, FDA master, openFDA, FDA web database, else "No Company Name Found". The name printed in the PDF is stored separately (`printed_name`, `printed_company`) for cross-checking.

## 8. Cross-check, confidence, and parse status

**Flags**
- *mentioned, not classified*: a K, DEN, or P number appears anywhere in the PDF, is not the subject's own, and was not captured as a predicate.
- *name mismatch*: none of the FDA device-name words and not the FDA company appear near the number.
- *partial name match*: some match, below the HIGH bar.
- *probable misread number*: the number exists in no FDA source.
- *wrong file*: the PDF's own number differs from the requested one.
- *PMA predicate*: a P number (not in 510(k) records; identity not checked).

**Name matching.** Significant words of the FDA device name (generic words such as "system", "device", "set" removed) are searched in a window of text around the number. Score = share of those words found. Company match = the first distinctive word of the FDA applicant (suffixes like Inc., LLC, Medical removed) appears in the window.

**Confidence per edge**
- **HIGH:** inside a Tier 1 or Tier 2 section, and the FDA record matches (name score at least 0.5, or company match plus name score at least 0.25). A missing printed company does not block HIGH.
- **MEDIUM:** inside a section but the FDA record is missing or only partly matches; or outside a section with a full match.
- **LOW:** anything else, including predicates with no number.

**Parse status per document**
- **CLEAN:** exactly one predicate section used, every edge HIGH, and no blocking flag. Under review rule C (approved at Gate 1), "PMA predicate" never blocks, and "mentioned, not classified" blocks only when the document has no HIGH predicate from a labeled section. Under `REVIEW_RULE = strict`, every flag blocks.
- **AMBIGUOUS:** anything else.

**Review rule D (current setting, parser 1.3.0, set by the project owner on 2026-11-17).** Three common-sense rules replace the name-based checks above:

1. A predicate named without an FDA number is ignored. The edge is kept for the record with confidence `NO NUMBER`, and the device stops with "Predicate has no FDA number" when it lists no numbered predicate. Nobody tries to guess the number.
2. The FDA number decides identity. Companies rename products after clearance, so a printed name that differs from FDA's record never lowers confidence or blocks a document. Edges in a predicate section are HIGH; other edges are MEDIUM.
3. Any other K-number (or DEN number) in the Summary is a predicate, even when the text does not call it one. These edges carry `printed_label` "mentioned in Summary". They are reference predicates when the document lists a numbered predicate; otherwise the first one mentioned is primary. FDA letter pages, the document's own number, and numbers one character off the document's own number are skipped.

Under rule D a document is AMBIGUOUS, and goes to review, only for a number not found in any FDA source ("probable misread number"), a PDF that belongs to another number ("wrong file"), or a number read by OCR or from a repaired font that matches neither the FDA device name nor the company ("possible OCR misread", edge LOW). The last check is a safeguard on our own reading of the page; it does not second-guess what the submitter printed. From parser 1.3.1 the safeguard also accepts a number when FDA's device name or company appears in the evidence around it, or when FDA's applicant is the document's own submitter. A number found in no FDA record that sits in a "510(k) Number" field, or is within two characters of the document's own number, is treated as the document's own number misread (fax stamps, page headers, Indications for Use forms) and dropped with an informational "own number misread" flag. Trade-offs: a typo in the submitter's own K-number is taken at face value, and rule 3 also turns K-numbers cited for compatibility or test comparisons into predicates.

**Review queue:** LOW edges, "wrong file" flags, "probable misread number" flags, and every AMBIGUOUS document.

## 9. Stop reasons (exactly one per node)

| Stop reason | When |
|---|---|
| De Novo (DEN) | Number starts with DEN |
| PMA (P number) | Number starts with P |
| Predicate has no FDA number | The only predicates listed carry no K, DEN, or P number |
| Statement only, no predicate data | STATEORSUMM = Statement, the detail page links a Statement, or the PDF is a 510(k) Statement |
| No Summary PDF available | No link on the detail page and every URL pattern returned 404 |
| No summary on file (pre-1991) | Blank STATEORSUMM, decided 1990 or earlier (approved at Gate 1) |
| No summary on file (1991-1995) | STATEORSUMM Summary or blank, decided 1991-1995 (approved at Gate 1) |
| Needs OCR | Image-only PDF and Tesseract unavailable |
| Unreadable PDF after OCR | Corrupt PDF, or OCR produced no usable text |
| K-number not found in any FDA source | Not in the starting set, FDA master, openFDA, or the FDA web database |
| TRUNCATED | Chain view only: the node sits at `MAX_GENERATIONS` and still has numbered predicates |
| Summary parsed, no predicate found | *Added:* the PDF reads fine but holds no predicate number or predicate section |
| Wrong file (PDF is for another number) | *Added:* the PDF's own number differs from the requested one |

A dead end says nothing about whether a device is the original of its lineage. The tool never labels a node "root" or "original".

## 10. Generations and the ancestor frontier

- **Generation** is the number of predicate steps from the device being looked up (generation 0). Each node is drawn once, at its smallest generation.
- **Frontier (`walk-ancestors`):** predicates outside the starting set whose distance from the nearest starting-set device is `MAX_GENERATIONS` or less. Nodes at the maximum distance are extracted so the tool can tell whether they have further predicates (TRUNCATED); their own predicates are stored as edges but not followed.

## 11. Re-extraction and provenance

Every documents, edges, flags, node_status, and review_queue row carries `parser_version`. After a parser fix, bump `PARSER_VERSION` and run `python orthoparity.py reparse-offline`. It re-reads cached PDFs with no downloads and keeps every older version's rows. The lookup layer uses each node's newest parser version.

## 12. Network etiquette

At most one request per second across all FDA hosts, up to three retries with exponential backoff (5, 10, 20 seconds) on 429/5xx and connection errors, and a descriptive User-Agent (`USER_AGENT` in `config.ini`).

## 13. Limitations

- Predicates are what the submitter wrote in the Summary. The tool does not verify FDA's internal review.
- Substantial equivalence is a regulatory finding. It says nothing about clinical performance, outcomes, or price.
- 510(k) summaries were not required before 1990, so most chains end in the early 1990s whatever the generation limit. Statement-only clearances and unreadable PDFs also end a branch.
- The starting set covers orthopedic product codes only (FDA Orthopedic panel and 21 CFR 888). Non-orthopedic ancestors come in through the frontier.
- Applicant names appear as printed at clearance and are not rolled up to current owners.
- Text extraction can misread layouts. The Flags tab and Reviewer_Checklist exist for human review.
- Segment labels are unofficial (assigned by Claude, not FDA).
- Independent research tool built from public FDA data, provided as is, not regulatory advice, and the author's personal work and views.

## 14. Vendors (`build-vendor-registry`)

A vendor owns many raw names from three sources: Open Payments paying entities (by payer ID), 510(k) applicants,
and GUDID labelers (by DUNS number, orthopedic product codes only). Names are assigned in this order:

1. **Curated families** (`reference/vendor_families.csv`): a regular expression on the name with spaces and
   punctuation removed.
2. **Evidence:** a labeler joins the vendor that filed 60% or more of the 510(k)s its orthopedic devices cite; a
   payer joins the vendor whose devices make up 60% or more of its device-ID tags.
3. **Otherwise** the cleaned name itself (legal suffixes and words such as Holdings removed) is the vendor.

Answers typed in `reviews/Vendor_Registry_REVIEW.xlsx` (a rename, a parent correction, or moving a name) are
applied on every run.

**Parent companies.** OrthoParity benchmarks the parent company. Every vendor rolls up to its current owner through
up to three dated links in `reference/vendor_lineage.csv` (acquired by, merged into, owned by, became part of), and
the site shows the parent with every company it owns, for every year, including years before a purchase. A search
for a company another company owns lands on the parent, with an explanation and the source links. Two more rules:

- **Private equity.** The roll-up stops at the operating company. The private-equity owner is noted, not used as a
  parent (for example Highridge Medical, owned by H.I.G. Capital).
- **Divestitures follow the business.** When a source names the product lines sold, the clearances in those FDA
  product codes move to the buyer (`reference/vendor_divestitures.csv`); everything else stays with the seller.
  Example: Stryker's U.S. spinal implants business moved to VB Spine on 2025-04-01 for 17 spine product codes.

**Evidence standard.** Every ownership change needs a public source: an SEC filing, a company release, or
reputable business and trade press (Citeline, MassDevice, ORTHOWORLD, Becker's and similar). Name variants of one
company (spelling errors, "dba" names, foreign subsidiaries) are merged when FDA records show the same product
lines under both names. `reference/ownership_sources.csv` lists every claim checked and its status. A claim backed
only by a single data-vendor page, or by nothing, is listed as NOT APPLIED and left out.

The build also keeps the dated **as owned at the time** roll-up. The "Is it new?" card uses it to ask whether a
predicate belonged to the same company on the clearance date, and some payment tables keep both columns
(`vendor_pit`, `vendor_current`). The site reads the current owner everywhere else.

A vendor is **listed** on the site when it has at least one orthopedic 510(k) in the data.

## 15. Industry payments (`load-open-payments` to `export-payments`)

**Which rows load.** A payer is in orthopedic scope when device IDs that GUDID maps to an orthopedic product code
make up 1% or more of its product tags (or 500 tags or more); or 5% or more of its tags are devices, supplies or
biologics whose category or name reads as orthopedic; or it shares a name with a 510(k) applicant and either has
under 1,000 tags or 1% or more orthopedic tags. Pharma, wound care, dental and neurostimulation wording never
counts. Every row from an in-scope payer loads, plus every row to a recipient with an orthopedic, neurosurgery or
podiatry specialty (for validation). Records CMS lists as removed or deleted are taken out. No recipient names
load.

**Which payments count for a vendor.** A payment belongs to its payer's vendor. For dedicated orthopedic vendors
(80% or more of matched device tags orthopedic, or no device tags) every payment counts unless all its product
tags are non-orthopedic devices or drugs. For diversified vendors a payment counts when it names an orthopedic
product, or names no known non-orthopedic product and goes to an orthopedic, neurosurgery or podiatry recipient.

**Product links** (`match-products`), one tier per product slot:

1. **Device ID:** the reported device ID is in GUDID; the device's 510(k)s, product codes and brand follow.
2. **Brand:** no usable device ID, but the reported name matches one of the same vendor's GUDID brands (exact, the
   brand inside the name, or the name starting the brand with 6 or more letters). Brands that are only the
   company's name never match. A brand match never crosses vendors.
3. **Name only:** counted at vendor level only.

A payment counts in full for every product it names, so product totals overlap.

**Nature groups:** royalty, consulting, services, speaking, travel, food, education, grant, honoraria,
acquisitions, debt forgiveness, ownership, other.

**Surgeons** appear only as an anonymous key: an MD5 hash of a secret salt plus the NPI (or the CMS profile ID
when no NPI is reported). Without the salt the key can't be matched back to an NPI. The salt is created on the first build and stays in `data/`.

**Validation** (`validate-payments`, `docs/validation/payments_validation.md`) reproduces published 2025 totals
and checks that every aggregate adds back to the fact table in both roll-ups.

## 16. Recalls (`fetch-recalls`)

Recalls come from the openFDA device recall endpoint for each of the 254 orthopedic product codes. FDA's recall
class (I, II, III) comes from the enforcement endpoint, matched on the recall number; recalls with no enforcement
record show "NOT FOUND". A recall links to a vendor by a 510(k) number it lists that is in the portfolio, then by
the recalling firm's name (curated patterns, then an exact match after removing punctuation and suffixes). Each
row records which basis linked it. Impossible dates in openFDA are left blank.

## 16b. Adverse event reports (`fetch-maude`)

MAUDE reports come from the openFDA device adverse event endpoint. Each report carries the premarket number the
manufacturer entered (`pma_pmn_number`). FDA's data stores some 510(k) numbers with a leading P (PK140881 for
K140881), so both forms count. For every clearance in the starting set the step counts the reports that name it: all reports by event type (death, injury, malfunction, other or not answered), reports received in the
last five years by event type, and reports by the year FDA received them. A product's counts are the reports that
name its own 510(k); a company's counts add up every 510(k) in its family, the same family the portfolio and
recalls use (parent company, everything it owns, and product lines it bought). The download resumes where it
stopped and needs a free openFDA API key for the full set (about 30,000 requests).

## 16c. Manufacturing sites and FDA inspections (`fetch-establishments`, `load-fda-compliance`)

Sites come from the openFDA registration and listing endpoint. Every firm that makes, designs, sterilizes, relabels
or imports devices for the US market registers each site with FDA every year and lists its devices; a listing can
name the 510(k) it markets under. The step downloads every listing under the 254 orthopedic product codes and keeps
the link between each site (FEI number) and each starting-set 510(k) it names, with the activities the site
registered for that product. "Makes" means manufacture, contract manufacture, remanufacture, reprocessing or
contract sterilization. Contact people, US agents and official correspondents are dropped.

Each site gets a company only when its owner/operator's name matches a name the company files under (the same
applicant, labeler and payer names the rest of the site uses). Words that every device firm uses (Medical,
Orthopedics, Spine, Inc, GmbH and similar) never count as a match. When an owner lists 510(k)s of several companies,
the company holding the most of them wins, but only if its name matches. Distributors, logistics firms and contract
manufacturers match no company and stay blank.

On a company page, sites fall into three groups. Company sites belong to the company or a company it owns. Partner
sites belong to firms with no matched company (contract manufacturers, sterilizers, importers, relabelers). Other
companies' sites belong to a different device company that lists some of this company's 510(k)s, which usually means
a product line changed hands; they are counted, not mixed in.

Inspections, Form 483 citations and compliance actions come from the FDA Data Dashboard's full exports and are
kept only for the sites above, joined on FEI number. An inspection can carry several project areas with different
classifications; the page uses the most serious (OAI over VAI over NAI) and counts device inspections only. The
five-year window ends on the latest inspection date in the export. Warning letters count once per case number.

## 16d. Medicare add-on payments (`load-add-on-payments`)

Two CMS programs pay hospitals extra for some new technologies. The inpatient new technology add-on payment (NTAP)
adds to the MS-DRG payment, up to a maximum per case, for a fiscal year (FY 2027 runs October 1, 2026 to September
30, 2027). Outpatient transitional pass-through pays separately for a device, by HCPCS C-code, for two to three
years in hospital outpatient departments and ASCs.

CMS names technologies, not 510(k) numbers, so the orthopedic list is human-reviewed. `reference/add_on_payments.csv`
holds one row per technology and program: the CMS name, status, company, the FDA numbers it maps to with an FDA
source link, and the starting-set 510(k)s for that product line. Navigation instruments, cement and other accessory
510(k)s are left out. A PMA device (Infuse, PearlMatrix, TOPS, TOUCH CMC 1) links to its approval page (section 16e).

The step then checks every reviewed row against the CMS files: each NTAP name must appear in the matching list
(new, continued or discontinued) of FY 2027 MAC Implementation File 8, and each pass-through code must carry status
indicator H in CY 2027 OPPS Addendum B with the same expiration flag. Any mismatch stops the step. The maximum add-on,
ICD-10 codes, APC and short descriptor come from the CMS files, not from the reference file. The report lists every
CMS technology and pass-through code the reference file leaves out, so a reviewer can confirm nothing orthopedic
was missed. A product line that changed owners counts under its current owner, the same as the portfolio (Stryker
bought 4WEB's Ankle Truss System in 2024).

## 16e. FDA approvals: PMA and HDE (`load-approvals`, `supabase/13_approvals.sql`)

Class III orthopedic devices reach the market through premarket approval (PMA) instead of a 510(k): the company
submits its own clinical evidence of safety and effectiveness, and there is no predicate. A humanitarian device
exemption (HDE) is FDA's path for a device that treats a condition affecting not more than 8,000 people in the US a
year: FDA reviews safety and probable benefit, not effectiveness, and a hospital's institutional review board must
approve its use.

- **Scope.** Every PMA in openFDA's PMA dataset with advisory committee "OR" (Orthopedic), originals and supplements
  (116 approvals, 2,411 supplements on 2026-11-22), which includes hyaluronic acid knee injections (MOZ) and bone
  growth stimulators (LOF, LOE). HDEs come from FDA's HDE database (no API), advisory committee Orthopedic
  (15 HDEs, 157 records). Old "N" numbers (pre-PMA new drug applications for devices) count as PMAs.
- **One page per approval.** The approval number is the page's ID, the same as a 510(k) number. The page shows the
  original approval and its supplements. A PMA chain has no predicates, so the predicate boxes say so.
- **Supplements.** Each is sorted by FDA's supplement type and reason: panel-track supplements are new indications;
  then design, labeling, post-approval study, manufacturing (process changes and 30-day notices), site (location
  changes) and other. The page lists new indications and design, labeling and study changes, and counts
  manufacturing and site notices. Every supplement is in `pc_approval_supplements.csv`.
- **Indications.** From the approval order statement of the original approval, without its opening "Approval for
  the device." sentence. When the statement has no indications text, the page reads NOT FOUND and points to the
  Summary of Safety and Effectiveness Data (or Summary of Safety and Probable Benefit) on FDA's page.
- **Missing originals.** openFDA lists only supplements for 6 PMAs, and the HDE database lists only supplements for
  1 HDE (VEPTR, H030009). Those pages say the original is not on file and give no approval date.
- **Company.** The FDA applicant name, matched to the vendor registry the same way as a 510(k) applicant (exact name,
  reviewed family, then company name). An applicant the registry does not know gets its own company record.
- **Everything else** uses the same rules as a 510(k): GUDID device IDs that cite the approval number, Open Payments
  product records, recalls whose `pma_numbers` name it, MAUDE reports in the same five-year window, FDA-registered
  sites whose listing names it, and Medicare add-on payments whose FDA number is the approval.
- **Payments.** A record counts when a device ID in it resolves to the approval in GUDID (tier 1), or when it names a
  brand that GUDID lists only under approvals (tier 2). A brand also used on 510(k) devices (Stryker's "Trident") is
  left to the 510(k) pages, so no payment is counted twice. Approval records come from every Open Payments general
  payment, not only the orthopedic-scope set the company pages use, because most approval makers (hyaluronic acid
  makers, for example) are outside the 510(k) vendor registry. Many older products are named without a device ID or
  a GUDID brand (Euflexxa, for example); those records are not counted, and the box says so.
- **Adverse events.** Many recent MAUDE reports on PMA devices leave the FDA number blank (16 of 100 sampled MOZ
  reports from 2024 to 2026 carried one). When an approval has no report in the last five years, the box gives the
  year of the last report naming it and says newer reports can be missed.
- **Registered sites.** A site counts as the company's own when its owner's name matches the approval's company or
  FDA applicant (Genzyme for Sanofi Genzyme); otherwise it reads as a partner.
- **Text.** FDA's older PMA records are in ALL CAPS. Indications and supplement descriptions are shown in sentence
  case with the device's trade name, the applicant's name and acronyms kept capitalized; the words are FDA's.
- **Reclassified codes.** FDA later moved some PMA product codes to Class II (bone cement LOD, interbody cages MAX,
  bone growth stimulators LOF and others, per openFDA's product classification). Those pages give the code's
  current class and say newer devices of that type reach the market through 510(k).
- **Missing originals.** When FDA's database has only the supplements, the approval date reads NOT FOUND and the
  earliest supplement date is given as such.
- **Draft names and Medicare links.** The 37 product codes only approvals use carry plain-English names and 21
  Medicare procedure links (`reference/approval_procedure_links.csv`) that Claude reviewed at the project owner's
  direction on 2026-11-22. A professional review is still pending. Hand and finger joint codes stay unlinked, the
  same rule as total wrist: the family for that DRG range is named "other than replacement".
- **Alternatives.** A PMA or HDE counts as an active alternative in its product code when FDA approved it, or any
  supplement to it, in the last five years. Many approvals are decades old and still sold; a recent supplement is
  the public sign that a company still makes the device.
- **Limitations.** The HDE database has no API, so HDEs are refreshed by hand. Hyaluronic acid injections, shock wave
  therapy and similar office treatments are not in the Medicare view (the box reads NOT FOUND). Company pages count
  only orthopedic-scope payments; product pages for approvals count every payment that links to them.

## 17. Decision briefs (`supabase/05_decision_functions.sql`)

Each product and vendor page has a bottom line and one box (card) per question: 12 on a product page and 11 on a
vendor page. Every card has a question, a short label for the page's tab bar, a badge, a finding drawn from the
data, why it matters, and one or more questions to ask the vendor (`asks`; the first is also `ask`). A question
appears only when the data triggers it, so a product with no studies is asked why, and one with studies is asked
for the results. Every card shows even when the answer is "none", and missing data reads NOT FOUND with a reason.
The rules are fixed SQL, so the same data always gives the same cards. "Last five years" is measured back from the
latest clearance date in the data, or for inspections, from the latest inspection date.

**Product cards**

| Card | Rule |
|---|---|
| Is it new? | Line extension when every direct predicate is the same company's; competitive entry when none are; mixed otherwise; "predicate not on file" when no numbered predicate was read. Same company: the cleaned applicant names match, or both applicants belong to vendors with the same owner on the clearance date (the dated roll-up used for payments) |
| What is it cleared to treat? | The Indications for Use extracted from the 510(k) summary, and how closely its wording matches the primary predicate's (trigram similarity: same wording at 90% or more, close at 60% or more, otherwise differs). A wording comparison, not a clinical judgment |
| Who sells it today? | The 510(k) holder at clearance against the company that owns the product line now (vendor roll-up and dated product-line sales) |
| What else does the job? | Other companies with clearances in the same product code in the last five years, grouped by current owner |
| What are the financial ties for this product? | Open Payments naming this 510(k) or its brand |
| What industry-funded studies name it? | Industry-funded research in Open Payments that names this 510(k), and ClinicalTrials.gov numbers on those records |
| What will it take to stock on the shelf? | GUDID device IDs citing this 510(k), how many are in distribution, and the category median |
| Any recalls? | Recalls naming this 510(k), and recalls naming its direct predicates |
| Any adverse events? | MAUDE reports naming this 510(k): all years, the last five years by type, and the median for its product code |
| What is the vendor's supplier record? | Registered sites that list this 510(k), with device inspections, OAI classifications and warning letters at those sites in the last five years |
| What does Medicare pay for procedures that use it? | The procedure family its product code maps to: the DRGs, the range of average Medicare payments per case by DRG, discharges and the published implant-cost range. Procedure-level, not product-level, with the mapping's review status |
| Any Medicare add-on payments? | FY 2027 inpatient NTAP and CY 2027 outpatient pass-through for this product line, and others in its product code |

**Vendor cards**

| Card | Rule |
|---|---|
| Where do they compete? | Product codes in the portfolio, active codes in the last five years, and categories where the vendor is a top-3 filer. Broad at 12 or more codes, focused at 3 or fewer |
| Are they still investing? | Clearances in the last five years against the five before: more (20% or more up), fewer (20% or more down), steady, new entrant, or none recent |
| Have any acquisitions or mergers occurred? | Acquisitions by the vendor in the last five years (older ones listed as earlier), and the vendor's current owner if another company bought it |
| What are the financial ties for this vendor? | Latest year's total and recipients, consulting recipients, royalty share, physician owners |
| Are they funding clinical studies? | Research studies funded, in orthopedic scope, and how many carry ClinicalTrials.gov numbers |
| Is the portfolio in distribution? | GUDID brands, and brands with no device ID still in commercial distribution. NOT FOUND when GUDID lists no orthopedic brand for the company (GUDID started in 2014, so older or private-label lines have no record) |
| Any recalls? | Recall events and Class I recalls |
| Any adverse events? | MAUDE reports across the company's 510(k)s, and the product with the most recent reports |
| What is the vendor's supplier record? | Company and partner sites, countries, device inspections and warning letters (see section 16c) |
| What does Medicare pay for procedures that use their products? | The procedure families its product codes map to, and the payment range for the family with its most recent clearances |
| Any Medicare add-on payments? | Its technologies with a FY 2027 NTAP or a CY 2027 pass-through code |

**Ties.** Every "latest" or "top" pick breaks ties the same way (newest 510(k) number for same-day clearances,
then name), so the same data always picks the same device.

**Out-of-scope devices.** A 510(k) on file only as a predicate of an orthopedic device, outside the orthopedic
product codes, gets no brief: the page says it is outside the database's scope.

### 17b. Reviewed fixes on top of the import (`supabase/12_curated_fixes.sql`)

The pipeline matches company names automatically, and some matches are wrong. `12_curated_fixes.sql` applies
reviewed corrections after every import, each with its public source in the file and in `reference/`:

- **Splits:** companies merged because their names share one generic word (for example "Medical", "Spine",
  "Surgical"), split back out using the FDA applicant and GUDID labeler names.
- **Merges:** spelling variants of one company, each confirmed by the same street address on FDA's 510(k) records.
- **Ownership:** acquisitions, divestitures and product-line sales (`reference/vendor_lineage.csv`), and parents
  from listings, filings or company statements. Where no public source names a parent, the parent stays empty.
- **Segments and Medicare mappings** for companies and product codes that had none.

### 17c. Page cache

The five heaviest page functions keep each answer in `pc_cache` (see `supabase/README.md`). The cache changes
speed only: every SQL file and every import empties it, so a cached answer always equals a fresh one.

## 18. Medicare payments by procedure (`load-medicare-hospitals`)

The procedure view shows what Original Medicare pays hospitals for orthopedic surgery, next to the device
categories a case can use. National figures only. No hospital names, no hospital IDs, and no charges.

**Sources.** CMS Medicare Inpatient Hospitals by Provider and Service (one row per hospital and DRG) and Medicare
Outpatient Hospitals by Provider and Service (one row per hospital and APC), data year 2024. The load checks the
row and hospital counts in `config.ini` and stops if they differ.

**Procedure families.** `reference/procedure_families.csv` groups 58 surgical DRGs into 15 families. The first 8
families are the implant-heavy ones (fusion, joint replacement, revision, fracture fixation) and carry 83% of
Medicare's 2024 payments for musculoskeletal stays (MDC 08 plus spinal DRGs 28 to 30). The other 7 cover the
remaining surgical DRGs with reported hospitals; all 15 together carry 88%. Medical DRGs (care without surgery, such as medical back problems) are left out because no implant is
involved. DRG titles come from the CMS MS-DRG v41.1 Definitions Manual (`reference/drg_titles.csv`), in sentence
case. The load stops if the CMS file's description doesn't match the official title.

**Payment fields.** Each is a per-case average, weighted by discharges across hospitals:

| Field | Inpatient source column | Meaning |
|---|---|---|
| Medicare pays | `Avg_Mdcr_Pymt_Amt` | Medicare's own payment |
| Total payment | `Avg_Tot_Pymt_Amt` | Medicare plus the patient's deductible and coinsurance plus any other payer |
| Patient and other payers | total minus Medicare | What the hospital bills the patient and secondary payers. Collections can run lower |

Charges (`Avg_Submtd_Cvrd_Chrg`) are never read: they are list prices, not payments.

**Hospital spread.** For each DRG, the 25th percentile, median and 75th percentile of each hospital's own average
Medicare payment. Shown only when at least 5 hospitals report the DRG (`SPREAD_MIN_HOSPITALS`). Otherwise the
spread reads NOT FOUND with the hospital count.

**Supply range.** The family payment times 30%, 40% and 50%, a planning reference drawn from published studies of
implant cost as a share of payment (`reference/supply_cost_evidence.csv`). It is shown only for families a study
covers (`supply_range = yes`). The other families read NOT FOUND with the reason.

**Device categories.** `reference/procedure_devices.csv` links FDA product codes to each family, with a role
(implant, biologic, cement and accessories, enabling technology, instrument). Links are drafted from the DRG definition and the
product code's anatomy and stay marked draft until reviewed. For the 7 families added in November 2026, each link
was checked against public manufacturer coding guides and the CMS MS-DRG v41.1 Definitions Manual. Links with a clear
source are marked reviewed; links without one were removed. That check confirms a device type's procedures group to
the family's DRGs. It does not show how often the device is used there. Families whose DRGs mix many unrelated
operations, or remove implants, get no device categories. For each category the build counts all clearances, clearances in the
last five years, and active vendors: parent companies with a clearance in those five years.

**Outpatient.** The outpatient file reports payment groups (APCs), not procedures. The view keeps the five
musculoskeletal APCs (5112 to 5116) and, for a few key procedure codes, its outpatient status from a cited source
(`reference/procedure_outpatient.csv`). Status not confirmed from an official CMS list reads NOT FOUND.

**Checks.** No row below the 11-case suppression floor, no total payment below Medicare's payment, family
discharges equal to the sum of their DRGs, every product code known, and no DRG in two families. Results go to
`outputs/Medicare_Report.txt`.

## 18b. Medicare ASC payment rates (`load-asc`, `supabase/14_asc_rates.sql`)

Source: CMS's CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addendum AA (covered surgical procedures, payment
indicator and national payment rate) and Addendum FF (device offset: the share and dollar amount of a device-intensive
procedure's payment that CMS counts as the device portion). `reference/procedure_asc_codes.csv` lists the key procedure
codes for each procedure family; the step copies each code's indicator, rate and device portion, and stops if either
addendum isn't for the year in `[cms_asc] RATE_YEAR`.

- Rates are national and unadjusted. Each ASC's Medicare payment is wage-adjusted for its area, and commercial payers
  set their own rates.
- One ASC payment covers the facility and the implant; the surgeon is paid separately under the physician fee schedule.
- The device portion comes from Addendum FF for device-intensive procedures (payment indicator J8) only.
- CPT descriptions in the CMS files are AMA copyright, so only the codes and rates are copied. Procedure names come
  from the reference file.
- The Medicare box adds the ASC rates for the family it already shows. Hospital outpatient payments are still not
  shown in that box.

## 18c. Part-number lookup (`export-catalog`, `supabase/15_part_search.sql`)

Source: the FDA GUDID full release (November 2026), indexed by `index-gudid`, plus `gudid-device-fields` for
packaged-sterile and MRI safety status. The lookup covers every GUDID device record that lists an FDA number on the
site (a 510(k), De Novo, PMA or HDE), plus, since Phase 9, every record filed under one of the site's 291 orthopedic
product codes whatever FDA number it lists. For each it keeps the catalog number and the version or model number as
printed, the FDA number (or none), the brand and whether the record is in commercial distribution.

- 1,682,488 rows (1,361,618 distinct part numbers) from 1,461,001 GUDID device IDs, November 2026 release:
  - 808,046 device IDs list an FDA number on the site (996,831 rows; 772,414 distinct part numbers);
  - 1,963 list only an FDA number outside the site's orthopedic set (1,796 rows). The page shows that number;
  - 650,992 list no FDA number at all (683,861 rows). The page shows "FDA number NOT FOUND in GUDID" and says whether
    the company marked the device premarket exempt (280,255 device IDs) or listed no premarket submission. GUDID lets
    a company leave the submission out; OrthoParity never guesses one from the brand or product code.
- Before Phase 9 the lookup held only the first group, so 43% of orthopedic part numbers in GUDID returned no match.
- Device facts, shown only when every device ID on the row agrees: device IDs on the row, units in the base package
  (`deviceCount`), packaged sterile (`deviceSterile`) and MRI safety status (`MRISafetyStatus`). When the device IDs
  disagree, units and sterile stay blank and MRI safety reads "Differs across device IDs".
- Identical rows merge. Identifiers with fewer than 3 letters or digits and placeholders (N/A, NONE, TBD) are dropped.
- Search ignores case, spaces and punctuation ("213-65-05" finds "21365 05"). Exact matches come first, then part
  numbers that start with what was typed. At least 3 letters or digits are required.
- A part number listed under several FDA numbers shows every one: companies reuse part numbers across submissions and
  across product lines, and GUDID records what each company submitted.
- GUDID is company-reported. A part number missing here may still be sold under that 510(k).

## 18d. Medicare TEAM model (`load-team`, `supabase/17_team_data.sql`, `supabase/18_team_functions.sql`)

Sources: CMS's TEAM model page (Preliminary Target Prices PY1 and PY2, the Participant List as of August 18, 2026,
and the TEAM DRG Mapping Specifications FY2020 to FY2027), 42 CFR 512.525(d) and 512.540 (eCFR, amended effective
October 1, 2026), and CMS's Participation Tracks fact sheet.

- **Trigger codes** (`reference/team_triggers.csv`): copied from 42 CFR 512.525(d): 32 MS-DRGs and 8 HCPCS codes in 5
  episode categories. Each HCPCS code is priced under the MS-DRG 512.540 names. The step stops if CMS's target price
  workbooks price an MS-DRG the regulation doesn't list, or (for 2027) miss one it does.
- **Families** (`reference/team_episode_families.csv`): which procedure families are TEAM episodes and which MS-DRGs
  price them. Primary hip and knee (469, 470), hip replacement for fracture (521, 522), hip and femur fixation (480 to
  482) and cervical fusion (471 to 473) use the same numbers as the family. Lumbar and thoracolumbar fusion uses the
  2024 numbers 453 to 460; CMS's DRG mapping workbook (Table 1) shows every one of them renumbered into TEAM spinal
  fusion MS-DRGs (402, 426 to 430, 447, 448, 450, 451 in FY 2025; 523 to 525 in FY 2027), so the whole family is a
  TEAM episode. Revision hip and knee (466 to 468) is not. Drafted by Claude at the project owner's direction,
  pending review.
- **Target prices:** CMS's preliminary price for each MS-DRG and census division, with benchmark, trend and
  discount, for 2026 and 2027. CMS's PY1 file repeats 35 rows word for word; each is kept once, and the step stops if
  a repeated row differs.
- **Participants:** 721 hospitals (711 mandatory, 10 voluntary) by CCN with CBSA and dates. A hospital's census
  division comes from its state.
- **On the site:** the Medicare box adds one sentence, one figure and one question for a TEAM family; procedure pages
  show the codes and prices; `/team` looks up hospitals and codes; `/team/calculator` is browser-only arithmetic on
  the user's own figures.
- **Not published by CMS, so NOT FOUND:** hospital-specific target prices and each hospital's track.

## 18e. Registered clinical trials (`fetch-trials`, `supabase/19_trials.sql`)

Source: the ClinicalTrials.gov API v2, every study with a device intervention (77,365 on November 24, 2026).

- **Device links, exact only:** a trial links to a product when its registry record writes the product's FDA number
  (K, DEN, P or H) in its title, summary, description or interventions and the number is in OrthoParity (43 links),
  or when an Open Payments research record names both the 510(k) and the trial's NCT number (34 links): 77 links, 59
  trials, 67 products. A scan of all 17,589 cached 510(k) summary PDFs found no NCT number, so summaries are not a
  source.
- **Company links:** the lead sponsor's name, with case, punctuation and legal suffixes removed, must equal a name
  the company is known by in the vendor registry, and the sponsor must be an industry sponsor; or the sponsor is
  listed in `reference/trial_sponsors.csv` (7 business unit names, drafted by Claude, pending review). A name that
  matches more than one parent company is left out. Counts roll up to today's parent company.
- **Orthopedic scope:** company counts include only trials whose MeSH conditions (or their ancestors) include one of
  the 10 terms in `reference/trial_mesh_terms.csv`: musculoskeletal diseases, bone fractures, spinal diseases and
  limb, tendon and sprain injuries. 5,598 device trials qualify; 872 are linked to 145 parent companies.
- **Not linked:** 407 industry sponsors of musculoskeletal device trials (661 trials) match no company; most are
  companies outside OrthoParity (dental implants, physical therapy apps). They're listed in
  `outputs/trials/unmatched_industry_sponsors.csv` for review.
- A trial's status and "results posted" come from ClinicalTrials.gov as of the download. Published papers are not
  included.
- **No personal names:** a sponsor that is a person (sponsor class "individual", a title such as Dr or Prof, or no
  organization word in the name) is stored as "Individual investigator (name not shown)", and a text excerpt that
  names a person is left blank. Investigator and contact fields are never downloaded.

## 18f. Category directories (`supabase/16_directory.sql`)

Every orthopedic FDA record with a product code (18,267 of 18,355; 88 have none), grouped by FDA product code and by
the reviewed segment in the product code dictionary. Each row shows identity facts only: number, pathway, name, the
company on the FDA record, today's parent, decision date and GUDID brand and listing counts. The directory lists;
it doesn't rank. Recalls and adverse events stay on product pages, because their links to FDA numbers are partial.

