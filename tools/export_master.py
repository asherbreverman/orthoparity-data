"""Master outputs: CSV exports and Corpus_Summary.xlsx (aggregates only, no chains).

Usage:  python orthoparity.py export-master
Writes outputs/exports/{nodes,edges,documents,flags,review_queue,review_decisions}.csv and outputs/Corpus_Summary.xlsx.
Each table is exported at the newest parser version recorded for each K-number; review decisions are all kept.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import sys
from collections import deque

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from predicate_chain import PARSER_VERSION, TOOL_VERSION
from predicate_chain.chains import latest_versions, review_overrides
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.lookup_core import LIMITATIONS

FONT = "Arial"


def export_csvs(cfg, con, versions) -> dict:
    out = cfg.output_dir / "exports"
    out.mkdir(parents=True, exist_ok=True)
    counts = {}

    def dump(name, sql, params=(), keep=None):
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        n = 0
        with (out / f"{name}.csv").open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in cur:
                if keep and not keep(r):
                    continue
                w.writerow(["" if v is None else v for v in r])
                n += 1
        counts[name] = n

    latest = lambda r: versions.get(r[0]) == r[1]  # noqa: E731  (knumber, parser_version) first two columns
    dump("nodes", "SELECT knumber, parser_version, in_starting_set, stateorsumm, decision_year, status, stop_reason, "
                  "stop_detail, distance, discovered_from, updated_at_utc FROM node_status ORDER BY knumber", keep=latest)
    dump("edges", "SELECT child_knumber, parser_version, edge_id, predicate_number, predicate_base, predicate_kind, "
                  "list_order, role, role_basis, printed_label, family_of, printed_name, printed_company, fda_applicant, "
                  "fda_device_name, fda_decision_date, fda_product_code, fda_review_panel, identity_source, "
                  "name_match_score, company_match, in_predicate_section, section_heading, confidence, page, evidence "
                  "FROM edges ORDER BY child_knumber, list_order", keep=latest)
    dump("documents", "SELECT knumber, parser_version, fetch_outcome, url, url_source, sha256, bytes, retrieved_at_utc, "
                      "file_source, cache_path, page_count, text_method, text_chars, pdf_own_knumber, "
                      "predicate_sections, parse_status, parse_notes, parsed_at_utc FROM documents ORDER BY knumber",
         keep=latest)
    dump("flags", "SELECT knumber, parser_version, flag_id, flag_type, number, detail, page, evidence FROM flags "
                  "ORDER BY knumber", keep=latest)
    dump("review_queue", "SELECT knumber, parser_version, queue_id, item_type, ref_id, reason, status FROM review_queue "
                         "WHERE parser_version=? ORDER BY knumber", (PARSER_VERSION,))
    dump("review_decisions", "SELECT * FROM review_decisions ORDER BY decision_id")
    return counts


def chain_stats(con, versions):
    """Depth and earliest decision year of every starting-set clearance's full ancestor chain (review decisions applied)."""
    ov = review_overrides(con)
    adj = collections.defaultdict(set)
    for c, v, p in con.execute("SELECT child_knumber, parser_version, predicate_number FROM edges "
                               "WHERE predicate_number IS NOT NULL"):
        if versions.get(c) != v:
            continue
        o = ov.get((c, p))
        if o and o[0] == "drop":
            continue
        adj[c].add(o[1] if o and o[0] == "replace" else p)
    year = {}
    for k, y in con.execute("SELECT knumber, decision_year FROM fda_master"):
        year[k] = y
    for k, y in con.execute("SELECT knumber, decision_year FROM clearances"):
        year[k] = y
    cfg = load_config()
    depth, earliest = collections.Counter(), collections.Counter()
    for (s,) in con.execute("SELECT knumber FROM clearances"):
        seen = {s: 0}
        dq = deque([s])
        while dq:
            x = dq.popleft()
            if seen[x] >= cfg.max_generations:
                continue
            for p in adj.get(x, ()):
                if p not in seen:
                    seen[p] = seen[x] + 1
                    dq.append(p)
        depth[max(seen.values())] += 1
        ys = [year[n] for n in seen if year.get(n)]
        earliest[(min(ys) // 5) * 5 if ys else None] += 1
    return depth, earliest


def corpus_summary(cfg, con, versions, counts) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Read_me"
    lines = ["OrthoParity corpus summary (aggregates only; use the lookup tool for individual chains)",
             f"Created {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. Parser {PARSER_VERSION}, tool "
             f"{TOOL_VERSION}. Newest parser version per K-number.", "",
             "Tabs: Stop_reasons, Confidence, Parse_status, Clearance_year, Chain_depth, Earliest_year, Exports.", "",
             "Limitations"] + [f"- {t}" for t in LIMITATIONS]
    for t in lines:
        ws.append([t])
    ws["A1"].font = Font(name=FONT, size=13, bold=True)
    ws.column_dimensions["A"].width = 140
    hdr = PatternFill("solid", fgColor="123B5E")

    def tab(name, headers, rows, chart_title=None):
        s = wb.create_sheet(name)
        s.append(headers)
        for c in s[1]:
            c.font = Font(name=FONT, bold=True, color="FFFFFF")
            c.fill = hdr
        for r in rows:
            s.append(list(r))
        n = len(rows)
        s.append(["Total", f"=SUM(B2:B{n + 1})"] + [f"=SUM({get_column_letter(i)}2:{get_column_letter(i)}{n + 1})"
                                                  for i in range(3, len(headers) + 1)])
        for row in s.iter_rows(min_row=2):
            for c in row:
                c.font = Font(name=FONT, size=10, bold=(c.row == n + 2))
                if c.column > 1:
                    c.number_format = "#,##0"
        s.column_dimensions["A"].width = 46
        for i in range(2, len(headers) + 1):
            s.column_dimensions[get_column_letter(i)].width = 18
        if chart_title and n:
            ch = BarChart()
            ch.type = "col"
            ch.title = chart_title
            ch.roundedCorners = False
            ch.legend = None
            ch.x_axis.delete = False
            ch.y_axis.delete = False
            ch.add_data(Reference(s, min_col=2, min_row=1, max_row=n + 1), titles_from_data=True)
            ch.set_categories(Reference(s, min_col=1, min_row=2, max_row=n + 1))
            ch.height, ch.width = 8, 18
            s.add_chart(ch, f"{get_column_letter(len(headers) + 2)}2")
        return s

    ss = {r[0] for r in con.execute("SELECT knumber FROM clearances")}
    st_rows = collections.defaultdict(lambda: [0, 0])
    for k, v, sr in con.execute("SELECT knumber, parser_version, stop_reason FROM node_status"):
        if versions.get(k) == v:
            st_rows[sr or "(continues: has predicates)"][0 if k in ss else 1] += 1
    tab("Stop_reasons", ["Stop reason", "Starting-set clearances", "Ancestors outside the starting set"],
        sorted(([k, a, b] for k, (a, b) in st_rows.items()), key=lambda r: -(r[1] + r[2])))
    conf = collections.Counter()
    for c, v, cf in con.execute("SELECT child_knumber, parser_version, confidence FROM edges"):
        if versions.get(c) == v:
            conf[cf or "(none)"] += 1
    tab("Confidence", ["Edge confidence", "Edges"], conf.most_common())
    ps = collections.Counter()
    for k, v, p in con.execute("SELECT knumber, parser_version, parse_status FROM documents"):
        if versions.get(k) == v:
            ps[p or "(none)"] += 1
    tab("Parse_status", ["Parse status", "Documents"], ps.most_common())
    yr = collections.Counter(r[0] for r in con.execute("SELECT decision_year FROM clearances"))
    tab("Clearance_year", ["Decision year (starting set)", "Clearances"], sorted(yr.items()),
        "Orthopedic clearances by year")
    depth, earliest = chain_stats(con, versions)
    tab("Chain_depth", ["Deepest generation in the full chain", "Starting-set clearances"], sorted(depth.items()),
        "Chain depth (generations)")
    tab("Earliest_year", ["Earliest decision year reached (5-year bucket)", "Starting-set clearances"],
        [[f"{k}-{k + 4}" if k is not None else "no dated ancestor", v]
         for k, v in sorted(earliest.items(), key=lambda x: (x[0] is None, x[0] or 0))],
        "Earliest ancestor year per chain")
    tab("Exports", ["CSV file in outputs/exports", "Rows"], [[f"{k}.csv", v] for k, v in counts.items()])
    wb.calculation.fullCalcOnLoad = True
    wb.save(cfg.output_dir / "Corpus_Summary.xlsx")


def main() -> int:
    cfg = load_config()
    con = connect(cfg.db_path)
    init_schema(con)
    versions = latest_versions(con)
    counts = export_csvs(cfg, con, versions)
    for k, v in counts.items():
        print(f"  outputs/exports/{k}.csv  {v:,} rows")
    corpus_summary(cfg, con, versions, counts)
    print("  outputs/Corpus_Summary.xlsx")
    return 0


if __name__ == "__main__":
    sys.exit(main())
