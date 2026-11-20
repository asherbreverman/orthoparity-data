"""Business lines sold to another company (reference/vendor_divestitures.csv).

A divestiture moves a seller's clearances to the buyer when the clearance's FDA product code is in the sold line
(and, if decided_before is set, the clearance was decided before that date). Every row has a public source.
Payments stay with the company that made them: Open Payments records the payer, and that is a fact.
"""
from __future__ import annotations

import csv
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "reference" / "vendor_divestitures.csv"


def load(path: Path | None = None) -> list[dict]:
    path = path or PATH
    if not path.exists():
        return []
    rules = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            r["codes"] = {c.strip().upper() for c in r["product_codes"].split("|") if c.strip()}
            rules.append(r)
    return rules


def owner(vendor_id: str | None, product_code: str | None, decision_date: str | None, rules: list[dict]) -> str | None:
    """The vendor a clearance belongs to after divestitures (vendor_id itself when no rule applies)."""
    if not vendor_id:
        return vendor_id
    code = (product_code or "").upper()
    for r in rules:
        if r["seller"] == vendor_id and code in r["codes"] and (not r["decided_before"] or (decision_date or "") < r["decided_before"]):
            return r["buyer"]
    return vendor_id
