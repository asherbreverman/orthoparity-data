"""Export the part-number lookup: every catalog and version or model number FDA's GUDID lists for the site's devices.

For each GUDID device record whose premarket submission is a 510(k), De Novo, PMA or HDE number on the site (any number
in outputs/site_data/pc_portfolio_510k.csv), it keeps the catalog number and the version or model number as printed,
the FDA number, the brand and whether the record is in commercial distribution. Identical rows are merged, and
identifiers with fewer than 3 letters or digits, or placeholders such as N/A, are dropped. Brands go in a separate
small table so the big one stays lean (about 83 MB in Postgres for the November 2026 GUDID release).

Reads data/payments.duckdb (index-gudid must have run) and outputs/site_data/pc_portfolio_510k.csv (export-payments).

Outputs: outputs/site_data/pc_catalog_brand.csv, pc_catalog_1.csv ... pc_catalog_N.csv (split so each stays under
the Supabase dashboard's CSV import limit) and outputs/Catalog_Report.txt

Usage:  python orthoparity.py export-catalog
"""
from __future__ import annotations

import argparse
import csv
import sys

from predicate_chain.config import load_config
from predicate_chain.paycommon import PaySettings, connect_duck

ROWS_PER_FILE = 250_000
PLACEHOLDERS = ("N/A", "NA", "NONE", "UNKNOWN", "NOT APPLICABLE", "TBD")


def export(con, portfolio_csv, site, outputs) -> dict:
    con.execute(f"""create or replace temp table site_numbers as
        select distinct upper(knumber) as n from read_csv_auto('{portfolio_csv.as_posix()}', all_varchar=true)""")
    con.execute("""create or replace temp table cat_base as
        select distinct d.primary_di, nullif(trim(d.catalog_number), '') as cat, nullif(trim(d.version_model), '') as vm,
               coalesce(trim(d.brand), '') as brand, upper(s.submission_number) as n,
               d.distribution_status ilike 'in commercial%' as in_dist
          from gudid_devices d join gudid_submissions s using (primary_di)
          join site_numbers x on x.n = upper(s.submission_number)""")
    ph = ", ".join("'" + p + "'" for p in PLACEHOLDERS)
    con.execute(f"""create or replace temp table cat_ids as
        select ident, n, brand, bool_or(in_dist) as in_dist from (
            select cat as ident, n, brand, in_dist from cat_base where cat is not null
            union all select vm, n, brand, in_dist from cat_base where vm is not null) u
         where length(regexp_replace(upper(ident), '[^A-Z0-9]', '', 'g')) >= 3 and upper(ident) not in ({ph})
         group by 1, 2, 3""")
    con.execute("""create or replace temp table cat_brand as
        select row_number() over (order by brand)::int as brand_id, brand from (select distinct brand from cat_ids) b""")
    site.mkdir(parents=True, exist_ok=True)
    for old in site.glob("pc_catalog_*.csv"):
        old.unlink()
    con.execute(f"copy (select brand_id, brand from cat_brand order by brand_id) to "
                f"'{(site / 'pc_catalog_brand.csv').as_posix()}' (header, delimiter ',')")
    rows = con.execute("""select c.ident, c.n, b.brand_id, c.in_dist from cat_ids c join cat_brand b using (brand)
                          order by c.ident, c.n""").fetchall()
    files = []
    for i in range(0, len(rows), ROWS_PER_FILE):
        path = site / f"pc_catalog_{i // ROWS_PER_FILE + 1}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ident", "n", "brand_id", "in_dist"])
            w.writerows([r[0], r[1], r[2], "true" if r[3] else "false"] for r in rows[i:i + ROWS_PER_FILE])
        files.append(path)
    stats = con.execute("""select (select count(*) from cat_base), (select count(distinct primary_di) from cat_base),
                                  (select count(*) from cat_ids), (select count(distinct ident) from cat_ids),
                                  (select count(distinct n) from cat_ids), (select count(*) from cat_brand),
                                  (select count(*) from site_numbers)""").fetchall()[0]
    report = ["Part-number lookup (FDA GUDID catalog and version or model numbers)",
              f"Site FDA numbers: {stats[6]:,}; with GUDID records: {stats[4]:,}",
              f"GUDID records linked: {stats[0]:,} ({stats[1]:,} device IDs)",
              f"Lookup rows: {stats[2]:,} ({stats[3]:,} distinct part numbers); brands: {stats[5]:,}",
              *[f"Wrote {p.name} ({p.stat().st_size / 1e6:.1f} MB)" for p in files], "Wrote pc_catalog_brand.csv"]
    (outputs / "Catalog_Report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return {"rows": stats[2], "files": len(files)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    portfolio = cfg.site_data_dir / "pc_portfolio_510k.csv"
    if not portfolio.exists():
        print("Run export-payments first: outputs/site_data/pc_portfolio_510k.csv is missing.")
        return 1
    con = connect_duck(PaySettings(cfg))
    export(con, portfolio, cfg.site_data_dir, cfg.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
