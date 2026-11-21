"""Load FDA inspections, 483 citations and compliance actions for the sites that handle orthopedic 510(k)s.

Source: FDA Data Dashboard (datadashboard.fda.gov), three exports, all public:
  - Inspections: "Download Dataset" > "Entire Inspections Dataset"
  - Inspection citations: "Download Dataset" > "Entire Citations Dataset" (Form FDA 483 observations)
  - Compliance actions: "Download Dataset" > "Entire Dataset" (warning letters, injunctions, seizures)
Save the three .xlsx files in the folder named by [fda_dashboard] DIR in config.ini. The step finds each file by
its column headings, so the file names do not matter.

Only rows whose FEI number belongs to a site in pc_establishment.csv are kept (run fetch-establishments first).
Inspections cover fiscal year 2009 on and exclude state inspections, pre-approval inspections and inspections still
waiting for a final action (FDA's own notes on the dashboard).

Outputs: outputs/site_data/pc_inspection.csv, pc_inspection_citation.csv, pc_compliance_action.csv
         and outputs/FDA_Compliance_Report.txt

Usage:  python orthoparity.py load-fda-compliance
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from predicate_chain.config import load_config

KINDS = {
    "inspections": {"FEI Number", "Inspection ID", "Classification", "Project Area"},
    "citations": {"FEI Number", "Inspection ID", "Short Description"},
    "actions": {"FEI Number", "Action Type", "Action Taken Date"},
}


def norm(h) -> str:
    return " ".join(str(h or "").replace("\n", " ").split())


def to_date(v) -> str:
    if v in (None, "", "-"):
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def fei(v) -> str:
    s = str(v or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def read_rows(path: Path):
    """Yield (headers, row iterator) for the first sheet whose header row we recognize."""
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    for ws in wb.worksheets:
        it = ws.iter_rows(values_only=True)
        for _ in range(15):  # the header row can sit under a title block
            row = next(it, None)
            if row is None:
                break
            heads = [norm(h) for h in row]
            for kind, need in KINDS.items():
                if need <= set(heads):
                    return kind, heads, it, wb
    wb.close()
    return None, [], iter(()), None


def classify(folder: Path) -> dict:
    found = {}
    for p in sorted(folder.glob("*.xlsx")):
        if p.name.startswith("~$"):
            continue
        kind, heads, it, wb = read_rows(p)
        if wb:
            wb.close()
        if kind and kind not in found:
            found[kind] = p
    return found


def load(folder: Path, site: Path, out_dir: Path) -> dict:
    with open(site / "pc_establishment.csv", encoding="utf-8-sig", newline="") as fh:
        feis = {r["fei_number"] for r in csv.DictReader(fh)}
    files = classify(folder)
    missing = [k for k in KINDS if k not in files]
    if missing:
        raise SystemExit(f"Could not find the {', '.join(missing)} export(s) in {folder}. "
                         "See the instructions at the top of pipeline/load_fda_compliance.py.")
    stats: dict = {"files": {k: p.name for k, p in files.items()}}
    specs = {
        "inspections": ("pc_inspection.csv",
                        ["inspection_id", "fei_number", "legal_name", "fiscal_year", "end_date", "classification",
                         "project_area", "product_type", "posted_citations"],
                        lambda g: [g("Inspection ID"), fei(g("FEI Number")), g("Legal Name"), g("Fiscal Year"),
                                   to_date(g("Inspection End Date")), g("Classification"), g("Project Area"),
                                   g("Product Type"), str(g("Posted Citations")).strip().lower() == "yes"]),
        "citations": ("pc_inspection_citation.csv",
                      ["inspection_id", "fei_number", "end_date", "program_area", "cfr", "short_description"],
                      lambda g: [g("Inspection ID"), fei(g("FEI Number")), to_date(g("Inspection End Date")),
                                 g("Program Area"), g("Act/CFR Number"), g("Short Description")]),
        "actions": ("pc_compliance_action.csv",
                    ["case_id", "fei_number", "legal_name", "action_date", "action_type", "product_type"],
                    lambda g: [g("Case/Injunction ID"), fei(g("FEI Number")), g("Legal Name"),
                               to_date(g("Action Taken Date")), g("Action Type"), g("Product Type")]),
    }
    for kind, (name, cols, build) in specs.items():
        _, heads, it, wb = read_rows(files[kind])
        idx = {h: i for i, h in enumerate(heads)}
        read = kept = 0
        seen = set()
        types = Counter()
        with open(site / name, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for row in it:
                if not row or all(v in (None, "") for v in row):
                    continue
                read += 1

                def g(h, row=row):
                    i = idx.get(h)
                    v = row[i] if i is not None and i < len(row) else ""
                    v = "" if v is None else v
                    return v if isinstance(v, (datetime, date)) else str(v).strip()

                if fei(g("FEI Number")) not in feis:
                    continue
                rec = build(g)
                key = tuple(rec)
                if key in seen:
                    continue
                seen.add(key)
                w.writerow(rec)
                kept += 1
                types[rec[cols.index("product_type")] if "product_type" in cols else rec[cols.index("program_area")]] += 1
        wb.close()
        stats[kind] = {"read": read, "kept": kept, "by_type": types.most_common(6)}
    lines = ["FDA inspections, citations and compliance actions (FDA Data Dashboard)"]
    for kind in KINDS:
        s = stats[kind]
        lines.append(f"{kind}: {s['read']:,} rows read from {stats['files'][kind]}, {s['kept']:,} kept for "
                     f"orthopedic sites. Top types: " + ", ".join(f"{t or 'blank'} {n:,}" for t, n in s["by_type"]))
    lines += ["", "Kept rows are those whose FEI number matches a site in pc_establishment.csv."]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "FDA_Compliance_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.ini")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    d = Path(cfg.get("fda_dashboard", "DIR", "../FDA Data Dashboard"))
    folder = d if d.is_absolute() else (cfg.project_dir / d).resolve()
    load(folder, cfg.site_data_dir, cfg.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
