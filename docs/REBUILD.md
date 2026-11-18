# Rebuild the data from scratch

This guide rebuilds every CSV the website uses, from the public source files. You don't need to do this to use
OrthoParity: the website already runs on the published data, and each GitHub release carries the CSVs.

## What you need

- **Windows, macOS or Linux** with Python 3.10 or newer (3.12 recommended). On Windows, `run.bat` does the setup.
- **About 85 GB of free disk space.** In the November 2026 build the inputs took about 72 GB (Open Payments
  2019-2025 unzipped 52 GB, GUDID 20 GB, FDA files 39 MB), the Summary PDFs about 7 GB and the databases about
  2 GB.
- **Internet access** to `www.accessdata.fda.gov` and `api.fda.gov`.
- **Tesseract OCR** (recommended) to read scanned PDFs. Windows installer: https://github.com/UB-Mannheim/tesseract/wiki
  (keep the default folder). Without it, scanned summaries are marked "Needs OCR" and the run continues.
- **Graphviz** (optional) for the tree drawings in the lookup tools.

## 1. Get the source files

Download them as `docs/DATA_SOURCES.md` describes and put them in the folders `config.ini` names. File names and
expected row counts are in `config.ini`. If a count differs (a newer FDA release, say), `load-fda` stops and tells
you which one. Update the count in `config.ini` once you've checked the new file.

## 2. Build the predicate data

```
python orthoparity.py predicates
```

That runs seven steps in order:

1. `load-fda` loads the starting set, the FDA release files and the product codes, and checks every count.
2. `extract-predicates` downloads each orthopedic Summary PDF and reads its predicates. This is the long one:
   about 18,000 PDFs at one request per second, so many hours. Progress: `outputs/progress_full.txt`.
3. `walk-ancestors` follows every chain back up to 10 generations and reads each ancestor's Summary.
   Progress: `outputs/progress_frontier.txt`.
4. `import-review` applies the reviewed decisions in `reviews/predicate_review/`.
5. `extract-ifu` pulls the Indications for Use text from the saved PDFs.
6. `product-dictionary` refreshes `reviews/Product_Code_Dictionary_REVIEW.xlsx` and keeps reviewed answers.
7. `export-predicates` writes the device, predicate, flag, IFU and product code CSVs to `outputs/site_data/`.

**Stop and resume.** Close the window, press Ctrl+C, or create an empty file named `STOP` in `outputs/`. Work is
saved after each document. Run the same command again to continue.

## 3. Build the vendor and payment data

```
python orthoparity.py payments
```

1. `index-gudid` reads the GUDID XML parts (resumable; finished parts are skipped).
2. `load-open-payments` loads Open Payments for orthopedic payers and recipients. No names are loaded.
3. `build-vendor-registry` groups names into vendors and writes `reviews/Vendor_Registry_REVIEW.xlsx`. Answers
   typed in its yellow columns are kept and applied on every run.
4. `match-products` links payment product tags to device IDs, brands and 510(k)s.
5. `build-payment-aggregates` builds every total the site shows. On its first run it creates the private salt
   `data/recipient_salt.txt`. Keep that file, and never publish it: a new salt changes every anonymous key.
6. `validate-payments` writes `outputs/payments_validation.md`. Read it before you publish.
7. `repair-text` restores lost trademark signs and accents.
8. `export-payments` writes the vendor and payment CSVs to `outputs/site_data/`.

## 4. Download recalls

```
python orthoparity.py recalls
```

It reads `pc_portfolio_510k.csv` and `pc_vendor_names.csv` from step 3, so run it after `payments`.

## 5. Check, then load the database

```
python orthoparity.py test
python orthoparity.py check --release
```

Then follow `supabase/README.md` to build or update the database.

## 6. Publish a data release

Zip the CSVs in `outputs/site_data/` as `site_data_YYYY-MM-DD.zip`, add the starting-set workbook, and attach both
to a new GitHub release with a short note on what changed. Run `python orthoparity.py check --release` first.

## Review work

When the parser can't settle a document (a number in no FDA record, a scan that reads as nothing, a PDF for
another number), it goes to the review queue:

1. `python orthoparity.py review-packet` writes the next batch to `outputs/review/Review_Batch_NN.json`, ranked
   by how many chains run through each document.
2. A reviewer writes `reviews/predicate_review/Review_Batch_NN_decisions.json`: one decision per item
   (confirmed, corrected, own number, not a predicate, unresolved), each with its reasoning.
3. `python orthoparity.py import-review` records the decisions and reads any corrected numbers.

Decisions never overwrite what the parser read. Every decision is listed in
`reviews/predicate_review/Review_Log.csv`.

## Validation

`python orthoparity.py make-validation` draws a fresh random sample and writes a hand-check workbook. Fill in the
yellow columns against each PDF, then score it with `python orthoparity.py accuracy-report <workbook>`.

## After a parser change

Raise `PARSER_VERSION` in `predicate_chain/__init__.py`, then run `python orthoparity.py reparse-offline --run
full` (or `pilot`, `frontier`) to re-read the saved PDFs with no downloads. Older versions' results are kept, so you can compare.
