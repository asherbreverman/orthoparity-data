"""Build the procedure view from CMS Medicare Inpatient and Outpatient Hospitals by Provider and Service.

Sources (public, data.cms.gov; file names and expected counts in config.ini [medicare]):
  Inpatient:  one row per hospital and DRG, Original Medicare Part A discharges at IPPS hospitals.
  Outpatient: one row per hospital and APC, Original Medicare Part B outpatient services.

Reference files (published with the code, edited by hand):
  reference/procedure_families.csv     procedure families, the DRGs in each, and whether a supply range applies
  reference/drg_titles.csv             official MS-DRG titles (CMS Definitions Manual, Appendix A), sentence case
  reference/procedure_devices.csv      FDA product codes typically used in each family, with their role
  reference/procedure_outpatient.csv   outpatient status and APC of key procedure codes, with sources
  reference/supply_cost_evidence.csv   published studies of implant cost as a share of payment

Also reads (from the last export): outputs/site_data/pc_portfolio_510k.csv, pc_vendors.csv, pc_product_codes.csv

Outputs (outputs/site_data/):
  pc_procedures.csv           one row per family: volume, the three-way payment split, the supply-cost range
  pc_procedure_drg.csv        one row per DRG in a family, with the spread of hospital averages
  pc_procedure_apc.csv        national totals for each musculoskeletal APC
  pc_procedure_outpatient.csv key procedure codes and their outpatient status, joined to the APC totals
  pc_procedure_devices.csv    device categories per family, with 510(k) and active-vendor counts
  pc_supply_evidence.csv      the published evidence behind the supply-cost range
  outputs/Medicare_Report.txt  validation report

Payment fields:
  Medicare pays             inpatient Avg_Mdcr_Pymt_Amt, outpatient Avg_Mdcr_Pymt_Amt
  Total payment             inpatient Avg_Tot_Pymt_Amt, outpatient Avg_Mdcr_Alowd_Amt. CMS: Medicare's payment plus
                            the patient's deductible and coinsurance plus any third-party payment.
  Patient and other payers  total minus Medicare. It shows what the hospital bills; collections can run lower.
Charges (Avg_Submtd_Cvrd_Chrg, Avg_Tot_Sbmtd_Chrgs) are never read: list prices, not payments.
No hospital names or identifiers are written. National figures only.

Usage:  python orthoparity.py load-medicare-hospitals
"""
from __future__ import annotations

import csv
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from predicate_chain.config import load_config

IP_COLS = ["Rndrng_Prvdr_CCN", "DRG_Cd", "DRG_Desc", "Tot_Dschrgs", "Avg_Tot_Pymt_Amt", "Avg_Mdcr_Pymt_Amt"]
OP_COLS = ["Rndrng_Prvdr_CCN", "APC_Cd", "APC_Desc", "Bene_Cnt", "CAPC_Srvcs", "Avg_Mdcr_Alowd_Amt",
           "Avg_Mdcr_Pymt_Amt"]
ROLES = ("implant", "biologic", "cement and accessories", "enabling technology", "instrument")


class MedicareError(Exception):
    """A check failed. The load stops and says why."""


def num(value: str, where: str) -> float:
    s = (value or "").replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        raise MedicareError(f"{where}: '{value}' is not a number") from None


def read_rows(path: Path, need: list[str]) -> tuple[list[dict], str]:
    if not path.exists():
        raise MedicareError(f"File not found: {path}. Download it from data.cms.gov or fix the path in config.ini.")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            with open(path, newline="", encoding=enc) as fh:
                rd = csv.DictReader(fh)
                missing = [c for c in need if c not in (rd.fieldnames or [])]
                if missing:
                    raise MedicareError(f"{path.name} is missing columns: {', '.join(missing)}")
                return list(rd), enc
        except UnicodeDecodeError:
            continue
    raise MedicareError(f"{path.name}: can't read the text encoding")


def in_path(cfg, key: str) -> Path:
    p = Path(cfg.get("medicare", key))
    return p if p.is_absolute() else (cfg.project_dir / p).resolve()


def read_ref(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def wavg(pairs: list[tuple[float, float]]) -> float:
    """Average weighted by case count: pairs of (cases, average)."""
    n = sum(c for c, _ in pairs)
    return sum(c * a for c, a in pairs) / n if n else 0.0


def quartiles(values: list[float]) -> tuple[float, float, float]:
    if len(values) < 2:
        v = values[0] if values else 0.0
        return v, v, v
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[1], q[2]


def write(path: Path, cols: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def r0(x: float) -> int:
    return int(round(x))


KEEP_UPPER = {"MCC", "CC", "CC/MCC", "O.R."}


def sentence_case(title: str) -> str:
    """CMS writes DRG titles in capitals. Keep MCC, CC and O.R. in capitals and lower-case the rest."""
    out = []
    for i, w in enumerate(title.strip().lower().split()):
        core = w.rstrip(",")
        tail = w[len(core):]
        if core.upper() in KEEP_UPPER:
            core = core.upper()
        elif i == 0:
            core = core.capitalize()
        out.append(core + tail)
    return " ".join(out)


def build(cfg) -> list[str]:
    """Run every check and write the outputs. Returns the report lines. Raises MedicareError on a failed check."""
    g = lambda k: cfg.get("medicare", k)  # noqa: E731
    year = g("DATA_YEAR")
    supmin = int(g("SUPPRESSION_MIN") or 11)
    spread_min = int(g("SPREAD_MIN_HOSPITALS") or 5)
    shares = [float(s) for s in g("SUPPLY_SHARES").split(",") if s.strip()]
    if not shares or any(not 0 < s < 1 for s in shares):
        raise MedicareError("SUPPLY_SHARES in config.ini must be fractions between 0 and 1, for example 0.30, 0.40")
    ref = cfg.project_dir / "reference"
    site = cfg.site_data_dir
    report: list[str] = []
    problems: list[str] = []

    # ---------------- reference files
    fams = sorted(read_ref(ref / "procedure_families.csv"), key=lambda r: int(r["sort_order"]))
    fam_ids = [f["family_id"] for f in fams]
    if len(set(fam_ids)) != len(fam_ids):
        raise MedicareError("procedure_families.csv repeats a family_id")
    drg_fam: dict[str, str] = {}
    for f in fams:
        for d in f["drgs"].split("|"):
            d = d.strip().zfill(3)
            if d in drg_fam:
                raise MedicareError(f"DRG {d} is in two families: {drg_fam[d]} and {f['family_id']}")
            drg_fam[d] = f["family_id"]
    for f in fams:
        f["drgs"] = "|".join(sorted((d.strip() for d in f["drgs"].split("|")), key=int))
        if (f.get("supply_range") or "yes").strip().lower() not in ("yes", "no"):
            raise MedicareError(f"supply_range for {f['family_id']} must be yes or no")
    titles: dict[str, str] = {}
    if (ref / "drg_titles.csv").exists():
        titles = {r["drg"].strip().zfill(3): r["title"].strip() for r in read_ref(ref / "drg_titles.csv")}
    devices = read_ref(ref / "procedure_devices.csv")
    outpatient = read_ref(ref / "procedure_outpatient.csv")
    evidence = read_ref(ref / "supply_cost_evidence.csv")
    for r in devices + outpatient:
        if r["family_id"] not in fam_ids:
            raise MedicareError(f"Unknown family_id '{r['family_id']}' in a reference file")
    bad_roles = {r["role"] for r in devices} - set(ROLES)
    if bad_roles:
        raise MedicareError(f"Unknown role in procedure_devices.csv: {', '.join(sorted(bad_roles))}")
    dup = [k for k, n in Counter((r["family_id"], r["product_code"]) for r in devices).items() if n > 1]
    if dup:
        raise MedicareError(f"procedure_devices.csv lists a product code twice in one family: {dup[0]}")

    # ---------------- inpatient
    ip, enc = read_rows(in_path(cfg, "IP_FILE"), IP_COLS)
    hosp = {r["Rndrng_Prvdr_CCN"] for r in ip}
    report += [f"Inpatient file: {len(ip):,} rows, {len(hosp):,} hospitals ({enc})"]
    for key, got in (("IP_EXPECTED_ROWS", len(ip)), ("IP_EXPECTED_HOSPITALS", len(hosp))):
        if g(key) and int(g(key)) != got:
            raise MedicareError(f"Inpatient {key} is {g(key)} in config.ini but the file has {got:,}")
    by_drg: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    desc: dict[str, Counter] = defaultdict(Counter)
    below, tot_lt_med = 0, 0
    for i, r in enumerate(ip, start=2):
        d = r["DRG_Cd"].strip().zfill(3)
        n = num(r["Tot_Dschrgs"], f"Inpatient row {i}, Tot_Dschrgs")
        tot = num(r["Avg_Tot_Pymt_Amt"], f"Inpatient row {i}, Avg_Tot_Pymt_Amt")
        med = num(r["Avg_Mdcr_Pymt_Amt"], f"Inpatient row {i}, Avg_Mdcr_Pymt_Amt")
        below += n < supmin
        tot_lt_med += tot + 0.005 < med
        desc[d][r["DRG_Desc"].strip()] += 1
        if d in drg_fam:
            by_drg[d].append((r["Rndrng_Prvdr_CCN"], n, med, tot))
    report.append(f"Inpatient rows under the {supmin}-discharge suppression floor: {below} (expected 0)")
    report.append(f"Inpatient rows where total payment is below Medicare's payment: {tot_lt_med}")
    if below:
        problems.append(f"{below} inpatient rows fall under the suppression floor")
    missing = sorted(set(drg_fam) - set(by_drg))
    for d in missing:
        report.append(f"DRG {d} ({drg_fam[d]}): NOT FOUND. Reason: no hospital reported {supmin} or more "
                      f"discharges, so CMS suppressed every row")

    for d in sorted(drg_fam):
        cms = desc[d].most_common(1)[0][0] if desc[d] else ""
        if d in titles and cms and not titles[d].lower().startswith(cms.lower().rstrip(" .")[:60]):
            problems.append(f"DRG {d}: the CMS file calls it '{cms}', which doesn't match the title in drg_titles.csv")
        if d not in titles:
            report.append(f"DRG {d}: no official title in drg_titles.csv, so the CMS file's description is used")

    # ---------------- outpatient
    op, enc = read_rows(in_path(cfg, "OP_FILE"), OP_COLS)
    ohosp = {r["Rndrng_Prvdr_CCN"] for r in op}
    report.append(f"Outpatient file: {len(op):,} rows, {len(ohosp):,} hospitals ({enc})")
    for key, got in (("OP_EXPECTED_ROWS", len(op)), ("OP_EXPECTED_HOSPITALS", len(ohosp))):
        if g(key) and int(g(key)) != got:
            raise MedicareError(f"Outpatient {key} is {g(key)} in config.ini but the file has {got:,}")
    rx = re.compile(g("OP_APC_REGEX") or "musculoskeletal procedures", re.I)
    by_apc: dict[str, list] = defaultdict(list)
    apc_desc: dict[str, str] = {}
    obelow, olt, bene_hidden = 0, 0, 0
    suppressed: Counter = Counter()
    for i, r in enumerate(op, start=2):
        if not rx.search(r["APC_Desc"]):
            continue
        a = r["APC_Cd"].strip()
        if not r["CAPC_Srvcs"].strip():
            # CMS keeps suppressed rows (fewer than 11 services) in the file with every count and amount blank
            if any(r[k].strip() for k in ("Avg_Mdcr_Alowd_Amt", "Avg_Mdcr_Pymt_Amt")):
                raise MedicareError(f"Outpatient row {i}: blank CAPC_Srvcs but payment amounts present")
            suppressed[a] += 1
            continue
        s = num(r["CAPC_Srvcs"], f"Outpatient row {i}, CAPC_Srvcs")
        if r["Bene_Cnt"].strip():
            b = num(r["Bene_Cnt"], f"Outpatient row {i}, Bene_Cnt")
        else:
            b = 0.0  # patient count hidden (fewer than 11 patients); services and payments are still reported
            bene_hidden += 1
        allowed = num(r["Avg_Mdcr_Alowd_Amt"], f"Outpatient row {i}, Avg_Mdcr_Alowd_Amt")
        med = num(r["Avg_Mdcr_Pymt_Amt"], f"Outpatient row {i}, Avg_Mdcr_Pymt_Amt")
        obelow += s < supmin
        olt += allowed + 0.005 < med
        apc_desc[a] = r["APC_Desc"].strip()
        by_apc[a].append((r["Rndrng_Prvdr_CCN"], s, b, med, allowed))
    report.append(f"Outpatient APCs kept ({rx.pattern}): {', '.join(sorted(by_apc)) or 'none'}")
    report.append(f"Outpatient rows CMS suppressed (blank, fewer than {supmin} services), left out: "
                  f"{sum(suppressed.values()):,} ({', '.join(f'{k} {v:,}' for k, v in sorted(suppressed.items()))})")
    report.append(f"Outpatient rows with the patient count hidden (services and payments kept): {bene_hidden:,}. "
                  "patients_reported is a floor")
    report.append(f"Outpatient rows under the {supmin}-service suppression floor: {obelow} (expected 0)")
    report.append(f"Outpatient rows where total allowed is below Medicare's payment: {olt}")
    if obelow:
        problems.append(f"{obelow} outpatient rows fall under the suppression floor")
    if not by_apc:
        raise MedicareError(f"No outpatient APC matches OP_APC_REGEX '{rx.pattern}'")

    # ---------------- devices: 510(k) and active-vendor counts
    pcodes = {r["product_code"]: r for r in read_ref(site / "pc_product_codes.csv")}
    vend = {r["vendor_id"]: r for r in read_ref(site / "pc_vendors.csv")}
    port = read_ref(site / "pc_portfolio_510k.csv")
    unknown = sorted({r["product_code"] for r in devices} - set(pcodes))
    if unknown:
        raise MedicareError(f"Product codes in procedure_devices.csv not in pc_product_codes.csv: {', '.join(unknown)}")
    data_end = max(r["decision_date"] for r in port if r["decision_date"])
    end = date.fromisoformat(data_end)
    yrs = int(g("ACTIVE_VENDOR_YEARS") or 5)
    try:
        start = end.replace(year=end.year - yrs)
    except ValueError:  # 29 February
        start = end.replace(year=end.year - yrs, day=28)
    start_s = start.isoformat()
    owner = lambda v: (vend.get(v) or {}).get("rolls_up_to") or v  # noqa: E731
    n_all, n_recent, v_recent = Counter(), Counter(), defaultdict(set)
    for r in port:
        c = r["product_code"]
        n_all[c] += 1
        if r["decision_date"] > start_s:
            n_recent[c] += 1
            v_recent[c].add(owner(r["vendor_id"]))
    report.append(f"Active vendors: owners with a 510(k) decided after {start_s} (510(k) data ends {data_end})")

    # ---------------- outputs
    fam_rows, drg_rows = [], []
    for f in fams:
        fid = f["family_id"]
        drgs = [d.strip().zfill(3) for d in f["drgs"].split("|")]
        rows = [x for d in drgs for x in by_drg.get(d, [])]
        cases = sum(x[1] for x in rows)
        med = wavg([(x[1], x[2]) for x in rows])
        tot = wavg([(x[1], x[3]) for x in rows])
        supply = (f.get("supply_range") or "yes").strip().lower() == "yes"
        supply_note = "" if supply else (
            "NOT FOUND. Reason: none of the published studies in the Evidence list measures implant cost for these "
            "DRGs, so OrthoParity shows no supply range for this procedure.")
        fam_rows.append([fid, f["sort_order"], f["name"], f["description"], "|".join(d.lstrip("0") for d in drgs),
                         f["flagship"], year, r0(cases), len({x[0] for x in rows}), r0(med), r0(tot - med), r0(tot),
                         round((tot - med) / tot, 4) if tot else "",
                         *[r0(med * s) if supply else "" for s in shares],
                         *[r0(tot * s) if supply else "" for s in shares], supply_note])
        for d in drgs:
            xs = by_drg.get(d, [])
            title = titles.get(d) or (sentence_case(desc[d].most_common(1)[0][0]) if desc[d] else "NOT FOUND")
            if not xs:
                drg_rows.append([fid, d.lstrip("0"), title, 0, 0, "", "", "", "", "", "", "",
                                 f"Every hospital row suppressed by CMS (fewer than {supmin} discharges)", ""])
                continue
            n = sum(x[1] for x in xs)
            m, t = wavg([(x[1], x[2]) for x in xs]), wavg([(x[1], x[3]) for x in xs])
            if len(xs) < spread_min:
                q = ("", "", "")
                spread_note = (f"NOT FOUND. Reason: only {len(xs)} hospital{'s' if len(xs) != 1 else ''} reported this "
                               f"DRG (CMS hides hospitals with fewer than {supmin} discharges), too few to show a spread. "
                               f"OrthoParity needs at least {spread_min}.")
            else:
                q = tuple(r0(v) for v in quartiles(sorted(x[2] for x in xs)))
                spread_note = ""
            drg_rows.append([fid, d.lstrip("0"), title, r0(n), len(xs), r0(m), r0(t - m), r0(t),
                             round(n / cases, 4) if cases else "", *q, "", spread_note])
    pct = [f"{int(round(s * 100))}" for s in shares]
    write(site / "pc_procedures.csv",
          ["family_id", "sort_order", "name", "description", "drgs", "flagship", "data_year", "discharges",
           "hospitals", "medicare_pays", "patient_other_pays", "total_payment", "patient_other_share",
           *[f"supply_medicare_{p}" for p in pct], *[f"supply_total_{p}" for p in pct], "supply_note"], fam_rows)
    write(site / "pc_procedure_drg.csv",
          ["family_id", "drg", "drg_desc", "discharges", "hospitals", "medicare_pays", "patient_other_pays",
           "total_payment", "share_of_family", "hospital_medicare_p25", "hospital_medicare_median",
           "hospital_medicare_p75", "note", "spread_note"], drg_rows)

    apc_rows = []
    for a in sorted(by_apc):
        xs = by_apc[a]
        s = sum(x[1] for x in xs)
        m, t = wavg([(x[1], x[3]) for x in xs]), wavg([(x[1], x[4]) for x in xs])
        apc_rows.append([a, apc_desc[a], year, r0(s), r0(sum(x[2] for x in xs)), len(xs), r0(m), r0(t - m), r0(t)])
    write(site / "pc_procedure_apc.csv",
          ["apc", "apc_desc", "data_year", "services", "patients_reported", "hospitals", "medicare_pays", "patient_other_pays",
           "total_allowed"], apc_rows)
    apcs = {r[0]: r for r in apc_rows}
    op_rows = []
    for r in outpatient:
        a = r["apc"].strip()
        if a and a != "NOT FOUND" and a not in apcs:
            problems.append(f"APC {a} for CPT {r['cpt']} is not in the outpatient file")
        x = apcs.get(a)
        op_rows.append([r["family_id"], r["cpt"], r["procedure"], r["outpatient_status_2024"], a or "",
                        x[3] if x else "", x[6] if x else "", x[7] if x else "", x[8] if x else "",
                        r["source"], r["source_url"]])
    write(site / "pc_procedure_outpatient.csv",
          ["family_id", "cpt", "procedure", "outpatient_status", "apc", "apc_services", "apc_medicare_pays",
           "apc_patient_other_pays", "apc_total_allowed", "source", "source_url"], op_rows)

    dev_rows = []
    order = {fid: i for i, fid in enumerate(fam_ids)}
    for r in sorted(devices, key=lambda r: (order[r["family_id"]], ROLES.index(r["role"]), r["product_code"])):
        c = r["product_code"]
        p = pcodes[c]
        dev_rows.append([r["family_id"], r["role"], c, p.get("plain_name") or p.get("fda_name"), p.get("fda_name"),
                         n_all[c], n_recent[c], len(v_recent[c]), r["status"]])
    write(site / "pc_procedure_devices.csv",
          ["family_id", "role", "product_code", "plain_name", "fda_name", "clearances_all", "clearances_recent",
           "active_vendors", "status"], dev_rows)
    write(site / "pc_supply_evidence.csv", list(evidence[0].keys()) if evidence else ["source"],
          [list(e.values()) for e in evidence])

    # ---------------- reconciliation
    fam_cases = sum(r[7] for r in fam_rows)
    drg_cases = sum(r[3] for r in drg_rows)
    if fam_cases != drg_cases:
        problems.append(f"Family discharges ({fam_cases:,}) differ from the DRG rows ({drg_cases:,})")
    report += ["", f"Procedure families ({year}):"]
    for r in fam_rows:
        report.append(f"  {r[2]}: {r[7]:,} discharges at {r[8]:,} hospitals; Medicare pays ${r[9]:,}, patient and "
                      f"other payers ${r[10]:,}, total ${r[11]:,}")
    report.append(f"  All families: {fam_cases:,} discharges")
    report += ["", "Musculoskeletal APCs:"]
    for r in apc_rows:
        report.append(f"  {r[0]} {r[1]}: {r[3]:,} services; Medicare pays ${r[6]:,}, patient and other payers "
                      f"${r[7]:,}, total allowed ${r[8]:,}")
    thin = [f"{r[1]} ({r[4]})" for r in drg_rows if r[13]]
    report += ["", f"DRGs with fewer than {spread_min} hospitals (no hospital spread shown): " + (", ".join(thin) or "none")]
    if (ref / "drg_titles.csv").exists():
        surg = {r["drg"].strip().zfill(3) for r in read_ref(ref / "drg_titles.csv") if r.get("type") == "surgical"}
        left = sorted(d for d in surg - set(drg_fam) if d in desc)
        absent = sorted(d for d in surg - set(desc))
        report.append("Surgical DRGs in drg_titles.csv with hospital rows but in no family: " + (", ".join(left) or "none"))
        report.append("Surgical DRGs in drg_titles.csv with no hospital row in the file (every row suppressed or none "
                      "billed): " + (", ".join(absent) or "none"))
    report += ["", f"Device links: {len(dev_rows)} across {len({r[2] for r in dev_rows})} product codes",
               f"Outpatient code rows: {len(op_rows)} ({sum(r[4] == 'NOT FOUND' for r in op_rows)} with APC NOT FOUND)",
               f"Evidence rows: {len(evidence)}", "",
               "Problems: " + ("; ".join(problems) if problems else "none")]
    if problems:
        raise MedicareError("Validation failed: " + "; ".join(problems))
    return report


def main(argv=None) -> int:
    cfg = load_config()
    stamp = f"Medicare report, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC"
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        lines = build(cfg)
    except MedicareError as e:
        msg = f"{stamp}\n\nSTOPPED: {e}\n"
        (cfg.output_dir / "Medicare_Report.txt").write_text(msg, encoding="utf-8")
        print(msg)
        return 1
    text = "\n".join([stamp, ""] + lines) + "\n"
    (cfg.output_dir / "Medicare_Report.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"Wrote 6 CSVs to {cfg.site_data_dir} and {cfg.output_dir / 'Medicare_Report.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
