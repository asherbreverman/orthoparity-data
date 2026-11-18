"""Phase 3: extract the ancestor frontier.

Walks every predicate chain from the 18,224 starting-set clearances, generation by generation (up to
MAX_GENERATIONS), and extracts each ancestor that has no result yet for the current parser version. Most of
these ancestors sit outside the orthopedic product codes or are older devices the starting set cites.
Ancestors only: nothing here looks for devices that cite a given device.

Resumable: run it again after any interruption and it continues where it stopped.
Usage:  python orthoparity.py walk-ancestors
Progress: outputs/progress_frontier.txt   Summary: outputs/Phase3_Summary.txt
"""
from __future__ import annotations

import collections
import datetime as dt
import sys

from predicate_chain import PARSER_VERSION
from predicate_chain.chains import pending_nodes
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.pdftext import tesseract_available
from predicate_chain.runner import run

RUN = "frontier"


def ensure_targets(cfg) -> int:
    """The frontier walk starts from the same seeds as Phase 2 (the whole starting set)."""
    con = connect(cfg.db_path)
    init_schema(con)
    n = con.execute("SELECT COUNT(*) FROM run_targets WHERE run_name=?", (RUN,)).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM clearances").fetchone()[0]
    if n != total:
        rows = con.execute("SELECT knumber, unofficial_segment FROM clearances "
                           "ORDER BY decision_date DESC, knumber").fetchall()
        con.execute("DELETE FROM run_targets WHERE run_name=?", (RUN,))
        con.executemany("INSERT INTO run_targets (run_name, knumber, stratum, seq) VALUES (?,?,?,?)",
                        [(RUN, r[0], r[1], i) for i, r in enumerate(rows)])
        con.commit()
        n = len(rows)
    con.close()
    return n


def reachable(con, seeds, max_gen):
    """Distance from the starting set to every node reachable through current-version edges."""
    adj = collections.defaultdict(set)
    for c, p in con.execute("SELECT child_knumber, predicate_number FROM edges WHERE parser_version=? "
                            "AND predicate_number IS NOT NULL", (PARSER_VERSION,)):
        adj[c].add(p)
    dist = {s: 0 for s in seeds}
    frontier = list(seeds)
    while frontier:
        nxt = []
        for k in frontier:
            if dist[k] >= max_gen:
                continue
            for p in adj.get(k, ()):
                if p not in dist:
                    dist[p] = dist[k] + 1
                    nxt.append(p)
        frontier = nxt
    return dist


def write_summary(cfg, res) -> None:
    con = connect(cfg.db_path)
    seeds = [r[0] for r in con.execute("SELECT knumber FROM run_targets WHERE run_name=?", (RUN,))]
    sset = set(seeds)
    dist = reachable(con, seeds, cfg.max_generations)
    anc = {k: d for k, d in dist.items() if k not in sset}
    ns = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT knumber, status, stop_reason FROM node_status WHERE parser_version=?", (PARSER_VERSION,))}
    done = {k for k in anc if k in ns}
    pend = pending_nodes(con, seeds, cfg.max_generations, PARSER_VERSION)
    by_gen = collections.Counter(anc.values())
    done_gen = collections.Counter(anc[k] for k in done)
    stops = collections.Counter((ns[k][1] or "(continues: has predicates)") for k in done)
    panels = collections.Counter()
    for k in done:
        row = con.execute("SELECT review_panel FROM fda_master WHERE knumber=?", (k,)).fetchone()
        panels[(row[0] if row and row[0] else "not in 510(k) records")] += 1
    edges = con.execute("SELECT COUNT(*), SUM(confidence='HIGH'), SUM(confidence='MEDIUM'), SUM(confidence='LOW') "
                        "FROM edges e JOIN node_status n ON n.knumber=e.child_knumber AND n.parser_version=e.parser_version "
                        "WHERE e.parser_version=? AND e.child_knumber IN (SELECT knumber FROM node_status "
                        "WHERE parser_version=?)", (PARSER_VERSION, PARSER_VERSION)).fetchone()
    lines = [f"OrthoParity Phase 3 summary: ancestor frontier (parser {PARSER_VERSION})",
             f"Written {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} (your local time)",
             f"Run ended: {res['ended']}",
             f"Ancestor documents processed this run: {res['chain_docs']:,}    Download errors this run: {res['errors']}",
             "",
             f"Ancestors reachable from the starting set (within {cfg.max_generations} generations): {len(anc):,}",
             f"  extracted: {len(done):,}    still pending: {len(pend):,}"
             + ("    (rerun to finish)" if pend else ""),
             "", "Ancestors by generation (reachable / extracted):"]
    lines += [f"  generation {g:>2}: {by_gen[g]:>6,} / {done_gen[g]:>6,}" for g in sorted(by_gen)]
    lines += ["", "Ancestor stop reasons:"] + [f"  {v:>7,}  {k}" for k, v in stops.most_common()]
    lines += ["", "Ancestor FDA review panel:"] + [f"  {v:>7,}  {k}" for k, v in panels.most_common()]
    lines += ["", f"All current-version edges (starting set plus ancestors): {edges[0]:,}  "
                  f"(HIGH {edges[1] or 0:,}, MEDIUM {edges[2] or 0:,}, LOW {edges[3] or 0:,})"]
    (cfg.output_dir / "Phase3_Summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    con.close()


def main() -> int:
    cfg = load_config()
    n = ensure_targets(cfg)
    print(f"OrthoParity Phase 3: ancestor frontier from {n:,} starting clearances, parser {PARSER_VERSION}.")
    if not tesseract_available(cfg.get("ocr", "TESSERACT_PATH")):
        print("WARNING: Tesseract OCR was not found. Scanned PDFs will be marked 'Needs OCR' and can be redone later.")
    print("Progress: outputs\\progress_frontier.txt. Close this window or press Ctrl+C to stop; run again to resume.\n")
    res = run(cfg, RUN, walk_chains=True, phase="phase3")
    write_summary(cfg, res)
    print(f"\nPhase 3 run ended: {res['ended']}. Items with download errors (retried next run): {res['errors']}.")
    print("Summary: outputs\\Phase3_Summary.txt")
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
        (cfg.output_dir / "Phase3_ERROR.txt").write_text(msg, encoding="utf-8")
        print(msg)
        print("The run stopped on an error (saved to outputs\\Phase3_ERROR.txt). Attach it to a GitHub issue if you need help.")
        input("Press Enter to close this window.")
        sys.exit(1)
