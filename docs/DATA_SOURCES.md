# Data sources

Every input is public US government data or a public company filing. None of it needs an account or a key.
Download the files yourself; they are too large for git and they change with each FDA or CMS release. File names
and expected row counts live in `config.ini`, so a new release that doesn't match stops the build instead of
quietly changing the numbers.

Folder layout the default `config.ini` expects, next to this repository:

```
OrthoData\
  orthoparity-data\                               this repository
  FDA 510K Clearances for Orthopedics\            starting set, 510(k) release files, product codes
  GUDID Full Release as of 2026 November\         GUDID XML parts
  CMS Open Payments for 2025 to 2019\
    CMS Open Payments for 2019\ ... for 2025\     one folder per program year
  Medicare Inpatient Hospitals by Provider and Service 2024\
  Medicare Outpatient Hospitals by Provider and Service 2024\
```

Change `INPUT_DIR`, `GUDID_DIR` and `OP_DIR` in `config.ini` to use other folders, and `IP_FILE` and `OP_FILE`
under `[medicare]` for the Medicare files.

## 1. FDA 510(k) premarket notification release files

- **What:** every 510(k) and De Novo decision since 1976, all review panels.
- **Where:** FDA, "Downloadable 510(k) Files" (search for that title on fda.gov). Five zipped text files:
  1976-1980, 1981-1985, 1986-1990, 1991-1995, 1996 to present.
- **Used for:** the identity of every predicate by number (company, device name, decision date, product code).
- **Version in the published data:** decisions through Nov 13, 2026; 176,747 unique records.

## 2. Orthopedic starting set

- **What:** the 18,224 clearances in orthopedic product codes (FDA Orthopedic panel and 21 CFR 888), with an
  unofficial segment label on each. Every field except the segment comes from FDA's own records.
- **File:** `Orthopedic_510K_Clearances_1976_to_Present.xlsx`, sheet "510K Clearances". It ships with each data
  release. `pc_devices.csv` in the release also lists every starting-set clearance (`in_starting_set = true`) with
  its segment.
- **Note:** the segment labels are unofficial. They were assigned with AI help, not by FDA.

## 3. FDA product code classification

- **What:** every device product code with its name, class, regulation number and definition.
- **Where:** FDA, "Download Product Code Classification Files" (fda.gov). Text file `foiclass.txt`, saved here
  as `FDA Product Code Classification.txt`.
- **Version in the published data:** 7,105 product codes.

## 4. FDA 510(k) Summary PDFs

- **What:** the summary each submitter posted, which names the predicate devices.
- **Where:** downloaded by `extract-predicates` and `walk-ancestors` from `www.accessdata.fda.gov`, at most one
  request per second, with a descriptive user agent. Each PDF is saved once with its SHA-256 hash.
- **Version in the published data:** read November 16-17, 2026, parser 1.3.1.

## 5. FDA Global Unique Device Identification Database (GUDID)

- **What:** every device identifier (UDI-DI) with its brand, labeler, product codes and 510(k) numbers.
- **Where:** AccessGUDID, "Download" page, Full Release (XML, about 200 parts).
- **Version in the published data:** November 2026 full release, 211 parts, 5,258,157 device records (from the
  release header).

## 6. CMS Open Payments

- **What:** payments and transfers of value from drug and device makers to physicians, other clinicians and
  teaching hospitals, plus research payments and physician ownership.
- **Where:** CMS Open Payments, "Dataset Downloads", one zip per program year (general, research, ownership,
  and removed or deleted records).
- **Version in the published data:** program years 2019 to 2025, as published June 30, 2026.
- **Privacy:** no recipient names, NPIs or CMS profile IDs leave the build machine. Recipients are counted with a
  salted hash.

## 7. openFDA device recalls

- **What:** FDA device recalls (recall endpoint) and FDA recall class (enforcement endpoint).
- **Where:** `https://api.fda.gov/device/recall.json` and `https://api.fda.gov/device/enforcement.json`,
  downloaded by `fetch-recalls` for each of the 254 orthopedic product codes.
- **Version in the published data:** 8,096 recalled products in 2,537 events, 2002 to Nov 14, 2026.

## 7b. openFDA device adverse event reports (MAUDE)

- **What:** FDA's MAUDE database of medical device reports, counted per 510(k) number.
- **Where:** `https://api.fda.gov/device/event.json`, queried by `fetch-maude` for each clearance in the starting
  set. A free openFDA API key raises the daily limit from 1,000 to 120,000 requests.
- **Version in the published data:** openFDA data through Nov 11, 2026: 649,641 reports naming 7,484 orthopedic
  510(k)s, downloaded Nov 20, 2026. Details in `outputs/MAUDE_Report.txt`.

## 7c. openFDA establishment registration and listing

- **What:** FDA's registry of device establishments (sites) and the devices each one lists, including the 510(k)
  number when the firm entered it.
- **Where:** `https://api.fda.gov/device/registrationlisting.json`, queried by `fetch-establishments` for each
  orthopedic product code. Uses the same openFDA key as MAUDE.
- **Version in the published data:** downloaded Nov 20, 2026: 101,081 listings, 2,944 sites, 981 of them linked to
  at least one starting-set 510(k) (25,222 links covering 11,661 of 18,224 clearances). Details in
  `outputs/Establishments_Report.txt`.

## 7d. FDA Data Dashboard: inspections, 483 citations and compliance actions

- **What:** FDA's published inspection classifications (fiscal year 2009 on), Form 483 citations and compliance
  actions (warning letters, injunctions, seizures), each keyed by FEI number.
- **Where:** `https://datadashboard.fda.gov/oii/cd/inspections.htm` (Download Dataset > Entire Inspections Dataset,
  then Entire Citations Dataset) and `https://datadashboard.fda.gov/oii/cd/complianceactions.htm` (Download
  Dataset > Entire Dataset). Save the three .xlsx files in the folder named by `[fda_dashboard] DIR`.
- **Version in the published data:** exported Nov 20, 2026 (inspections through Nov 6, 2026): 346,169 inspection
  rows, 283,583 citation rows and 178,672 compliance action rows read; 6,529, 5,983 and 139 kept for orthopedic
  sites. Details in `outputs/FDA_Compliance_Report.txt`.

## 7e. CMS Medicare add-on payments (NTAP and device pass-through)

- **What:** the FY 2027 inpatient new technology add-on payment lists (new, continued, discontinued, with maximum
  amounts and ICD-10 codes) and the CY 2027 outpatient device pass-through codes.
- **Where:** FY 2027 IPPS final rule home page, MAC Implementation File 8 (ZIP),
  `https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/fy-2027-ipps-final-rule-home-page`;
  CY 2027 OPPS final rule (CMS-1850-FC), "2027 FR OPPS Addenda" (ZIP), Addendum B,
  `https://www.cms.gov/medicare/payment/prospective-payment-systems/hospital-outpatient/regulations-notices/cms-1850-fc`.
- **Version in the published data:** File 8 (corrected) and the addenda updated Nov 10, 2026, downloaded Nov 20,
  2026: 12 orthopedic NTAP technologies (3 new, 8 continued, 1 discontinued) and 6 orthopedic pass-through codes.
  Details in `outputs/Add_on_Payments_Report.txt`.

## 8. Ownership changes

- **What:** dated acquisitions, mergers and product-line sales, so clearances, payments and recalls roll up to
  the parent company.
- **Where:** `reference/vendor_lineage.csv` (83 dated links, each with a source link),
  `reference/vendor_divestitures.csv` (5 product-line sales, by FDA product code) and
  `reference/ownership_sources.csv` (166 claims checked, each with its status and source).
- **Evidence:** SEC filings, company releases, and reputable business and trade press. A claim found only on a
  single data-vendor page is not applied.

## 9. CMS Medicare hospital payments

- **What:** Original Medicare payments to hospitals, one row per hospital and DRG (inpatient) or APC (outpatient).
- **Where:** data.cms.gov, datasets "Medicare Inpatient Hospitals - by Provider and Service" and "Medicare
  Outpatient Hospitals - by Provider and Service". Download the CSV for the data year.
- **Version in the published data:** data year 2024. Inpatient: 145,879 rows from 2,906 hospitals. Outpatient:
  116,182 rows from 3,126 hospitals.
- **Privacy:** hospital names and IDs are read only to count hospitals and compute spreads. None are written.

## 10. MS-DRG titles

- **What:** the official title of each MS-DRG, so the site shows complete titles (the CMS payment file shortens
  some).
- **Where:** CMS ICD-10 MS-DRG v41.1 Definitions Manual, Appendix A,
  https://www.cms.gov/icd10m/FY2024-version41.1-fullcode-cms/fullcode_cms/P0380.html. Stored in
  `reference/drg_titles.csv`.

## 11. Implant cost studies and outpatient status

- `reference/supply_cost_evidence.csv`: 8 published studies and reports of implant cost as a share of payment,
  each with a link. They set the 30% to 50% supply range.
- `reference/procedure_outpatient.csv`: outpatient status and APC for key procedure codes, each with its source.
  Rows not confirmed from an official CMS list read NOT FOUND.

## 12. CMS TEAM model

- **What:** Medicare's Transforming Episode Accountability Model: preliminary target prices by MS-DRG and census
  division (PY1 2026, dated 2025-12-10; PY2 2027, dated 2026-11-04), the participant list (as of August 18, 2026) and
  the TEAM DRG Mapping Specifications (updated October 2026).
- **Where:** https://www.cms.gov/priorities/innovation/innovation-models/team-model. Save the four XLSX files,
  unopened, in `../CMS TEAM`. Rules: 42 CFR 512.525 and 512.540 (eCFR) and the Participation Tracks fact sheet.

## 13. ClinicalTrials.gov

- **What:** registry records for every study with a device intervention: status, sponsor, design, primary outcome,
  conditions (with NLM's MeSH terms) and whether results are posted.
- **Where:** the ClinicalTrials.gov API v2 (https://clinicaltrials.gov/api/v2/studies), 78 requests at 1 per second.
  `fetch-trials` caches the download in `outputs/trials/device_trials.jsonl`. Downloaded November 24, 2026: 77,365
  studies.

## Human review inputs (in this repository)

- `reference/vendor_families.csv`: name patterns that group a company's many spellings into one vendor.
- `reference/add_on_payments.csv`: which CMS add-on payment technologies are orthopedic, who makes them and which
  FDA numbers they map to, each with an FDA source link. `load-add-on-payments` checks it against the CMS files.
- `reviews/Vendor_Registry_REVIEW.xlsx`: reviewed vendor names, parents and name moves.
- `reviews/Product_Code_Dictionary_REVIEW.xlsx`: plain-English product code names; a row counts as reviewed only
  when marked Y.
- `reviews/predicate_review/`: decisions on documents the parser could not settle, each with its reasoning.
