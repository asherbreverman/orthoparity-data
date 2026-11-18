"""Phase 4: record a review batch's decisions, then extract any corrected numbers and their chains.

Decisions never change parser output. They sit in review_decisions and the lookup layer applies them:
  confirmed        the edge stands as read (LOW edges become usable)
  corrected        the document meant another number (corrected_number); chains follow the corrected number
  own number       the number is the document's own K-number misread; the edge is left out
  not a predicate  the number is a misread with no predicate meaning; the edge is left out
  unresolved       no supported reading; the edge stays as read (a number in no FDA record is a dead end)

Usage:  python orthoparity.py import-review [decisions.json ...]
With no file names it imports every reviews/predicate_review/Review_Batch_NN_decisions.json, then goes online for
corrected numbers that were never extracted. Writes reviews/predicate_review/Review_Log.csv (every decision so far).
Safe to run again: a batch's earlier decisions are replaced, never doubled.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
from pathlib import Path

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.runner import run

VALID = {"confirmed", "corrected", "own number", "not a predicate", "unresolved"}
BLOCKING = ("probable misread number", "possible OCR misread", "wrong file")


def import_file(con, path: Path) -> tuple[int, int]:
    d = json.loads(path.read_text(encoding="utf-8"))
    version = d.get("parser_version") or PARSER_VERSION
    reviewer = d.get("reviewer") or "Claude"
    source = "human review" if reviewer.lower() not in ("claude",) else "Claude review"
    tag = f"[{version}] batch {d['batch']}:"
    con.execute("DELETE FROM review_decisions WHERE reasoning LIKE ?", (tag + "%",))
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    docs = set()
    for k, number, decision, corrected, why in d["decisions"]:
        if decision not in VALID:
            raise ValueError(f"{path.name}: unknown decision '{decision}' for {k} {number}")
        if decision == "corrected" and not corrected:
            raise ValueError(f"{path.name}: 'corrected' needs a corrected number for {k} {number}")
        e = con.execute("SELECT edge_id, page FROM edges WHERE child_knumber=? AND parser_version=? AND predicate_number=? "
                        "ORDER BY list_order LIMIT 1", (k, version, number)).fetchone()
        q = con.execute("SELECT queue_id FROM review_queue WHERE knumber=? AND parser_version=? AND status='open' "
                        "AND (ref_id=? OR item_type='document') ORDER BY item_type='document' LIMIT 1",
                        (k, version, e[0] if e else -1)).fetchone()
        con.execute("INSERT INTO review_decisions (queue_id, knumber, edge_id, decision, reasoning, evidence_page, "
                    "decision_source, reviewer, decided_at_utc, predicate_number, corrected_number, parser_version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (q[0] if q else None, k, e[0] if e else None, decision, f"{tag} {why}", e[1] if e else None,
                     source, reviewer, now, number, corrected, version))
        docs.add(k)
    # close queue items for documents whose blocking items all have a decision
    closed = 0
    for k in docs:
        decided = {r[0] for r in con.execute("SELECT predicate_number FROM review_decisions WHERE knumber=? "
                                             "AND parser_version=?", (k, version))}
        open_nums = {r[0] for r in con.execute(
            f"SELECT number FROM flags WHERE knumber=? AND parser_version=? AND flag_type IN ({','.join('?' * len(BLOCKING))})",
            (k, version, *BLOCKING))}
        low = {r[0] for r in con.execute("SELECT predicate_number FROM edges WHERE child_knumber=? AND parser_version=? "
                                         "AND confidence='LOW' AND predicate_number IS NOT NULL", (k, version))}
        if (open_nums | low) <= decided:
            closed += con.execute("UPDATE review_queue SET status='reviewed' WHERE knumber=? AND parser_version=? "
                                  "AND status='open'", (k, version)).rowcount
    con.commit()
    return len(d["decisions"]), closed


def write_log(cfg, con) -> Path:
    out = cfg.review_dir / "predicate_review" / "Review_Log.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = con.execute("SELECT knumber, predicate_number, decision, corrected_number, reasoning, evidence_page, "
                       "decision_source, reviewer, decided_at_utc, parser_version FROM review_decisions "
                       "WHERE predicate_number IS NOT NULL ORDER BY decision_id").fetchall()
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Document", "Number as printed", "Decision", "Corrected to", "Reasoning", "Evidence page",
                    "Source", "Reviewer", "Decided (UTC)", "Parser version"])
        w.writerows([list(r) for r in rows])
    return out


def main() -> int:
    cfg = load_config()
    con = connect(cfg.db_path)
    init_schema(con)
    files = [Path(a) for a in sys.argv[1:]] or sorted((cfg.review_dir / "predicate_review").glob("Review_Batch_*_decisions.json"))
    if not files:
        print("No decision files found in reviews/predicate_review.")
        return 1
    for f in files:
        n, closed = import_file(con, f)
        print(f"{f.name}: {n} decisions recorded; {closed} queue items closed.")
    print("Log:", write_log(cfg, con))
    left = con.execute("SELECT COUNT(DISTINCT knumber) FROM review_queue WHERE parser_version=? AND status='open'",
                       (PARSER_VERSION,)).fetchone()[0]
    print(f"Documents still in the review queue: {left:,}")
    con.close()
    print("\nExtracting corrected numbers that were never extracted, and their chains (online).")
    res = run(cfg, "frontier", walk_chains=True, phase="phase4-review")
    print(f"Done: {res['ended']}. Documents processed: {res['chain_docs']:,}. Download errors: {res['errors']}.")
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
        (cfg.output_dir / "Review_ERROR.txt").write_text(msg, encoding="utf-8")
        print(msg)
        print("The import stopped on an error (saved to outputs\\Review_ERROR.txt). Attach it to a GitHub issue if you need help.")
        input("Press Enter to close this window.")
        sys.exit(1)
