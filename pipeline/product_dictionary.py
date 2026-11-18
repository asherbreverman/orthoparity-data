"""Plain-English product-code dictionary: review workbook and loader.

    python orthoparity.py product-dictionary   writes reviews/Product_Code_Dictionary_REVIEW.xlsx (keeps your answers if the
                                        file already exists)

Claude drafted plain-English entries for the 60 most common orthopedic product codes (pipeline/
product_code_drafts.py). Fill the yellow columns: Reviewed (Y/N) and, where you want a different wording,
your own text. Your text wins over the draft. Codes without a draft fall back to FDA's own device name on the website.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from predicate_chain.config import load_config
from predicate_chain.db import connect

from pipeline.product_code_drafts import DRAFT

FILE = "Product_Code_Dictionary_REVIEW.xlsx"
FIELDS = ["plain_name", "plain_description", "anatomy", "procedures", "kind"]
HEAD = ["Product code", "Clearances", "FDA device name", "Regulation", "Class", "FDA definition",
        "Draft plain name", "Draft description", "Draft anatomy", "Draft procedures", "Draft kind",
        "Reviewed (Y/N)", "Your plain name", "Your description", "Your anatomy", "Your procedures", "Your kind", "Notes"]


def _drafts():
    return {d[0]: dict(zip(FIELDS, d[1:])) for d in DRAFT}


def load_dictionary(cfg) -> dict:
    """{code: {plain_name, plain_description, anatomy, procedures, kind, reviewed}} with the reviewer's edits applied."""
    out = {k: {**v, "reviewed": False} for k, v in _drafts().items()}
    path = cfg.review_dir / FILE
    if not path.exists():
        return out
    ws = load_workbook(path, data_only=True)["Dictionary"]
    for r in ws.iter_rows(min_row=3, values_only=True):
        code = r[0]
        if not code or code == "EXAMPLE":
            continue
        e = out.setdefault(code, {f: None for f in FIELDS})
        for i, f in enumerate(FIELDS):
            mine = r[12 + i]
            if mine not in (None, ""):
                e[f] = str(mine).strip()
        e["reviewed"] = str(r[11] or "").strip().upper() == "Y" and bool(e.get("plain_name"))
    return out


def main() -> int:
    cfg = load_config()
    con = connect(cfg.db_path)
    path = cfg.review_dir / FILE
    previous = {}
    if path.exists():
        for r in load_workbook(path, data_only=True)["Dictionary"].iter_rows(min_row=3, values_only=True):
            if r[0] and r[0] != "EXAMPLE":
                previous[r[0]] = r[11:18]
    drafts = _drafts()
    wb = Workbook()
    ws = wb.active
    ws.title = "Dictionary"
    ws.append(["How to use: check each draft against your own knowledge. Type Y in 'Reviewed' when the draft (or your "
               "edit) is right. To change wording, type yours in the 'Your ...' columns; it replaces the draft. Leave a "
               "code blank and the website shows FDA's own name, labeled as such. Row 3 is an example."])
    ws.append(HEAD)
    ws.append(["EXAMPLE", 354, "Intervertebral Fusion Device With Bone Graft, Cervical", "888.3080", "2", "Intended to "
               "stabilize cervical spinal segment ...", "Cervical interbody cage", "A spacer placed between two cervical "
               "vertebrae ...", "Cervical spine", "ACDF", "implant", "Y", "", "", "", "", "", "Example row"])
    rows = con.execute("SELECT c.product_code, COUNT(*) AS n, p.device_name, p.regulation_number, p.device_class, "
                       "p.definition FROM clearances c LEFT JOIN product_codes p ON p.product_code=c.product_code "
                       "WHERE c.product_code IS NOT NULL GROUP BY c.product_code ORDER BY n DESC").fetchall()
    for r in rows:
        d = drafts.get(r[0], {})
        prev = previous.get(r[0], (None,) * 7)
        ws.append([r[0], r[1], r[2], r[3], r[4], r[5]] + [d.get(f) for f in FIELDS] + list(prev))
    hdr, fill = PatternFill("solid", fgColor="1F3864"), PatternFill("solid", fgColor="FFFF00")
    for row in ws.iter_rows():
        for c in row:
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws["A1"].font = Font(name="Arial", size=10, bold=True)
    for c in ws[2]:
        c.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        c.fill = hdr
    for c in ws[3]:
        c.font = Font(name="Arial", size=10, italic=True, color="808080")
    for row in ws.iter_rows(min_row=3, min_col=12, max_col=18):
        for c in row:
            c.fill = fill
    for col, w in zip("ABCDEFGHIJKLMNOPQR", [9, 9, 30, 9, 5, 40, 26, 44, 22, 26, 10, 9, 26, 44, 22, 26, 10, 24]):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "B3"
    dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"L4:L{ws.max_row}")
    wb.save(path)
    print(f"Wrote {path}: {len(rows)} product codes, {sum(1 for r in rows if r[0] in drafts)} with drafts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
