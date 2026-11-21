"""Download FDA establishment registrations that list orthopedic devices, and link each site to the 510(k)s it lists.

Source: openFDA device registration and listing endpoint (public). Every establishment that makes, designs,
relabels, sterilizes, imports or otherwise handles devices for the US market registers with FDA each year and lists
its devices. A listing can name the 510(k) it markets under. This step downloads every listing under the orthopedic
product codes in the starting set and keeps:
  - each establishment (FEI number, firm name, city, state, country, owner/operator, registration year)
  - each link between an establishment and a starting-set 510(k), with the activities the site performs for it

The data shows current registrations only. A site that stopped making a product, or closed, drops out. Contact
names, US agents and official correspondents are not kept.

Key: same as fetch-maude (OPENFDA_API_KEY in the environment, .env or .env.txt). The key is never written out.

Inputs:  outputs/site_data/pc_devices.csv (the starting-set clearances and their product codes)
Cache:   outputs/establishments/<product code>.jsonl (one file per code; the step resumes where it stopped)
Outputs: outputs/site_data/pc_establishment.csv, pc_establishment_510k.csv and outputs/Establishments_Report.txt

Usage:  python orthoparity.py fetch-establishments              (download what is missing, then write the CSVs)
        python orthoparity.py fetch-establishments --refresh    (download everything again)
        python orthoparity.py fetch-establishments --export-only
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from predicate_chain.config import load_config
from pipeline.fetch_maude import Throttle, api_key

URL = "https://api.fda.gov/device/registrationlisting.json"
PAGE = 1000
PER_MINUTE = 200
WORKERS = 6

# Activities FDA lets a site register. "Makes" means the site produces or finishes the device itself.
MAKES = {
    "Manufacture Medical Device",
    "Contract Manufacturer",
    "Contract Manufacturer for Subassembly",
    "Manufacture Medical Device for Another Party (Contract Manufacturer)",
    "Remanufacture Medical Device",
    "Reprocess Single-Use Device",
    "Sterilize Medical Device for Another Party (Contract Sterilizer)",
    "Contract Sterilizer",
}


def make_get(key: str, throttle: Throttle):
    def get(params: dict, tries: int = 6) -> dict:
        p = dict(params)
        if key:
            p["api_key"] = key
        url = URL + "?" + urllib.parse.urlencode(p, safe=':+()"[]')
        for i in range(tries):
            throttle.wait()
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return {"results": [], "meta": {"results": {"total": 0}}}
                if e.code == 429:
                    time.sleep(30 * (i + 1))
                    continue
                if i == tries - 1:
                    raise
            except Exception:
                if i == tries - 1:
                    raise
            time.sleep(3 * (i + 1))
        raise RuntimeError("openFDA did not answer")
    return get


def slim(r: dict) -> dict:
    """Keep firm-level facts only. No contact people, US agents or correspondents."""
    e = r.get("registration") or {}
    oo = e.get("owner_operator") or {}
    return {
        "registration_number": e.get("registration_number") or "",
        "fei_number": e.get("fei_number") or "",
        "name": (e.get("name") or "").strip(),
        "city": (e.get("city") or "").strip(),
        "state": (e.get("state_code") or "").strip(),
        "country": (e.get("iso_country_code") or "").strip(),
        "status_code": e.get("status_code") or "",
        "reg_expiry_year": e.get("reg_expiry_date_year") or "",
        "owner_operator_number": oo.get("owner_operator_number") or "",
        "owner_operator_name": (oo.get("firm_name") or "").strip(),
        "k_number": r.get("k_number") or "",
        "pma_number": r.get("pma_number") or "",
        "proprietary_name": r.get("proprietary_name") or [],
        "establishment_type": r.get("establishment_type") or [],
        "product_codes": sorted({p.get("product_code") or "" for p in r.get("products") or []} - {""}),
    }


def fetch_code(get, code: str) -> list[dict]:
    out, skip = [], 0
    while True:
        d = get({"search": f"products.product_code:{code}", "limit": PAGE, "skip": skip})
        rows = d.get("results", [])
        out.extend(slim(r) for r in rows)
        total = d.get("meta", {}).get("results", {}).get("total", 0)
        skip += PAGE
        if not rows or skip >= total:
            return out
        if skip > 25000:
            raise RuntimeError(f"{code}: more than 25,000 listings; split the query")


def starting_set(site: Path) -> tuple[dict, list[str]]:
    ks, codes = {}, set()
    with open(site / "pc_devices.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("in_starting_set", "")).lower() in ("true", "t", "1", "yes"):
                ks[r["knumber"]] = r.get("product_code") or ""
                if r.get("product_code"):
                    codes.add(r["product_code"])
    return ks, sorted(codes)


# Words that say nothing about which company a firm is. Matching on them would tie unrelated firms together.
LEGAL = set("INC CORP CORPORATION CO COMPANY LLC LTD LIMITED GMBH AG SA SAS SARL BV NV SPA SRL KG PLC LP THE DBA".split())
GENERIC = LEGAL | set("""AND OF DE LA DU FOR USA US INTERNATIONAL INTL GROUP HOLDINGS MEDICAL MEDICALS SURGICAL SURGERY
    ORTHOPEDIC ORTHOPEDICS ORTHOPAEDIC ORTHOPAEDICS ORTHO SPINE SPINAL TECHNOLOGIES TECHNOLOGY DEVICES DEVICE SYSTEMS
    SYSTEM HEALTH HEALTHCARE PRODUCTS SOLUTIONS INNOVATIONS MANUFACTURING SCIENCES LABORATORIES LAB BIOMEDICAL IMPLANTS
    INSTRUMENTS NORTH AMERICA AMERICAS EUROPE IRELAND METAL METALS PRECISION ADVANCED GLOBAL SUPPLY CHAIN SERVICES
    DISTRIBUTION ENTERPRISES INDUSTRIES ENGINEERING""".split())


def _words(s: str) -> list[str]:
    return re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper().replace("&", " ")).split()


def name_tokens(s: str) -> set[str]:
    return {w for w in _words(s) if len(w) >= 3 and w not in GENERIC}


def name_core(s: str) -> str:
    return "".join(w for w in _words(s) if w not in LEGAL)


def load_vendors(site: Path) -> tuple[dict, dict, dict]:
    """Return 510(k) -> parent company, and each parent's name tokens and full names, from the site data."""
    parent = {}
    with open(site / "pc_vendors.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            parent[r["vendor_id"]] = r.get("rolls_up_to") or r["vendor_id"]
    k_parent = {}
    with open(site / "pc_portfolio_510k.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            k_parent[r["knumber"]] = parent.get(r["vendor_id"], r["vendor_id"])
    tokens: dict[str, set] = defaultdict(set)
    cores: dict[str, set] = defaultdict(set)
    names = [(r["vendor_id"], r["raw_name"]) for r in csv.DictReader(open(site / "pc_vendor_names.csv", encoding="utf-8-sig", newline=""))]
    names += [(v, r["display_name"]) for v, r in ((r["vendor_id"], r) for r in csv.DictReader(open(site / "pc_vendors.csv", encoding="utf-8-sig", newline="")))]
    for v, n in names:
        p = parent.get(v, v)
        tokens[p] |= name_tokens(n)
        c = name_core(n)
        if len(c) >= 5:
            cores[p].add(c)
    return k_parent, tokens, cores


def owner_company(owner_name: str, counts: Counter, tokens: dict, cores: dict) -> str:
    """The parent company an owner/operator belongs to: the company holding the most of its listed 510(k)s whose
    names match the owner's name. Distributors, logistics firms and contract manufacturers match none and stay blank."""
    t, c = name_tokens(owner_name), name_core(owner_name)
    for p, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        if t & tokens.get(p, set()):
            return p
        if len(c) >= 5 and any(f in c or c in f for f in cores.get(p, ())):
            return p
    return ""


def norm_k(v: str) -> str:
    v = (v or "").strip().upper()
    return v[1:] if v.startswith("PK") or v.startswith("PDEN") else v


def export(cache_dir: Path, ks: dict, codes: list[str], site: Path, out_dir: Path) -> dict:
    sites: dict[str, dict] = {}
    links: dict[tuple, dict] = {}
    listings = 0
    for code in codes:
        p = cache_dir / f"{code}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            listings += 1
            fei = r["fei_number"] if r["fei_number"] not in ("", "0") else "R" + r["registration_number"]
            s = sites.setdefault(fei, {
                "fei_number": fei, "registration_number": r["registration_number"], "name": r["name"],
                "city": r["city"], "state": r["state"], "country": r["country"],
                "owner_operator_number": r["owner_operator_number"], "owner_operator_name": r["owner_operator_name"],
                "reg_expiry_year": r["reg_expiry_year"], "activities": set(), "product_codes": set(), "knumbers": set(),
            })
            s["activities"].update(r["establishment_type"])
            s["product_codes"].update(c for c in r["product_codes"] if c in codes)
            k = norm_k(r["k_number"])
            if k in ks:
                s["knumbers"].add(k)
                lk = links.setdefault((fei, k), {"fei_number": fei, "knumber": k, "activities": set(), "names": set()})
                lk["activities"].update(r["establishment_type"])
                lk["names"].update(n.strip() for n in r["proprietary_name"] if n and n.strip())
    k_parent, tokens, cores = load_vendors(site)
    owner_counts: dict[str, Counter] = defaultdict(Counter)
    owner_name: dict[str, str] = {}
    for s in sites.values():
        oo = s["owner_operator_number"] or s["fei_number"]
        owner_name.setdefault(oo, s["owner_operator_name"] or s["name"])
        for k in s["knumbers"]:
            if k in k_parent:
                owner_counts[oo][k_parent[k]] += 1
    company = {oo: owner_company(owner_name[oo], c, tokens, cores) for oo, c in owner_counts.items()}
    site.mkdir(parents=True, exist_ok=True)
    with open(site / "pc_establishment.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fei_number", "registration_number", "name", "city", "state", "country", "owner_operator_number",
                    "owner_operator_name", "company_vendor_id", "reg_expiry_year", "activities", "makes_devices",
                    "product_codes", "knumbers"])
        for fei in sorted(sites):
            s = sites[fei]
            w.writerow([fei, s["registration_number"], s["name"], s["city"], s["state"], s["country"],
                        s["owner_operator_number"], s["owner_operator_name"],
                        company.get(s["owner_operator_number"] or fei, ""), s["reg_expiry_year"],
                        "; ".join(sorted(s["activities"])), bool(s["activities"] & MAKES),
                        "; ".join(sorted(s["product_codes"])), len(s["knumbers"])])
    with open(site / "pc_establishment_510k.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fei_number", "knumber", "activities", "makes_device", "proprietary_names"])
        for key in sorted(links):
            lk = links[key]
            w.writerow([lk["fei_number"], lk["knumber"], "; ".join(sorted(lk["activities"])),
                        bool(lk["activities"] & MAKES), "; ".join(sorted(lk["names"]))[:500]])
    linked_ks = {k for (_, k) in links}
    by_country = Counter(s["country"] for s in sites.values() if s["knumbers"])
    stats = {
        "codes": len(codes), "listings": listings, "sites": len(sites),
        "sites_with_510k": sum(1 for s in sites.values() if s["knumbers"]),
        "company_sites": sum(1 for f, s in sites.items() if s["knumbers"] and company.get(s["owner_operator_number"] or f)),
        "making_sites_with_510k": sum(1 for s in sites.values() if s["knumbers"] and s["activities"] & MAKES),
        "links": len(links), "knumbers_linked": len(linked_ks), "starting_set": len(ks),
        "top_countries": by_country.most_common(10),
        "downloaded": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    lines = [
        "Establishment registrations (openFDA registration and listing)",
        f"Downloaded {stats['downloaded']} for {stats['codes']} orthopedic product codes.",
        f"Listings read: {listings:,}. Establishments: {stats['sites']:,}.",
        f"Establishments that list at least one starting-set 510(k): {stats['sites_with_510k']:,} "
        f"({stats['making_sites_with_510k']:,} of them make, contract-make, remanufacture or sterilize).",
        f"Of those, {stats['company_sites']:,} belong to the company that holds the 510(k)s (by owner/operator name); "
        "the rest are contract manufacturers, sterilizers, distributors, importers and other partner firms.",
        f"Site-to-510(k) links: {stats['links']:,}, covering {stats['knumbers_linked']:,} of {len(ks):,} 510(k)s.",
        "Countries with the most linked sites: " + ", ".join(f"{c or 'blank'} {n}" for c, n in stats["top_countries"]),
        "",
        "Limits: current registrations only. A listing names a 510(k) only when the firm entered one, so many",
        "older clearances and 510(k)-exempt products have no site link.",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "Establishments_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    site, out_dir = cfg.site_data_dir, cfg.output_dir
    cache_dir = out_dir / "establishments"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ks, codes = starting_set(site)
    if not args.export_only:
        key = api_key(cfg.project_dir)
        if not key:
            print("No openFDA key found. The step still works, but stops at 1,000 requests a day.")
        get = make_get(key, Throttle(PER_MINUTE))
        todo = [c for c in codes if args.refresh or not (cache_dir / f"{c}.jsonl").exists()]
        print(f"{len(codes)} product codes, {len(todo)} to download")

        def one(code: str) -> str:
            rows = fetch_code(get, code)
            tmp = cache_dir / f"{code}.jsonl.part"
            tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            tmp.replace(cache_dir / f"{code}.jsonl")
            return f"{code} {len(rows)}"

        with ThreadPoolExecutor(WORKERS) as ex:
            for i, msg in enumerate(ex.map(one, todo), 1):
                if i % 25 == 0 or i == len(todo):
                    print(f"  {i}/{len(todo)} codes ({msg})", flush=True)
    export(cache_dir, ks, codes, site, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
