"""Excel workbook for one lookup: Predicate_Chain_[Product]_[YYYY-MM-DD].xlsx."""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import PARSER_VERSION, TOOL_VERSION
from .lookup_core import LIMITATIONS, Lookup, audit_lines, benchmark_rows, clean, earliest_year, role_label, stop_text

FONT = "Arial"
HDR = PatternFill("solid", fgColor="123B5E")
INPUT = PatternFill("solid", fgColor="FFFF00")
WRAP = Alignment(wrap_text=True, vertical="top")


def _date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _xml(v):
    if isinstance(v, str):
        v = "".join(ch for ch in v if ch in "\t\n\r" or ord(ch) >= 32)[:32000]
        return " " + v if v[:1] in ("=", "+", "-", "@") and not v[1:2].isdigit() else v  # text, never a formula
    return v


def _sheet(wb, title, headers, rows, widths=None, wrap_cols=()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HDR
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for r in rows:
        ws.append([_xml(v) for v in r])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font = Font(name=FONT, size=10)
            if c.column in wrap_cols:
                c.alignment = WRAP
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    return ws


def write_workbook(res: Lookup, path: Path, cfg, tree_files: tuple | None = None) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    bench = benchmark_rows(res)
    n = len(bench)

    # ---- Summary (formulas over the Benchmark tab) ----------------------------
    ws = wb.create_sheet("Summary")
    subj = [res.nodes[k] for k in res.roots if k in res.nodes]
    top = [
        ("OrthoParity ancestor lookup", None),
        ("Product", res.label),
        ("Subject device(s)", ", ".join(f"{k} {clean(s['devicename'])} ({clean(s['applicant'])})"
                                         for k, s in zip(res.roots, subj))),
        ("Created (UTC)", res.created_utc),
        ("Parser version", PARSER_VERSION),
        ("Tool version", TOOL_VERSION),
        ("Generation limit", res.chain.max_generations),
        (None, None),
        ("Devices in the chain (including the subject)", f"=COUNTA(Benchmark!C2:C{n + 1})"),
        ("Deepest generation reached", f"=MAX(Benchmark!A2:A{n + 1})"),
        ("Earliest decision year reached", f"=YEAR(MIN(Benchmark!F2:F{n + 1}))"),
        ("Edges HIGH confidence", f'=COUNTIF(Edges!K2:K{len(res.edges) + 1},"HIGH")'),
        ("Edges MEDIUM confidence", f'=COUNTIF(Edges!K2:K{len(res.edges) + 1},"MEDIUM")'),
        ("Edges LOW confidence", f'=COUNTIF(Edges!K2:K{len(res.edges) + 1},"LOW")'),
        ("Edges with a review decision", f'=COUNTIF(Edges!O2:O{len(res.edges) + 1},"<>parser")'),
        ("Branches stopped at the generation limit (TRUNCATED)",
         f'=COUNTIF(Benchmark!N2:N{n + 1},"TRUNCATED*")'),
        (None, None),
        ("Where branches stop (count of devices)", None),
    ]
    for a, b in top:
        ws.append([a, b])
    stops = Counter(stop_text(x) for x in res.nodes.values() if stop_text(x))
    for reason in sorted(stops):
        r = ws.max_row + 1
        ws.append([reason, f'=COUNTIF(Benchmark!N2:N{n + 1},A{r})'])
    ws.append([])
    ws.append(["Read the Methodology_and_Limitations tab before using these results.", None])
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name=FONT, size=10)
    ws["A1"].font = Font(name=FONT, size=14, bold=True)
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 90
    ws["B11"].number_format = "0"

    # ---- Benchmark ------------------------------------------------------------
    cols = list(bench[0].keys()) if bench else []
    rows = [[_date(r[c]) if c == "Decision date" else r[c] for c in cols] for r in bench]
    wsb = _sheet(wb, "Benchmark", cols, rows, [11, 22, 11, 40, 32, 13, 10, 12, 8, 9, 20, 13, 14, 34], (4, 5, 14))
    for row in wsb.iter_rows(min_row=2, min_col=6, max_col=6):
        for c in row:
            c.number_format = "yyyy-mm-dd"

    # ---- Edges ----------------------------------------------------------------
    eh = ["Generation", "Child K-number", "Number as printed", "Number used in chain", "Kind", "Role", "Role basis",
          "Label in document", "Name as printed", "FDA device name (by number)", "Confidence", "In predicate section",
          "Page", "Review decision", "Review source", "Review reasoning", "Evidence", "Parser version"]
    er = [[e["generation"], e["child_knumber"], e["number_as_printed"], e["number_used"], e["predicate_kind"], e["role"],
           e["role_basis"], e["printed_label"], e["printed_name"], clean(e.get("fda_device_name")), e["confidence"],
           "yes" if e["in_predicate_section"] else "no", e["page"], e["review_decision"], e["review_source"],
           e["review_reasoning"], e["evidence"], e["parser_version"]]
          for e in sorted(res.edges, key=lambda x: (x["generation"] or 0, x["child_knumber"], x["list_order"]))]
    _sheet(wb, "Edges", eh, er, [10, 12, 12, 12, 6, 10, 26, 18, 26, 30, 11, 9, 6, 14, 13, 40, 60, 9], (7, 9, 10, 16, 17))

    # ---- Nodes ----------------------------------------------------------------
    nh = ["K-number", "Generation", "Device name", "Applicant (as printed)", "Decision date", "Product code",
          "Regulation number", "Device class", "Review panel", "Unofficial segment", "In orthopedic starting set",
          "Identity source", "Status", "Where the chain stops", "Parser version", "Summary PDF URL", "URL source",
          "SHA-256", "Retrieved (UTC)", "File source", "Text method", "Pages", "Parse status", "Parse notes"]
    nr = []
    for k, x in sorted(res.nodes.items(), key=lambda i: (i[1]["generation"], i[0])):
        d = x["doc"] or {}
        nr.append([k, x["generation"], x["devicename"], x["applicant"], _date(x["decision_date"]), x["product_code"],
                   x["regulation_number"], x["device_class"], x["review_panel"], x["unofficial_segment"],
                   "yes" if x["in_starting_set"] else "no", x["source"], x["status"] or "not extracted", stop_text(x),
                   x["parser_version"], d.get("url"), d.get("url_source"), d.get("sha256"), d.get("retrieved_at_utc"),
                   d.get("file_source"), d.get("text_method"), d.get("page_count"), d.get("parse_status"),
                   d.get("parse_notes")])
    wsn = _sheet(wb, "Nodes", nh, nr, [11, 9, 38, 30, 12, 9, 11, 7, 8, 18, 9, 16, 11, 32, 9, 50, 12, 20, 20, 16, 12, 6,
                                       11, 40], (3, 4, 14, 24))
    for row in wsn.iter_rows(min_row=2, min_col=5, max_col=5):
        for c in row:
            c.number_format = "yyyy-mm-dd"

    # ---- Companies ------------------------------------------------------------
    by_co = defaultdict(list)
    for k, x in res.nodes.items():
        by_co[x["applicant"] or "(unknown)"].append(x)
    cr = sorted(([co, len(v), min(i["generation"] for i in v), max(i["generation"] for i in v),
                  ", ".join(sorted(i["knumber"] for i in v))[:2000]] for co, v in by_co.items()),
                key=lambda r: (-r[1], r[0]))
    _sheet(wb, "Companies", ["Applicant (as printed, no parent roll-up)", "Devices in chain", "First generation",
                             "Last generation", "K-numbers"], cr, [44, 12, 12, 12, 90], (5,))

    # ---- Flags ----------------------------------------------------------------
    fh = ["K-number", "Flag", "Number", "Detail", "Page", "Review decision", "Review source", "Evidence"]
    fr = [[f["knumber"], f["flag_type"], f["number"], f["detail"], f["page"], f["review_decision"], f["review_source"],
           f["evidence"]] for f in sorted(res.flags, key=lambda x: (x["knumber"], x["flag_type"]))]
    _sheet(wb, "Flags", fh, fr, [11, 24, 12, 50, 6, 14, 13, 70], (4, 8))

    # ---- Excluded name matches -----------------------------------------------
    xr = [[x["knumber"], clean(x["devicename"]), clean(x["applicant"]), x.get("decision_date"), x["reason"]]
          for x in res.excluded]
    if not xr:
        xr = [["(none)", "No other-company devices share this brand name, or the lookup was for a single K-number.",
               None, None, None]]
    _sheet(wb, "Excluded name matches", ["K-number", "Device name", "Applicant", "Decision date", "Why excluded"], xr,
           [11, 44, 34, 12, 60], (2, 5))

    # ---- Audit_Log ------------------------------------------------------------
    logs = audit_lines(cfg, set(res.nodes))
    ah = ["Record", "K-number", "UTC time", "Parser version", "Action", "Depth", "URL", "HTTP status", "Result",
          "Reason", "Log file"]
    ar = []
    for k, x in sorted(res.nodes.items()):
        d = x["doc"] or {}
        ar.append(["extraction record", k, d.get("retrieved_at_utc"), x["parser_version"], "extract",
                   x["generation"], d.get("url"), None, f"{x['status'] or 'not extracted'}; {d.get('parse_status') or ''}",
                   stop_text(x) or d.get("parse_notes"), "database"])
    for r in logs:
        ar.append(["log line", r.get("knumber"), r.get("ts_utc"), r.get("parser_version"), r.get("action"),
                   r.get("depth"), r.get("url"), r.get("http_status"), r.get("result"), r.get("reason"),
                   r.get("log_file")])
    _sheet(wb, "Audit_Log", ah, ar, [16, 11, 26, 9, 12, 7, 50, 8, 26, 50, 22], (10,))

    # ---- Reviewer_Checklist ---------------------------------------------------
    ws = wb.create_sheet("Reviewer_Checklist")
    ws.append(["How to use: check each edge against the Summary PDF (URL on the Nodes tab). Fill in the four yellow "
               "columns. The first data row is an example; delete it before you start."])
    ws.append(["Generation", "Child K-number", "Predicate K-number", "Role", "Confidence", "Review source",
               "Page", "Evidence", "Reviewer agrees (Y/N)", "Reviewer notes", "Reviewer name", "Date"])
    ws.append(["1", "K000000", "K111111", "primary", "HIGH", "parser", 3, "Example: Predicate Device: Alpha Interbody "
               "System (K111111)", "Y", "Matches the predicate table on page 3", "J. Smith", "2026-11-20"])
    for e in sorted(res.edges, key=lambda x: (x["generation"] or 0, x["child_knumber"], x["list_order"])):
        if not e["number_as_printed"]:
            continue
        ws.append([e["generation"], e["child_knumber"], e["number_used"] or f"{e['number_as_printed']} (left out)",
                   e["role"], e["confidence"], e["review_source"], e["page"], _xml(e["evidence"][:400]),
                   None, None, None, None])
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name=FONT, size=10)
    ws["A1"].font = Font(name=FONT, size=10, bold=True)
    for c in ws[2]:
        c.font = Font(name=FONT, bold=True, color="FFFFFF")
        c.fill = HDR
    for c in ws[3]:
        c.font = Font(name=FONT, size=10, italic=True, color="808080")
    for row in ws.iter_rows(min_row=3, min_col=9, max_col=12):
        for c in row:
            c.fill = INPUT
    for i, w in enumerate([10, 12, 18, 10, 11, 13, 6, 60, 12, 40, 18, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"

    # ---- Methodology_and_Limitations -----------------------------------------
    ws = wb.create_sheet("Methodology_and_Limitations")
    lines = [
        "Methodology",
        "1. Each clearance's 510(k) Summary PDF was downloaded from FDA once, hashed (SHA-256), and read by the "
        "OrthoParity predicate parser (text layer, repaired fonts, or OCR for scans).",
        "2. Predicates are the K-numbers (and DEN and PMA numbers) the Summary cites. Identity comes from FDA records "
        "by number (starting set, FDA master file, openFDA, FDA web database), never from the PDF text.",
        "3. The chain follows every numbered predicate, generation by generation, up to the generation limit. Each "
        "device appears once, at its nearest generation.",
        "4. Confidence: HIGH = number in a labeled predicate section and found in FDA records; MEDIUM = number found "
        "elsewhere in the Summary (counted as a predicate under rule D); LOW = number read by OCR that matches neither "
        "the FDA device name nor the company, or not found in FDA records; NO NUMBER = predicate printed without a number.",
        "5. Review decisions (confirmed, corrected, own number, not a predicate, unresolved) come from the Phase 4 review "
        "and never overwrite the parser's rows. 'Review source' says who decided.",
        "",
        "Limitations",
    ] + [f"- {t}" for t in LIMITATIONS] + [
        "",
        "Source: public FDA data (510(k) database release files, product classification file, 510(k) Summary PDFs at "
        "accessdata.fda.gov). Tool: OrthoParity, MIT License, Copyright (c) 2026 Asher Breverman.",
    ]
    for t in lines:
        ws.append([t])
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name=FONT, size=10, bold=c.value in ("Methodology", "Limitations"))
            c.alignment = WRAP
    ws.column_dimensions["A"].width = 140

    wb.calculation.fullCalcOnLoad = True
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
