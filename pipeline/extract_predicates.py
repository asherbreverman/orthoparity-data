"""Phase 2: extract predicates for every clearance in the starting set (no chain walk; that is Phase 3).

Resumable: run it again after any interruption and it continues where it stopped.
Usage:  python orthoparity.py extract-predicates
Progress: outputs/progress_full.txt   Checkpoint: outputs/checkpoint_full.json   Summary: outputs/Phase2_Summary.txt
"""
from __future__ import annotations

import collections
import datetime as dt
import sys

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.pdftext import tesseract_available
from predicate_chain.runner import run

RUN = "full"


def ensure_targets(cfg) -> int:
    con = connect(cfg.db_path)
    init_schema(con)
    n = con.execute("SELECT COUNT(*) FROM run_targets WHERE run_name=?", (RUN,)).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM clearances").fetchone()[0]
    if n != total:
        # Newest clearances first, so the devices a VAC is most likely to look up finish early.
        rows = con.execute("SELECT knumber, unofficial_segment FROM clearances "
                           "ORDER BY decision_date DESC, knumber").fetchall()
        con.execute("DELETE FROM run_targets WHERE run_name=?", (RUN,))
        con.executemany("INSERT INTO run_targets (run_name, knumber, stratum, seq) VALUES (?,?,?,?)",
                        [(RUN, r[0], r[1], i) for i, r in enumerate(rows)])
        con.commit()
        n = len(rows)
    con.close()
    return n


def write_summary(cfg) -> None:
    con = connect(cfg.db_path)
    targets = [r[0] for r in con.execute("SELECT knumber FROM run_targets WHERE run_name=?", (RUN,))]
    tset = set(targets)
    ns = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT knumber, status, stop_reason FROM node_status WHERE parser_version=?", (PARSER_VERSION,)) if r[0] in tset}
    docs = {r[0]: r for r in con.execute(
        "SELECT knumber, parse_status, text_method, fetch_outcome FROM documents WHERE parser_version=?", (PARSER_VERSION,))
        if r[0] in tset}
    stops = collections.Counter((v[1] or "(continues: has predicates)") for v in ns.values())
    parse = collections.Counter((d[1] or "") for d in docs.values())
    method = collections.Counter((d[2] or "none") for d in docs.values() if d[2])
    lines = [f"OrthoParity Phase 2 summary (parser {PARSER_VERSION})",
             f"Written {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} (your local time)",
             f"Clearances processed: {len(ns):,} of {len(targets):,}",
             f"Still pending (rerun to finish): {len(targets) - len(ns):,}", "", "Stop reasons:"]
    lines += [f"  {v:>7,}  {k}" for k, v in stops.most_common()]
    lines += ["", "Parse status:"] + [f"  {v:>7,}  {k}" for k, v in parse.most_common() if k]
    lines += ["", "Text method:"] + [f"  {v:>7,}  {k}" for k, v in method.most_common()]
    (cfg.output_dir / "Phase2_Summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    con.close()


def main() -> int:
    cfg = load_config()
    n = ensure_targets(cfg)
    print(f"OrthoParity Phase 2: {n:,} clearances, parser {PARSER_VERSION}.")
    if not tesseract_available(cfg.get("ocr", "TESSERACT_PATH")):
        print("WARNING: Tesseract OCR was not found. Scanned PDFs will be marked 'Needs OCR' and can be redone later.")
    print("Progress: outputs\\progress_full.txt. Close this window or press Ctrl+C to stop; run again to resume.\n")
    res = run(cfg, RUN, walk_chains=False, phase="phase2")
    write_summary(cfg)
    print(f"\nPhase 2 run ended: {res['ended']}. Items with download errors (retried next run): {res['errors']}.")
    print("Summary: outputs\\Phase2_Summary.txt")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        cfg = load_config()
        msg = traceback.format_exc()
        (cfg.output_dir / "Phase2_ERROR.txt").write_text(msg, encoding="utf-8")
        print(msg)
        print("The run stopped on an error (saved to outputs\\Phase2_ERROR.txt). Attach it to a GitHub issue if you need help.")
        input("Press Enter to close this window.")
        sys.exit(1)
