"""Export the part-number lookup: every catalog and version or model number FDA's GUDID lists for orthopedic devices.

Which GUDID records it covers: every record that lists an FDA number on the site, plus every record filed under one
of the site's orthopedic product codes (the codes in outputs/site_data/pc_portfolio_510k.csv and, when present,
pc_approvals.csv), whatever FDA number it lists:
  - records that list a 510(k), De Novo, PMA or HDE number on the site (one row per part number and FDA number);
  - records that list an FDA number that isn't on the site (the row keeps that number);
  - records that list no FDA number at all (the row keeps the product code and the company GUDID names, and whether
    the company marked the device premarket exempt). The site shows these as "FDA number NOT FOUND in GUDID".
It keeps the catalog number and the version or model number as printed, the brand, whether any record is in
commercial distribution, how many device IDs share the row, and three device facts when every device ID on the row
agrees: units per package (deviceCount), packaged sterile, and MRI safety status. Identical rows are merged, and
identifiers with fewer than 3 letters or digits, or placeholders such as N/A, are dropped. Brands and companies go in
separate small tables so the big one stays lean (about 150 MB in Postgres for the November 2026 GUDID release).

MRI codes in the mri column: 0 labeling has no MRI safety information, 1 MR Safe, 2 MR Conditional, 3 MR Unsafe,
9 the device IDs on the row disagree, blank unknown.

Reads data/payments.duckdb (index-gudid and gudid-device-fields must have run; without gudid-device-fields the
sterile and MRI columns stay blank), outputs/site_data/pc_portfolio_510k.csv (export-payments) and, when present,
outputs/site_data/pc_approvals.csv (load-approvals).

Outputs: outputs/site_data/pc_catalog_brand.csv, pc_catalog_company.csv, pc_catalog_1.csv ... pc_catalog_N.csv
(split so each stays under the Supabase dashboard's CSV import limit) and outputs/Catalog_Report.txt

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
COLUMNS = ["ident", "n", "pc", "brand_id", "company_id", "in_dist", "n_di", "units", "sterile", "mri", "exempt"]
MRI_CODES = {"MR Safe": 1, "MR Conditional": 2, "MR Unsafe": 3, "Labeling does not contain MRI Safety Information": 0}


def _has_table(con, name: str) -> bool:
    return con.execute("select count(*) from information_schema.tables where table_name = ?", [name]).fetchone()[0] > 0


def export(con, portfolio_csv, site, outputs) -> dict:
    p = portfolio_csv.as_posix()
    # FDA approvals (PMA, HDE) are on the site too: pc_approvals.csv sits next to the portfolio when load-approvals ran
    approvals = portfolio_csv.parent / "pc_approvals.csv"
    appr_n = (f"union select distinct upper(number) from read_csv_auto('{approvals.as_posix()}', all_varchar=true)"
              if approvals.exists() else "")
    appr_pc = (f"""union select distinct upper(trim(product_code)) from read_csv_auto('{approvals.as_posix()}',
                   all_varchar=true) where coalesce(trim(product_code), '') <> ''""" if approvals.exists() else "")
    con.execute(f"""create or replace temp table site_numbers as
        select distinct upper(knumber) as n from read_csv_auto('{p}', all_varchar=true) {appr_n}""")
    con.execute(f"""create or replace temp table site_codes as select distinct upper(trim(product_code)) as pc
        from read_csv_auto('{p}', all_varchar=true) where coalesce(trim(product_code), '') <> '' {appr_pc}""")
    if _has_table(con, "gudid_product_codes"):
        con.execute("create or replace temp view dev_codes as select primary_di, product_code from gudid_product_codes")
    else:
        con.execute("""create or replace temp view dev_codes as select primary_di, unnest(string_split(product_codes, '|'))
                       as product_code from gudid_devices where coalesce(product_codes, '') <> ''""")
    fields = _has_table(con, "gudid_device_fields")
    mri_case = "case f.mri_safety " + " ".join(f"when '{k}' then {v}" for k, v in MRI_CODES.items()) + " end"
    con.execute(f"""create or replace temp table dev as
        select d.primary_di, nullif(trim(d.catalog_number), '') as cat, nullif(trim(d.version_model), '') as vm,
               coalesce(trim(d.brand), '') as brand, coalesce(trim(d.company), '') as company,
               d.distribution_status ilike 'in commercial%' as in_dist, try_cast(d.device_count as integer) as units,
               {"f.sterile = 'true'" if fields else "null::boolean"} as sterile,
               {mri_case if fields else "null::integer"} as mri,
               coalesce(d.premarket_exempt, '') = 'true' as exempt, c.pc
          from gudid_devices d
          left join (select k.primary_di, min(upper(k.product_code)) as pc from dev_codes k
                       join site_codes s on s.pc = upper(k.product_code) group by 1) c using (primary_di)
          {"left join gudid_device_fields f using (primary_di)" if fields else ""}
         where c.pc is not null or d.primary_di in (select s.primary_di from gudid_submissions s
                                                     join site_numbers x on x.n = upper(s.submission_number))""")
    # One row per device ID and FDA number: every site number it lists; otherwise its first other number; else none
    con.execute("""create or replace temp table dev_n as
        with s as (select distinct primary_di, upper(submission_number) as n from gudid_submissions
                    where primary_di in (select primary_di from dev) and coalesce(submission_number, '') <> ''),
        on_site as (select s.* from s join site_numbers using (n)),
        other as (select primary_di, min(n) as n from s where primary_di not in (select primary_di from on_site) group by 1)
        select d.*, o.n, 'site' as kind from dev d join on_site o using (primary_di)
        union all select d.*, o.n, 'other' from dev d join other o using (primary_di)
        union all select d.*, null, 'none' from dev d
         where primary_di not in (select primary_di from on_site) and primary_di not in (select primary_di from other)""")
    ph = ", ".join("'" + x + "'" for x in PLACEHOLDERS)
    # Site rows keep only the FDA number (the site knows its product code and company); the rest keep both
    con.execute(f"""create or replace temp table cat_ids as
        select ident, n, case when kind = 'site' then null else pc end as pc, brand,
               case when kind = 'site' then null else company end as company,
               bool_or(in_dist) as in_dist, count(distinct primary_di) as n_di,
               case when min(units) = max(units) and count(units) = count(*) then min(units) end as units,
               case when count(sterile) < count(*) then null when bool_and(sterile) then true
                    when not bool_or(sterile) then false end as sterile,
               case when count(mri) < count(*) then null when min(mri) = max(mri) then min(mri) else 9 end as mri,
               case when kind = 'none' then bool_and(exempt) end as exempt, any_value(kind) as kind
          from (select cat as ident, * from dev_n where cat is not null
                union all select vm, * from dev_n where vm is not null) u
         where length(regexp_replace(upper(ident), '[^A-Z0-9]', '', 'g')) >= 3 and upper(ident) not in ({ph})
         group by ident, n, case when kind = 'site' then null else pc end, brand,
                  case when kind = 'site' then null else company end, kind""")
    con.execute("""create or replace temp table cat_brand as
        select row_number() over (order by brand)::int as brand_id, brand from (select distinct brand from cat_ids) b""")
    con.execute("""create or replace temp table cat_company as
        select row_number() over (order by company)::int as company_id, company
          from (select distinct company from cat_ids where company is not null) c""")
    site.mkdir(parents=True, exist_ok=True)
    for old in site.glob("pc_catalog_*.csv"):
        old.unlink()
    con.execute(f"copy (select brand_id, brand from cat_brand order by brand_id) to "
                f"'{(site / 'pc_catalog_brand.csv').as_posix()}' (header, delimiter ',')")
    con.execute(f"copy (select company_id, company from cat_company order by company_id) to "
                f"'{(site / 'pc_catalog_company.csv').as_posix()}' (header, delimiter ',')")
    rows = con.execute("""select c.ident, c.n, c.pc, b.brand_id, co.company_id, c.in_dist, c.n_di, c.units, c.sterile,
                                 c.mri, c.exempt
                            from cat_ids c join cat_brand b using (brand) left join cat_company co using (company)
                           order by c.ident, c.n nulls last, c.pc, b.brand_id, co.company_id""").fetchall()

    def cell(v):
        return "" if v is None else ("true" if v is True else "false" if v is False else v)

    files = []
    for i in range(0, len(rows), ROWS_PER_FILE):
        path = site / f"pc_catalog_{i // ROWS_PER_FILE + 1}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLUMNS)
            w.writerows([cell(v) for v in r] for r in rows[i:i + ROWS_PER_FILE])
        files.append(path)
    q = lambda sql: con.execute(sql).fetchone()
    by_kind = dict(con.execute("select kind, count(*) from cat_ids group by 1").fetchall())
    dis = dict(con.execute("select kind, count(distinct primary_di) from dev_n group by 1").fetchall())
    exempt = q("select count(distinct primary_di) from dev_n where kind = 'none' and exempt")[0]
    keys = q("""select count(*), count(*) filter (where site) from (select upper(regexp_replace(ident, '[^A-Za-z0-9]', '',
                'g')) k, bool_or(kind = 'site') site from cat_ids group by 1)""")
    report = ["Part-number lookup (FDA GUDID catalog and version or model numbers)",
              f"Site product codes: {q('select count(*) from site_codes')[0]:,}; "
              f"GUDID device IDs covered: {q('select count(*) from dev')[0]:,}",
              f"  listing an FDA number on the site: {dis.get('site', 0):,}",
              f"  listing an FDA number that isn't on the site: {dis.get('other', 0):,}",
              f"  listing no FDA number: {dis.get('none', 0):,} "
              f"({exempt:,} marked premarket exempt)",
              f"Lookup rows: {len(rows):,} (site {by_kind.get('site', 0):,}; other number {by_kind.get('other', 0):,}; "
              f"no number {by_kind.get('none', 0):,})",
              f"Distinct part numbers: {keys[0]:,}; with a site FDA number: {keys[1]:,}",
              f"Brands: {q('select count(*) from cat_brand')[0]:,}; companies: {q('select count(*) from cat_company')[0]:,}",
              f"Device facts loaded: {'yes' if fields else 'no (run gudid-device-fields)'}",
              *[f"Wrote {p.name} ({p.stat().st_size / 1e6:.1f} MB)" for p in files],
              "Wrote pc_catalog_brand.csv and pc_catalog_company.csv"]
    (outputs / "Catalog_Report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return {"rows": len(rows), "files": len(files), "by_kind": by_kind}


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
