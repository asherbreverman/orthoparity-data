# Database setup (Supabase)

The website reads a Postgres database hosted on Supabase. These files build it from nothing. Every file is safe
to run again, and none of them writes data except `07_after_import.sql`, which tidies what you imported.

| File | What it creates |
|---|---|
| `01_tables.sql` | 36 tables, their indexes, and public read-only access (anyone can read, nobody can write) |
| `02_device_functions.sql` | Device search, predicate chains, the device brief, peers, compare and batch |
| `03_vendor_functions.sql` | Vendor search, the parent-company redirect, portfolio, vendor brief, vendor compare, product payments, home page counts |
| `04_recall_functions.sql` | Recall lookups and the recall cards |
| `05_decision_functions.sql` | The decision briefs: the signal cards on each product and vendor page |
| `06_admin.sql` | Two maintenance functions (not callable from the website) and a 15-second query timeout |
| `07_after_import.sql` | Run after every CSV import: turns blank cells into NULL, marks research rows in orthopedic scope, prints row counts |
| `08_procedure_functions.sql` | The procedure view (Medicare payments by procedure family) and the procedure links on device pages |
| `09_maude_functions.sql` | FDA adverse event reports (MAUDE) for products and companies |
| `10_supplier_functions.sql` | The supplier record on company pages: manufacturing sites, FDA inspections, 483 citations and warning letters |
| `11_add_on_functions.sql` | Medicare add-on payments (NTAP and device pass-through) for products and companies |

## Build a new database

1. Create a Supabase project. In the SQL Editor, open a new query, paste `01_tables.sql`, and press Run.
   Repeat for `02` through `06`, then `08` through `11`, in number order. (`07` comes after the import in step 3.)
2. Import the CSV files. Get them from the latest GitHub release (`site_data_YYYY-MM-DD.zip`) or build them
   yourself with `python orthoparity.py all`. Each file goes into the table with the same name
   (`pc_devices.csv` into `pc_devices`, and so on).
   - Dashboard: Table Editor, pick the table, Insert, Import data from CSV.
   - Command line: `DATABASE_URL="postgresql://..." bash supabase/load_csv.sh outputs/site_data`
3. Run `07_after_import.sql`. Its last query lists row counts; each should be one less than the line count of
   the matching CSV (the header line).

## Update an existing database

- Medicare add-on payments (2026-11-20): run `01_tables.sql` (it only adds `pc_add_on_payment` and
  `pc_add_on_payment_510k`), import the two new CSVs, run `07_after_import.sql`, then run `11_add_on_functions.sql`.
- Supplier record (2026-11-20): run `01_tables.sql` (it only adds `pc_establishment`, `pc_establishment_510k`,
  `pc_inspection`, `pc_inspection_citation` and `pc_compliance_action`; existing data stays), import the five new
  CSVs, run `07_after_import.sql`, then run `10_supplier_functions.sql`. Needs `09_maude_functions.sql` first.
- Adverse event reports (2026-11-20): run `01_tables.sql` (it only adds `pc_maude_product` and `pc_maude_year`;
  existing data stays), import the two new CSVs, run `07_after_import.sql`, then run `09_maude_functions.sql`.
- Parent companies and 15 procedure families (2026-11-19): run `01_tables.sql` (it adds the
  `pc_vendor_divestitures` table and two note columns; existing data stays), then `02`, `03`, `05` and `08`.
  Empty and re-import the changed tables (list in `CHANGELOG.md`), then run `07_after_import.sql`.
- Added the procedure view (2026-11-19): run `01_tables.sql` (it only adds the six new `pc_procedure*` and
  `pc_supply_evidence` tables; existing tables and data stay as they are), then `08_procedure_functions.sql`. Import
  the six new CSVs and run `07_after_import.sql`.
- New data, same structure: re-import the CSVs, then run `07_after_import.sql`.
- Changed functions: run the file that holds them. Each uses `create or replace`, so nothing is lost.

## Keys

The website uses the project's **anon** key. It is public by design: row-level security limits it to reading.
Never put the **service-role** key in code, in the website, or in git. `python orthoparity.py check` looks for it.

## History

The first seven files replace eight files written as the site grew (`supabase_setup.sql`, then v2, v3, v4, v6, v9,
v10 and v12). On 2026-11-18 both versions were built side by side in Postgres 16. `pg_dump --schema-only` of the
two databases matched line for line except one code comment that now names the new file. Two older patch files were data fixes and are not needed for a new
build: `supabase_v9_product_names.sql` (the CSV now carries every plain-English name) and
`supabase_text_repair.sql` (the CSVs are written after the repair).
