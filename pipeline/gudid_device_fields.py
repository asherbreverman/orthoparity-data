"""Phase 9: read the GUDID device facts the part lookup shows (sterile, MRI safety) from the full release.

index-gudid keeps the fields needed to link devices to companies and FDA numbers. This step reads the same 211 XML
parts once more for two fields it skips: whether the device is packaged sterile (deviceSterile) and its MRI safety
status (MRISafetyStatus). Units per package come from deviceCount, which index-gudid already keeps. Each part is
written to a small gzip CSV under data/gudid_fields_stage (resumable: finished parts are skipped), then loaded into
data/payments.duckdb as gudid_device_fields (one row per primary device ID).

Usage:  python orthoparity.py gudid-device-fields   (after index-gudid, before export-catalog)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from predicate_chain.config import load_config
from predicate_chain.paycommon import (PaySettings, StopRequested, check_stop, connect_duck, keep_awake, mark_step,
                                       step_done)

NS = "{http://www.fda.gov/cdrh/gudid}"
COLS = ["primary_di", "sterile", "sterilize_before_use", "mri_safety"]
STEP = "A1b_gudid_fields"


def _t(elem, tag: str) -> str:
    e = elem.find(NS + tag) if elem is not None else None
    return " ".join(e.text.split()) if e is not None and e.text else ""


def parse_fields(dev) -> list[str]:
    primary = ""
    box = dev.find(NS + "identifiers")
    for i in (box if box is not None else []):
        if _t(i, "deviceIdType") == "Primary":
            primary = _t(i, "deviceId")
            break
    ster = dev.find(NS + "sterilization")
    return [primary, _t(ster, "deviceSterile"), _t(ster, "sterilizationPriorToUse"), _t(dev, "MRISafetyStatus")]


def parse_part(xml_path: str, stage_dir: str) -> tuple[str, int]:
    name = Path(xml_path).stem
    out = Path(stage_dir) / f"{name}.fields.csv.gz"
    if out.exists():
        with gzip.open(out, "rt", encoding="utf-8") as f:
            return name, sum(1 for _ in f) - 1
    tmp = out.with_suffix(".tmp")
    n = 0
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        root = None
        for event, elem in ET.iterparse(xml_path, events=("start", "end")):
            if root is None and event == "start":
                root = elem
            if event == "end" and elem.tag == NS + "device":
                row = parse_fields(elem)
                if row[0]:
                    w.writerow(row)
                    n += 1
                elem.clear()
                if n % 2000 == 0 and root is not None:
                    root.clear()
    tmp.replace(out)
    return name, n


def load(con, stage: Path) -> int:
    con.execute(f"""CREATE OR REPLACE TABLE gudid_device_fields AS
        SELECT DISTINCT ON (primary_di) primary_di, sterile, sterilize_before_use, mri_safety
          FROM read_csv('{stage.as_posix()}/*.fields.csv.gz', header=true, all_varchar=true)""")
    return con.execute("SELECT count(*) FROM gudid_device_fields").fetchone()[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    if step_done(con, STEP):
        print(f"GUDID device fields already loaded (step {STEP}). Delete that row from run_steps to rebuild.")
        return 0
    files = ps.gudid_files()
    if len(files) != ps.gudid_parts:
        print(f"Expected {ps.gudid_parts} GUDID parts in {ps.gudid_dir}, found {len(files)}. "
              "Check GUDID_DIR and GUDID_PARTS in config.ini.")
        return 1
    stage = ps.stage.parent / "gudid_fields_stage"
    stage.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    keep_awake(True)
    total = 0
    try:
        with ProcessPoolExecutor(max_workers=ps.gudid_workers) as pool:
            futs = {pool.submit(parse_part, str(f), str(stage)): f for f in files}
            for i, fut in enumerate(as_completed(futs), 1):
                name, n = fut.result()
                total += n
                print(f"  {i}/{len(files)}  {name}: {n:,} devices")
                try:
                    check_stop(cfg)
                except StopRequested:
                    for other in futs:
                        other.cancel()
                    raise
        rows = load(con, stage)
    except StopRequested as e:
        print(f"Stopped: {e}. Run the same step again to resume.")
        return 2
    finally:
        keep_awake(False)
    mark_step(con, STEP, rows, time.monotonic() - t0, f"parsed={total}; device_ids={rows}")
    print(f"GUDID device fields: {rows:,} device IDs ({total:,} records parsed) in {time.monotonic() - t0:,.0f} s.")
    if rows != ps.gudid_expected:
        print(f"Note: config.ini expects {ps.gudid_expected:,} records; check the release if the counts differ.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
