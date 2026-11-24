"""Load Medicare ASC payment rates for the key procedure codes behind each procedure family.

Source (CMS, public): the CY 2027 OPPS/ASC final rule (CMS-1850-FC) page, Related Links, "2027 FR Addendum AA, BB,
DD1, DD2, EE, and FF" (ZIP). Save the ZIP, unopened, in the folder named by [cms_asc] DIR in config.ini.
  - Addendum AA: every ASC covered surgical procedure with its payment indicator and national payment rate.
  - Addendum FF: for device-intensive procedures (payment indicator J8), the share and dollar amount of the ASC
    payment CMS counts as the device portion.

The rates are national and unadjusted: each ASC's Medicare payment is wage-adjusted for its area. Medicare pays the
ASC one amount per procedure, covering the facility and the implant; surgeon fees are paid separately.

reference/procedure_asc_codes.csv lists the procedure codes to look up for each family. Only codes and rates are
copied; the CPT descriptions in the CMS files are AMA copyright and stay out of the output.

Outputs: outputs/site_data/pc_procedure_asc.csv, supabase/14_asc_rates.sql (table plus rows, ready to run in
Supabase) and outputs/ASC_Report.txt

Usage:  python orthoparity.py load-asc
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import Path

from predicate_chain.config import load_config

SOURCE = "CMS CY 2027 OPPS/ASC final rule (CMS-1850-FC), ASC Addenda AA and FF"
SOURCE_URL = ("https://www.cms.gov/medicare/payment/prospective-payment-systems/ambulatory-surgical-center-asc/"
              "asc-regulations-and-notices/cms-1850-fc")
COLUMNS = ["family_id", "cpt", "procedure", "sort_order", "asc_status", "payment_indicator", "device_intensive",
           "asc_rate", "device_share", "device_portion", "rate_year", "source", "source_url"]
STATUS = {"covered": "On the ASC list", "packaged": "On the ASC list, packaged (no separate payment)",
          "absent": "Not on the ASC list"}


def money(v) -> str:
    s = str(v or "").replace("$", "").replace(",", "").replace('"', "").strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return ""


def pct(v) -> str:
    s = str(v or "").replace("%", "").strip()
    try:
        return f"{float(s) / 100:.4f}"
    except ValueError:
        return ""


def find_zip(folder: Path) -> Path:
    hits = sorted(p for p in folder.glob("*.zip") if re.search(r"asc.*addend|addend.*asc|addendum-aa", p.name, re.I))
    if not hits:
        raise SystemExit(f"No ASC addenda ZIP in {folder}. See pipeline/load_asc.py for where to download it.")
    return hits[-1]


def read_addendum(z: zipfile.ZipFile, letter: str) -> tuple[str, dict[str, list[str]]]:
    """Return (title line, {HCPCS: row}) for one addendum CSV inside the ZIP."""
    name = next((n for n in z.namelist() if re.search(rf"addend\w*\s+{letter}\.csv$", n, re.I)), None)
    if not name:
        raise SystemExit(f"Addendum {letter} CSV not found in the ZIP.")
    text = z.read(name).decode("cp1252", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    title = " ".join(rows[0][0].split()) if rows and rows[0] else ""
    h = next(i for i, r in enumerate(rows) if r and r[0].strip().lower() == "hcpcs code")
    out = {}
    for r in rows[h + 1:]:
        if r and r[0].strip():
            out[r[0].strip().upper()] = [c.strip() for c in r]
    return title, out


def build(zip_path: Path, codes_csv: Path, rate_year: int) -> tuple[list[dict], list[str]]:
    with zipfile.ZipFile(zip_path) as z:
        title_aa, aa = read_addendum(z, "AA")
        title_ff, ff = read_addendum(z, "FF")
    for t, letter in ((title_aa, "AA"), (title_ff, "FF")):
        if str(rate_year) not in t:
            raise SystemExit(f"Addendum {letter} is titled '{t}', not CY {rate_year}. Check the ZIP or [cms_asc] RATE_YEAR.")
    out, notes = [], [f"Addendum AA: {title_aa} ({len(aa):,} codes)", f"Addendum FF: {title_ff} ({len(ff):,} codes)"]
    with open(codes_csv, newline="", encoding="utf-8") as f:
        refs = list(csv.DictReader(f))
    for i, ref in enumerate(refs, 1):
        cpt = ref["cpt"].strip().upper()
        a, d = aa.get(cpt), ff.get(cpt)
        row = {"family_id": ref["family_id"], "cpt": cpt, "procedure": ref["procedure"], "sort_order": i,
               "asc_status": STATUS["absent"], "payment_indicator": "", "device_intensive": "no", "asc_rate": "",
               "device_share": "", "device_portion": "", "rate_year": rate_year, "source": SOURCE,
               "source_url": SOURCE_URL}
        if a:
            ind, rate = a[5], money(a[7])
            row["payment_indicator"] = ind
            row["device_intensive"] = "yes" if ind == "J8" else "no"
            row["asc_rate"] = rate
            row["asc_status"] = STATUS["covered"] if rate else STATUS["packaged"]
            if d and ind == "J8":
                row["device_share"], row["device_portion"] = pct(d[7]), money(d[8])
        out.append(row)
        notes.append(f"  {cpt} {ref['procedure']}: {row['asc_status']}"
                     + (f", ${float(row['asc_rate']):,.2f}" if row["asc_rate"] else "")
                     + (f", device portion ${float(row['device_portion']):,.2f}" if row["device_portion"] else ""))
    return out, notes


def sql_text(rows: list[dict]) -> str:
    def lit(v):
        return "null" if v in ("", None) else ("'" + str(v).replace("'", "''") + "'")
    values = ",\n".join("  (" + ", ".join([lit(r["family_id"]), lit(r["cpt"]), lit(r["procedure"]), str(r["sort_order"]),
                                          lit(r["asc_status"]), lit(r["payment_indicator"]),
                                          "true" if r["device_intensive"] == "yes" else "false",
                                          r["asc_rate"] or "null", r["device_share"] or "null", r["device_portion"] or "null",
                                          str(r["rate_year"]), lit(r["source"]), lit(r["source_url"])]) + ")" for r in rows)
    return f"""-- 14_asc_rates.sql: Medicare ASC payment rates for the key procedure codes of each procedure family.
-- Written by `python orthoparity.py load-asc` from CMS's ASC Addenda AA and FF. Don't edit by hand; rerun the step.
-- Safe to run again. Run order after an import: 07, 13, 14, 12, 05.

create table if not exists pc_procedure_asc (
  family_id text not null, cpt text not null, procedure text, sort_order int, asc_status text, payment_indicator text,
  device_intensive boolean, asc_rate numeric, device_share numeric, device_portion numeric, rate_year int,
  source text, source_url text, primary key (family_id, cpt));
alter table pc_procedure_asc enable row level security;
drop policy if exists "public read" on pc_procedure_asc;
create policy "public read" on pc_procedure_asc for select to anon, authenticated using (cpt is not null);
grant select on pc_procedure_asc to anon, authenticated;

delete from pc_procedure_asc;
insert into pc_procedure_asc (family_id, cpt, procedure, sort_order, asc_status, payment_indicator, device_intensive,
  asc_rate, device_share, device_portion, rate_year, source, source_url) values
{values};

-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
"""


def load(folder: Path, codes_csv: Path, rate_year: int, site: Path, outputs: Path, sql_path: Path) -> list[dict]:
    zip_path = find_zip(folder)
    rows, notes = build(zip_path, codes_csv, rate_year)
    site.mkdir(parents=True, exist_ok=True)
    with open(site / "pc_procedure_asc.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    sql_path.write_text(sql_text(rows), encoding="utf-8")
    report = [f"Medicare ASC payment rates, CY {rate_year}", f"Source file: {zip_path.name}", *notes,
              "Rates are national and unadjusted; each ASC's payment is wage-adjusted for its area.",
              f"Wrote {len(rows)} rows to {site / 'pc_procedure_asc.csv'} and {sql_path}."]
    (outputs / "ASC_Report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.ini")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    d = Path(cfg.get("cms_asc", "DIR", "../CMS ASC Addenda 2027"))
    folder = d if d.is_absolute() else (cfg.project_dir / d).resolve()
    year = int(cfg.get("cms_asc", "RATE_YEAR", "2027"))
    load(folder, cfg.project_dir / "reference" / "procedure_asc_codes.csv", year, cfg.site_data_dir, cfg.output_dir,
         cfg.project_dir / "supabase" / "14_asc_rates.sql")
    return 0


if __name__ == "__main__":
    sys.exit(main())
