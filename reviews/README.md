# Review decisions

The build reads these files, so a fresh rebuild gives the same answers as the live site. They hold human (and
AI-assisted, labeled as such) judgment calls that the rules alone can't make.

| File | Read by | What it holds |
|---|---|---|
| `Vendor_Registry_REVIEW.xlsx` | `build-vendor-registry` | Which names belong to which vendor, current parents, dated ownership. Yellow columns are the reviewer's answers and override the draft. |
| `Product_Code_Dictionary_REVIEW.xlsx` | `product-dictionary`, `export-predicates` | Plain-English names for the 254 orthopedic product codes. A row counts as reviewed only when marked Y. |
| `predicate_review/Review_Batch_NN_decisions.json` | `import-review` | Decisions on documents the parser couldn't settle, each with its reasoning. `reviewer` says who decided. |
| `predicate_review/Review_Log.csv` | (written by `import-review`) | Every decision so far, in one table. |
| `Procedure_Crosswalk_REVIEW.xlsx` | (reference only) | The DRG ranking, procedure families, outpatient codes, device categories and evidence behind the procedure view. The build reads the CSVs in `reference/`, not this workbook. |
| `Procedure_Families_Added_REVIEW.xlsx` | (reference only) | The 7 procedure families added on 2026-11-19, with their DRGs, 2024 figures and device categories. Research columns and sources added 2026-11-19; decisions applied to `reference/procedure_devices.csv`. |

The build rewrites the two workbooks each time it runs (to add new names or codes) and keeps every answer typed in
the yellow columns. To change a decision, edit the yellow cell, save, and run the step again.
