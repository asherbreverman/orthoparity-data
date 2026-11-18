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
applied on every run. **Ownership over time** comes from `reference/vendor_lineage.csv`; every event has a date
and a source link. Two roll-ups sit side by side everywhere: **pit** (as owned at the time: an acquired company's
history moves to its buyer from the closing date) and **current** (everything moves to the final owner).

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

## 17. Decision briefs (`supabase/05_decision_functions.sql`)

Each product and vendor page ends in a bottom line and a few cards. Every card has a question, a short badge, a
finding drawn from the data, why it matters, and a question to ask the vendor. The rules are fixed SQL, so the same
data always gives the same cards. "Last five years" is measured back from the latest clearance date in the data.

**Product cards**

| Card | Rule |
|---|---|
| Is it new? | Line extension when every direct predicate is the same company's; competitive entry when none are; mixed otherwise; "predicate not on file" when no numbered predicate was read |
| What else does this job? | Other companies with clearances in the same product code in the last five years, grouped by current owner |
| Financial ties | Open Payments naming this 510(k) or its brand |
| Evidence | Industry-funded research in Open Payments that names this 510(k) |
| What will it take to stock? | GUDID device IDs citing this 510(k), how many are in distribution, and the category median |
| Recalls | Recalls naming this 510(k), and recalls naming its direct predicates |

**Vendor cards**

| Card | Rule |
|---|---|
| Where do they compete? | Product codes in the portfolio, active codes in the last five years, and categories where the vendor is a top-3 filer. Broad at 12 or more codes, focused at 3 or fewer |
| Are they still investing? | Clearances in the last five years against the five before: more (20% or more up), fewer (20% or more down), steady, new entrant, or none recent |
| Ownership | Dated acquisitions by the vendor in the last five years, and who owns it now |
| Payments | Latest year's total and recipients, consulting recipients, royalty share, physician owners |
| Evidence | Research studies funded, in orthopedic scope |
| Supply | GUDID brands, and brands with no device ID still in commercial distribution |
| Recalls | Recall events and Class I recalls |
