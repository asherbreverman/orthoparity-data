# OrthoParity data

OrthoParity is a free, open-source tool that helps hospital supply chain and value analysis teams benchmark
orthopedic implants and the companies that make them, using only public FDA and CMS data. This repository holds
everything behind the numbers on the site: the code that builds the data, the database that serves it, the human
review decisions, and the validation results.

- **Website:** https://www.orthoparity.com
- **Website code:** the `orthoparity-web` repository (the page design; it reads the database built here)
- **License:** MIT. Free to use, change and share, with no warranty.

## What it answers

For an **orthopedic 510(k) device**: what FDA cleared it against (its predicate chain, back up to 10
generations), which other companies sell devices that do the same job, what industry payments name it, how
large its catalog is, and whether it or its predicates were recalled.

For a **vendor**: where it competes, whether it is still adding products, who owns it now and since when, what it
pays surgeons and for what, what research it funds, and its recall history. A vendor always means the parent
company with every company it owns.

For a **procedure**: what Original Medicare pays hospitals per case for 15 groups of orthopedic surgery (58 DRGs),
split into Medicare's payment and the patient's and other payers' share, with the device categories a case can use
and the companies active in each.

Each page ends in a short list of signals, each with a finding, why it matters, and a question to ask the vendor.
The signals follow fixed rules (see `supabase/05_decision_functions.sql`), so the same data always gives the same
answer. A payment or a recall is a fact to ask about, never a judgment of a company or a surgeon.

## What's in the data

| Source | What we use | Coverage |
|---|---|---|
| FDA 510(k) release files | Every clearance, all panels | 176,747 records, 1976 to Nov 13, 2026 |
| FDA 510(k) Summary PDFs | The predicates each submitter cited | 18,224 orthopedic clearances plus their ancestors (23,764 devices, 51,442 predicate links) |
| FDA product code classification | Device names, class, regulation | 7,105 codes; 254 orthopedic codes with plain-English names |
| FDA GUDID full release | Device IDs, brands, catalog size | 5,258,157 device records, November 2026 release |
| CMS Open Payments | Industry payments to surgeons and teaching hospitals | Program years 2019 to 2025 |
| openFDA device recalls | Recalls and FDA recall class | 8,096 recalled products in 2,537 events, 2002 to Nov 14, 2026 |
| openFDA adverse event reports (MAUDE) | Reports naming each orthopedic 510(k), by type and year | 649,641 reports naming 7,484 510(k)s, through Nov 11, 2026 |
| openFDA establishment registration and listing | Sites that list each orthopedic 510(k), and what they do | 981 sites linked to 11,661 510(k)s, Nov 20, 2026 |
| FDA Data Dashboard | Device inspections, Form 483 citations and warning letters for those sites | Fiscal year 2009 through Nov 6, 2026 |
| CMS add-on payments | Orthopedic technologies with an inpatient NTAP or outpatient device pass-through code | FY 2027 NTAP, CY 2027 OPPS |
| CMS Medicare hospital payments | Inpatient payments by DRG, outpatient by APC | Data year 2024: 2,906 inpatient and 3,126 outpatient hospitals |
| SEC filings, company releases, business and trade press | Dated ownership changes | 83 dated links and 5 product-line sales, each with a source link |

`docs/DATA_SOURCES.md` says where to download each one.

## How the data gets built

```
FDA release files ─┐
Summary PDFs ──────┼─> predicate database (SQLite) ─┐
FDA product codes ─┘                                 │
GUDID ─────────────┐                                 ├─> 36 CSV files ─> Supabase (Postgres) ─> website
Open Payments ─────┼─> payments database (DuckDB) ───┤
vendor registry ───┘                                 │
openFDA recalls ─────────────────────────────────────┤
openFDA adverse event reports (MAUDE) ───────────────┤
openFDA establishments + FDA Data Dashboard ─────────┤
CMS add-on payments (NTAP, pass-through) ────────────┤
CMS Medicare hospital payments ──────────────────────┘
```

One command runs any step: `python orthoparity.py <step>`. Run it with no step to see the list.

| Group | Steps, in order |
|---|---|
| `predicates` | load-fda, extract-predicates, walk-ancestors, import-review, extract-ifu, product-dictionary, export-predicates |
| `payments` | index-gudid, load-open-payments, build-vendor-registry, match-products, build-payment-aggregates, validate-payments, repair-text, export-payments |
| `recalls` | fetch-recalls |
| `maude` | fetch-maude (needs a free openFDA API key) |
| `supplier` | fetch-establishments, load-fda-compliance (needs the openFDA key and three FDA Data Dashboard exports) |
| `addon` | load-add-on-payments (needs two CMS ZIP files) |
| `medicare` | load-medicare-hospitals |
| `all` | all of the above |

`docs/REBUILD.md` walks through a full rebuild. The first predicate download reads about 18,000 Summary PDFs
at one request per second, so it takes many hours; it resumes where it stopped.

## Quick start (Windows)

1. Install Python 3.12 from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
2. Download this repository (green Code button, Download ZIP) and unzip it.
3. Double-click `run.bat`. The first run sets up Python packages (a minute or two), then lists every step.
4. Type `test` and press Enter to run the unit tests.

To use the published data without rebuilding it, download `site_data_YYYY-MM-DD.zip` from the latest
GitHub release and follow `supabase/README.md`.

## Folder layout

```
orthoparity.py        one command for every step
run.bat               Windows launcher: sets up Python, then runs orthoparity.py
config.ini            every setting, input file name and expected row count
predicate_chain/      the core library (PDF reading, predicate parser, chains, shared helpers)
pipeline/             one file per build step, in the order above
tools/                lookups, review and validation tools, reports, the pre-publish check
supabase/             the database: tables, functions, load script
reference/            curated vendor families and dated ownership changes, each with a source
reviews/              human review decisions the build reads (vendors, product names, predicates)
docs/                 methodology, data dictionary, sources, limitations, rebuild guide, validation
tests/                unit tests on synthetic data only
```

Large and private files stay off GitHub: the databases (`data/`), downloaded PDFs (`cache/`), build outputs
(`outputs/`) and the salt that anonymizes surgeons (`data/recipient_salt.txt`). `.gitignore` excludes them, and
`python orthoparity.py check` confirms nothing private is about to be published.

## Accuracy

On 2026-11-17 a fresh random sample of 40 orthopedic clearances (10 per era, 1996 to 2026) was checked by hand
against the Summary PDFs: 0 errors in 143 predicate links (95% interval 0.0% to 2.6%). The sample is small, so
read that as a range, not a guarantee. Details: `docs/validation/accuracy_report.md`.

The Open Payments build reproduces published 2025 totals for named companies within 0.5%
(`docs/validation/payments_validation.md`).

## Limitations

Read `docs/LIMITATIONS.md` before relying on any number. The short version:

- Predicates are what the submitter wrote in the 510(k) Summary. Substantial equivalence is a regulatory finding
  and says nothing about clinical performance, outcomes or price.
- Most chains end in the early 1990s, because summaries were not required before then. A chain's last device is
  where the public record stops, not necessarily the original design.
- Open Payments shows reported payments only, and a payment is not evidence of influence.
- Recall reporting and recall classes come from FDA as published; older recalls have no class in openFDA.
- A MAUDE report is not proof that a device caused an event, and counts are not rates. A report counts toward a
  product only when it names the 510(k) number, so counts are a floor.
- Manufacturing sites are current FDA registrations linked by 510(k) number, so site counts are a floor. An
  inspection classification describes one visit to one site, not a rating of a company or its products.
- Medicare add-on payments are a human-reviewed list checked against CMS. The amount is the most Medicare adds per
  case, not a device price.
- Medicare figures cover Original Medicare only, at national level. No public data shows what a hospital pays for
  devices, so the supply range is a planning reference, not a price.
- A parent company's numbers include every company it owns, for all years.
- Segment labels and plain-English product names were drafted with AI help and are marked when not yet reviewed.

## Privacy

No surgeon names or NPIs appear anywhere in this repository or on the site. Surgeons appear only as an anonymous
key (a salted hash) used to count recipients; the salt never leaves the machine that builds the data.

## Contributing

Found a wrong number? Open an issue with the K-number or vendor, what the site shows, and the public source that
says otherwise. Code changes are welcome too: see `CONTRIBUTING.md`.

## Disclaimer

OrthoParity is an independent research tool built from public FDA and CMS data, provided as is. It is not
affiliated with FDA or CMS, and it is not regulatory, legal or compliance advice. It is the author's personal
work and views.

Copyright (c) 2026 Asher Breverman. MIT License (see `LICENSE`).
