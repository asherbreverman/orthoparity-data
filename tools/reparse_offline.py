"""Re-run the parser on cached PDFs only (no downloads). Use after a parser fix.

Bump PARSER_VERSION in predicate_chain/__init__.py first so older results are kept.
With --force the current version's results for the run are cleared and rebuilt.

Usage:  python orthoparity.py reparse-offline --run pilot [--force]
"""
from __future__ import annotations

import argparse
import sys

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect
from predicate_chain.runner import run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="pilot")
    ap.add_argument("--force", action="store_true", help="clear this parser version's rows first")
    ap.add_argument("--no-walk", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    if args.force:
        con = connect(cfg.db_path)
        for t in ("edges", "flags", "review_queue", "node_status"):
            con.execute(f"DELETE FROM {t} WHERE parser_version=?", (PARSER_VERSION,))
        # documents rows are kept: they hold download provenance and are replaced row by row
        con.commit()
        con.close()
    res = run(cfg, args.run, walk_chains=not args.no_walk, max_chain_docs=None, phase="reparse", offline=True,
              echo=lambda s: None)
    print(f"Offline re-parse ended: {res['ended']}; chain documents {res['chain_docs']}; "
          f"left for an online run: {res['errors']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
