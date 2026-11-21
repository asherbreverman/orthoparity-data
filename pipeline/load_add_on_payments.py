"""Load Medicare add-on payments for orthopedic technologies: inpatient NTAP and outpatient device pass-through.

Sources (CMS, public):
  - FY 2027 IPPS final rule, MAC Implementation File 8 (ZIP): technologies newly approved for, continuing, and no
    longer receiving the new technology add-on payment (NTAP), with the maximum add-on per case and the ICD-10
    codes that identify eligible cases.
  - CY 2027 OPPS final rule addenda (ZIP): Addendum B lists every HCPCS code; status indicator H marks a device
    category with transitional pass-through payment, and the expiration column flags categories that expire
    during the year.
Save both ZIP files, unopened, in the folder named by [cms_add_on] DIR in config.ini.

CMS names technologies, not 510(k) numbers. The human-reviewed file reference/add_on_payments.csv says which
orthopedic technologies count, who makes them, and which FDA numbers they map to (with an FDA source link). This
step checks every row of that file against the CMS files and stops if a name, status, code or expiration flag does
not match, then copies the CMS figures (maximum add-on, ICD-10 codes, APC) into the output. It also lists every
CMS technology and pass-through code the reference file leaves out, so a reviewer can see what was skipped.

Outputs: outputs/site_data/pc_add_on_payment.csv, pc_add_on_payment_510k.csv and outputs/Add_on_Payments_Report.txt

Usage:  python orthoparity.py load-add-on-payments
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

CMS_SOURCE = {
    "NTAP": "https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/"
            "fy-2027-ipps-final-rule-home-page",
    "TPT": "https://www.cms.gov/medicare/payment/prospective-payment-systems/hospital-outpatient/"
           "regulations-notices/cms-1850-fc",
}
NTAP_SHEETS = {"new": "new ntap", "continued": "continued ntap", "discontinued": "discontinued ntap"}
TPT_STATUS = {"new", "continuing"}
TPT_ENDS = {"during CY 2027", "after CY 2027"}


def norm(s: str) -> str:
    """Compare names without trademark symbols, case or spacing."""
    s = re.sub(r"[®™©�]", "", str(s or ""))
    return " ".join(s.lower().split())


def money(v) -> str:
    s = str(v or "").replace("$", "").replace(",", "").replace('"', "").strip()
    try:
        return f"{float(s):.2f}"
    except ValueError:
        return ""


def find_zip(folder: Path, pattern: str) -> Path:
    hits = sorted(p for p in folder.glob("*.zip") if re.search(pattern, p.name, re.I))
    if not hits:
        raise SystemExit(f"No ZIP matching '{pattern}' in {folder}. See pipeline/load_add_on_payments.py.")
    return hits[-1]


def read_file8(path: Path) -> dict:
    """Return {status: {normalized name: row}} from MAC Implementation File 8."""
    from openpyxl import load_workbook
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(".xlsx"))
        wb = load_workbook(io.BytesIO(z.read(name)), read_only=True, data_only=True)
    out: dict = {k: {} for k in NTAP_SHEETS}
    for ws in wb.worksheets:
        title = ws.title.lower()
        status = next((k for k, v in NTAP_SHEETS.items() if title.startswith(v)), None)
        if not status:
            continue
        rows = list(ws.iter_rows(values_only=True))
        h = next(i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Technology")
        for r in rows[h + 1:]:
            if not r or not r[0] or str(r[0]).startswith("*"):
                continue
            out[status][norm(r[0])] = {"technology": str(r[0]).strip(), "max_payment": money(r[1]),
                                       "codes": " ".join(str(r[2] or "").split()),
                                       "pathway": str(r[3] or "").strip()}
    wb.close()
    return out


def read_addendum_b(path: Path) -> dict:
    """Return {HCPCS: row} for pass-through device codes (status indicator H) in OPPS Addendum B."""
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if re.search(r"addendum b[^/]*\.csv$", n, re.I))
        text = z.read(name).decode("latin-1")
    rows = list(csv.reader(io.StringIO(text)))
    h = next(i for i, r in enumerate(rows) if r and r[0].strip().lower() == "hcpcs code")
    idx = {c.strip().lower(): i for i, c in enumerate(rows[h])}
    exp = next(i for c, i in idx.items() if c.startswith("drug and device pass-through expiration"))
    out = {}
    for r in rows[h + 1:]:
        if len(r) > idx["si"] and r[idx["si"]].strip() == "H":
            out[r[0].strip()] = {"descriptor": r[idx["short descriptor"]].strip(), "apc": r[idx["apc"]].strip(),
                                 "expires_this_year": r[exp].strip() == "*"}
    return out


def load(folder: Path, reference: Path, site: Path, out_dir: Path) -> dict:
    file8 = read_file8(find_zip(folder, r"implementation_file_8"))
    addb = read_addendum_b(find_zip(folder, r"opps-addenda"))
    with open(site / "pc_devices.csv", encoding="utf-8-sig", newline="") as fh:
        devices = {r["knumber"]: r for r in csv.DictReader(fh)
                   if str(r.get("in_starting_set", "")).lower() in ("true", "t", "1", "yes")}
    with open(site / "pc_portfolio_510k.csv", encoding="utf-8-sig", newline="") as fh:
        owner = {r["knumber"]: r["vendor_id"] for r in csv.DictReader(fh)}
    with open(reference, encoding="utf-8-sig", newline="") as fh:
        ref = list(csv.DictReader(fh))

    problems, techs, links, used8, usedb = [], [], [], set(), set()
    for r in ref:
        t = dict(r)
        t["cms_source"] = CMS_SOURCE.get(r["program"], "")
        t["max_payment"] = t["cms_codes"] = t["pathway"] = t["apc"] = t["cms_descriptor"] = ""
        if r["program"] == "NTAP":
            hit = file8.get(r["status"], {}).get(norm(r["technology"]))
            if not hit:
                problems.append(f"{r['tech_id']}: '{r['technology']}' is not in the File 8 '{r['status']}' list")
                continue
            used8.add((r["status"], norm(r["technology"])))
            t.update(max_payment=hit["max_payment"], cms_codes=hit["codes"], pathway=hit["pathway"])
        elif r["program"] == "TPT":
            hit = addb.get(r["hcpcs"])
            if not hit:
                problems.append(f"{r['tech_id']}: {r['hcpcs']} is not a pass-through device code in Addendum B")
                continue
            if r["status"] not in TPT_STATUS or r["pass_through_ends"] not in TPT_ENDS:
                problems.append(f"{r['tech_id']}: unknown status or pass_through_ends")
            if (r["pass_through_ends"] == "during CY 2027") != hit["expires_this_year"]:
                problems.append(f"{r['tech_id']}: {r['hcpcs']} expiration flag in Addendum B does not match "
                                f"'{r['pass_through_ends']}'")
            usedb.add(r["hcpcs"])
            t.update(apc=hit["apc"], cms_descriptor=hit["descriptor"])
        else:
            problems.append(f"{r['tech_id']}: unknown program {r['program']}")
            continue
        for k in [x for x in r["linked_510ks"].split(";") if x]:
            if k not in devices:
                problems.append(f"{r['tech_id']}: {k} is not in the starting set")
                continue
            links.append({"tech_id": r["tech_id"], "knumber": k, "vendor_id": owner.get(k, ""),
                          "product_code": devices[k].get("product_code", "")})
        if not t["vendor_id"]:
            vs = sorted({owner.get(k, "") for k in r["linked_510ks"].split(";") if k} - {""})
            t["vendor_id"] = vs[0] if len(vs) == 1 else ""
        techs.append(t)
    if problems:
        raise SystemExit("Add-on payment reference does not match the CMS files:\n  " + "\n  ".join(problems))

    cols = ["tech_id", "program", "period", "status", "technology", "company", "vendor_id", "fda_numbers", "hcpcs",
            "cms_descriptor", "apc", "max_payment", "cms_codes", "pathway", "effective", "pass_through_ends",
            "cms_source", "fda_source", "note"]
    site.mkdir(parents=True, exist_ok=True)
    with open(site / "pc_add_on_payment.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(techs)
    with open(site / "pc_add_on_payment_510k.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["tech_id", "knumber", "vendor_id", "product_code"])
        w.writeheader()
        w.writerows(links)

    skipped8 = sorted(v["technology"] for s, d in file8.items() for n, v in d.items() if (s, n) not in used8)
    skippedb = sorted(f"{c} ({v['descriptor']})" for c, v in addb.items() if c not in usedb)
    n = {p: sum(1 for t in techs if t["program"] == p) for p in ("NTAP", "TPT")}
    lines = [
        "Medicare add-on payments for orthopedic technologies",
        f"NTAP (FY 2027 IPPS, MAC Implementation File 8): {n['NTAP']} orthopedic technologies "
        f"({sum(1 for t in techs if t['program'] == 'NTAP' and t['status'] == 'new')} new, "
        f"{sum(1 for t in techs if t['program'] == 'NTAP' and t['status'] == 'continued')} continued, "
        f"{sum(1 for t in techs if t['program'] == 'NTAP' and t['status'] == 'discontinued')} discontinued).",
        f"Device pass-through (CY 2027 OPPS Addendum B, status indicator H): {n['TPT']} orthopedic codes.",
        f"Links to starting-set 510(k)s: {len(links)} ({len({l['knumber'] for l in links})} distinct 510(k)s).",
        "",
        f"File 8 technologies not in the reference file ({len(skipped8)}): " + "; ".join(skipped8),
        "",
        f"Pass-through codes not in the reference file ({len(skippedb)}): " + "; ".join(skippedb),
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Add_on_Payments_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return {"techs": len(techs), "links": len(links), "skipped_ntap": len(skipped8), "skipped_tpt": len(skippedb)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.ini")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    d = Path(cfg.get("cms_add_on", "DIR", "../CMS Add-on Payments"))
    folder = d if d.is_absolute() else (cfg.project_dir / d).resolve()
    reference = cfg.project_dir / "reference" / "add_on_payments.csv"
    load(folder, reference, cfg.site_data_dir, cfg.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
