"""Phase 4: write the next review batch as a packet for the reviewer.

Ranks open review-queue documents by impact (how many starting-set clearances have the document anywhere in
their predicate chain), skips documents that already have a decision for the current parser version, and writes
the next N to outputs/review/Review_Batch_NN.json. For each document the packet lists every blocking item with
its evidence text, FDA's record for the printed number, and candidate numbers one character away that exist in
FDA records (possible correct readings of a misread number). Candidates are hints for the reviewer only; a
correction needs support in the document's own text.

Usage:  python orthoparity.py review-packet [--size 50]
"""
from __future__ import annotations

import collections
import json
import re
import sys
from collections import deque

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema

DIGITS = "0123456789"


def impact_ranking(con, max_gen):
    adj = collections.defaultdict(set)
    for ch, p in con.execute("SELECT child_knumber, predicate_number FROM edges WHERE parser_version=? "
                             "AND predicate_number IS NOT NULL", (PARSER_VERSION,)):
        adj[ch].add(p)
    queued = {r[0] for r in con.execute("SELECT DISTINCT knumber FROM review_queue WHERE parser_version=? "
                                        "AND status='open'", (PARSER_VERSION,))}
    impact = collections.Counter()
    for (s,) in con.execute("SELECT knumber FROM clearances"):
        seen = {s: 0}
        dq = deque([s])
        while dq:
            x = dq.popleft()
            if seen[x] >= max_gen:
                continue
            for p in adj.get(x, ()):
                if p not in seen:
                    seen[p] = seen[x] + 1
                    dq.append(p)
        for n in seen:
            if n in queued:
                impact[n] += 1
    return sorted(queued, key=lambda k: (-impact[k], k)), impact


def fda(con, k):
    r = con.execute("SELECT applicant, devicename, decision_date, product_code, review_panel FROM fda_master "
                    "WHERE knumber=?", (k,)).fetchone()
    if r:
        return {"applicant": r[0], "device": r[1], "decided": r[2], "code": r[3], "panel": r[4]}
    r = con.execute("SELECT applicant, device_name, decision_date, product_code, review_panel FROM external_lookups "
                    "WHERE number=? AND found=1", (k,)).fetchone()
    if r:
        return {"applicant": r[0], "device": r[1], "decided": r[2], "code": r[3], "panel": r[4]}
    return None


def candidates(con, number, context):
    """FDA numbers one digit off (substitution, or two adjacent digits swapped) ranked by word overlap."""
    if not re.fullmatch(r"K\d{6}", number or ""):
        return []
    d = number[1:]
    opts = set()
    for i in range(6):
        for ch in DIGITS:
            if ch != d[i]:
                opts.add("K" + d[:i] + ch + d[i + 1:])
        if i < 5 and d[i] != d[i + 1]:
            opts.add("K" + d[:i] + d[i + 1] + d[i] + d[i + 2:])
    words = set(re.findall(r"[a-z]{4,}", (context or "").lower()))
    out = []
    for k in opts:
        f = fda(con, k)
        if not f:
            continue
        fw = set(re.findall(r"[a-z]{4,}", f"{f['applicant']} {f['device']}".lower()))
        out.append({"number": k, **f, "word_overlap": len(words & fw)})
    out.sort(key=lambda x: -x["word_overlap"])
    return [c for c in out if c["word_overlap"] > 0][:5]


def main() -> int:
    size = int(sys.argv[sys.argv.index("--size") + 1]) if "--size" in sys.argv else 50
    cfg = load_config()
    con = connect(cfg.db_path)
    init_schema(con)
    order, impact = impact_ranking(con, cfg.max_generations)
    done = {r[0] for r in con.execute("SELECT DISTINCT knumber FROM review_decisions WHERE decision_source='Claude review' "
                                      "AND reasoning LIKE ?", (f"[{PARSER_VERSION}]%",))}
    todo = [k for k in order if k not in done]
    batch = todo[:size]
    out_dir = cfg.output_dir / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Number the batch after every batch so far: packets here, decisions in reviews/predicate_review.
    seen = [int(m.group(1)) for d in (out_dir, cfg.review_dir / "predicate_review")
            for f in d.glob("Review_Batch_*.json") if (m := re.fullmatch(r"Review_Batch_(\d+)(_decisions)?\.json", f.name))]
    n = max(seen, default=0) + 1
    docs = []
    for k in batch:
        me = fda(con, k)
        edges = [dict(r) for r in con.execute(
            "SELECT edge_id, predicate_number, role, printed_label, printed_name, printed_company, fda_applicant, "
            "fda_device_name, confidence, in_predicate_section, page, evidence FROM edges WHERE child_knumber=? "
            "AND parser_version=? AND predicate_number IS NOT NULL ORDER BY list_order", (k, PARSER_VERSION))]
        flags = [dict(r) for r in con.execute(
            "SELECT flag_id, flag_type, number, detail, page, evidence FROM flags WHERE knumber=? AND parser_version=? "
            "AND flag_type IN ('probable misread number','possible OCR misread','wrong file')", (k, PARSER_VERSION))]
        for f in flags:
            f["candidates"] = candidates(con, f["number"], f.get("evidence"))
        doc = con.execute("SELECT text_method, cache_path, url FROM documents WHERE knumber=? AND parser_version=?",
                          (k, PARSER_VERSION)).fetchone()
        docs.append({"knumber": k, "impact": impact[k], "fda": me, "text_method": doc[0] if doc else None,
                     "url": doc[2] if doc else None, "edges": edges, "flags": flags})
    path = out_dir / f"Review_Batch_{n:02d}.json"
    path.write_text(json.dumps({"batch": n, "parser_version": PARSER_VERSION, "documents": docs,
                                "remaining_after": len(todo) - len(batch)}, indent=1, default=str), encoding="utf-8")
    print(f"Wrote {path} ({len(batch)} documents; {len(todo) - len(batch)} left after this batch).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
