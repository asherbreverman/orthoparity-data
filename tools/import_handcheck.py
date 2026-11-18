"""Record a filled hand-check workbook in review_decisions (decision_source = "human review").

Never changes parser output: one decision row per checked edge and per checked device.
Usage:  python orthoparity.py import-handcheck outputs\\Pilot_HandCheck_2026-11-16.xlsx "Reviewer Name" [parser_version]
"""
from __future__ import annotations

import datetime as dt
import sys

import openpyxl

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect


def yn(v):
    v = (str(v).strip().upper() if v is not None else "")
    return v if v in ("Y", "N") else None


def main() -> int:
    path, reviewer = sys.argv[1], sys.argv[2]
    version = sys.argv[3] if len(sys.argv) > 3 else PARSER_VERSION
    cfg = load_config()
    con = connect(cfg.db_path)
    wb = openpyxl.load_workbook(path, data_only=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tag = f"hand-check {path.replace(chr(92), '/').split('/')[-1]}"
    con.execute("DELETE FROM review_decisions WHERE decision_source='human review' AND reasoning LIKE ?", (tag + "%",))
    n_edges = n_dev = 0
    for r in wb["Edges"].iter_rows(min_row=3, values_only=True):
        k, pred, page = r[0], r[9], r[7]
        a, b, c, note = yn(r[18]), yn(r[19]), yn(r[20]), r[21]
        if not k or k == "EXAMPLE" or not (a or b or c):
            continue
        num = None if pred in ("NO NUMBER", "NOT FOUND") else pred
        row = con.execute("SELECT edge_id FROM edges WHERE child_knumber=? AND parser_version=? AND "
                          "COALESCE(predicate_number,'')=COALESCE(?, '') ORDER BY list_order LIMIT 1",
                          (k, version, num)).fetchone()
        decision = "confirmed" if (a, b, c) == ("Y", "Y", "Y") else "disputed"
        con.execute("INSERT INTO review_decisions (knumber, edge_id, decision, reasoning, evidence_page, decision_source, "
                    "reviewer, decided_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                    (k, row[0] if row else None, decision,
                     f"{tag}: number {a}, role {b}, real predicate {c}" + (f"; note: {note}" if note else ""),
                     page, "human review", reviewer, now))
        n_edges += 1
    for r in wb["Devices"].iter_rows(min_row=3, values_only=True):
        k, found, missed, note = r[0], yn(r[13]), r[14], r[15]
        if not k or k == "EXAMPLE" or not found:
            continue
        con.execute("INSERT INTO review_decisions (knumber, edge_id, decision, reasoning, evidence_page, decision_source, "
                    "reviewer, decided_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                    (k, None, "all predicates found" if found == "Y" else "predicates missed",
                     f"{tag}: device check" + (f"; missed: {missed}" if missed else "") + (f"; note: {note}" if note else ""),
                     None, "human review", reviewer, now))
        n_dev += 1
    con.commit()
    print(f"Recorded {n_edges} edge decisions and {n_dev} device decisions (parser {version}, reviewer {reviewer}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
