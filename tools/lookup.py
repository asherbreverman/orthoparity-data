"""Command-line ancestor lookup.

    python orthoparity.py lookup K241487              one clearance: workbook + tree PNG/SVG in outputs/lookups/
    python orthoparity.py lookup K241487 --brand      all clearances for that brand by that applicant
    python orthoparity.py lookup "interwedge"         search by product name or company and list the matches

Reads only the database. Never downloads or reads a PDF.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from predicate_chain.config import load_config
from predicate_chain.db import connect
from predicate_chain.lookup_core import (benchmark_rows, brand_family, clean, earliest_year, norm_k, render_tree,
                                         run_lookup, safe_name, search)
from predicate_chain.lookup_workbook import write_workbook
from predicate_chain.runlog import RunLog


def make_outputs(cfg, con, roots, label, excluded, out_dir: Path):
    res = run_lookup(con, roots, cfg.max_generations, label=label, excluded=excluded)
    stem = f"Predicate_Chain_{safe_name(label)}_{dt.date.today().isoformat()}"
    png, svg, how = render_tree(res, out_dir / f"{stem}_tree_primary", scope="primary")
    fpng, fsvg, _ = render_tree(res, out_dir / f"{stem}_tree_full", scope="full")
    xlsx = write_workbook(res, out_dir / f"{stem}.xlsx", cfg)
    RunLog(cfg.log_dir, "lookup", con).log("lookup", roots[0], result="ok",
                                           reason=f"{len(roots)} subject(s), {len(res.nodes)} devices; {label}")
    return res, xlsx, (png, svg, fpng, fsvg), None, how


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cfg = load_config()
    con = connect(cfg.db_path)
    query = " ".join(a for a in argv if not a.startswith("--"))
    out_dir = cfg.output_dir / "lookups"
    k = norm_k(query)
    if not k:
        hits = search(con, query)
        if not hits:
            print(f"No clearances match '{query}'.")
            return 1
        print(f"{len(hits)} match(es) for '{query}':")
        for h in hits:
            print(f"  {h['knumber']}  {str(h['decision_date'])[:10]}  {clean(h['devicename'])[:50]:50}  "
                  f"{clean(h['applicant'])[:40]}{'  (fuzzy)' if h.get('fuzzy') else ''}")
        print("\nRun again with a K-number, for example: python orthoparity.py lookup " + hits[0]["knumber"])
        return 0
    roots, excluded = [k], []
    hit = search(con, k)
    label = clean(hit[0]["devicename"]) if hit else k
    if "--brand" in argv:
        fam, excluded, brand = brand_family(con, k)
        if fam:
            roots = [f["knumber"] for f in fam]
            label = f"{brand} family ({clean(hit[0]['applicant'])})" if brand else label
    res, xlsx, files, _, how = make_outputs(cfg, con, roots, label, excluded, out_dir)
    print(f"{label}: {len(roots)} subject clearance(s), {len(res.nodes)} devices in the ancestor chain, "
          f"deepest generation {res.chain.depth}, earliest year {earliest_year(res)}.")
    for r in benchmark_rows(res)[:15]:
        print(f"  gen {r['Generation']:>2}  {r['K-number']:9} {str(r['Decision date'])[:4]}  {r['Role'][:22]:22} "
              f"{(r['Device name'] or '')[:40]:40} {(r['Where the chain stops'] or '')[:40]}")
    if len(res.nodes) > 15:
        print(f"  ... {len(res.nodes) - 15} more in the workbook")
    print(f"\nWorkbook: {xlsx}\nTrees ({how}), primary predicates only and the full chain:")
    for f in files:
        print("  ", f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
