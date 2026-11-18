"""Export the lookup data for a Supabase + Lovable website.

Usage:  python orthoparity.py export-predicates
Writes outputs/site_data/:
  pc_devices.csv   one row per device (starting set plus every ancestor), identity from FDA records by number
  pc_edges.csv     predicate links as the lookup uses them (current parser, Phase 4 review decisions applied)
  pc_flags.csv     parser flags on the current version
  pc_meta.csv      version, counts, and the limitations text the site must show
The database itself is not changed. Each CSV stays well under Supabase's 100 MB dashboard import limit.
"""
from __future__ import annotations

import csv
import datetime as dt
import sys

from predicate_chain import PARSER_VERSION, TOOL_VERSION
from predicate_chain.chains import latest_versions, review_overrides
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.lookup_core import LIMITATIONS, _ident, brand_token, clean, company_root

EVIDENCE_CHARS = 240


PC_COLUMNS = ["product_code", "fda_name", "regulation_number", "device_class", "fda_definition", "plain_name",
              "plain_description", "anatomy", "procedures", "kind", "segment", "clearances", "reviewed"]


def product_code_rows(con, cfg):
    """FDA product-code facts plus the plain-English dictionary (reviewed values win over Claude's drafts)."""
    from pipeline.product_dictionary import load_dictionary
    entries = load_dictionary(cfg)
    rows = []
    for r in con.execute("SELECT c.product_code, COUNT(*) AS n, p.device_name, p.regulation_number, p.device_class, "
                         "p.definition FROM clearances c LEFT JOIN product_codes p ON p.product_code=c.product_code "
                         "WHERE c.product_code IS NOT NULL GROUP BY c.product_code ORDER BY n DESC"):
        seg = con.execute("SELECT unofficial_segment, COUNT(*) FROM clearances WHERE product_code=? GROUP BY 1 "
                          "ORDER BY 2 DESC LIMIT 1", (r["product_code"],)).fetchone()
        e = entries.get(r["product_code"], {})
        rows.append([r["product_code"], clean(r["device_name"]), r["regulation_number"], r["device_class"],
                     clean(r["definition"]), e.get("plain_name"), e.get("plain_description"), e.get("anatomy"),
                     e.get("procedures"), e.get("kind"), seg[0] if seg else None, r["n"],
                     "true" if e.get("reviewed") else "false"])
    return rows


def ifu_rows(cfg):
    import json
    path = cfg.output_dir / "ifu" / "ifu.jsonl"
    if not path.exists():
        return []
    seen = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        seen[r["knumber"]] = r
    return [[k, r.get("text"), r.get("page"), r.get("source"), "true" if r.get("found") else "false"]
            for k, r in sorted(seen.items())]


def write(path, header, rows) -> int:
    n = 0
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])
            n += 1
    return n


def main() -> int:
    cfg = load_config()
    con = connect(cfg.db_path)
    init_schema(con)
    out = cfg.site_data_dir
    out.mkdir(parents=True, exist_ok=True)
    versions = latest_versions(con)
    ov = review_overrides(con)
    reviews = {}
    for k, n, dec, src in con.execute("SELECT knumber, predicate_number, decision, decision_source FROM "
                                      "review_decisions WHERE predicate_number IS NOT NULL "
                                      "AND decision_source='Claude review' ORDER BY decided_at_utc, decision_id"):
        reviews[(k, n)] = (dec, src)

    # devices: starting set plus every node reachable through current edges (and corrected numbers)
    status = {}
    for k, v, st, sr in con.execute("SELECT knumber, parser_version, status, stop_reason FROM node_status"):
        if versions.get(k) == v:
            status[k] = (st, sr)
    url = {}
    for k, v, u in con.execute("SELECT knumber, parser_version, url FROM documents"):
        if versions.get(k) == v:
            url[k] = u
    edges = []
    numbers = set()
    for r in con.execute("SELECT * FROM edges WHERE predicate_number IS NOT NULL ORDER BY child_knumber, list_order"):
        if versions.get(r["child_knumber"]) != r["parser_version"]:
            continue
        o = ov.get((r["child_knumber"], r["predicate_number"]))
        if o and o[0] == "drop":
            continue
        used = o[1] if o and o[0] == "replace" else r["predicate_number"]
        dec, src = reviews.get((r["child_knumber"], r["predicate_number"]), (None, "parser"))
        edges.append([r["edge_id"], r["child_knumber"], used,
                      r["predicate_number"] if used != r["predicate_number"] else None, r["role"], r["confidence"],
                      dec, src, r["page"], clean(r["printed_label"]), clean(r["evidence"])[:EVIDENCE_CHARS],
                      r["list_order"]])
        numbers.add(used)
    starting = {r[0] for r in con.execute("SELECT knumber FROM clearances")}
    devices = []
    for k in sorted(starting | set(status) | numbers):
        i = _ident(con, k)
        st, sr = status.get(k, (None, None))
        devices.append([k, i["devicename"], i["applicant"], i["decision_date"],
                        str(i["decision_date"])[:4] if i["decision_date"] else None, i["product_code"],
                        i["regulation_number"], i["device_class"], i["review_panel"], i["unofficial_segment"],
                        "true" if k in starting else "false", st or "not extracted", sr, url.get(k),
                        brand_token(i["devicename"]) if k in starting else None,
                        company_root(i["applicant"]) or None])
    flags = []
    for r in con.execute("SELECT flag_id, knumber, parser_version, flag_type, number, detail FROM flags"):
        if versions.get(r["knumber"]) == r["parser_version"]:
            dec = reviews.get((r["knumber"], r["number"]), (None, None))[0]
            flags.append([r["flag_id"], r["knumber"], r["flag_type"], r["number"], clean(r["detail"])[:200], dec])

    counts = {
        "pc_devices": write(out / "pc_devices.csv",
                            ["knumber", "device_name", "applicant", "decision_date", "decision_year", "product_code",
                             "regulation_number", "device_class", "review_panel", "segment", "in_starting_set",
                             "status", "stop_reason", "summary_url", "brand", "company_root"], devices),
        "pc_edges": write(out / "pc_edges.csv",
                          ["edge_id", "child", "predicate", "number_as_printed", "role", "confidence",
                           "review_decision", "review_source", "page", "printed_label", "evidence", "list_order"],
                          edges),
        "pc_flags": write(out / "pc_flags.csv", ["flag_id", "knumber", "flag_type", "number", "detail",
                                                 "review_decision"], flags),
    }
    counts["pc_product_codes"] = write(out / "pc_product_codes.csv", PC_COLUMNS, product_code_rows(con, cfg))
    counts["pc_ifu"] = write(out / "pc_ifu.csv", ["knumber", "ifu_text", "page", "source", "found"], ifu_rows(cfg))
    meta = [("parser_version", PARSER_VERSION), ("tool_version", TOOL_VERSION),
            ("max_generations", str(cfg.max_generations)),
            ("exported_utc", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")),
            ("starting_set_clearances", str(len(starting)))] + \
           [(f"rows_{k}", str(v)) for k, v in counts.items()] + \
           [(f"limitation_{i:02d}", t) for i, t in enumerate(LIMITATIONS, 1)]
    write(out / "pc_meta.csv", ["key", "value"], meta)
    for f in sorted(out.glob("*.csv")):
        print(f"  {f.name:16} {f.stat().st_size / 1e6:6.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
