"""Phase B1: draft the vendor registry for Benchmark a Vendor.

A vendor owns many raw names from three sources:
  payer      Open Payments paying entity (by payer ID)
  applicant  510(k) applicant name in the predicate database
  labeler    GUDID labeler (by DUNS number), orthopedic product codes only

How names are assigned, in order:
  1. Curated families (reference/vendor_families.csv): a regular expression on the name with spaces and
     punctuation removed. Claude drafted these; Asher reviews them.
  2. Evidence: a labeler joins the vendor that filed 60% or more of the 510(k)s its orthopedic devices cite;
     a payer joins the vendor whose devices make up 60% or more of its device-ID tags.
  3. Otherwise the cleaned name itself (legal suffixes and words like Holdings removed) is the vendor.
Ownership over time comes from reference/vendor_lineage.csv (every date has a source link).

Writes tables vendors, vendor_entities, vendor_lineage, vendor_cross_tags into data/payments.duckdb and the
review workbook reviews/Vendor_Registry_REVIEW.xlsx. Re-running keeps answers typed in the yellow columns,
and applies them: a vendor rename or parent correction, or moving a name to another vendor.
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from predicate_chain.config import load_config
from predicate_chain.paycommon import CO_SUFFIX, PaySettings, connect_duck, mark_step

EXTRA_GENERIC = {"holdings", "holding", "group", "international", "intl", "global", "worldwide", "america",
                 "americas", "north", "the", "of", "and", "dba"}
REF_DIR = Path(__file__).resolve().parent.parent / "reference"
REVIEW_FILE = "Vendor_Registry_REVIEW.xlsx"
EVIDENCE_SHARE, PAYER_MIN_TAGS, LABELER_MIN_DEVICES = 0.6, 50, 5


def squash(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower().replace("&", "").replace("+", ""))


def name_key(name: str | None) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", (name or "").lower().replace("+", " "))
             if w not in CO_SUFFIX and w not in EXTRA_GENERIC and len(w) > 1]
    return "".join(words) or squash(name)


def _tokens(name: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (name or "").lower())
            if len(w) >= 4 and w not in CO_SUFFIX and w not in EXTRA_GENERIC and w not in GENERIC_WORDS}


GENERIC_WORDS = {"medical", "surgical", "orthopedic", "orthopedics", "orthopaedic", "orthopaedics", "spine", "spinal",
                 "systems", "system", "technologies", "technology", "devices", "device", "solutions", "products",
                 "instruments", "health", "healthcare", "sciences", "science", "innovations", "biologics", "implants",
                 "industries", "manufacturing", "enterprises", "partners", "services", "sales", "company"}


def names_overlap(name: str, others: list[str]) -> bool:
    """True when two names plainly belong together: one cleaned name contains the other, or they share a
    distinctive word of four letters or more (not generic words like Medical or Spine)."""
    k = name_key(name)
    t = _tokens(name)
    for o in others:
        ko = squash(o)
        if len(k) >= 4 and (k in ko or name_key(o) in squash(name)):
            return True
        if t & _tokens(o):
            return True
    return False


def load_families(path: Path | None = None):
    path = path or REF_DIR / "vendor_families.csv"
    fams = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            r["rx"] = re.compile(r["name_regex"])
            fams.append(r)
    return fams


def load_lineage(path: Path | None = None):
    path = path or REF_DIR / "vendor_lineage.csv"
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def family_of(name: str, fams) -> dict | None:
    s = squash(name)
    for f in fams:
        if f["rx"].search(s):
            return f
    return None


# ----------------------------------------------------------------------------- review workbook answers
VENDOR_REVIEW_COLS = ["OK? (Y/N)", "Correct vendor name", "Correct current parent", "Notes"]
ENTITY_REVIEW_COLS = ["Move to vendor_id", "Notes"]
LINEAGE_REVIEW_COLS = ["OK? (Y/N)", "Correct date", "Notes"]


def read_answers(path: Path) -> dict:
    out = {"vendors": {}, "entities": {}, "lineage": {}}
    if not path.exists():
        return out
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    for sheet, key_cols, review_cols, bucket in (("Vendors", ["vendor_id"], VENDOR_REVIEW_COLS, "vendors"),
                                                 ("Names", ["source", "key"], ENTITY_REVIEW_COLS, "entities"),
                                                 ("Ownership events", ["vendor_id", "parent", "valid_from"],
                                                  LINEAGE_REVIEW_COLS, "lineage")):
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        hdr_i = next((i for i, r in enumerate(rows) if r and key_cols[0] in r), None)
        if hdr_i is None:
            continue
        hdr = [str(h) if h is not None else "" for h in rows[hdr_i]]
        for r in rows[hdr_i + 1:]:
            rec = dict(zip(hdr, r))
            key = tuple(str(rec.get(k) or "") for k in key_cols)
            ans = {c: (rec.get(c).strip() if isinstance(rec.get(c), str) else rec.get(c)) for c in review_cols
                   if rec.get(c) not in (None, "") and not (isinstance(rec.get(c), str) and not rec.get(c).strip())}
            if ans and key[0] and not key[0].startswith("(example)"):
                out[bucket][key if len(key) > 1 else key[0]] = ans
    return out


# ----------------------------------------------------------------------------- build
def build(con, cfg, answers: dict, fams, lineage) -> dict:
    sq = sqlite3.connect(str(cfg.db_path))
    applicants = Counter()
    first_last = {}
    app_k = defaultdict(list)
    for k, a, y in sq.execute("SELECT knumber, applicant, decision_year FROM clearances"):
        applicants[a] += 1
        app_k[a].append(k)
        if y:
            y = int(y)
            lo, hi = first_last.get(a, (y, y))
            first_last[a] = (min(lo, y), max(hi, y))
    sq.close()
    k_app = {k: a for a, ks in app_k.items() for k in ks}

    vendors: dict[str, dict] = {}
    entity_rows: list[dict] = []
    moves = {k: v["Move to vendor_id"] for k, v in answers["entities"].items() if v.get("Move to vendor_id")}

    def vend(vid, display, basis, parent="", segment="", note=""):
        if vid not in vendors:
            vendors[vid] = {"vendor_id": vid, "display_name": display, "basis": basis, "current_parent": parent,
                            "segment": segment, "note": note}
        return vid

    for f in fams:
        vend(f["vendor_id"], f["display_name"], "curated family", f["current_parent"], f["segment"], f["note"])

    names_of = defaultdict(list)

    def assign(source, key, raw, evidence_vid=None, evidence=""):
        mv = moves.get((source, str(key)))
        suggestion = ""
        if mv:
            vid, basis = mv, "moved by reviewer"
            vend(vid, raw, "reviewer")
        else:
            f = family_of(raw, fams)
            if f:
                vid, basis = f["vendor_id"], "curated family name match"
            elif evidence_vid and names_overlap(raw, names_of[evidence_vid] + [vendors[evidence_vid]["display_name"]]):
                vid, basis = evidence_vid, evidence
            else:
                if evidence_vid:
                    suggestion = f"{vendors[evidence_vid]['display_name']} ({evidence})"
                vid = "n_" + name_key(raw)
                basis = "own name"
                vend(vid, raw, "own name")
        names_of[vid].append(raw)
        entity_rows.append({"source": source, "key": str(key), "raw_name": raw, "vendor_id": vid, "basis": basis,
                            "suggestion": suggestion})
        return vid

    # 1. applicants
    app_vendor = {a: assign("applicant", a, a) for a in applicants}

    # 2. GUDID labelers with orthopedic devices
    lab = con.execute("""
        SELECT d.duns, mode(d.company) AS company, count(DISTINCT d.primary_di) AS devices,
               count(DISTINCT d.brand) AS brands
        FROM gudid_devices d JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o ON o.primary_di = d.primary_di
        WHERE coalesce(d.duns, '') <> '' GROUP BY d.duns""").fetchall()
    lab_k = defaultdict(Counter)
    for duns, k in con.execute("""
        SELECT d.duns, s.submission_number FROM gudid_devices d
        JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o ON o.primary_di = d.primary_di
        JOIN gudid_submissions s ON s.primary_di = d.primary_di WHERE s.submission_number LIKE 'K%'""").fetchall():
        if k in k_app:
            lab_k[duns][app_vendor[k_app[k]]] += 1
    labeler_vendor, labeler_meta = {}, {}
    for duns, company, devices, brands in lab:
        ev_vid, ev = None, ""
        c = lab_k.get(duns)
        if c:
            top, n = c.most_common(1)[0]
            tot = sum(c.values())
            if n >= LABELER_MIN_DEVICES and n / tot >= EVIDENCE_SHARE:
                ev_vid, ev = top, f"{n / tot:.0%} of its devices cite this vendor's 510(k)s"
        labeler_vendor[duns] = assign("labeler", duns, company, ev_vid, ev)
        labeler_meta[duns] = (company, devices, brands)

    # 3. in-scope payers
    tags = defaultdict(Counter)
    for pid, duns, n in con.execute("""
        SELECT g.payer_id, d.duns, count(*) FROM op_products p
        JOIN op_general g ON g.record_id = p.record_id AND g.year = p.year AND g.payer_in_scope
        JOIN gudid_identifiers i ON i.di = p.pdi_norm
        JOIN gudid_devices d ON d.primary_di = i.primary_di
        JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o ON o.primary_di = d.primary_di
        WHERE p.source = 'general' GROUP BY 1, 2""").fetchall():
        if duns in labeler_vendor:
            tags[pid][labeler_vendor[duns]] += n
    payers = con.execute("""SELECT s.payer_id, s.payer_name, s.scope_reason, coalesce(sum(g.amount), 0),
                                   count(DISTINCT g.year)
                            FROM payer_scope s LEFT JOIN op_general g ON g.payer_id = s.payer_id AND g.payer_in_scope
                            WHERE s.in_scope GROUP BY ALL""").fetchall()
    payer_vendor = {}
    for pid, pname, reason, amount, years in payers:
        ev_vid, ev = None, ""
        c = tags.get(pid)
        if c:
            top, n = c.most_common(1)[0]
            tot = sum(c.values())
            if n >= PAYER_MIN_TAGS and n / tot >= EVIDENCE_SHARE:
                ev_vid, ev = top, f"{n / tot:.0%} of its orthopedic device tags are this vendor's devices"
        payer_vendor[pid] = assign("payer", pid, pname, ev_vid, ev)

    # display names for vendors that stand on their own name: latest payer name, else the most used applicant
    # name, else the labeler name
    payer_name_of = {p[0]: p[1] for p in payers}
    for vid, v in vendors.items():
        if v["basis"] != "own name":
            continue
        ents = [e for e in entity_rows if e["vendor_id"] == vid]
        pn = [payer_name_of[e["key"]] for e in ents if e["source"] == "payer"]
        an = [e["raw_name"] for e in ents if e["source"] == "applicant"]
        ln = [e["raw_name"] for e in ents if e["source"] == "labeler"]
        if pn:
            v["display_name"] = pn[0]
        elif an:
            v["display_name"] = max(an, key=lambda a: applicants[a])
        elif ln:
            v["display_name"] = ln[0]

    # reviewer renames / parents
    for vid, ans in answers["vendors"].items():
        if vid in vendors:
            if ans.get("Correct vendor name"):
                vendors[vid]["display_name"] = str(ans["Correct vendor name"])
            if ans.get("Correct current parent"):
                vendors[vid]["current_parent"] = str(ans["Correct current parent"])
            vendors[vid]["reviewed"] = str(ans.get("OK? (Y/N)", "")).strip().upper() in ("Y", "YES")

    # metrics
    pay_amt = {p[0]: (p[3], p[4]) for p in payers}
    m = defaultdict(lambda: {"clearances": 0, "first": None, "last": None, "devices": 0, "brands": 0,
                             "payments": 0.0, "payer_names": [], "applicant_names": Counter(), "labeler_names": [],
                             "cross": Counter(), "own_tags": 0})
    for a, vid in app_vendor.items():
        mm = m[vid]
        mm["clearances"] += applicants[a]
        mm["applicant_names"][a] += applicants[a]
        lo, hi = first_last.get(a, (None, None))
        if lo:
            mm["first"] = lo if mm["first"] is None else min(mm["first"], lo)
        if hi:
            mm["last"] = hi if mm["last"] is None else max(mm["last"], hi)
    for duns, vid in labeler_vendor.items():
        company, devices, brands = labeler_meta[duns]
        m[vid]["devices"] += devices
        m[vid]["brands"] += brands
        m[vid]["labeler_names"].append(company)
    cross_rows = []
    for pid, vid in payer_vendor.items():
        amt, years = pay_amt[pid]
        mm = m[vid]
        mm["payments"] += amt
        mm["payer_names"].append(next(p[1] for p in payers if p[0] == pid))
        c = tags.get(pid, Counter())
        tot = sum(c.values())
        for other, n in c.items():
            if other != vid and tot and n / tot >= 0.10:
                mm["cross"][other] += n
                cross_rows.append([pid, vid, other, n, round(n / tot, 3)])

    # write tables
    con.execute("""CREATE OR REPLACE TABLE vendors (vendor_id VARCHAR PRIMARY KEY, display_name VARCHAR,
        basis VARCHAR, current_parent VARCHAR, segment VARCHAR, note VARCHAR, reviewed BOOLEAN, clearances INT,
        first_clearance_year INT, last_clearance_year INT, gudid_ortho_devices INT, gudid_brands INT,
        payments_2019_2025 DOUBLE)""")
    con.executemany("INSERT INTO vendors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        [v["vendor_id"], v["display_name"], v["basis"], v.get("current_parent", ""), v.get("segment", ""),
         v.get("note", ""), bool(v.get("reviewed")), m[v["vendor_id"]]["clearances"], m[v["vendor_id"]]["first"],
         m[v["vendor_id"]]["last"], m[v["vendor_id"]]["devices"], m[v["vendor_id"]]["brands"],
         round(m[v["vendor_id"]]["payments"], 2)] for v in vendors.values()])
    con.execute("""CREATE OR REPLACE TABLE vendor_entities (source VARCHAR, entity_key VARCHAR, raw_name VARCHAR,
        vendor_id VARCHAR, basis VARCHAR, suggestion VARCHAR)""")
    con.executemany("INSERT INTO vendor_entities VALUES (?,?,?,?,?,?)",
                    [[e["source"], e["key"], e["raw_name"], e["vendor_id"], e["basis"], e["suggestion"]]
                     for e in entity_rows])
    con.execute("""CREATE OR REPLACE TABLE vendor_lineage (vendor_id VARCHAR, parent VARCHAR, relation VARCHAR,
        valid_from DATE, valid_to DATE, source_url VARCHAR, note VARCHAR, reviewed BOOLEAN)""")
    lin_rows = []
    for r in lineage:
        key = (r["vendor_id"], r["parent"], r["valid_from"] or "")
        ans = answers["lineage"].get(key, {})
        vf = str(ans.get("Correct date") or r["valid_from"] or "") or None
        lin_rows.append([r["vendor_id"], r["parent"], r["relation"], vf, r["valid_to"] or None, r["source_url"],
                         r["note"], str(ans.get("OK? (Y/N)", "")).strip().upper() in ("Y", "YES")])
    con.executemany("INSERT INTO vendor_lineage VALUES (?,?,?,?,?,?,?,?)", lin_rows)
    con.execute("""CREATE OR REPLACE TABLE vendor_cross_tags (payer_id VARCHAR, payer_vendor VARCHAR,
        tagged_vendor VARCHAR, tags BIGINT, share DOUBLE)""")
    if cross_rows:
        con.executemany("INSERT INTO vendor_cross_tags VALUES (?,?,?,?,?)", cross_rows)
    return {"vendors": vendors, "metrics": m, "entities": entity_rows, "lineage": lineage, "answers": answers,
            "payers": payers}


# ----------------------------------------------------------------------------- workbook
def write_workbook(path: Path, res: dict, top_n: int = 300):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    yellow = PatternFill("solid", fgColor="FFF2CC")
    head = Font(name="Arial", bold=True)
    body = Font(name="Arial")
    vendors, m, answers = res["vendors"], res["metrics"], res["answers"]
    disp = {v: vendors[v]["display_name"] for v in vendors}

    def sheet(wb, title, legend, cols, rows, review_cols, widths):
        ws = wb.create_sheet(title)
        ws.append([legend])
        ws["A1"].font = Font(name="Arial", italic=True)
        ws.append(cols + review_cols)
        for c in ws[2]:
            c.font = head
        for r in rows:
            ws.append(r)
        for row in ws.iter_rows(min_row=3):
            for c in row:
                c.font = body
                c.alignment = Alignment(wrap_text=True, vertical="top")
        for j in range(len(cols) + 1, len(cols) + len(review_cols) + 1):
            for i in range(2, ws.max_row + 1):
                ws.cell(row=i, column=j).fill = yellow
        for j, w in enumerate(widths + [18] * len(review_cols), start=1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "B3"
        return ws

    wb = Workbook()
    ws = wb.active
    ws.title = "README"
    for line in [
        "Vendor registry review (OrthoParity, Benchmark a Vendor)",
        "",
        "What this is: Claude's draft of which company names belong to which vendor, and who owns each vendor over time.",
        "Names come from three public sources: Open Payments paying entities, 510(k) applicants, and GUDID labelers.",
        "Yellow columns are yours. Leave a cell blank to accept the draft. Re-running the script keeps your answers.",
        "",
        "Vendors tab: one row per vendor (top 300 by payments or 510(k)s). Type Y in 'OK?' when the grouping and parent look right.",
        "   Use 'Correct vendor name' or 'Correct current parent' to fix them. The example row shows the format.",
        "Names tab: every name and the vendor it landed in. To move a name, type the right vendor_id in 'Move to vendor_id'.",
        "   'Evidence suggests' flags names whose devices point at another vendor but whose names differ (often a",
        "   distributor, an acquisition or a private label). They stay separate unless you move them.",
        "Ownership events tab: dated acquisitions and divestitures with a source link. Type Y when right, or a corrected date (YYYY-MM-DD).",
        "Cross tags tab: payers whose device-ID tags point at another vendor's devices (10% or more). These are usually",
        "   acquisitions, distribution deals or transition services. Nothing is merged on this evidence alone.",
        "",
        "Basis column: 'curated family' = Claude's name pattern (reference/vendor_families.csv); 'NN% of ...' = device or",
        "   510(k) evidence; 'own name' = no match, the cleaned name stands alone. Payments are all products from orthopedic",
        "   payers before the orthopedic product filter, so diversified companies (Medtronic, J&J) show more than their",
        "   orthopedic spend here.",
    ]:
        ws.append([line])
    ws.column_dimensions["A"].width = 130
    for c in ws["A"]:
        c.font = body
    ws["A1"].font = Font(name="Arial", bold=True, size=12)

    ranked = sorted(vendors, key=lambda v: (-m[v]["payments"], -m[v]["clearances"]))
    by_510k = sorted(vendors, key=lambda v: -m[v]["clearances"])[:100]
    curated = [v for v in vendors if vendors[v]["basis"] == "curated family"]
    keep = list(dict.fromkeys(curated + ranked[:top_n] + by_510k))
    keep = [v for v in keep if m[v]["payments"] or m[v]["clearances"] or m[v]["devices"]]
    keep.sort(key=lambda v: -m[v]["payments"])
    example = ["(example) n_acmespine", "Acme Spine", "own name", "", "", 1234567, 12, "2015-2025", 340, 18,
               "Acme Spine, LLC", "ACME SPINE LLC", "ACME SPINE, LLC", "", "Y", "", "Acme Holdings", "Parent per 2025 10-K"]
    rows = [example]
    for v in keep:
        mm = m[v]
        ans = answers["vendors"].get(v, {})
        rows.append([v, vendors[v]["display_name"], vendors[v]["basis"], vendors[v].get("current_parent", ""),
                     vendors[v].get("segment", ""), round(mm["payments"]), mm["clearances"],
                     f"{mm['first']}-{mm['last']}" if mm["first"] else "", mm["devices"], mm["brands"],
                     "; ".join(sorted(set(mm["payer_names"])))[:500],
                     "; ".join(a for a, _ in mm["applicant_names"].most_common(8))[:500],
                     "; ".join(sorted(set(mm["labeler_names"])))[:500],
                     "; ".join(f"{disp.get(o, o)}" for o, _ in mm["cross"].most_common(4)),
                     ans.get("OK? (Y/N)"), ans.get("Correct vendor name"), ans.get("Correct current parent"),
                     ans.get("Notes")])
    sheet(wb, "Vendors", "One row per vendor. Yellow columns are yours; the first row is an example.",
          ["vendor_id", "Vendor (draft)", "Basis", "Current parent (draft)", "Segment",
           "Payments 2019-2025 ($, orthopedic payers, all products)", "510(k) clearances", "Clearance years",
           "GUDID orthopedic devices", "GUDID brands", "Open Payments names", "510(k) applicant names (top 8)",
           "GUDID labeler names", "Tags other vendors' devices (10%+)"],
          rows, VENDOR_REVIEW_COLS, [22, 30, 18, 24, 18, 16, 10, 12, 10, 9, 40, 45, 40, 30])

    ent = []
    for e in sorted(res["entities"], key=lambda e: (vendors[e["vendor_id"]]["display_name"].lower(), e["source"])):
        ans = answers["entities"].get((e["source"], e["key"]), {})
        ent.append([e["source"], e["key"], e["raw_name"], e["vendor_id"], vendors[e["vendor_id"]]["display_name"],
                    e["basis"], e.get("suggestion", ""), ans.get("Move to vendor_id"), ans.get("Notes")])
    sheet(wb, "Names", "Every name and the vendor it landed in. To move one, type the target vendor_id (from the Vendors tab).",
          ["source", "key", "Name as printed", "vendor_id", "Vendor", "Basis",
           "Evidence suggests (not applied: names differ)"], ent, ENTITY_REVIEW_COLS, [10, 22, 45, 22, 30, 40, 45])

    lin = []
    for r in res["lineage"]:
        ans = answers["lineage"].get((r["vendor_id"], r["parent"], r["valid_from"] or ""), {})
        lin.append([r["vendor_id"], disp.get(r["vendor_id"], r["vendor_id"]), r["parent"],
                    disp.get(r["parent"], r["parent"]), r["relation"], r["valid_from"], r["valid_to"],
                    r["source_url"], r["note"], ans.get("OK? (Y/N)"), ans.get("Correct date"), ans.get("Notes")])
    sheet(wb, "Ownership events", "Dated ownership changes with sources. Payments before valid_from count under the earlier owner.",
          ["vendor_id", "Vendor", "parent", "Parent", "Relation", "valid_from", "valid_to", "Source", "Note"],
          lin, LINEAGE_REVIEW_COLS, [16, 26, 16, 26, 26, 12, 12, 50, 40])

    ct = []
    pn = {p[0]: p[1] for p in res["payers"]}
    for v in keep:
        for o, n in m[v]["cross"].most_common():
            ct.append([vendors[v]["display_name"], disp.get(o, o), n])
    sheet(wb, "Cross tags", "Orthopedic device-ID tags pointing at another vendor's devices (10% or more of a payer's tags).",
          ["Payer's vendor", "Tagged vendor", "Tags (2021-2025)"], ct, [], [32, 32, 14])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp.xlsx")
    wb.save(tmp)
    tmp.replace(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    review = cfg.review_dir / REVIEW_FILE
    answers = read_answers(review)
    res = build(con, cfg, answers, load_families(), load_lineage())
    write_workbook(review, res)
    n_v = sum(1 for v in res["vendors"] if res["metrics"][v]["payments"] or res["metrics"][v]["clearances"])
    by = Counter(f"{e['source']}: " + ("device or 510(k) evidence" if "%" in e["basis"] else e["basis"])
                 for e in res["entities"])
    by["names with an evidence suggestion to review"] = sum(1 for e in res["entities"] if e["suggestion"])
    mark_step(con, "B1_registry", n_v, 0, "; ".join(f"{k}={v}" for k, v in by.items()))
    print(f"Vendor registry: {n_v:,} vendors with clearances or payments, {len(res['entities']):,} names.")
    for k, v in by.most_common():
        print(f"  {k}: {v:,}")
    print(f"Review workbook: {review}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
