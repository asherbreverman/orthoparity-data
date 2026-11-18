"""Download FDA medical device recalls for every orthopedic product code and link them to 510(k)s and vendors.

Source: openFDA device recall and enforcement endpoints (public, no key needed). Recalls come from the recall
endpoint; FDA's recall class (I, II, III) comes from the enforcement endpoint, matched on the recall number.
Older recalls (before FDA's enforcement reports) have no class in openFDA and are written as NOT FOUND.

Inputs (from the last export): outputs/site_data/pc_portfolio_510k.csv and pc_vendor_names.csv
Outputs: outputs/site_data/pc_recalls.csv and outputs/Recalls_Report.txt

Vendor link: first by a 510(k) number the recall lists that is in the portfolio; otherwise by the recalling
firm's name matching a known vendor name exactly after removing punctuation and company suffixes. Each row
says which basis was used; recalls that match neither keep a blank vendor.

Usage:  python orthoparity.py fetch-recalls
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

from predicate_chain.config import load_config
from predicate_chain.paycommon import company_root
from pipeline.build_vendor_registry import family_of, load_families

RECALL_URL = "https://api.fda.gov/device/recall.json"
ENFORCE_URL = "https://api.fda.gov/device/enforcement.json"
PAGE = 1000
CODE_BATCH = 20
NUMBER_BATCH = 40
PAUSE = 0.35  # openFDA allows 240 requests a minute without a key


def get(url: str, params: dict, tries: int = 4) -> dict:
    q = urllib.parse.urlencode(params, safe=':+()"')
    for i in range(tries):
        try:
            with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
                time.sleep(PAUSE)
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:  # openFDA answers "no matches" with 404
                time.sleep(PAUSE)
                return {"results": [], "meta": {"results": {"total": 0}}}
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2 * (i + 1))
    return {}


def fetch_recalls(codes: list[str]) -> list[dict]:
    out = {}
    for i in range(0, len(codes), CODE_BATCH):
        batch = codes[i:i + CODE_BATCH]
        search = "product_code:(" + "+".join(f'"{c}"' for c in batch) + ")"
        skip = 0
        while True:
            d = get(RECALL_URL, {"search": search, "limit": PAGE, "skip": skip})
            res = d.get("results", [])
            for r in res:
                out[r.get("product_res_number") or r.get("cfres_id")] = r
            total = d.get("meta", {}).get("results", {}).get("total", 0)
            skip += PAGE
            if skip >= total or not res:
                break
        print(f"  product codes {i + 1}-{i + len(batch)} of {len(codes)}: {len(out):,} recalls so far", flush=True)
    return list(out.values())


def fetch_classes(numbers: list[str]) -> dict:
    out = {}
    for i in range(0, len(numbers), NUMBER_BATCH):
        batch = numbers[i:i + NUMBER_BATCH]
        search = "recall_number:(" + "+".join(f'"{n}"' for n in batch) + ")"
        d = get(ENFORCE_URL, {"search": search, "limit": PAGE})
        for r in d.get("results", []):
            out[r.get("recall_number")] = r
        if (i // NUMBER_BATCH) % 25 == 0:
            print(f"  recall classes {min(i + NUMBER_BATCH, len(numbers)):,} of {len(numbers):,}", flush=True)
    return out


def clip(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    lov = cfg.site_data_dir

    k_vendor, codes = {}, set()
    with open(lov / "pc_portfolio_510k.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            codes.add(r["product_code"])
            if r["vendor_id"]:
                k_vendor[r["knumber"]] = r["vendor_id"]
    root_vendor: dict[str, set] = {}
    with open(lov / "pc_vendor_names.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            root = company_root(r["raw_name"])
            if root:
                root_vendor.setdefault(root, set()).add(r["vendor_id"])
    codes = sorted(c for c in codes if c)
    fams = load_families()

    print(f"Downloading recalls for {len(codes)} orthopedic product codes ...", flush=True)
    recalls = fetch_recalls(codes)
    numbers = sorted({r["product_res_number"] for r in recalls if r.get("product_res_number")})
    print(f"Looking up FDA recall class for {len(numbers):,} recalls ...", flush=True)
    classes = fetch_classes(numbers)

    rows, basis = [], Counter()
    n_bad_dates = 0
    for r in recalls:
        ks = sorted({k for k in (r.get("k_numbers") or []) if k})
        vid, how = None, ""
        linked = [k_vendor[k] for k in ks if k in k_vendor]
        if linked:
            vid, how = Counter(linked).most_common(1)[0][0], "510(k) number"
        else:
            fam = family_of(r.get("recalling_firm") or "", fams)
            cands = root_vendor.get(company_root(r.get("recalling_firm") or ""), set())
            if fam:
                vid, how = fam["vendor_id"], "firm name (curated family)"
            elif len(cands) == 1:
                vid, how = next(iter(cands)), "firm name"
        basis[how or "not linked"] += 1
        e = classes.get(r.get("product_res_number"), {})
        bad_dates = 0
        dates = {}
        for f in ("event_date_initiated", "event_date_posted", "event_date_terminated"):
            v = r.get(f)
            if v and not ("1976" <= v[:4] <= "2100"):
                bad_dates += 1
                v = None
            dates[f] = v
        n_bad_dates += bad_dates > 0
        rows.append({
            "recall_number": r.get("product_res_number"), "event_id": r.get("res_event_number"),
            "initiated": dates["event_date_initiated"], "posted": dates["event_date_posted"],
            "terminated": dates["event_date_terminated"], "status": r.get("recall_status"),
            "recall_class": e.get("classification") or "NOT FOUND",
            "product_code": r.get("product_code"), "knumbers": "|".join(ks),
            "recalling_firm": r.get("recalling_firm"), "vendor_id": vid, "vendor_basis": how,
            "product": clip(r.get("product_description"), 300), "reason": clip(r.get("reason_for_recall"), 600),
            "root_cause": r.get("root_cause_description"), "quantity": clip(r.get("product_quantity"), 80),
        })
    rows.sort(key=lambda x: (x["initiated"] or "", x["recall_number"] or ""), reverse=True)
    cols = list(rows[0].keys()) if rows else []
    with open(lov / "pc_recalls.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    cls = Counter(x["recall_class"] for x in rows)
    yrs = Counter((x["initiated"] or "")[:4] for x in rows)
    lines = [f"Recalls report, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC (openFDA data last updated "
             f"{get(RECALL_URL, {'limit': 1}).get('meta', {}).get('last_updated', 'unknown')})", "",
             f"Orthopedic product codes searched: {len(codes)}",
             f"Recalls (one row per recalled product): {len(rows):,}",
             f"Recall events: {len({x['event_id'] for x in rows}):,}",
             "FDA recall class: " + ", ".join(f"{k} {v:,}" for k, v in sorted(cls.items())),
             "Vendor link: " + ", ".join(f"{k} {v:,}" for k, v in basis.most_common()),
             f"Rows with an impossible date in openFDA (left blank, not guessed): {n_bad_dates}",
             f"Earliest initiated: {min((x['initiated'] for x in rows if x['initiated']), default='NOT FOUND')}",
             "By year initiated: " + ", ".join(f"{y} {n}" for y, n in sorted(yrs.items()) if y)]
    (cfg.output_dir / "Recalls_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
