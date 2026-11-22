"""Load FDA premarket approvals (PMA) and humanitarian device exemptions (HDE) for orthopedic devices.

Most Class III devices reach the US market through premarket approval (PMA) instead of 510(k) clearance, and a
few rare-disease devices through a humanitarian device exemption (HDE). Neither pathway uses predicates. Each
approval has an original decision and a history of supplements (design, labeling, manufacturing and site
changes). This step adds them to the website alongside the 510(k)s.

Sources (all public):
  - openFDA PMA endpoint: every PMA record whose advisory committee is Orthopedic (originals and supplements)
  - FDA HDE database (accessdata.fda.gov/scripts/cdrh/cfdocs/cfhde): every Orthopedic HDE record
  - openFDA recall, enforcement, adverse event (MAUDE) and registration-and-listing endpoints, by approval number
  - openFDA classification endpoint for product codes the 510(k) data doesn't cover
  - GUDID and Open Payments, already indexed in the payments database (PAYMENTS_DB) by earlier steps

Supplements: all of them are kept. Each gets a category from FDA's supplement type and reason, and "shown" marks
the ones that change the device, its labeling or its indications, or that set up a post-approval study. Process,
location and other manufacturing changes stay in the data and are counted, not listed, on the page.

Cache:   outputs/approvals/ (pma.json, hde.json, recalls.json, recall_classes.json, maude.jsonl, classification.json)
         outputs/establishments/<product code>.jsonl (shared with fetch-establishments)
Outputs: outputs/site_data/pc_approvals.csv, pc_approval_supplements.csv, pc_approval_rows.csv and
         outputs/Approvals_Report.txt. supabase/13_approvals.sql merges pc_approval_rows into the main tables.

Usage:  python orthoparity.py load-approvals                 (download what is missing, then export)
        python orthoparity.py load-approvals --export-only   (no network; needs the cache and PAYMENTS_DB)
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from predicate_chain.config import load_config
from predicate_chain.paycommon import company_root
from pipeline.build_vendor_registry import family_of, load_families, name_key

PMA_URL = "https://api.fda.gov/device/pma.json"
RECALL_URL = "https://api.fda.gov/device/recall.json"
ENFORCE_URL = "https://api.fda.gov/device/enforcement.json"
CLASS_URL = "https://api.fda.gov/device/classification.json"
HDE_BASE = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfhde/hde.cfm"
PMA_PAGE = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpma/pma.cfm?id={n}"
HDE_PAGE = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfhde/hde.cfm?id={id}"
REF_DIR = Path(__file__).resolve().parent.parent / "reference"

# supplement categories, from FDA's supplement reason (and type for panel-track)
SHOWN = {"new indication", "design change", "labeling change", "post-approval study"}


def category(stype: str, reason: str) -> str:
    t, r = (stype or "").lower(), (reason or "").lower()
    if "panel track" in t:
        return "new indication"
    if r.startswith("change design"):
        return "design change"
    if r.startswith("labeling change"):
        return "labeling change"
    if r.startswith("postapproval study") or r.startswith("post-approval study"):
        return "post-approval study"
    if r.startswith("process change") or r.startswith("express gmp") or "30-day" in t or "30 day" in t or "thirty day" in t:
        return "manufacturing change"
    if r.startswith("location change"):
        return "site change"
    return "other"


def pathway(number: str) -> str:
    n = (number or "").upper()
    return "HDE" if n.startswith("H") else "PMA"


# C1 control characters in FDA text are Windows-1252 bytes read as Latin-1 ("Infuse\x99" is "Infuse™")
C1_FIX = {c: bytes([c]).decode("cp1252", errors="ignore") for c in range(0x80, 0xA0)}


def clean(s) -> str:
    s = " ".join(html.unescape(str(s or "")).translate(C1_FIX).replace("\u00ad", "").split())
    return "" if s.lower() in ("undefined", "null", "none") else s


def clip(s, n):
    s = clean(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ----------------------------------------------------------------------------- downloads
def http_json(url: str, params: dict, tries: int = 5) -> dict:
    full = url + "?" + urllib.parse.urlencode(params, safe=':+()"[]*')
    for i in range(tries):
        try:
            with urllib.request.urlopen(full, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
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


def fetch_pma() -> list[dict]:
    out, skip = [], 0
    while True:
        d = http_json(PMA_URL, {"search": 'advisory_committee:"OR"', "limit": 1000, "skip": skip})
        rows = d.get("results", [])
        out += rows
        skip += len(rows)
        if not rows or skip >= d.get("meta", {}).get("results", {}).get("total", 0):
            return out


def fetch_hde() -> list[dict]:
    """Scrape the FDA HDE database (no API). Polite: one page every few seconds."""
    def page(url):
        for i in range(6):
            with urllib.request.urlopen(url, timeout=90) as r:
                t = r.read().decode("utf-8", "replace")
            if "excessive-requests" not in t:
                return t
            time.sleep(60)
        raise RuntimeError("FDA HDE database keeps refusing requests; try again later")
    q = {"start_search": 1, "advisorycommittee": "OR", "PAGENUM": 500}
    t = page(HDE_BASE + "?" + urllib.parse.urlencode(q))
    ids = sorted(set(re.findall(r"hde\.cfm\?id=(\d+)", t)))
    out = []
    for id_ in ids:
        time.sleep(3.5)
        out.append(parse_hde_detail(id_, page(HDE_PAGE.format(id=id_))))
    return out


def parse_hde_detail(id_: str, t: str) -> dict:
    rec = {"id": id_}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", t, flags=re.S | re.I):
        cells = [clean(re.sub(r"<[^>]+>", " ", c)) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S | re.I)]
        if len(cells) >= 2 and cells[0] and len(cells[0]) < 45 and cells[0] not in rec:
            rec[cells[0]] = cells[1]
    m = re.search(r"Approval Order Statement\s*</[^>]+>(.*?)</t[dr]>", t, flags=re.S | re.I)
    if m:
        rec["ao"] = clean(re.sub(r"<[^>]+>", " ", m.group(1)))
    return rec


def fetch_recalls(numbers: list[str]) -> tuple[list[dict], dict]:
    out = {}
    for i in range(0, len(numbers), 20):
        batch = numbers[i:i + 20]
        d = http_json(RECALL_URL, {"search": "pma_numbers:(" + "+".join(f'"{n}"' for n in batch) + ")", "limit": 1000})
        for r in d.get("results", []):
            out[r.get("product_res_number") or r.get("cfres_id")] = r
    nums = sorted({r["product_res_number"] for r in out.values() if r.get("product_res_number")})
    classes = {}
    for i in range(0, len(nums), 50):
        batch = nums[i:i + 50]
        d = http_json(ENFORCE_URL, {"search": "recall_number:(" + "+".join(f'"{n}"' for n in batch) + ")", "limit": 1000})
        for r in d.get("results", []):
            classes[r.get("recall_number")] = r.get("classification")
    return list(out.values()), classes


def fetch_classification(codes: list[str]) -> dict:
    out = {}
    for c in codes:
        d = http_json(CLASS_URL, {"search": f"product_code:{c}", "limit": 1})
        if d.get("results"):
            x = d["results"][0]
            out[c] = {k: x.get(k) for k in ("product_code", "device_name", "regulation_number", "device_class",
                                              "definition", "review_panel", "implant_flag", "submission_type_id")}
    return out


# ----------------------------------------------------------------------------- build
def load_csv(p: Path) -> list[dict]:
    with open(p, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def mdy(s: str) -> str:
    s = clean(s)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else s


KEEP_CAPS = {"OA", "ACL", "PCL", "MCL", "LCL", "MRI", "MR", "CT", "US", "USA", "U.S.", "FDA", "PMA", "HDE", "BMP", "TKA",
             "THA", "UKA", "PIP", "MCP", "CMC", "MTP", "DDD", "AIS", "HA", "PTFE", "UHMWPE", "PMMA", "PEEK", "EBI", "BAK",
             "LCS", "IFU", "SSED", "ISO", "II", "III", "IV", "AP", "LP", "BHR", "STAR", "ADN", "PAS", "IDE", "NJ", "CA",
             "TX", "TN", "NY", "FL", "MN", "UK", "GMBH", "LLC", "HCL",
             "RH", "CR", "PS", "DC", "EMS", "UV", "EO", "ETO", "QC", "QA", "QMS", "PCR", "DNA", "CHO", "TFA", "OP-1"}


COMMON = {"system", "systems", "device", "devices", "total", "implant", "prosthesis", "with", "and", "the", "for", "bone",
          "knee", "hip", "joint", "graft", "model", "cervical", "lumbar", "spinal", "disc", "artificial", "replacement",
          "inc", "corp", "corporation", "company", "medical", "orthopaedics", "orthopedics", "surgical", "acetabular",
          "ceramic", "cement", "growth", "stimulator", "fusion", "interbody", "cage", "plus", "one", "series",
          "resurfacing", "modular", "porous", "coated", "spine", "spinal", "synthetic", "cartilage", "ligament"}
MONTHS = ("january", "february", "march", "april", "june", "july", "august", "september", "october", "november",
          "december")


def fix_caps(s: str, names: tuple = ()) -> str:
    """FDA's older PMA records are in ALL CAPS. Sentence case them so they read like the rest of the site: the words
    stay FDA's, only the letter case changes. Acronyms, tokens with digits, short parenthesized codes and (R)/(TM)
    marks keep their capitals. Text that is not mostly capitals is returned unchanged."""
    t = clean(s)
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 20 or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return t

    def word(m):
        w = m.group(0)
        pre, post = t[max(0, m.start() - 1):m.start()], t[m.end():m.end() + 1]
        if w.upper() in KEEP_CAPS or any(ch.isdigit() for ch in w):
            return w
        if pre == "(" and post == ")" and (len(w) <= 5 or w in ("R", "TM")):  # (OA), (PRTC), (R), (TM)
            return w
        return w.lower()

    out = re.sub(r"[A-Za-z0-9][A-Za-z0-9'\-]*", word, t)
    # acronyms the text defines in parentheses, e.g. "(PRTC)", keep capitals wherever they recur
    for a in sorted(set(re.findall(r"\(([A-Z]{2,5})\)", t))):
        out = re.sub(r"\b" + a.lower() + r"\b", a, out)
    out = re.sub(r"\b(" + "|".join(MONTHS) + r")\b", lambda m: m.group(1).capitalize(), out)
    # the device's own trade name and the applicant's name read as names, e.g. "Synvisc", "Trident"
    for n in names:
        for w in sorted(set(re.findall(r"[A-Za-z][A-Za-z\-]{3,}", n or "")), key=lambda w: (-len(w), w)):
            if w.lower() not in COMMON:
                out = re.sub(r"\b" + re.escape(w.lower()) + r"\b", w[:1].upper() + w[1:].lower(), out)
    out = re.sub(r"(^|[.!?]\s+|:\s*\d\)\s*|;\s*\d\)\s*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), out)
    return out


def indications_text(s, names: tuple = ()) -> str:
    """The approval order statement, without its opening 'Approval for the <device>.' sentence when an indications
    sentence follows (FDA's wording is otherwise kept, in sentence case when FDA's record is ALL CAPS)."""
    t = fix_caps(s, names)
    m = re.match(r"(?i)\s*approval for [^.]{0,200}?\.\s+(?=.*\bindicated\b)", t)
    t = t[m.end():] if m else t
    return t[:1].upper() + t[1:]


def approvals_from_sources(pma: list[dict], hde: list[dict]) -> tuple[dict, list[dict]]:
    """One record per approval number (original), plus every supplement."""
    apps, sups = {}, []
    by_num = defaultdict(list)
    for r in pma:
        by_num[r["pma_number"]].append(r)
    for n, rows in by_num.items():
        orig = [r for r in rows if not r.get("supplement_number")]
        first = orig[0] if orig else min(rows, key=lambda r: r.get("decision_date") or "9999")
        apps[n] = {
            "number": n, "pathway": "PMA", "trade_name": clean(first.get("trade_name")),
            "generic_name": clean(first.get("generic_name")), "applicant": clean(first.get("applicant")),
            "product_code": clean(first.get("product_code")) or Counter(clean(r.get("product_code")) for r in rows).most_common(1)[0][0],
            "decision_date": clean(first.get("decision_date")) if orig else "",
            "date_received": clean(first.get("date_received")) if orig else "",
            "decision_code": clean(first.get("decision_code")) if orig else "",
            "expedited": clean(first.get("expedited_review_flag")) == "Y",
            "city": clean(first.get("city")), "state": clean(first.get("state")),
            "indications": indications_text(first.get("ao_statement"), (first.get("trade_name"), first.get("applicant"))) if orig else "",
            "original_on_file": bool(orig), "fei_numbers": sorted({f for r in rows for f in (r.get("openfda") or {}).get("fei_number", []) if f}),
            "url": PMA_PAGE.format(n=n),
        }
        if not orig:  # openFDA has supplements only: the original decision date is the earliest supplement's, as a floor
            apps[n]["note"] = "openFDA has no record of the original approval; dates and names come from its supplements"
        for r in rows:
            if r.get("supplement_number"):
                sups.append({"number": n, "supplement_number": clean(r["supplement_number"]),
                             "supplement_type": clean(r.get("supplement_type")), "supplement_reason": clean(r.get("supplement_reason")),
                             "decision_date": clean(r.get("decision_date")), "decision_code": clean(r.get("decision_code")),
                             "trade_name": clean(r.get("trade_name")), "change": clip(fix_caps(r.get("ao_statement"), (r.get("trade_name"), r.get("applicant"))), 600)})
    hby = defaultdict(list)
    for r in hde:
        n = clean(r.get("HDE Number"))
        if n:
            hby[n].append(r)
    for n, rows in hby.items():
        orig = [r for r in rows if not clean(r.get("Supplement Number"))]
        first = orig[0] if orig else min(rows, key=lambda r: mdy(r.get("Decision Date", "")) or "9999")
        apps[n] = {
            "number": n, "pathway": "HDE", "trade_name": clean(first.get("Trade Name") or first.get("Device")),
            "generic_name": clean(first.get("Generic Name")), "applicant": clean(first.get("applicant") or first.get("Applicant")),
            "product_code": clean(first.get("Product Code", ""))[:3], "decision_date": mdy(first.get("Decision Date", "")) if orig else "",
            "date_received": mdy(first.get("Date Received", "")) if orig else "", "decision_code": "APPR" if orig else "",
            "expedited": clean(first.get("Expedited Review Granted?")).lower() == "yes", "city": "", "state": "",
            "indications": indications_text(first.get("ao"), (first.get("Trade Name"), first.get("applicant"))) if orig else "", "original_on_file": bool(orig), "fei_numbers": [],
            "url": HDE_PAGE.format(id=first["id"]),
        }
        for r in rows:
            s = clean(r.get("Supplement Number"))
            if s:
                sups.append({"number": n, "supplement_number": s, "supplement_type": clean(r.get("Supplement Type")),
                             "supplement_reason": clean(r.get("Supplement Reason")), "decision_date": mdy(r.get("Decision Date", "")),
                             "decision_code": "", "trade_name": clean(r.get("Trade Name")), "change": clip(fix_caps(r.get("ao"), (r.get("Trade Name"), r.get("applicant"))), 600)})
    for s in sups:
        s["category"] = category(s["supplement_type"], s["supplement_reason"])
        s["shown"] = s["category"] in SHOWN
    return apps, sups


def match_vendors(apps: dict, site: Path) -> tuple[dict, list, list]:
    """Applicant name -> vendor id: exact name on file, then a curated family, then the company root, else new."""
    vendors = {r["vendor_id"]: r for r in load_csv(site / "pc_vendors.csv")}
    names = load_csv(site / "pc_vendor_names.csv")
    exact = {}
    root = defaultdict(set)
    seen_app = {(clean(r["raw_name"]).lower(), r["source"]) for r in names if r["source"] == "applicant"}
    for r in names:
        exact.setdefault(clean(r["raw_name"]).lower(), r["vendor_id"])
        rt = company_root(r["raw_name"])
        if rt:
            root[rt].add(r["vendor_id"])
    fams = load_families()
    new_vendors, new_names, out = {}, [], {}
    for a in apps.values():
        app = a["applicant"]
        vid, how = exact.get(app.lower()), "applicant name on file"
        if not vid:
            fam = family_of(app, fams)
            if fam:
                vid, how = fam["vendor_id"], "curated family"
        if not vid:
            c = root.get(company_root(app), set())
            if len(c) == 1:
                vid, how = next(iter(c)), "company name"
        if not vid:
            vid, how = "n_" + (name_key(app) or company_root(app)), "new vendor (own name)"
            if vid not in vendors and vid not in new_vendors:
                new_vendors[vid] = {"vendor_id": vid, "display_name": re.sub(r"\s+,", ",", app), "current_parent": "", "segment": "",
                                    "basis": "own name", "reviewed": False,
                                    "note": "Added with FDA premarket approvals (Phase 5); first seen as an approval applicant",
                                    "clearances": 0, "first_clearance_year": None, "last_clearance_year": None,
                                    "gudid_ortho_devices": 0, "gudid_brands": 0, "payment_kind": None, "rolls_up_to": vid}
        top = (vendors.get(vid) or new_vendors.get(vid) or {}).get("rolls_up_to") or vid
        out[a["number"]] = (top, how)
        if (app.lower(), "applicant") not in seen_app:
            # FDA's exact applicant spelling, so the owner card can tell the filer and today's owner are one company
            new_names.append({"vendor_id": vid, "source": "applicant", "raw_name": app, "basis": how})
            seen_app.add((app.lower(), "applicant"))
            exact.setdefault(app.lower(), vid)
    return out, list(new_vendors.values()), new_names


def same_company(owner_root: str, roots: list) -> bool:
    """A registered site's owner is the approval's company when the names share their first six letters or one
    contains the other ("genzyme" in "sanofigenzyme"). Roots shorter than six letters never match by containment."""
    for r in roots:
        if not r or not owner_root:
            continue
        if owner_root[:6] == r[:6] and len(owner_root) >= 4 and len(r) >= 4:
            return True
        if len(owner_root) >= 6 and len(r) >= 6 and (owner_root in r or r in owner_root):
            return True
    return False


def gudid_and_payments(numbers: list[str], vendor_of: dict, db_path: Path) -> tuple[dict, list, list]:
    """Device counts and brands per approval from GUDID, and product-level Open Payments, from PAYMENTS_DB."""
    import duckdb
    con = duckdb.connect(str(db_path), read_only=True)
    con.execute("CREATE TEMP TABLE appr(n VARCHAR)")
    con.executemany("INSERT INTO appr VALUES (?)", [[n] for n in numbers])
    per = {}
    for n, brand, devs, dist in con.execute("""
        WITH sd AS (SELECT DISTINCT s.submission_number AS n, d.primary_di, d.brand, d.distribution_status
                    FROM gudid_submissions s JOIN appr a ON a.n = s.submission_number JOIN gudid_devices d USING (primary_di)),
        b AS (SELECT n, brand, row_number() OVER (PARTITION BY n ORDER BY count(*) DESC, brand) AS rk
              FROM sd WHERE coalesce(brand, '') <> '' GROUP BY n, brand)
        SELECT sd.n, any_value(b.brand), count(DISTINCT sd.primary_di),
               count(DISTINCT sd.primary_di) FILTER (WHERE sd.distribution_status = 'In Commercial Distribution')
        FROM sd LEFT JOIN b ON b.n = sd.n AND b.rk = 1 GROUP BY sd.n""").fetchall():
        per[n] = (brand, devs, dist)
    # brands: only device IDs that cite no 510(k), so 510(k) brand rows are not double counted
    brands = []
    for n, brand, codes, devs, dist, impl in con.execute("""
        WITH only_appr AS (
          SELECT s.primary_di, min(s.submission_number) AS n FROM gudid_submissions s JOIN appr a ON a.n = s.submission_number
          WHERE NOT EXISTS (SELECT 1 FROM gudid_submissions k WHERE k.primary_di = s.primary_di
                            AND (k.submission_number LIKE 'K%' OR k.submission_number LIKE 'DEN%'))
          GROUP BY s.primary_di)
        SELECT o.n, d.brand, string_agg(DISTINCT pc.product_code, '|' ORDER BY pc.product_code),
               count(DISTINCT d.primary_di),
               count(DISTINCT d.primary_di) FILTER (WHERE d.distribution_status = 'In Commercial Distribution'),
               bool_or(d.implantable = 'true')
        FROM only_appr o JOIN gudid_devices d USING (primary_di) LEFT JOIN gudid_product_codes pc USING (primary_di)
        WHERE coalesce(d.brand, '') <> '' GROUP BY o.n, d.brand""").fetchall():
        brands.append({"vendor_id": vendor_of[n][0], "brand": brand, "product_codes": codes or "", "knumbers": n,
                       "devices": devs, "in_distribution": dist, "implantable": bool(impl)})
    # product payments, same tiers as build-payment-aggregates: 1 = device ID resolves to the approval in GUDID,
    # 2 = brand named without a device ID, matched to the approval's GUDID brands.
    # Read from op_general, not pay_fact: pay_fact keeps only payers in the 510(k) vendor registry and orthopedic
    # product codes, so it drops most approval makers (hyaluronic acid makers, for example). Recipients are counted
    # inside DuckDB from the raw identifiers; no recipient key leaves the database.
    from pipeline.build_payment_aggregates import NATURE_SQL
    pay = []
    have_pf = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'op_general'").fetchone()[0]
    if have_pf:
        rows = con.execute(r"""
          WITH bk AS (SELECT DISTINCT trim(regexp_replace(regexp_replace(regexp_replace(upper(coalesce(d.brand, '')),
                         '[®™©]', '', 'g'), '[^A-Z0-9 ]', ' ', 'g'), '\s+', ' ', 'g')) AS raw_bkey, s.submission_number AS n
                      FROM gudid_submissions s JOIN appr a ON a.n = s.submission_number JOIN gudid_devices d USING (primary_di)
                      WHERE coalesce(d.brand, '') <> ''),
          -- a brand also used on 510(k) devices (Stryker's "Trident", for example) is ambiguous without a device ID:
          -- those payments stay with the 510(k) pages, so the approval page never double counts them
          kb AS (SELECT DISTINCT trim(regexp_replace(regexp_replace(regexp_replace(upper(coalesce(d.brand, '')),
                         '[®™©]', '', 'g'), '[^A-Z0-9 ]', ' ', 'g'), '\s+', ' ', 'g')) AS raw_bkey
                 FROM gudid_submissions s JOIN gudid_devices d USING (primary_di)
                 WHERE s.submission_number LIKE 'K%' OR s.submission_number LIKE 'DEN%'),
          slots AS (
            SELECT m.source, m.year, m.record_id, s.submission_number AS n, 1 AS tier, d.brand, m.payer_vendor
            FROM op_product_match m JOIN gudid_submissions s ON s.primary_di = m.primary_di JOIN appr a ON a.n = s.submission_number
            LEFT JOIN gudid_devices d ON d.primary_di = m.primary_di
            WHERE m.tier = 1
            UNION
            SELECT m.source, m.year, m.record_id, bk.n, 2, m.matched_brand, m.payer_vendor
            FROM op_product_match m JOIN bk ON bk.raw_bkey = trim(regexp_replace(regexp_replace(regexp_replace(
                   upper(coalesce(m.matched_brand, '')), '[®™©]', '', 'g'), '[^A-Z0-9 ]', ' ', 'g'), '\s+', ' ', 'g'))
            WHERE m.tier = 2 AND bk.raw_bkey <> '' AND bk.raw_bkey NOT IN (SELECT raw_bkey FROM kb))
          SELECT ps.n, ps.tier, g.year, g.nature_group, min(ps.brand), min(ps.payer_vendor),
                 count(DISTINCT g.record_id), sum(g.amount), count(DISTINCT g.recipient)
          FROM (SELECT DISTINCT source, year, record_id, n, tier, brand, payer_vendor FROM slots WHERE source = 'general') ps
          JOIN (SELECT year, record_id, amount, """ + NATURE_SQL + r""" AS nature_group,
                       CASE WHEN recipient_type ILIKE '%teaching hospital%' THEN 'TH:' || coalesce(teaching_hospital_ccn, '')
                            ELSE coalesce(nullif(npi, ''), 'P' || profile_id) END AS recipient
                FROM op_general) g ON g.year = ps.year AND g.record_id = ps.record_id
          GROUP BY ps.n, ps.tier, g.year, g.nature_group""").fetchall()
        for n, tier, year, ng, brand, vpit, tx, amt, rec in rows:
            pay.append({"knumber": n, "tier": tier, "year": year, "nature_group": ng, "brand": brand,
                        "vendor_pit": vpit, "transactions": tx, "amount": round(float(amt or 0), 2), "recipients": rec})
    con.close()
    return per, brands, pay


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    site, out = cfg.site_data_dir, cfg.output_dir
    cache = out / "approvals"
    cache.mkdir(parents=True, exist_ok=True)
    est_cache = out / "establishments"

    def cached(name, fn):
        p = cache / name
        if p.exists() and not args.refresh:
            return json.loads(p.read_text(encoding="utf-8"))
        if args.export_only:
            raise SystemExit(f"{p} is missing; run without --export-only on a computer with internet")
        v = fn()
        p.write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        return v

    pma = cached("pma.json", fetch_pma)
    hde = cached("hde.json", fetch_hde)
    apps, sups = approvals_from_sources(pma, hde)
    numbers = sorted(apps)
    known_codes = {r["product_code"] for r in load_csv(site / "pc_product_codes.csv")}
    app_codes = sorted({a["product_code"] for a in apps.values() if a["product_code"]})
    new_codes = [c for c in app_codes if c not in known_codes]
    cls = cached("classification.json", lambda: fetch_classification(new_codes))
    rec = cached("recalls.json", lambda: fetch_recalls(numbers))
    recalls, rclass = rec if isinstance(rec, list) else (rec["recalls"], rec["classes"])

    # MAUDE, with the same rules and five-year window as fetch-maude
    from pipeline.fetch_maude import Throttle, api_key, count_one, make_get, split_types
    old = load_csv(site / "pc_maude_product.csv")
    window_start = old[0]["window_start"] if old else (date.today() - timedelta(days=5 * 365)).isoformat()
    data_through = old[0]["data_through"] if old else date.today().isoformat()
    mp = cache / "maude.jsonl"
    maude = {}
    if mp.exists() and not args.refresh:
        for line in mp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                maude[r["knumber"]] = r
    todo = [n for n in numbers if n not in maude]
    if todo and not args.export_only:
        get = make_get(api_key(cfg.project_dir), Throttle(200))
        with open(mp, "a", encoding="utf-8") as fh:
            for n in todo:
                r = count_one(get, n, window_start.replace("-", ""), data_through.replace("-", ""))
                maude[n] = r
                fh.write(json.dumps(r) + "\n")

    # establishments: listings under the approvals' product codes (same cache as fetch-establishments)
    from pipeline.fetch_establishments import MAKES, fetch_code
    from pipeline.fetch_establishments import make_get as est_get
    est_cache.mkdir(parents=True, exist_ok=True)
    if not args.export_only:
        eget = est_get(api_key(cfg.project_dir), Throttle(200))
        for c in app_codes:
            p = est_cache / f"{c}.jsonl"
            if not p.exists() or args.refresh:
                rows = fetch_code(eget, c)
                p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    vendor_of, new_vendors, new_names = match_vendors(apps, site)
    per, brands, pay = gudid_and_payments(numbers, vendor_of, _payments_db(cfg))

    # supplement summaries per approval
    sc = defaultdict(Counter)
    last = {}
    for s in sups:
        sc[s["number"]][s["category"]] += 1
        if s["shown"] and s["decision_date"] >= last.get(s["number"], ("",))[0]:
            last[s["number"]] = (s["decision_date"], s["category"])
    dict_rows = {r["product_code"]: r for r in load_csv(REF_DIR / "approval_product_codes.csv")}
    pc_rows = {r["product_code"]: r for r in load_csv(site / "pc_product_codes.csv")}

    def cur_class(code):
        """The product code's class today: FDA has moved some PMA codes to Class II (bone cement, interbody cages)."""
        c = str((pc_rows.get(code) or {}).get("device_class") or (cls.get(code) or {}).get("device_class") or "").strip()
        return c if c in ("1", "2") else "3"

    def seg(code):
        return (pc_rows.get(code) or dict_rows.get(code) or {}).get("segment", "")

    rows = []  # (target, dict)
    approvals_out = []
    for n in numbers:
        a = apps[n]
        vid = vendor_of[n][0]
        brand, devs, dist = per.get(n, (None, 0, 0))
        c = sc[n]
        dd = a["decision_date"] or min((s["decision_date"] for s in sups if s["number"] == n), default="")
        approvals_out.append({
            "number": n, "pathway": a["pathway"], "trade_name": a["trade_name"], "generic_name": a["generic_name"],
            "applicant": a["applicant"], "vendor_id": vid, "vendor_basis": vendor_of[n][1], "product_code": a["product_code"],
            "decision_date": dd, "original_on_file": a["original_on_file"], "date_received": a["date_received"],
            "expedited": a["expedited"], "indications": a["indications"], "url": a["url"],
            "supplements": sum(c.values()), "supplements_shown": sum(v for k, v in c.items() if k in SHOWN),
            "new_indications": c["new indication"], "design_changes": c["design change"], "labeling_changes": c["labeling change"],
            "study_changes": c["post-approval study"], "manufacturing_changes": c["manufacturing change"],
            "site_changes": c["site change"], "other_changes": c["other"],
            "last_change_date": last.get(n, ("", ""))[0], "last_change_type": last.get(n, ("", ""))[1],
            "note": a.get("note", ""),
        })
        rows.append(("pc_devices", {
            "knumber": n, "device_name": a["trade_name"], "applicant": a["applicant"], "decision_date": dd,
            "decision_year": dd[:4], "product_code": a["product_code"],
            "regulation_number": (pc_rows.get(a["product_code"]) or {}).get("regulation_number") or (cls.get(a["product_code"]) or {}).get("regulation_number") or "",
            "device_class": cur_class(a["product_code"]) if a["pathway"] == "PMA" else "HDE", "review_panel": "OR", "segment": seg(a["product_code"]),
            "in_starting_set": True, "status": "approved", "stop_reason": "", "summary_url": a["url"],
            "brand": brand or "", "company_root": company_root(a["applicant"])}))
        rows.append(("pc_portfolio_510k", {
            "vendor_id": vid, "knumber": n, "device_name": a["trade_name"], "applicant": a["applicant"],
            "product_code": a["product_code"], "decision_date": dd or None, "gudid_brand": brand, "gudid_devices": devs,
            "gudid_in_distribution": dist}))
        if a["indications"]:
            rows.append(("pc_ifu", {"knumber": n, "ifu_text": a["indications"], "page": "",
                                    "source": "FDA approval order statement", "found": True}))
        m = maude.get(n)
        if m and m.get("by_type"):
            t5, t = split_types(m.get("by_type_last5", {})), split_types(m["by_type"])
            ys = sorted(m.get("by_year", {}))
            rows.append(("pc_maude_product", {
                "knumber": n, "reports": t["reports"], "deaths": t["deaths"], "injuries": t["injuries"],
                "malfunctions": t["malfunctions"], "other": t["other"], "reports_last5": t5["reports"],
                "deaths_last5": t5["deaths"], "injuries_last5": t5["injuries"], "malfunctions_last5": t5["malfunctions"],
                "other_last5": t5["other"], "first_year": int(ys[0]) if ys else None, "last_year": int(ys[-1]) if ys else None,
                "window_start": window_start, "data_through": data_through}))
            for y in ys:
                rows.append(("pc_maude_year", {"knumber": n, "year": int(y), "reports": int(m["by_year"][y])}))
    for r in recalls:
        ns = sorted({x for x in (r.get("pma_numbers") or []) if x in apps})
        if not ns:
            continue
        ks = sorted({k for k in (r.get("k_numbers") or []) if k})
        dates = {}
        for f in ("event_date_initiated", "event_date_posted", "event_date_terminated"):
            v = r.get(f)
            dates[f] = v if v and "1976" <= v[:4] <= "2100" else None
        rows.append(("pc_recalls", {
            "recall_number": r.get("product_res_number"), "event_id": r.get("res_event_number"),
            "initiated": dates["event_date_initiated"], "posted": dates["event_date_posted"],
            "terminated": dates["event_date_terminated"], "status": r.get("recall_status"),
            "recall_class": (rclass.get(r.get("product_res_number")) or "NOT FOUND"),
            "product_code": r.get("product_code"), "knumbers": "|".join(ks + ns),
            "recalling_firm": r.get("recalling_firm"), "vendor_id": vendor_of[ns[0]][0], "vendor_basis": "approval number",
            "product": clip(r.get("product_description"), 300), "reason": clip(r.get("reason_for_recall"), 600),
            "root_cause": r.get("root_cause_description"), "quantity": clip(r.get("product_quantity"), 80)}))
    # sites that list an approval number
    sites, links = {}, {}
    for c in app_codes:
        p = est_cache / f"{c}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            n = (r.get("pma_number") or "").strip().upper()
            if n not in apps:
                continue
            fei = r["fei_number"] if r["fei_number"] not in ("", "0") else "R" + r["registration_number"]
            s = sites.setdefault(fei, {"fei_number": fei, "registration_number": r["registration_number"], "name": r["name"],
                                       "city": r["city"], "state": r["state"], "country": r["country"],
                                       "owner_operator_number": r["owner_operator_number"],
                                       "owner_operator_name": r["owner_operator_name"], "company_vendor_id": None,
                                       "reg_expiry_year": int(r["reg_expiry_year"]) if str(r["reg_expiry_year"]).isdigit() else None,
                                       "acts": set(), "codes": set(), "ns": set()})
            s["acts"].update(r["establishment_type"])
            s["codes"].update(r["product_codes"])
            s["ns"].add(n)
            lk = links.setdefault((fei, n), {"acts": set(), "names": set()})
            lk["acts"].update(r["establishment_type"])
            lk["names"].update(x.strip() for x in r["proprietary_name"] if x and x.strip())
    for fei, s in sites.items():
        oo = company_root(s["owner_operator_name"] or s["name"])
        vid = next((vendor_of[n][0] for n in sorted(s["ns"])
                    if same_company(oo, [company_root(vendor_of[n][0].replace("n_", "")), company_root(apps[n]["applicant"])])),
                   None)
        rows.append(("pc_establishment", {
            "fei_number": fei, "registration_number": s["registration_number"], "name": s["name"], "city": s["city"],
            "state": s["state"], "country": s["country"], "owner_operator_number": s["owner_operator_number"],
            "owner_operator_name": s["owner_operator_name"], "company_vendor_id": vid,
            "reg_expiry_year": s["reg_expiry_year"], "activities": "; ".join(sorted(s["acts"])),
            "makes_devices": bool(s["acts"] & MAKES), "product_codes": "; ".join(sorted(s["codes"])), "knumbers": len(s["ns"])}))
    for (fei, n), lk in links.items():
        rows.append(("pc_establishment_510k", {"fei_number": fei, "knumber": n, "activities": "; ".join(sorted(lk["acts"])),
                                               "makes_device": bool(lk["acts"] & MAKES),
                                               "proprietary_names": "; ".join(sorted(lk["names"]))[:500]}))
    for b in brands:
        rows.append(("pc_portfolio_brands", b))
    for p in pay:
        rows.append(("pc_op_product", p))
    for v in new_vendors:
        rows.append(("pc_vendors", v))
    for v in new_names:
        rows.append(("pc_vendor_names", v))
    for c in new_codes:
        d, k = dict_rows.get(c, {}), cls.get(c, {})
        rows.append(("pc_product_codes", {
            "product_code": c, "fda_name": (k.get("device_name") or d.get("note", "").split(". Reviewed by")[0].replace("FDA name: ", "")),
            "regulation_number": k.get("regulation_number") or "", "device_class": k.get("device_class") or "",
            "fda_definition": k.get("definition") or "", "plain_name": d.get("plain_name") or "NOT FOUND",
            "plain_description": d.get("plain_description") or "", "anatomy": d.get("anatomy") or "",
            "procedures": d.get("procedures") or "", "kind": d.get("kind") or "", "segment": d.get("segment") or "",
            "clearances": 0, "reviewed": d.get("status") == "reviewed"}))

    # Medicare procedure links for codes only approvals use (procedure_devices.csv must hold 510(k) codes only)
    fam_ids = {r["family_id"] for r in load_csv(REF_DIR / "procedure_families.csv")}
    for r in load_csv(REF_DIR / "approval_procedure_links.csv"):
        if r["family_id"] not in fam_ids:
            raise SystemExit(f"approval_procedure_links.csv: unknown family {r['family_id']}")
        if r["status"] == "reviewed" and r["product_code"] in app_codes:
            rows.append(("pc_procedure_devices", {"family_id": r["family_id"], "role": r["role"], "product_code": r["product_code"]}))

    site.mkdir(parents=True, exist_ok=True)
    acols = list(approvals_out[0].keys())
    with open(site / "pc_approvals.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=acols, lineterminator="\n")
        w.writeheader()
        w.writerows(approvals_out)
    scols = ["number", "supplement_number", "supplement_type", "supplement_reason", "category", "shown",
             "decision_date", "decision_code", "trade_name", "change"]
    with open(site / "pc_approval_supplements.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=scols, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(sups, key=lambda s: (s["number"], s["decision_date"], s["supplement_number"])))
    with open(site / "pc_approval_rows.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["target", "row"])
        for t, r in sorted(rows, key=lambda x: (x[0], json.dumps(x[1], ensure_ascii=False, default=str, sort_keys=True))):
            w.writerow([t, json.dumps(r, ensure_ascii=False, default=str)])

    cnt = Counter(t for t, _ in rows)
    lines = [
        "FDA premarket approvals (PMA) and humanitarian device exemptions (HDE), orthopedic",
        f"Built: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"Approvals: {len(apps):,} ({sum(1 for a in apps.values() if a['pathway'] == 'PMA')} PMA, "
        f"{sum(1 for a in apps.values() if a['pathway'] == 'HDE')} HDE); originals on file: "
        f"{sum(1 for a in apps.values() if a['original_on_file'])}",
        f"Supplements: {len(sups):,}; shown on pages: {sum(1 for s in sups if s['shown']):,}; by category: "
        + ", ".join(f"{k} {v:,}" for k, v in Counter(s['category'] for s in sups).most_common()),
        f"Indications from the approval order statement: {sum(1 for a in apps.values() if a['indications']):,} "
        f"of {len(apps):,} (NOT FOUND for the rest)",
        f"Product codes new to the site: {len(new_codes)} ({', '.join(new_codes)})",
        "Vendor match: " + ", ".join(f"{k} {v}" for k, v in Counter(h for _, h in vendor_of.values()).most_common()),
        f"New vendors: {len(new_vendors)}",
        "Rows for the main tables: " + ", ".join(f"{k} {v:,}" for k, v in sorted(cnt.items())),
    ]
    (out / "Approvals_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def _payments_db(cfg) -> Path:
    from predicate_chain.paycommon import PaySettings
    return PaySettings(cfg).db


if __name__ == "__main__":
    sys.exit(main())
