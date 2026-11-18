"""Phase 1 pilot report: metrics, extrapolations, and the 40-device hand-check workbook.

Usage:  python orthoparity.py pilot-report
Writes outputs/Pilot_Report.md, outputs/Pilot_Report.json and outputs/Pilot_HandCheck_[date].xlsx
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import random
import statistics
import sys

from predicate_chain import PARSER_VERSION
from predicate_chain.chains import NOT_EXTRACTED, build_chain, latest_versions
from predicate_chain.config import load_config
from predicate_chain.db import connect
from predicate_chain.numbers import pdf_folder_candidates
from predicate_chain.pilot import ERA_STRATA, era_label

LIMITATIONS = [
    "Predicates are what the submitter wrote in the Summary. The tool does not verify FDA's internal review.",
    "Substantial equivalence is a regulatory finding. It says nothing about clinical performance, outcomes, or price.",
    "510(k) summaries were not required before 1990, so most chains end in the early 1990s whatever the generation "
    "limit. Statement-only clearances and unreadable PDFs also end a branch.",
    "The starting set is orthopedic product codes only (FDA Orthopedic panel and 21 CFR 888). Non-orthopedic "
    "ancestors are covered through the frontier.",
    "Applicant names appear as printed at clearance and are not rolled up to current owners.",
    "Text extraction can misread layouts. The Flags tab and Reviewer_Checklist exist for human review.",
    "Segment labels are unofficial (assigned by Claude, not FDA).",
    "Independent research tool built from public FDA data, provided as is, not regulatory advice, and the "
    "author's personal work and views.",
]


def q(con, sql, *args):
    return [dict(r) for r in con.execute(sql, args)]


def main() -> int:
    cfg = load_config()
    con = connect(cfg.db_path)
    v = PARSER_VERSION
    if "--parser-version" in sys.argv:
        v = sys.argv[sys.argv.index("--parser-version") + 1]
    seeds = q(con, "SELECT r.knumber, r.stratum, c.decision_year, c.stateorsumm, c.applicant, c.devicename, "
                   "c.decision_date FROM run_targets r JOIN clearances c USING(knumber) WHERE run_name='pilot' ORDER BY seq")
    seed_set = {s["knumber"] for s in seeds}
    starting = {r["knumber"] for r in q(con, "SELECT knumber FROM clearances")}
    ns = {r["knumber"]: r for r in q(con, "SELECT * FROM node_status WHERE parser_version=?", v)}
    docs = {r["knumber"]: r for r in q(con, "SELECT * FROM documents WHERE parser_version=?", v)}
    rep: dict = {"parser_version": v, "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    done_seeds = [s for s in seeds if s["knumber"] in ns]
    rep["seeds_total"], rep["seeds_processed"] = len(seeds), len(done_seeds)
    rep["nodes_processed_total"] = len(ns)
    rep["chain_nodes_processed"] = len([k for k in ns if k not in seed_set])

    # ---- 1. PDF availability for pre-1991 and blank-status groups ----------
    def has_pdf(k):
        d = docs.get(k) or {}
        return bool(d.get("cache_path"))
    avail = collections.OrderedDict()
    for label, cond in [
        ("1976-1990 stratum (all blank status)", lambda s: s["stratum"] == "1976-1990"),
        ("All pilot pre-1991 blank-status seeds", lambda s: (s["decision_year"] or 0) <= 1990 and not s["stateorsumm"]),
        ("1991-1995 blank-status seeds (any stratum)", lambda s: 1991 <= (s["decision_year"] or 0) <= 1995 and not s["stateorsumm"]),
        ("1991-1995 Summary-status seeds", lambda s: 1991 <= (s["decision_year"] or 0) <= 1995 and s["stateorsumm"] == "Summary"),
        ("1996+ blank-status seeds (any stratum)", lambda s: (s["decision_year"] or 0) >= 1996 and not s["stateorsumm"] and not s["knumber"].startswith("DEN")),
    ]:
        grp = [s for s in done_seeds if cond(s)]
        labels = collections.Counter((docs.get(s["knumber"]) or {}).get("detail_page_label") or "no link" for s in grp)
        avail[label] = {"n": len(grp), "pdf_online": sum(has_pdf(s["knumber"]) for s in grp),
                        "detail_page_labels": dict(labels),
                        "with_predicates": sum(1 for s in grp if (ns.get(s["knumber"]) or {}).get("status") == "continues")}
    rep["pdf_availability"] = avail

    # ---- 2. text method ------------------------------------------------------
    def methods(keys):
        c = collections.Counter()
        for k in keys:
            d = docs.get(k)
            if d and d.get("cache_path"):
                c[d.get("text_method") or "none"] += 1
        return dict(c)
    rep["text_method_seeds"] = methods(seed_set)
    rep["text_method_all"] = methods(ns.keys())

    # ---- 3. edge confidence ---------------------------------------------------
    edges = q(con, "SELECT * FROM edges WHERE parser_version=?", v)
    seed_edges = [e for e in edges if e["child_knumber"] in seed_set]
    rep["edge_confidence_seeds"] = dict(collections.Counter(e["confidence"] for e in seed_edges))
    rep["edge_confidence_all"] = dict(collections.Counter(e["confidence"] for e in edges))
    rep["edge_roles_all"] = dict(collections.Counter(e["role"] for e in edges))
    rep["identity_source_all"] = dict(collections.Counter(e["identity_source"] for e in edges))

    # ---- 4. parse status by era (seeds) ----------------------------------------
    by_era = collections.defaultdict(collections.Counter)
    for s in done_seeds:
        d = docs.get(s["knumber"]) or {}
        by_era[era_label(s["decision_year"])][d.get("parse_status") or "NOT PARSED"] += 1
    rep["parse_status_by_era_seeds"] = {e: dict(by_era[e]) for e, _, _ in ERA_STRATA if e in by_era}
    rep["parse_status_all"] = dict(collections.Counter((docs.get(k) or {}).get("parse_status") or "NOT PARSED" for k in ns))
    rep["stop_reasons_seeds"] = dict(collections.Counter(ns[s["knumber"]]["stop_reason"] or "(continues)" for s in done_seeds))
    rep["stop_reasons_all"] = dict(collections.Counter(r["stop_reason"] or "(continues)" for r in ns.values()))
    rep["flags_all"] = dict(collections.Counter(r["flag_type"] for r in q(con, "SELECT flag_type FROM flags WHERE parser_version=?", v)))
    rep["review_queue_all"] = dict(collections.Counter(r["reason"] for r in q(con, "SELECT reason FROM review_queue WHERE parser_version=?", v)))

    # ---- 5. download size and time -----------------------------------------------
    dl = [d for d in docs.values() if d.get("fetch_outcome") == "downloaded" or (d.get("cache_path") and d.get("bytes"))]
    sizes = [d["bytes"] for d in dl if d.get("bytes")]
    times = [d["download_seconds"] for d in dl if d.get("download_seconds")]
    rep["pdf_count"] = len(sizes)
    rep["avg_pdf_mb"] = round(statistics.mean(sizes) / 1e6, 3) if sizes else None
    rep["median_pdf_mb"] = round(statistics.median(sizes) / 1e6, 3) if sizes else None
    rep["avg_download_seconds"] = round(statistics.mean(times), 2) if times else None
    # URL pattern check
    pat = cfg.get("network", "PDF_URL_PATTERN")
    via_detail = [d for d in dl if d.get("url_source") == "detail page link"]
    match = sum(1 for d in via_detail if d["url"] in [pat.format(folder=f, knumber=d["knumber"]) for f in pdf_folder_candidates(d["knumber"])])
    first = sum(1 for d in via_detail if d["url"] == pat.format(folder=pdf_folder_candidates(d["knumber"])[0], knumber=d["knumber"]))
    rep["url_pattern_check"] = {"downloads_via_detail_link": len(via_detail), "link_matches_a_pattern_candidate": match,
                                "link_matches_first_candidate": first,
                                "downloads_via_pattern_fallback": sum(1 for d in dl if d.get("url_source") == "URL pattern")}

    # wall time per node, by what the node needed, measured from the JSONL log of the online pilot run(s)
    rep["timing"] = node_timing(cfg)

    # ---- 6. extrapolation for the full run (starting set) ------------------------------
    rep["full_run"] = extrapolate(con, done_seeds, docs, rep, sizes)

    # ---- 7. chains, truncation, frontier ---------------------------------------------
    versions = {k: v for k in ns}   # chains for this parser version only; other nodes show as not extracted
    chains = []
    for s in done_seeds:
        ch = build_chain(con, s["knumber"], cfg.max_generations, versions)
        years = [r["decision_year"] for r in q(con, "SELECT decision_year FROM fda_master WHERE knumber IN (%s)" %
                                               ",".join("?" * len(ch.nodes)), *ch.nodes.keys()) if r["decision_year"]]
        chains.append({"seed": s["knumber"], "stratum": s["stratum"], "nodes": len(ch.nodes) - 1, "depth": ch.depth,
                       "truncated": ch.truncated,
                       "not_yet_extracted": sum(1 for n in ch.nodes.values() if n.stop_reason == NOT_EXTRACTED),
                       "earliest_year": min(years) if years else None,
                       "outside_starting_set": sum(1 for k in ch.nodes if k not in starting)})
    rep["chains_truncated"] = sum(c["truncated"] for c in chains)
    rep["chains_complete"] = sum(1 for c in chains if c["not_yet_extracted"] == 0)
    rep["chain_depth_distribution"] = dict(sorted(collections.Counter(c["depth"] for c in chains).items()))
    rep["chains"] = chains
    reached = set()
    for s in done_seeds:
        reached |= set(build_chain(con, s["knumber"], cfg.max_generations, versions).nodes)
    frontier_pilot = {k for k in reached if k not in starting}
    rep["frontier_nodes_in_pilot"] = len(frontier_pilot)
    gen1 = {e["predicate_number"] for e in seed_edges if e["predicate_number"]}
    gen1_out = {p for p in gen1 if p not in starting}
    rep["gen1_predicates_outside_starting_set_share"] = round(len(gen1_out) / len(gen1), 3) if gen1 else None
    rep["frontier_estimate"] = frontier_estimate(con, done_seeds, cfg, versions, starting, rep)

    out_json = cfg.output_dir / "Pilot_Report.json"
    out_json.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in rep.items() if k != "chains"}, indent=2, default=str))

    wb_path = None
    if "--no-workbook" not in sys.argv:
        wb_path = build_handcheck(con, cfg, seeds, ns, docs, v)
        print("Hand-check workbook:", wb_path)
    write_markdown(rep, cfg.output_dir / "Pilot_Report.md", wb_path.name if wb_path else None)
    return 0


# ----------------------------------------------------------------------------- helpers
def node_timing(cfg) -> dict:
    """Median seconds per node by category, from consecutive node completions in the online pilot log."""
    recs = []
    for f in sorted(cfg.log_dir.glob("run_log_*.jsonl")):
        for line in f.open(encoding="utf-8"):
            if '"run_id": "pilot-' in line:
                recs.append(json.loads(line))
    recs.sort(key=lambda r: r["ts_utc"])
    by_k = collections.defaultdict(list)
    order = []
    for r in recs:
        k = r.get("knumber")
        if k and r["action"] != "run":
            if k not in by_k:
                order.append(k)
            by_k[k].append(r)
    ts = lambda r: dt.datetime.fromisoformat(r["ts_utc"].replace("Z", "+00:00"))
    ends = sorted(((max(ts(x) for x in by_k[k]), k) for k in order))
    cats = collections.defaultdict(list)
    for (t_prev, _), (t, k) in zip(ends, ends[1:]):
        acts = by_k[k]
        if any(x["action"] == "ocr" for x in acts):
            c = "downloaded, OCR"
        elif any(x["action"] == "download" and x["result"] == "ok" for x in acts):
            c = "downloaded, text layer"
        elif any(x["action"] in ("download", "lookup") and x.get("url") for x in acts):
            c = "looked up, no PDF"
        else:
            c = "no request (Statement, DEN, PMA)"
        d = (t - t_prev).total_seconds()
        if 0 <= d < 600:
            cats[c].append(d)
    out = {c: {"n": len(v), "median_s": round(statistics.median(v), 2), "mean_s": round(statistics.mean(v), 2)}
           for c, v in cats.items() if v}
    allv = [x for v in cats.values() for x in v]
    out["all"] = {"n": len(allv), "median_s": round(statistics.median(allv), 2) if allv else None,
                  "mean_s": round(statistics.mean(allv), 2) if allv else None}
    return out


def extrapolate(con, done_seeds, docs, rep, sizes) -> dict:
    """Disk and runtime for extracting all starting-set clearances, from pilot hit rates and timings."""
    t = rep.get("timing", {})
    med = lambda c, default: (t.get(c) or {}).get("median_s") or default
    t_skip = 0.05
    t_nopdf = med("looked up, no PDF", 2.0)
    t_text = med("downloaded, text layer", 2.0)
    t_ocr = med("downloaded, OCR", 5.0)
    rows = q(con, "SELECT knumber, decision_year, stateorsumm FROM clearances")
    groups = collections.Counter()
    for r in rows:
        k, y, s = r["knumber"], r["decision_year"] or 0, r["stateorsumm"]
        if k.startswith("DEN") or s == "Statement":
            groups["skip"] += 1
        elif y <= 1990:
            groups["pre1991_blank"] += 1
        elif y <= 1995:
            groups["1991-1995"] += 1
        else:
            groups[era_label(y)] += 1
    # pilot hit rate and OCR share by group
    def rate(cond):
        g = [s for s in done_seeds if cond(s) and s["stateorsumm"] != "Statement" and not s["knumber"].startswith("DEN")]
        if not g:
            return None, None, 0
        hits = [s for s in g if (docs.get(s["knumber"]) or {}).get("cache_path")]
        ocr = [s for s in hits if (docs.get(s["knumber"]) or {}).get("text_method") == "OCR"]
        return len(hits) / len(g), (len(ocr) / len(hits) if hits else 0.0), len(g)
    est = {"groups": dict(groups), "seconds_assumed": {"skip": t_skip, "no PDF": t_nopdf, "text": t_text, "OCR": t_ocr}}
    detail = {}
    total_a = groups["skip"] * t_skip
    total_b = groups["skip"] * t_skip
    pdfs = 0.0
    for g, n in groups.items():
        if g == "skip":
            continue
        if g == "pre1991_blank":
            hit, ocr, m = rate(lambda s: (s["decision_year"] or 0) <= 1990)
        elif g == "1991-1995":
            hit, ocr, m = rate(lambda s: 1991 <= (s["decision_year"] or 0) <= 1995)
        else:
            hit, ocr, m = rate(lambda s, g=g: era_label(s["decision_year"]) == g)
        hit = hit if hit is not None else 1.0
        ocr = ocr if ocr is not None else 0.0
        per_hit = ocr * t_ocr + (1 - ocr) * t_text
        a = n * (hit * per_hit + (1 - hit) * t_nopdf)
        # scenario B: pattern_first saves the detail-page request (about 1 s) on each hit; pre-1991 blanks stop
        if g in ("pre1991_blank", "1991-1995"):  # both stop without a request under the Gate 1 rules
            b = n * t_skip
        else:
            b = n * (hit * max(per_hit - 1.0, 0.5) + (1 - hit) * t_nopdf)
        total_a += a
        total_b += b
        pdfs += n * hit
        detail[g] = {"clearances": n, "pilot_sample": m, "pilot_pdf_rate": round(hit, 2), "pilot_ocr_share": round(ocr, 2),
                     "hours_A": round(a / 3600, 2), "hours_B": round(b / 3600, 2)}
    avg = statistics.mean(sizes) if sizes else 0
    est.update(by_group=detail, expected_pdfs=round(pdfs), expected_disk_gb=round(pdfs * avg / 1e9, 2),
               runtime_hours_A_current_settings=round(total_a / 3600, 1),
               runtime_hours_B_pattern_first_and_pre1991_stop=round(total_b / 3600, 1))
    return est


def frontier_estimate(con, done_seeds, cfg, versions, starting, rep) -> dict:
    """Species-accumulation extrapolation: distinct non-starting-set ancestors reached by random subsets of
    pilot seeds, fitted as F(n) = a * n^b, projected to every starting-set clearance with a Summary.
    Rough by design; the real count comes from Phase 2 edges before Phase 3 starts."""
    import math
    reach = {}
    for s in done_seeds:
        ch = build_chain(con, s["knumber"], cfg.max_generations, versions)
        reach[s["knumber"]] = {k for k in ch.nodes if k not in starting}
    seeds = [s["knumber"] for s in done_seeds if reach[s["knumber"]] or True]
    rng = random.Random(7)
    pts = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        vals = []
        for _ in range(20 if frac < 1 else 1):
            sub = rng.sample(seeds, max(1, int(len(seeds) * frac)))
            vals.append(len(set().union(*[reach[k] for k in sub])))
        pts.append((len(sub), statistics.mean(vals)))
    pts = [(n, f) for n, f in pts if f > 0]
    out = {"pilot_points": pts, "pilot_frontier_nodes": pts[-1][1] if pts else 0}
    if len(pts) >= 2:
        xs = [math.log(n) for n, _ in pts]
        ys = [math.log(f) for _, f in pts]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
        a = math.exp(my - b * mx)
        n_full = len(starting)
        out.update(exponent_b=round(b, 3), projected_for_all_starting_set=round(a * n_full ** b),
                   note="Projection from 142 seeds to 18,224 clearances; treat as order of magnitude only.")
    return out


# ----------------------------------------------------------------------------- workbook
def build_handcheck(con, cfg, seeds, ns, docs, v=PARSER_VERSION):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation

    n = cfg.getint("settings", "HANDCHECK_SAMPLE", 40)
    rng = random.Random(cfg.getint("settings", "PILOT_SEED", 20261116) + 1)
    eligible = [s for s in seeds if (docs.get(s["knumber"]) or {}).get("cache_path")
                and (docs.get(s["knumber"]) or {}).get("text_method") in ("text layer", "OCR")]
    known = [s for s in eligible if s["stratum"] == "Known case"]
    rest = [s for s in eligible if s["stratum"] != "Known case"]
    # spread across strata: round-robin draw
    by = collections.defaultdict(list)
    for s in rest:
        by[s["stratum"]].append(s)
    for k in by:
        rng.shuffle(by[k])
    picked = list(known)
    while len(picked) < n and any(by.values()):
        for k in sorted(by):
            if by[k] and len(picked) < n:
                picked.append(by[k].pop())
    picked.sort(key=lambda s: (s["decision_year"] or 0, s["knumber"]))

    F = "Arial"
    hdr_font = Font(name=F, bold=True, color="FFFFFF")
    hdr_fill = PatternFill("solid", fgColor="1F3864")
    fill_in = PatternFill("solid", fgColor="FFFF00")
    example_fill = PatternFill("solid", fgColor="E7E6E6")
    body = Font(name=F, size=10)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    wb = Workbook()
    ws0 = wb.active
    ws0.title = "Instructions"
    lines = [
        ("OrthoParity pilot hand-check", True),
        (f"Parser version {v}. Generated {dt.date.today().isoformat()}. {len(picked)} pilot devices, "
         f"drawn at random (seeded) across the pilot strata from devices with a readable Summary PDF.", False),
        ("", False),
        ("How to check", True),
        ("1. Open each device's PDF (link in column 'Summary PDF') and go to the page shown.", False),
        ("2. On the 'Edges' tab, fill the yellow columns for every extracted predicate: is the number right, is the "
         "role (primary/reference) right, and is it really a predicate of this device? Type Y or N.", False),
        ("3. On the 'Devices' tab, say whether the parser found every predicate. List any it missed.", False),
        ("4. Use 'Notes' for anything odd (wrong page, family member, reference device, OCR error).", False),
        ("Fill only the yellow cells. Grey rows are worked examples and are excluded from the tallies.", False),
        ("", False),
        ("Column legend", True),
        ("Confidence: HIGH = in a labeled predicate section and matches the FDA record; MEDIUM = found but FDA record "
         "missing or partial match; LOW = anything else.", False),
        ("FDA applicant / FDA device name come from FDA records by number, never from the PDF text. "
         "'Printed in PDF' is the nearby text, kept only for comparison.", False),
        ("Unofficial segment: assigned by Claude, not FDA.", False),
        ("", False),
        ("Limitations", True),
    ] + [("• " + l, False) for l in LIMITATIONS]
    for i, (t, bold) in enumerate(lines, 1):
        c = ws0.cell(row=i, column=1, value=t)
        c.font = Font(name=F, bold=bold, size=12 if i == 1 else 10)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws0.column_dimensions["A"].width = 120

    # ---------------- Edges
    ws = wb.create_sheet("Edges")
    cols = ["K-number", "Applicant", "Device name", "Decision date", "Era", "Unofficial segment", "Summary PDF",
            "Page", "#", "Predicate number", "Role", "Role basis", "Printed label", "Printed in PDF",
            "FDA applicant", "FDA device name", "Confidence", "Evidence (verbatim, max 300 chars)",
            "Number correct (Y/N)", "Role correct (Y/N)", "Real predicate (Y/N)", "Notes"]
    widths = [11, 22, 28, 11, 10, 12, 22, 6, 4, 13, 10, 22, 16, 30, 24, 30, 10, 60, 12, 12, 12, 30]
    ws.append(cols)
    example = ["EXAMPLE", "Example Spine, Inc.", "EXAMPLE INTERBODY SYSTEM", "2024-01-15", "2020-2026", "Spine",
               "https://www.accessdata.fda.gov/cdrh_docs/pdf24/K000000.pdf", 5, 1, "K111111", "primary",
               "labeled primary in PDF", "primary predicate", "Example Cage System Example Spine",
               "Example Spine, Inc.", "EXAMPLE CAGE SYSTEM", "HIGH",
               "Primary Predicate: Example Cage System (K111111) - Example Spine, Inc.", "Y", "Y", "Y",
               "Example row: shows the expected format"]
    ws.append(example)
    for c in ws[2]:
        c.fill = example_fill
    seg = {r[0]: r[1] for r in con.execute("SELECT knumber, unofficial_segment FROM clearances")}
    for s in picked:
        d = docs.get(s["knumber"]) or {}
        es = [dict(r) for r in con.execute("SELECT * FROM edges WHERE child_knumber=? AND parser_version=? "
                                           "ORDER BY list_order", (s["knumber"], v))]
        if not es:
            ws.append([s["knumber"], s["applicant"], s["devicename"], s["decision_date"], era_label(s["decision_year"]),
                       seg.get(s["knumber"]), d.get("url"), None, None, "NOT FOUND", None, None, None, None, None, None,
                       None, f"No predicate extracted. Stop reason: {(ns.get(s['knumber']) or {}).get('stop_reason')}",
                       None, None, None, None])
            continue
        for e in es:
            printed = " ".join(x for x in [e["printed_name"], e["printed_company"]] if x)
            ws.append([s["knumber"], s["applicant"], s["devicename"], s["decision_date"], era_label(s["decision_year"]),
                       seg.get(s["knumber"]), d.get("url"), e["page"], e["list_order"],
                       e["predicate_number"] or "NO NUMBER", e["role"], e["role_basis"], e["printed_label"], printed,
                       e["fda_applicant"], e["fda_device_name"], e["confidence"], e["evidence"], None, None, None, None])
    _style(ws, cols, widths, hdr_font, hdr_fill, body, border, wrap, fill_in, fill_cols=(19, 20, 21, 22))
    _links(ws, 7)
    dv = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    ws.add_data_validation(dv)
    last = ws.max_row
    for col in ("S", "T", "U"):
        dv.add(f"{col}3:{col}{last}")

    # ---------------- Devices
    wd = wb.create_sheet("Devices")
    dcols = ["K-number", "Applicant", "Device name", "Decision date", "Era", "Stratum", "Summary PDF", "Pages",
             "Text method", "Parse status", "Stop reason", "Predicates extracted", "Flags",
             "All predicates found (Y/N)", "Missed predicates (numbers)", "Notes"]
    dwidths = [11, 22, 28, 11, 10, 18, 22, 7, 11, 12, 26, 26, 30, 14, 22, 30]
    wd.append(dcols)
    wd.append(["EXAMPLE", "Example Spine, Inc.", "EXAMPLE INTERBODY SYSTEM", "2024-01-15", "2020-2026", "2020-2026",
               "https://www.accessdata.fda.gov/cdrh_docs/pdf24/K000000.pdf", 8, "text layer", "CLEAN", None,
               "K111111, K222222", "", "N", "K333333", "Example row: K333333 listed in the comparison table"])
    for c in wd[2]:
        c.fill = example_fill
    for s in picked:
        d = docs.get(s["knumber"]) or {}
        preds = [r[0] or "NO NUMBER" for r in con.execute(
            "SELECT predicate_number FROM edges WHERE child_knumber=? AND parser_version=? ORDER BY list_order",
            (s["knumber"], v))]
        flags = [f"{r[0]}: {r[1]}" for r in con.execute(
            "SELECT flag_type, number FROM flags WHERE knumber=? AND parser_version=?", (s["knumber"], v))]
        wd.append([s["knumber"], s["applicant"], s["devicename"], s["decision_date"], era_label(s["decision_year"]),
                   s["stratum"], d.get("url"), d.get("page_count"), d.get("text_method"), d.get("parse_status"),
                   (ns.get(s["knumber"]) or {}).get("stop_reason"), ", ".join(preds), "; ".join(flags)[:500],
                   None, None, None])
    _style(wd, dcols, dwidths, hdr_font, hdr_fill, body, border, wrap, fill_in, fill_cols=(14, 15, 16))
    _links(wd, 7)
    dv2 = DataValidation(type="list", formula1='"Y,N"', allow_blank=True)
    wd.add_data_validation(dv2)
    dlast = wd.max_row
    dv2.add(f"N3:N{dlast}")

    # ---------------- Tally (formulas; example row 2 excluded)
    wt = wb.create_sheet("Tally")
    wt.append(["Measure", "Y", "N", "Blank", "Share Y of answered"])
    rows = [("Edges: number correct", "Edges", "S", last), ("Edges: role correct", "Edges", "T", last),
            ("Edges: real predicate", "Edges", "U", last), ("Devices: all predicates found", "Devices", "N", dlast)]
    for i, (label, sh, col, lr) in enumerate(rows, 2):
        rng_ = f"{sh}!${col}$3:${col}${lr}"
        wt.cell(row=i, column=1, value=label)
        wt.cell(row=i, column=2, value=f'=COUNTIF({rng_},"Y")')
        wt.cell(row=i, column=3, value=f'=COUNTIF({rng_},"N")')
        if sh == "Edges":  # rows still to answer, ignoring devices with no extracted predicate
            wt.cell(row=i, column=4, value=f'=COUNTA(Edges!$J$3:$J${lr})-COUNTIF(Edges!$J$3:$J${lr},"NOT FOUND")-B{i}-C{i}')
        else:
            wt.cell(row=i, column=4, value=f'=COUNTBLANK({rng_})')
        wt.cell(row=i, column=5, value=f'=IF(B{i}+C{i}=0,"",B{i}/(B{i}+C{i}))')
        wt.cell(row=i, column=5).number_format = "0.0%"
    wt.cell(row=7, column=1, value="Counts exclude the grey example row (row 2) on each tab. Edge rows marked "
                                    "NOT FOUND (device with no extracted predicate) are not counted as edges.")
    _style(wt, ["Measure", "Y", "N", "Blank", "Share Y of answered"], [34, 8, 8, 8, 18], hdr_font, hdr_fill, body,
           border, Alignment(vertical="top"), None, fill_cols=())

    path = cfg.output_dir / f"Pilot_HandCheck_{dt.date.today().isoformat()}.xlsx"
    wb.save(path)
    return path


def _xml_safe(ws):
    """Remove characters Excel cannot store (stray control characters from OCR or broken fonts)."""
    import re as _re
    bad = _re.compile("[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD\U00010000-\U0010FFFF]")
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str):
                c.value = bad.sub("", c.value)


def _links(ws, col):
    from openpyxl.styles import Font
    for row in ws.iter_rows(min_row=3, min_col=col, max_col=col):
        c = row[0]
        if isinstance(c.value, str) and c.value.startswith("http"):
            c.hyperlink = c.value
            c.font = Font(name="Arial", size=10, color="0563C1", underline="single")


def _style(ws, cols, widths, hdr_font, hdr_fill, body, border, wrap, fill_in, fill_cols):
    from openpyxl.utils import get_column_letter
    _xml_safe(ws)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for c in ws[1]:
        c.font, c.fill, c.border = hdr_font, hdr_fill, border
        c.alignment = wrap
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.font, c.border, c.alignment = body, border, wrap
            if fill_in is not None and c.column in fill_cols and c.row > 2:
                c.fill = fill_in
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions


# ----------------------------------------------------------------------------- markdown
def _table(rows: list[list], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join("" if c is None else str(c) for c in r) + " |")
    return "\n".join(out)


def write_markdown(rep: dict, path, workbook_name: str | None) -> None:
    L = []
    a = L.append
    a(f"# OrthoParity Phase 1 pilot report")
    a("")
    a(f"Parser version {rep['parser_version']}. Generated {rep['generated_utc']} UTC. "
      f"{rep['seeds_processed']} of {rep['seeds_total']} pilot devices processed; "
      f"{rep['chain_nodes_processed']:,} more ancestor nodes processed in the chain walk.")
    a("")
    a("## 1. Do pre-1991 and blank-status clearances have a Summary PDF online?")
    a("")
    a(_table([[k, v["n"], v["pdf_online"], v["with_predicates"], ", ".join(f"{a}: {b}" for a, b in v["detail_page_labels"].items())]
              for k, v in rep["pdf_availability"].items()],
             ["Group (pilot devices)", "Devices", "Summary PDF online", "Predicates found", "FDA detail-page link"]))
    a("")
    a("## 2. Text extraction")
    a("")
    tm_s, tm_a = rep["text_method_seeds"], rep["text_method_all"]
    keys = sorted(set(tm_s) | set(tm_a))
    a(_table([[k, tm_s.get(k, 0), tm_a.get(k, 0)] for k in keys], ["Method", "Pilot devices", "All pilot nodes"]))
    a("")
    a("## 3. Edge confidence")
    a("")
    cs, ca = rep["edge_confidence_seeds"], rep["edge_confidence_all"]
    a(_table([[k, cs.get(k, 0), ca.get(k, 0)] for k in ("HIGH", "MEDIUM", "LOW")], ["Confidence", "Pilot devices' edges", "All edges"]))
    a("")
    a("## 4. Parse status by era (pilot devices)")
    a("")
    eras = rep["parse_status_by_era_seeds"]
    a(_table([[e, d.get("CLEAN", 0), d.get("AMBIGUOUS", 0), d.get("NOT PARSED", 0)] for e, d in eras.items()],
             ["Era", "CLEAN", "AMBIGUOUS", "NOT PARSED (no PDF, Statement, DEN)"]))
    a("")
    a("## 5. Stop reasons")
    a("")
    ss, sa = rep["stop_reasons_seeds"], rep["stop_reasons_all"]
    keys = sorted(set(ss) | set(sa), key=lambda k: -sa.get(k, 0))
    a(_table([[k, ss.get(k, 0), sa.get(k, 0)] for k in keys], ["Stop reason", "Pilot devices", "All pilot nodes"]))
    a("")
    a("## 6. Downloads")
    a("")
    u = rep["url_pattern_check"]
    a(f"- PDFs downloaded or cached: {rep['pdf_count']:,}. Average {rep['avg_pdf_mb']} MB, median {rep['median_pdf_mb']} MB.")
    a(f"- Average download time: {rep['avg_download_seconds']} s per PDF (requests are throttled to one per second).")
    a(f"- URL pattern check: {u['link_matches_first_candidate']:,} of {u['downloads_via_detail_link']:,} detail-page links "
      f"equal the first URL-pattern guess; {u['downloads_via_pattern_fallback']} PDFs came from the pattern fallback.")
    t = rep.get("timing", {})
    a("")
    a(_table([[k, v["n"], v["median_s"], v["mean_s"]] for k, v in t.items()], ["Per node (your PC)", "Nodes", "Median s", "Mean s"]))
    a("")
    a("## 7. Full-run extrapolation (18,224 starting-set clearances)")
    a("")
    f = rep["full_run"]
    a(_table([[g, d["clearances"], d["pilot_sample"], d["pilot_pdf_rate"], d["pilot_ocr_share"], d["hours_A"], d["hours_B"]]
              for g, d in f["by_group"].items()],
             ["Group", "Clearances", "Pilot sample", "PDF online rate", "OCR share", "Hours (A)", "Hours (B)"]))
    a("")
    a(f"- Statement-only and De Novo clearances need no request: {f['groups'].get('skip', 0):,}.")
    a(f"- Expected Summary PDFs: about {f['expected_pdfs']:,}, about {f['expected_disk_gb']} GB of cache.")
    a(f"- Runtime A (current settings: detail page first, pre-1991 blanks looked up): about {f['runtime_hours_A_current_settings']} hours.")
    a(f"- Runtime B (approved Gate 1 settings: URL pattern first, 1995-and-earlier clearances stopped without a request): about {f['runtime_hours_B_pattern_first_and_pre1991_stop']} hours.")
    a("- The ancestor frontier (Phase 3) comes on top of this.")
    a("")
    a("## 8. Chains")
    a("")
    a(f"- Pilot chains that hit TRUNCATED at MAX_GENERATIONS: **{rep['chains_truncated']}** of {rep['seeds_processed']}.")
    a(f"- Chains fully extracted within the pilot: {rep['chains_complete']} of {rep['seeds_processed']}.")
    a("")
    a(_table([[k, v] for k, v in rep["chain_depth_distribution"].items()], ["Chain depth (generations)", "Pilot devices"]))
    a("")
    fe = rep.get("frontier_estimate", {})
    a(f"- Ancestors outside the starting set reached by the pilot: {rep['frontier_nodes_in_pilot']:,}.")
    if fe.get("projected_for_all_starting_set"):
        a(f"- Rough frontier projection for the full run: about {fe['projected_for_all_starting_set']:,} extra nodes "
          f"(species-accumulation fit, exponent {fe['exponent_b']}). Order of magnitude only; Phase 2 edges give the real count "
          "before Phase 3 starts.")
    a("")
    a("## 9. Flags and review queue")
    a("")
    a(_table([[k, v] for k, v in sorted(rep["flags_all"].items(), key=lambda x: -x[1])], ["Flag", "Count (all pilot nodes)"]))
    a("")
    a(_table([[k, v] for k, v in sorted(rep["review_queue_all"].items(), key=lambda x: -x[1])], ["Review queue item", "Count"]))
    a("")
    if workbook_name:
        a(f"## 10. Hand-check workbook\n\n`outputs/{workbook_name}`: 40 pilot devices with page numbers, extracted predicates, "
          "and blank Y/N columns.")
        a("")
    a("## Limitations")
    a("")
    for l in LIMITATIONS:
        a(f"- {l}")
    a("")
    path.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
