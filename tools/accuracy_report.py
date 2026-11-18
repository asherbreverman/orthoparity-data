"""Phase 6: accuracy report from a filled validation hand-check workbook.

Usage:  python orthoparity.py accuracy-report outputs\\Validation_HandCheck_YYYY-MM-DD.xlsx
Writes outputs/accuracy_report.md. Edge-level and device-level error rates, by confidence tier and by era,
with 95% Wilson confidence intervals.
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

from predicate_chain import PARSER_VERSION
from predicate_chain.config import load_config


def yn(v):
    v = str(v).strip().upper() if v is not None else ""
    return v if v in ("Y", "N") else None


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def fmt(k, n):
    if n == 0:
        return "n/a", "n/a"
    lo, hi = wilson(k, n)
    return f"{k} of {n} ({100 * k / n:.1f}%)", f"{100 * lo:.1f}% to {100 * hi:.1f}%"


def table(title_col, groups):
    out = [f"| {title_col} | Errors | 95% CI for the error rate |", "|---|---|---|"]
    for name, (err, n) in groups:
        a, b = fmt(err, n)
        out.append(f"| {name} | {a} | {b} |")
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    path = Path(sys.argv[1])
    cfg = load_config()
    wb = openpyxl.load_workbook(path, data_only=True)
    edges, missing = [], 0
    for r in wb["Edges"].iter_rows(min_row=3, values_only=True):
        if not r[0] or r[0] == "EXAMPLE" or r[9] == "NOT FOUND":
            continue
        num, role, real = yn(r[18]), yn(r[19]), yn(r[20])
        if not (num and real):
            missing += 1
            continue
        edges.append({"k": r[0], "era": r[4] or "unknown", "conf": r[16] or "(none)", "ok": num == "Y" and real == "Y",
                      "role_ok": role == "Y" if role else None, "reviewed": (r[23] or "parser") != "parser"})
    devices = []
    by_dev = defaultdict(list)
    for e in edges:
        by_dev[e["k"]].append(e)
    dev_missing = 0
    for r in wb["Devices"].iter_rows(min_row=3, values_only=True):
        if not r[0] or r[0] == "EXAMPLE":
            continue
        found = yn(r[13])
        if not found:
            dev_missing += 1
            continue
        es = by_dev.get(r[0], [])
        devices.append({"k": r[0], "era": r[5], "ok": found == "Y" and all(e["ok"] for e in es),
                        "found_all": found == "Y", "edges_ok": all(e["ok"] for e in es), "n_edges": len(es)})
    ne, ee = len(edges), sum(not e["ok"] for e in edges)
    roles = [e for e in edges if e["role_ok"] is not None]
    nd, ed = len(devices), sum(not d["ok"] for d in devices)
    conf_groups, era_groups, dev_era = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for e in edges:
        for g, key in ((conf_groups, e["conf"]), (era_groups, e["era"])):
            g[key][0] += not e["ok"]
            g[key][1] += 1
    for d in devices:
        dev_era[d["era"]][0] += not d["ok"]
        dev_era[d["era"]][1] += 1

    a, b = fmt(ee, ne)
    lines = [
        "# OrthoParity accuracy report (Phase 6)", "",
        f"Written {dt.date.today()}. Parser {PARSER_VERSION}, review rule D, Phase 4 review decisions applied. "
        f"Source: `{path.name}`, a fresh random sample of 40 orthopedic clearances (10 per era, 1996 to 2026) drawn "
        "with a fixed seed from devices whose Summary PDF was read, excluding every pilot device. A person checked each "
        "reported predicate against the PDF.", "",
        "## Results", "",
        f"- **Edge error rate:** {a}; 95% Wilson interval {b}. An edge counts as an error if the number is wrong or "
        "it is not a predicate under rule D.",
    ]
    if roles:
        ra, rb = fmt(sum(not e["role_ok"] for e in roles), len(roles))
        lines.append(f"- **Role errors (primary vs reference):** {ra}; 95% interval {rb}. Reported separately; a role "
                     "error does not change which devices are in a chain.")
    da, db_ = fmt(ed, nd)
    lines += [
        f"- **Device error rate:** {da}; 95% interval {db_}. A device counts as an error if any reported predicate is "
        "wrong or the tool missed a numbered predicate.",
        f"- Devices where the tool missed at least one numbered predicate: "
        f"{sum(not d['found_all'] for d in devices)} of {nd}.", "",
        "### Edges by confidence tier", ""] + table("Confidence", sorted(conf_groups.items())) + [
        "", "### Edges by era", ""] + table("Era", sorted(era_groups.items())) + [
        "", "### Devices by era", ""] + table("Era", sorted(dev_era.items())) + [
        "",
        "## What this sample can and cannot support", "",
        f"- This is a small sample: {nd} devices and {ne} edges. The intervals above are wide, and the per-tier and "
        "per-era rows rest on even fewer cases. Read them as rough ranges, not precise rates.",
        "- Zero errors in a group does not mean the tool is error-free there. With n checks and no errors, the upper "
        "end of the 95% interval is roughly 3.7/n (for example about 9% at n = 40).",
        "- The sample covers 1996 to 2026, the years with posted summaries. Earlier chains end by rule (no summary on "
        "file), so there is nothing to extract or check for them.",
        "- The check measures extraction against the document. It does not test whether FDA agreed with the "
        "submitter's choice of predicate, or anything about clinical performance, outcomes or price.",
        "- Rule D counts every K-number in a Summary as a predicate; this report judges the tool against that rule, "
        "not against a narrower definition of 'predicate'.",
    ]
    if missing or dev_missing:
        lines += ["", f"Not yet answered: {missing} edge rows and {dev_missing} device rows were left blank and are "
                      "excluded."]
    out = cfg.output_dir / "accuracy_report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}: {ne} edges ({ee} errors), {nd} devices ({ed} errors).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
