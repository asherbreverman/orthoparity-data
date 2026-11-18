"""Phase 6: draw a fresh validation sample and write the hand-check workbook.

40 starting-set clearances (10 from each era with posted summaries: 1996-1999, 2000-2009, 2010-2019, 2020-2026),
drawn at random with a fixed seed from devices whose Summary PDF was read, excluding every pilot device.
The workbook shows what the tool reports today: current parser version with Phase 4 review decisions applied.

Usage:  python orthoparity.py make-validation
Writes outputs/Validation_HandCheck_[date].xlsx. After filling it in: python orthoparity.py accuracy-report <that file>
"""
from __future__ import annotations

import datetime as dt
import random
import sys

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

from tools.pilot_report import _links, _style
from predicate_chain import PARSER_VERSION
from predicate_chain.chains import latest_versions, review_overrides
from predicate_chain.config import load_config
from predicate_chain.db import connect, init_schema
from predicate_chain.lookup_core import LIMITATIONS, clean
from predicate_chain.pilot import era_label

ERAS = [("1996-1999", 1996, 1999), ("2000-2009", 2000, 2009), ("2010-2019", 2010, 2019), ("2020-2026", 2020, 2026)]
RUN = "validation"


def draw(con, cfg) -> list[dict]:
    n_total = cfg.getint("settings", "HANDCHECK_SAMPLE", 40)
    per = n_total // len(ERAS)
    rng = random.Random(cfg.getint("settings", "PILOT_SEED", 20261116) + 6)
    pilot = {r[0] for r in con.execute("SELECT knumber FROM run_targets WHERE run_name='pilot'")}
    versions = latest_versions(con)
    picked = []
    for name, a, b in ERAS:
        pool = sorted(r[0] for r in con.execute(
            "SELECT c.knumber, d.parser_version FROM clearances c JOIN documents d ON d.knumber=c.knumber "
            "WHERE c.decision_year BETWEEN ? AND ? AND d.cache_path IS NOT NULL "
            "AND d.text_method IN ('text layer','OCR')", (a, b)) if versions.get(r[0]) == r[1] and r[0] not in pilot)
        for k in rng.sample(pool, min(per, len(pool))):
            picked.append({"knumber": k, "stratum": name})
    con.execute("DELETE FROM run_targets WHERE run_name=?", (RUN,))
    con.executemany("INSERT INTO run_targets (run_name, knumber, stratum, seq) VALUES (?,?,?,?)",
                    [(RUN, p["knumber"], p["stratum"], i) for i, p in enumerate(picked)])
    con.commit()
    return picked


def main() -> int:
    cfg = load_config()
    con = connect(cfg.db_path)
    init_schema(con)
    picked = draw(con, cfg)
    versions = latest_versions(con)
    ov = review_overrides(con)
    rev = {}
    for k, n, src in con.execute("SELECT knumber, predicate_number, decision_source FROM review_decisions "
                                 "WHERE predicate_number IS NOT NULL"):
        rev[(k, n)] = src

    F = "Arial"
    hdr_font, hdr_fill = Font(name=F, bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3864")
    fill_in, example_fill = PatternFill("solid", fgColor="FFFF00"), PatternFill("solid", fgColor="E7E6E6")
    body = Font(name=F, size=10)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Instructions"
    lines = [
        ("OrthoParity validation hand-check (Phase 6)", True),
        (f"Parser {PARSER_VERSION}, review rule D, Phase 4 review decisions applied. Generated {dt.date.today()}. "
         f"{len(picked)} clearances drawn at random (fixed seed) from devices whose Summary PDF was read: "
         f"{len(picked) // len(ERAS)} from each of 1996-1999, 2000-2009, 2010-2019, 2020-2026. No pilot devices.", False),
        ("", False),
        ("How to check", True),
        ("1. Open each device's PDF (link in 'Summary PDF') and find the page shown.", False),
        ("2. 'Edges' tab, one row per predicate the tool reports. Fill the yellow columns with Y or N:", False),
        ("   Number correct: the K-number matches what the document prints (or what it plainly meant, if a review "
         "corrected a typo).", False),
        ("   Role correct: primary vs reference matches the document (if the document labels none, the first listed "
         "is primary).", False),
        ("   Real predicate: under rule D, any K-number in the Summary other than the device's own counts. Answer N only "
         "if the number is not in the document, is the device's own number, or comes from FDA's letter.", False),
        ("3. 'Devices' tab: did the tool find every K-number predicate in the Summary? Under rule D, predicates "
         "named without a number are ignored, so do not count those as missed. List any missed numbers.", False),
        ("Fill only the yellow cells. Grey rows are worked examples and are excluded from the tallies.", False),
        ("", False),
        ("Confidence: HIGH = in a labeled predicate section and found in FDA records; MEDIUM = found elsewhere in the "
         "Summary; LOW = number read by OCR that matches neither the FDA name nor the company, or not in FDA records.",
         False),
        ("", False),
        ("Limitations", True),
    ] + [("• " + t, False) for t in LIMITATIONS]
    for i, (t, bold) in enumerate(lines, 1):
        c = ws0.cell(row=i, column=1, value=t)
        c.font = Font(name=F, bold=bold, size=12 if i == 1 else 10)
        c.alignment = wrap
    ws0.column_dimensions["A"].width = 120

    # Edges: columns 1-22 match the pilot hand-check so import_handcheck.py reads both.
    ws = wb.create_sheet("Edges")
    cols = ["K-number", "Applicant", "Device name", "Decision date", "Era", "Unofficial segment", "Summary PDF",
            "Page", "#", "Predicate number", "Role", "Role basis", "Printed label", "Printed in PDF",
            "FDA applicant", "FDA device name", "Confidence", "Evidence (verbatim, max 300 chars)",
            "Number correct (Y/N)", "Role correct (Y/N)", "Real predicate (Y/N)", "Notes",
            "Number as printed (if a review changed it)", "Review source"]
    widths = [11, 22, 28, 11, 10, 12, 22, 6, 4, 13, 10, 22, 16, 30, 24, 30, 10, 60, 12, 12, 12, 30, 16, 13]
    ws.append(cols)
    ws.append(["EXAMPLE", "Example Spine, Inc.", "EXAMPLE INTERBODY SYSTEM", "2024-01-15", "2020-2026", "Spine",
               "https://www.accessdata.fda.gov/cdrh_docs/pdf24/K000000.pdf", 5, 1, "K111111", "primary",
               "labeled primary in PDF", "primary predicate", "Example Cage System Example Spine",
               "Example Spine, Inc.", "EXAMPLE CAGE SYSTEM", "HIGH",
               "Primary Predicate: Example Cage System (K111111) - Example Spine, Inc.", "Y", "Y", "Y",
               "Example row: shows the expected format", None, "parser"])
    for c in ws[2]:
        c.fill = example_fill
    wd = wb.create_sheet("Devices")
    dcols = ["K-number", "Applicant", "Device name", "Decision date", "Era", "Stratum", "Summary PDF", "Pages",
             "Text method", "Parse status", "Stop reason", "Predicates reported", "Flags",
             "All predicates found (Y/N)", "Missed predicates (numbers)", "Notes"]
    wd.append(dcols)
    wd.append(["EXAMPLE", "Example Spine, Inc.", "EXAMPLE INTERBODY SYSTEM", "2024-01-15", "2020-2026", "2020-2026",
               "https://www.accessdata.fda.gov/cdrh_docs/pdf24/K000000.pdf", 8, "text layer", "CLEAN", None,
               "K111111, K222222", "", "N", "K333333", "Example row: K333333 listed in the comparison table"])
    for c in wd[2]:
        c.fill = example_fill
    picked.sort(key=lambda p: (p["stratum"], p["knumber"]))
    for p in picked:
        k = p["knumber"]
        v = versions[k]
        c = con.execute("SELECT applicant, devicename, decision_date, decision_year, unofficial_segment FROM clearances "
                        "WHERE knumber=?", (k,)).fetchone()
        d = con.execute("SELECT url, page_count, text_method, parse_status FROM documents WHERE knumber=? AND "
                        "parser_version=?", (k, v)).fetchone()
        st = con.execute("SELECT stop_reason FROM node_status WHERE knumber=? AND parser_version=?", (k, v)).fetchone()
        reported = []
        for e in con.execute("SELECT * FROM edges WHERE child_knumber=? AND parser_version=? AND predicate_number IS NOT "
                             "NULL ORDER BY list_order", (k, v)):
            o = ov.get((k, e["predicate_number"]))
            if o and o[0] == "drop":
                continue
            used = o[1] if o and o[0] == "replace" else e["predicate_number"]
            reported.append(used)
            printed = " ".join(x for x in [e["printed_name"], e["printed_company"]] if x)
            ws.append([k, clean(c["applicant"]), clean(c["devicename"]), c["decision_date"], era_label(c["decision_year"]),
                       c["unofficial_segment"], d["url"], e["page"], e["list_order"], used, e["role"], e["role_basis"],
                       e["printed_label"], clean(printed), clean(e["fda_applicant"]), clean(e["fda_device_name"]),
                       e["confidence"], clean(e["evidence"])[:300], None, None, None, None,
                       e["predicate_number"] if used != e["predicate_number"] else None,
                       rev.get((k, e["predicate_number"]), "parser")])
        if not reported:
            ws.append([k, clean(c["applicant"]), clean(c["devicename"]), c["decision_date"], era_label(c["decision_year"]),
                       c["unofficial_segment"], d["url"], None, None, "NOT FOUND", None, None, None, None, None, None,
                       None, f"No numbered predicate reported. Stop reason: {st[0] if st else None}", None, None, None,
                       None, None, None])
        flags = [f"{r[0]}: {r[1]}" for r in con.execute("SELECT flag_type, number FROM flags WHERE knumber=? AND "
                                                        "parser_version=?", (k, v))]
        wd.append([k, clean(c["applicant"]), clean(c["devicename"]), c["decision_date"], era_label(c["decision_year"]),
                   p["stratum"], d["url"], d["page_count"], d["text_method"], d["parse_status"], st[0] if st else None,
                   ", ".join(reported), "; ".join(flags)[:500], None, None, None])
    last, dlast = ws.max_row, wd.max_row
    _style(ws, cols, widths, hdr_font, hdr_fill, body, border, wrap, fill_in, fill_cols=(19, 20, 21, 22))
    _links(ws, 7)
    _style(wd, dcols, [11, 22, 28, 11, 10, 12, 22, 7, 11, 12, 26, 26, 30, 14, 22, 30], hdr_font, hdr_fill, body,
           border, wrap, fill_in, fill_cols=(14, 15, 16))
    _links(wd, 7)
    for sheet, colset, lr in ((ws, ("S", "T", "U"), last), (wd, ("N",), dlast)):
        dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
        sheet.add_data_validation(dv)
        for col in colset:
            dv.add(f"{col}3:{col}{lr}")

    wt = wb.create_sheet("Tally")
    wt.append(["Measure", "Y", "N", "Still blank", "Share Y of answered"])
    rows = [("Edges: number correct", "Edges", "S", last), ("Edges: role correct", "Edges", "T", last),
            ("Edges: real predicate", "Edges", "U", last), ("Devices: all predicates found", "Devices", "N", dlast)]
    for i, (label, sh, col, lr) in enumerate(rows, 2):
        rng_ = f"{sh}!${col}$3:${col}${lr}"
        wt.cell(row=i, column=1, value=label)
        wt.cell(row=i, column=2, value=f'=COUNTIF({rng_},"Y")')
        wt.cell(row=i, column=3, value=f'=COUNTIF({rng_},"N")')
        if sh == "Edges":
            wt.cell(row=i, column=4, value=f'=COUNTA(Edges!$J$3:$J${lr})-COUNTIF(Edges!$J$3:$J${lr},"NOT FOUND")-B{i}-C{i}')
        else:
            wt.cell(row=i, column=4, value=f"=COUNTBLANK({rng_})")
        wt.cell(row=i, column=5, value=f'=IF(B{i}+C{i}=0,"",B{i}/(B{i}+C{i}))')
        wt.cell(row=i, column=5).number_format = "0.0%"
    wt.cell(row=7, column=1, value="Counts exclude the grey example row. NOT FOUND rows (no numbered predicate) are "
                                    "not edges; check those devices on the Devices tab.")
    _style(wt, ["Measure", "Y", "N", "Still blank", "Share Y of answered"], [34, 8, 8, 12, 18], hdr_font, hdr_fill,
           body, border, Alignment(vertical="top"), None, fill_cols=())
    wb.calculation.fullCalcOnLoad = True
    path = cfg.output_dir / f"Validation_HandCheck_{dt.date.today().isoformat()}.xlsx"
    wb.save(path)
    n_edges = last - 2 - sum(1 for r in ws.iter_rows(min_row=3, min_col=10, max_col=10, values_only=True)
                             if r[0] == "NOT FOUND")
    print(f"Wrote {path}: {len(picked)} devices, {n_edges} edges to check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
