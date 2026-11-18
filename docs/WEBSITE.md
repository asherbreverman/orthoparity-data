# How the website works

```
browser ──> website (orthoparity-web, built in Lovable) ──> Supabase API ──> Postgres functions ──> tables
                                                         (anon key, read only)   (supabase/*.sql)     (CSV data)
```

- **The website** is a React app built with Lovable. Its code lives in the `orthoparity-web` repository, which
  Lovable keeps in sync with GitHub. It has no data of its own: every page calls a database function and draws
  what comes back.
- **The database** is Postgres on Supabase. `supabase/01_tables.sql` creates the tables; the other files create
  the functions the site calls. Row-level security lets anyone read and nobody write.
- **The data** is the CSV files this repository builds (`outputs/site_data/`), imported into the tables.

## Public functions

Each returns JSON (or rows) and is callable with the public anon key.

| Function | Used for | Returns |
|---|---|---|
| `pc_search(q)` | Search | Devices matching a K-number, name or company |
| `pc_brief(k)` | Product | Everything on the device page: identity, predicates, lineage, peers, category, IFU, VAC questions |
| `pc_signals(k)` | Product | The decision brief: bottom line and signal cards |
| `pc_lookup(roots, max_gen)` | Product | The full predicate chain as nodes, edges and flags |
| `pc_brand_family(k)` | Product | Other clearances with the same brand word |
| `pc_direct`, `pc_peers`, `pc_category`, `pc_primary_lineage` | Product | Pieces of the brief, callable on their own |
| `pc_compare(a, b)`, `pc_batch(ks)` | Comparisons | Two devices side by side; up to 50 at once |
| `pc_product_payments(k)` | Product | Open Payments naming this 510(k) or its brand |
| `pc_device_recalls(k)` | Product | Recalls naming this 510(k) or its direct predicates |
| `pc_vendor_search(q)` | Search | Vendors matching a name |
| `pc_vendor_brief(v, mode)` | Vendor | Everything on the vendor page |
| `pc_vendor_signals(v, mode)` | Vendor | The vendor decision brief |
| `pc_vendor_portfolio(v, mode, ...)` | Vendor | The vendor's 510(k)s, filterable by anatomy, kind and product code |
| `pc_vendor_compare(a, b, mode)` | Comparisons | Two vendors side by side |
| `pc_vendor_recalls(v, mode)` | Vendor | The vendor's recall events |

`mode` is `pit` (as owned at the time, the default) or `current` (current owner, with acquired companies'
history).

You can call any of them yourself, for example in the Supabase SQL Editor: `select pc_signals('K241487');`

## Keys and hosting

- The site uses the Supabase **anon** key, which is public by design. Row-level security limits it to reading.
- The **service-role** key bypasses security. It must never appear in the website code, in this repository, or in
  a chat. `python orthoparity.py check` looks for it.
- Supabase's free plan pauses a project after a week with little traffic and keeps no backups; the Pro plan
  avoids both. Queries from the site time out after 15 seconds (`supabase/06_admin.sql`).

## Updating the site's data

1. Rebuild the CSVs (`docs/REBUILD.md`) or download the latest release.
2. Re-import the CSVs into their tables and run `supabase/07_after_import.sql`.
3. If a function changed, run the file that holds it. Each uses `create or replace`, so nothing is lost.
4. Publish a dated release of the CSVs on GitHub, so anyone can see what the site is running on.
