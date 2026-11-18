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
```

Change `INPUT_DIR`, `GUDID_DIR` and `OP_DIR` in `config.ini` to use other folders.

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

## 8. Ownership changes

- **What:** dated acquisitions and mergers, so payments and clearances roll up to the right owner at the right
  time.
- **Where:** `reference/vendor_lineage.csv`, 25 events. Each has a source link (SEC filing or company press
  release) and a closing date.

## Human review inputs (in this repository)

- `reference/vendor_families.csv`: name patterns that group a company's many spellings into one vendor.
- `reviews/Vendor_Registry_REVIEW.xlsx`: reviewed vendor names, parents and name moves.
- `reviews/Product_Code_Dictionary_REVIEW.xlsx`: plain-English product code names; a row counts as reviewed only
  when marked Y.
- `reviews/predicate_review/`: decisions on documents the parser could not settle, each with its reasoning.
