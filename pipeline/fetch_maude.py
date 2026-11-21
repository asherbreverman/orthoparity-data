"""Count FDA adverse event reports (MAUDE) for every orthopedic 510(k) and write them for the website.

Source: openFDA device adverse event endpoint (public). Each MAUDE report carries the premarket number the
manufacturer entered (pma_pmn_number). This step counts, for each orthopedic 510(k) in the starting set:
  - all reports by event type (death, injury, malfunction, other or not answered)
  - reports in the last five years by event type
  - reports by the year FDA received them

A report counts toward a 510(k) only when it names that 510(k) number (FDA's data stores some numbers with a
leading P, such as PK140881 for K140881; both forms count). Reports with a missing or wrong number
are not matched, so the counts are a floor. A report is a fact about a filing, not proof that the device caused
the event, and counts are not rates: FDA publishes no count of devices in use.

Key: openFDA allows 1,000 requests a day without a key. Put a free key in an environment variable named
OPENFDA_API_KEY, or in a file named .env (or .env.txt) in the project folder with the line
OPENFDA_API_KEY=your-key. Both files are excluded from git. The key is never written to any output.

Inputs:  outputs/site_data/pc_devices.csv (the starting-set clearances)
Cache:   outputs/maude/maude_counts.jsonl (one line per 510(k); the step resumes where it stopped)
Outputs: outputs/site_data/pc_maude_product.csv, pc_maude_year.csv and outputs/MAUDE_Report.txt

Usage:  python orthoparity.py fetch-maude              (download what is missing, then write the CSVs)
        python orthoparity.py fetch-maude --refresh    (download everything again)
        python orthoparity.py fetch-maude --export-only
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from predicate_chain.config import load_config

EVENT_URL = "https://api.fda.gov/device/event.json"
TYPES = {"Death": "deaths", "Injury": "injuries", "Malfunction": "malfunctions"}
PER_MINUTE = 220  # openFDA allows 240 requests a minute per key
WORKERS = 10


class Throttle:
    def __init__(self, per_minute: int):
        self.gap = 60.0 / per_minute
        self.lock = threading.Lock()
        self.next = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next)
            self.next = t + self.gap
        if t > now:
            time.sleep(t - now)


def api_key(project_dir: Path) -> str:
    key = os.environ.get("OPENFDA_API_KEY", "").strip()
    if key:
        return key
    for name in (".env", ".env.txt"):
        p = project_dir / name
        if p.exists():
            for line in p.read_text(encoding="utf-8-sig").splitlines():
                if line.strip().startswith("OPENFDA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def make_get(key: str, throttle: Throttle):
    def get(params: dict, tries: int = 5) -> dict:
        p = dict(params)
        if key:
            p["api_key"] = key
        url = EVENT_URL + "?" + urllib.parse.urlencode(p, safe=':+()"[]')
        for i in range(tries):
            throttle.wait()
            try:
                with urllib.request.urlopen(url, timeout=90) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:  # openFDA answers "no matches" with 404
                    return {"results": []}
                if e.code == 429:
                    time.sleep(30 * (i + 1))
                    continue
                if i == tries - 1:
                    raise
            except Exception:
                if i == tries - 1:
                    raise
            time.sleep(3 * (i + 1))
        return {"results": []}
    return get


def count_one(get, k: str, since: str, today: str) -> dict:
    # FDA's data stores some 510(k) numbers with a leading P (PK140881 for K140881); count both forms
    q = f'pma_pmn_number:("{k}" "P{k}")'
    rec = {"knumber": k, "by_type": {}, "by_type_last5": {}, "by_year": {}}
    for r in get({"search": q, "count": "event_type.exact"}).get("results", []):
        rec["by_type"][r["term"]] = r["count"]
    if not rec["by_type"]:
        return rec
    years: Counter = Counter()
    recent = False
    for r in get({"search": q, "count": "date_received"}).get("results", []):
        years[str(r["time"])[:4]] += r["count"]
        recent = recent or str(r["time"]) >= since
    rec["by_year"] = dict(sorted(years.items()))
    if recent:  # only products with a report in the window need the five-year breakdown
        q5 = f"{q} AND date_received:[{since} TO {today}]"
        for r in get({"search": q5, "count": "event_type.exact"}).get("results", []):
            rec["by_type_last5"][r["term"]] = r["count"]
    return rec


def load_cache(path: Path) -> dict:
    out = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    r = json.loads(line)
                    out[r["knumber"]] = r
    return out


def starting_set(site: Path) -> list[str]:
    ks = set()
    with open(site / "pc_devices.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("in_starting_set", "")).lower() == "true" and r["knumber"]:
                ks.add(r["knumber"])
    return sorted(ks)


def last_updated(get) -> str:
    d = get({"limit": 1})
    return d.get("meta", {}).get("last_updated", "")


def split_types(by_type: dict) -> dict:
    out = {v: int(by_type.get(k, 0)) for k, v in TYPES.items()}
    out["other"] = int(sum(n for t, n in by_type.items() if t not in TYPES))
    out["reports"] = int(sum(by_type.values()))
    return out


def export(cache: dict, ks: list[str], site: Path, out_dir: Path, meta: dict) -> dict:
    prod_rows, year_rows = [], []
    for k in ks:
        r = cache.get(k)
        if not r or not r["by_type"]:
            continue
        a, b = split_types(r["by_type"]), split_types(r["by_type_last5"])
        years = sorted(r["by_year"])
        prod_rows.append([k, a["reports"], a["deaths"], a["injuries"], a["malfunctions"], a["other"],
                          b["reports"], b["deaths"], b["injuries"], b["malfunctions"], b["other"],
                          years[0] if years else "", years[-1] if years else "", meta["window_start"],
                          meta["data_through"]])
        for y in years:
            year_rows.append([k, int(y), int(r["by_year"][y])])
    with open(site / "pc_maude_product.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["knumber", "reports", "deaths", "injuries", "malfunctions", "other",
                    "reports_last5", "deaths_last5", "injuries_last5", "malfunctions_last5", "other_last5",
                    "first_year", "last_year", "window_start", "data_through"])
        w.writerows(prod_rows)
    with open(site / "pc_maude_year.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["knumber", "year", "reports"])
        w.writerows(year_rows)

    tot = Counter()
    for row in prod_rows:
        for i, f in enumerate(["reports", "deaths", "injuries", "malfunctions", "other"], start=1):
            tot[f] += row[i]
    missing = [k for k in ks if k not in cache]
    lines = [
        "MAUDE adverse event reports matched to orthopedic 510(k)s",
        f"Built: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Source: openFDA device adverse event endpoint, data last updated {meta['data_through']}",
        f"Five-year window starts: {meta['window_start']}",
        "",
        f"510(k)s checked: {len(ks):,}",
        f"510(k)s with at least one report naming them: {len(prod_rows):,}",
        f"510(k)s not yet downloaded: {len(missing):,}",
        f"Reports matched: {tot['reports']:,} (deaths {tot['deaths']:,}, injuries {tot['injuries']:,}, "
        f"malfunctions {tot['malfunctions']:,}, other or not answered {tot['other']:,})",
        "",
        "Limits: a report counts only when it names the 510(k) number, so counts are a floor. A report is not proof",
        "that a device caused an event, and counts are not rates.",
    ]
    (out_dir / "MAUDE_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return {"products": len(prod_rows), "missing": len(missing), **tot}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--refresh", action="store_true", help="download every 510(k) again")
    ap.add_argument("--export-only", action="store_true", help="write the CSVs from the cache, no downloads")
    ap.add_argument("--limit", type=int, default=0, help="download at most this many 510(k)s (testing)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    site = cfg.site_data_dir
    out_dir = cfg.output_dir
    cache_dir = out_dir / "maude"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "maude_counts.jsonl"
    meta_path = cache_dir / "maude_meta.json"

    ks = starting_set(site)
    cache = {} if args.refresh else load_cache(cache_path)
    if args.refresh and cache_path.exists():
        cache_path.unlink()
    meta = json.loads(meta_path.read_text()) if meta_path.exists() and not args.refresh else {}

    if not args.export_only:
        key = api_key(cfg.project_dir)
        throttle = Throttle(PER_MINUTE if key else 200)
        get = make_get(key, throttle)
        if not key:
            print("No OPENFDA_API_KEY found. openFDA allows 1,000 requests a day without one; see the notes at the "
                  "top of pipeline/fetch_maude.py.", flush=True)
        if not meta:
            today = date.today()
            meta = {"window_start": (today - timedelta(days=5 * 365)).isoformat(), "today": today.isoformat(),
                    "data_through": last_updated(get)}
            meta_path.write_text(json.dumps(meta))
        since, until = meta["window_start"].replace("-", ""), meta["today"].replace("-", "")
        todo = [k for k in ks if k not in cache]
        if args.limit:
            todo = todo[: args.limit]
        print(f"Counting MAUDE reports for {len(todo):,} of {len(ks):,} orthopedic 510(k)s ...", flush=True)
        lock = threading.Lock()
        done = 0
        with open(cache_path, "a", encoding="utf-8") as fh, ThreadPoolExecutor(WORKERS) as pool:
            for rec in pool.map(lambda k: count_one(get, k, since, until), todo):
                with lock:
                    rec["fetched_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    fh.write(json.dumps(rec) + "\n")
                    fh.flush()
                    cache[rec["knumber"]] = rec
                    done += 1
                    if done % 500 == 0:
                        print(f"  {done:,} of {len(todo):,}", flush=True)

    if not meta:
        print("No MAUDE download yet. Run without --export-only first.")
        return 1
    export(cache, ks, site, out_dir, meta)
    return 0


if __name__ == "__main__":
    sys.exit(main())
