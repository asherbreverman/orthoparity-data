"""Phase 1 pilot runner (downloads Summary PDFs, so run it on a PC with internet access).

Usage:  python orthoparity.py pilot            (seeds + chain walk, resumable)
        python orthoparity.py pilot --seeds-only
        python orthoparity.py pilot --offline  (re-parse from cached PDFs only, no network)
"""
from __future__ import annotations

import argparse
import sys

from predicate_chain.config import load_config
from predicate_chain.runner import run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds-only", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    cfg = load_config()
    walk = cfg.getbool("settings", "PILOT_WALK_CHAINS", True) and not args.seeds_only
    cap = cfg.getint("settings", "PILOT_MAX_CHAIN_DOCS", 2500)
    res = run(cfg, "pilot", walk_chains=walk, max_chain_docs=cap, phase="pilot", offline=args.offline)
    print(f"\nPilot run ended: {res['ended']}. Chain documents this session: {res['chain_docs']}. "
          f"Items with errors (retried next run): {res['errors']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
