"""Phase A1: index the FDA GUDID full release (211 XML parts) for Benchmark a Vendor.

For every device record it keeps the fields needed to link an Open Payments device ID (PDI) to a brand,
company, product code and 510(k) number. Each XML part is parsed once into three small gzip CSV files under
data/gudid_stage (resumable: finished parts are skipped). Then everything loads into data/payments.duckdb:

  gudid_devices      one row per device record (primary DI)
  gudid_identifiers  every device identifier (primary, package, previous...) -> primary DI
  gudid_submissions  primary DI -> premarket submission number (K, P, DEN...) and supplement

Usage:  python orthoparity.py index-gudid   (then load-open-payments)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import os
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from predicate_chain.config import load_config
from predicate_chain.paycommon import (PaySettings, Progress, StopRequested, check_stop, connect_duck,
                                       keep_awake, mark_step, step_done)

NS = "{http://www.fda.gov/cdrh/gudid}"
DEVICE_COLS = ["primary_di", "issuing_agency", "brand", "version_model", "catalog_number", "company", "duns",
               "description", "record_status", "public_version", "publish_date", "distribution_status",
               "distribution_end", "device_count", "kit", "combination", "single_use", "rx", "otc",
               "product_codes", "product_code_names", "gmdn_code", "gmdn_name", "implantable", "premarket_exempt",
               "submissions"]
IDENT_COLS = ["di", "di_type", "issuing_agency", "pkg_quantity", "contains_di", "pkg_status", "primary_di"]
SUB_COLS = ["primary_di", "submission_number", "supplement_number"]


def _t(elem, tag: str) -> str:
    e = elem.find(NS + tag)
    if e is None or e.text is None:
        return ""
    return " ".join(e.text.split())


def parse_device(dev) -> tuple[list, list[list], list[list]]:
    idents, primary, agency = [], "", ""
    box = dev.find(NS + "identifiers")
    for i in (box if box is not None else []):
        di, typ = _t(i, "deviceId"), _t(i, "deviceIdType")
        idents.append([di, typ, _t(i, "deviceIdIssuingAgency"), _t(i, "pkgQuantity"), _t(i, "containsDINumber"),
                       _t(i, "pkgStatus")])
        if typ == "Primary" and not primary:
            primary, agency = di, _t(i, "deviceIdIssuingAgency")
    codes, code_names = [], []
    box = dev.find(NS + "productCodes")
    for pc in (box if box is not None else []):
        c = _t(pc, "productCode")
        if c:
            codes.append(c)
            code_names.append(_t(pc, "productCodeName"))
    subs = []
    box = dev.find(NS + "premarketSubmissions")
    for s in (box if box is not None else []):
        n = _t(s, "submissionNumber").upper()
        if n:
            subs.append([primary, n, _t(s, "supplementNumber")])
    gm_code = gm_name = implantable = ""
    box = dev.find(NS + "gmdnTerms")
    if box is not None:
        g = box.find(NS + "gmdn")
        if g is not None:
            gm_code, gm_name, implantable = _t(g, "gmdnCode"), _t(g, "gmdnPTName"), _t(g, "implantable")
    row = [primary, agency, _t(dev, "brandName"), _t(dev, "versionModelNumber"), _t(dev, "catalogNumber"),
           _t(dev, "companyName"), _t(dev, "dunsNumber"), _t(dev, "deviceDescription")[:300],
           _t(dev, "deviceRecordStatus"), _t(dev, "publicVersionNumber"), _t(dev, "devicePublishDate"),
           _t(dev, "deviceCommDistributionStatus"), _t(dev, "deviceCommDistributionEndDate"),
           _t(dev, "deviceCount"), _t(dev, "deviceKit"), _t(dev, "deviceCombinationProduct"),
           _t(dev, "singleUse"), _t(dev, "rx"), _t(dev, "otc"), "|".join(codes), "|".join(code_names),
           gm_code, gm_name, implantable, _t(dev, "premarketExempt"),
           "|".join(sorted({s[1] for s in subs}))]
    return row, [r + [primary] for r in idents], subs


def parse_part(xml_path: str, stage_dir: str) -> tuple[str, int, int]:
    """Parse one XML part into three gzip CSVs. Returns (part name, devices, header record count)."""
    name = Path(xml_path).stem
    out = Path(stage_dir)
    done = out / f"{name}.done"
    if done.exists():
        n, header = done.read_text(encoding="utf-8").split(",")
        return name, int(n), int(header)
    files = {k: out / f"{name}.{k}.csv.gz" for k in ("devices", "identifiers", "submissions")}
    tmp = {k: v.with_suffix(".tmp") for k, v in files.items()}
    n, header_total = 0, -1
    with gzip.open(tmp["devices"], "wt", newline="", encoding="utf-8") as fd, \
         gzip.open(tmp["identifiers"], "wt", newline="", encoding="utf-8") as fi, \
         gzip.open(tmp["submissions"], "wt", newline="", encoding="utf-8") as fs:
        wd, wi, ws = csv.writer(fd), csv.writer(fi), csv.writer(fs)
        wd.writerow(DEVICE_COLS); wi.writerow(IDENT_COLS); ws.writerow(SUB_COLS)
        context = ET.iterparse(xml_path, events=("start", "end"))
        root = None
        for event, elem in context:
            if root is None and event == "start":
                root = elem
            if event != "end":
                continue
            if elem.tag == NS + "numberRecordsDatabase" and elem.text:
                header_total = int(elem.text.strip())
            elif elem.tag == NS + "device":
                row, idents, subs = parse_device(elem)
                wd.writerow(row); wi.writerows(idents); ws.writerows(subs)
                n += 1
                elem.clear()
                if n % 2000 == 0 and root is not None:
                    root.clear()
    for k in files:
        tmp[k].replace(files[k])
    done.write_text(f"{n},{header_total}", encoding="utf-8")
    return name, n, header_total


def load_into_duckdb(ps: PaySettings, con) -> dict:
    stage = ps.stage.as_posix()
    opts = "header=true, all_varchar=true, quote='\"', escape='\"'"
    con.execute(f"CREATE OR REPLACE TABLE gudid_devices AS SELECT * FROM read_csv('{stage}/*.devices.csv.gz', {opts})")
    con.execute(f"CREATE OR REPLACE TABLE gudid_identifiers AS SELECT * FROM read_csv('{stage}/*.identifiers.csv.gz', {opts})")
    con.execute(f"CREATE OR REPLACE TABLE gudid_submissions AS SELECT DISTINCT * FROM read_csv('{stage}/*.submissions.csv.gz', {opts})")
    con.execute("""CREATE OR REPLACE TABLE gudid_product_codes AS
                   SELECT DISTINCT primary_di, unnest(string_split(product_codes, '|')) AS product_code
                   FROM gudid_devices WHERE product_codes <> ''""")
    q = lambda sql: con.execute(sql).fetchone()[0]
    return {
        "devices": q("SELECT count(*) FROM gudid_devices"),
        "distinct_primary_di": q("SELECT count(DISTINCT primary_di) FROM gudid_devices"),
        "blank_primary_di": q("SELECT count(*) FROM gudid_devices WHERE primary_di IS NULL OR primary_di = ''"),
        "identifiers": q("SELECT count(*) FROM gudid_identifiers"),
        "submissions": q("SELECT count(*) FROM gudid_submissions"),
        "devices_with_510k": q("SELECT count(DISTINCT primary_di) FROM gudid_submissions WHERE submission_number LIKE 'K%'"),
        "distinct_510k": q("SELECT count(DISTINCT submission_number) FROM gudid_submissions WHERE submission_number LIKE 'K%'"),
        "product_code_links": q("SELECT count(*) FROM gudid_product_codes"),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="alternative config.ini (tests)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    if step_done(con, "A1_gudid"):
        print("GUDID index already built (step A1_gudid). Delete that row from run_steps to rebuild.")
        return 0
    files = ps.gudid_files()
    if len(files) != ps.gudid_parts:
        print(f"Expected {ps.gudid_parts} GUDID parts in {ps.gudid_dir}, found {len(files)}. "
              "Check GUDID_DIR and GUDID_PARTS in config.ini.")
        return 1
    ps.stage.mkdir(parents=True, exist_ok=True)
    prog = Progress(cfg, "payments_phase_a", "OrthoParity: Phase A1, GUDID index")
    t0 = time.monotonic()
    keep_awake(True)
    results = {}
    try:
        already = [f for f in files if (ps.stage / f"{f.stem}.done").exists()]
        todo = [f for f in files if f not in already]
        for f in already:
            results[f.stem] = parse_part(str(f), str(ps.stage))
        prog.write("Parsing GUDID XML parts", len(results), len(files), "resuming", count_session=False)
        print(f"GUDID: {len(already)} parts already done, {len(todo)} to parse with {ps.gudid_workers} workers.")
        with ProcessPoolExecutor(max_workers=ps.gudid_workers) as pool:
            futs = {pool.submit(parse_part, str(f), str(ps.stage)): f for f in todo}
            for fut in as_completed(futs):
                name, n, header = fut.result()
                results[name] = (name, n, header)
                prog.write("Parsing GUDID XML parts", len(results), len(files), f"{name}: {n:,} devices")
                print(f"  {len(results)}/{len(files)}  {name}: {n:,} devices")
                try:
                    check_stop(cfg)
                except StopRequested:
                    for other in futs:
                        other.cancel()
                    raise
        prog.write("Loading GUDID into DuckDB", len(files), len(files), "loading", count_session=False)
        stats = load_into_duckdb(ps, con)
    except StopRequested as e:
        print(f"Stopped: {e}. Run the same step again to resume.")
        return 2
    finally:
        keep_awake(False)
    parsed = sum(r[1] for r in results.values())
    headers = {r[2] for r in results.values() if r[2] >= 0}
    stats["parsed_records"] = parsed
    stats["header_records"] = ",".join(str(h) for h in sorted(headers))
    stats["expected_records"] = ps.gudid_expected
    ok = parsed == ps.gudid_expected
    mark_step(con, "A1_gudid", stats["devices"], time.monotonic() - t0,
              "; ".join(f"{k}={v}" for k, v in stats.items()))
    report = cfg.output_dir / "PhaseA1_GUDID_Report.txt"
    lines = ["OrthoParity: Phase A1, GUDID index", ""]
    lines += [f"{k}: {v:,}" if isinstance(v, int) else f"{k}: {v}" for k, v in stats.items()]
    lines += ["", "Record count matches the release header." if ok else
              f"NOTE: parsed {parsed:,} records, config expects {ps.gudid_expected:,}. Tell Claude."]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
