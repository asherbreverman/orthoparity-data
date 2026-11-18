"""Restore registered and trademark signs, dashes and accented letters lost before the data reached the database.

Repairs, using the FDA release files already loaded in table fda_master:
  - clearances: applicant, contact, street, city and device name
  - edges: the FDA applicant and device name stored for each predicate
  - payments.duckdb vendor registry: vendor display names and matched applicant names
A value is changed only when the FDA value for the same 510(k) has the same length and matches every other
character. Anything else is left alone and listed in the report.

Writes outputs/Text_Repair_Report.txt and outputs/site_data/supabase_text_repair.sql (paste into Supabase).

Usage:  python orthoparity.py repair-text            (repair)
        python orthoparity.py repair-text --dry-run  (report only, change nothing)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from predicate_chain.config import load_config
from predicate_chain.paycommon import PaySettings
from predicate_chain.textrepair import repair_duckdb, repair_sqlite, supabase_patch


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    write = not args.dry_run

    sq = sqlite3.connect(str(cfg.db_path))
    res = repair_sqlite(sq, write=write)
    sq.close()

    duck = {"vendor_entities": 0, "vendors": 0, "vendor_rows": [], "name_rows": []}
    pay_db = PaySettings(cfg).db
    if pay_db.exists():
        import duckdb
        dc = duckdb.connect(str(pay_db), read_only=not write)
        duck = repair_duckdb(dc, res.applicant_map, write=write)
        dc.close()

    lines = ["Text repair report" + (" (dry run, nothing changed)" if not write else ""), ""]
    lines.append("Restored values (table, column: rows):")
    for (t, c), n in sorted(res.fixed.items()):
        lines.append(f"  {t}.{c}: {n:,}")
    if not res.fixed:
        lines.append("  none")
    lines.append("")
    lines.append("Characters restored: " + ", ".join(f"{ch!r} {n:,}" for ch, n in
                                                     sorted(res.characters.items(), key=lambda x: -x[1])))
    lines.append(f"Vendor registry: {duck['vendors']} vendor display names, {duck['vendor_entities']} matched names")
    lines.append("")
    lines.append("Left as they were, because no FDA value matched character for character (table, column: rows):")
    for (t, c), n in sorted(res.left.items()):
        lines.append(f"  {t}.{c}: {n:,}")
    if not res.left:
        lines.append("  none")
    for t, c, k, broken, good in res.left_examples:
        lines.append(f"    {t}.{c} {k}: {broken!r}  FDA: {good!r}" if good else f"    {t}.{c} {k}: {broken!r}  FDA: NOT FOUND (no FDA value for this number)")
    report = cfg.output_dir / "Text_Repair_Report.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if write:
        out = cfg.site_data_dir
        out.mkdir(parents=True, exist_ok=True)
        (out / "supabase_text_repair.sql").write_text(
            supabase_patch(res.portfolio_rows, duck["vendor_rows"], duck["name_rows"]), encoding="utf-8")
    print("\n".join(lines))
    print(f"\nReport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
