"""Phase 0: create folders, build the empty database, load the three FDA inputs, verify counts,
copy any reusable PDFs from OLD_PROJECT_DIR (if set), and draw the pilot sample.

Usage:  python orthoparity.py load-fda
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.loaders import CountMismatch, cross_counts, load_fda_master, load_product_codes, load_starting_set
from predicate_chain.pilot import select_pilot
from predicate_chain.pipeline import copy_previous_cache
from predicate_chain.runlog import RunLog
from predicate_chain.textrepair import repair_sqlite


def main() -> int:
    cfg = load_config()
    for d in (cfg.data_dir, cfg.output_dir, cfg.log_dir, cfg.cache_dir, cfg.detail_cache_dir):
        d.mkdir(parents=True, exist_ok=True)
    con = connect(cfg.db_path)
    init_schema(con)
    log = RunLog(cfg.log_dir, "phase0", con)
    report: dict = {"parser_version": PARSER_VERSION}
    try:
        print("Loading starting set ...", flush=True)
        report["starting_set"] = load_starting_set(con, cfg)
        log.log("load", None, result="ok", reason=f"starting set {report['starting_set']['rows']} rows")
        print("Loading FDA master release files ...", flush=True)
        report["fda_master"] = load_fda_master(con, cfg)
        log.log("load", None, result="ok", reason=f"fda_master {report['fda_master']['rows']} rows")
        print("Loading product codes ...", flush=True)
        report["product_codes"] = load_product_codes(con, cfg)
        log.log("load", None, result="ok", reason=f"product codes {report['product_codes']['rows']} rows")
    except CountMismatch as exc:
        log.log("load", None, result="error", reason=str(exc))
        log.close(ended_how="count mismatch")
        print("\nSTOPPED: " + str(exc))
        return 2
    # restore characters the starting-set workbook lost (registered signs, accents) from the FDA release files
    tr = repair_sqlite(con)
    report["text_repair"] = {f"{t}.{c}": n for (t, c), n in tr.fixed.items()} | \
        {f"{t}.{c} left": n for (t, c), n in tr.left.items()}
    report["cross_counts"] = cross_counts(con)
    report["pdfs_reused_from_previous_run"] = copy_previous_cache(cfg, log)
    pilot = select_pilot(con, cfg)
    report["pilot_targets"] = len(pilot)
    log.close(ended_how="completed")
    out = cfg.output_dir / "Phase0_Load_Report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nAll counts verified. Report saved to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
