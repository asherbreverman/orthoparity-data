"""Lineage trees back to the earliest ancestors on record, by unofficial segment (full dataset).

Every device follows its PRIMARY predicate back, generation by generation (up to MAX_GENERATIONS). Because
each device has one primary predicate, the lineages form trees. For each segment the page draws the trunk
of that tree: the ancestors that the most lineages run through, connected to the nearest kept ancestor, with
the earliest ancestors on record at the top. Tables list the earliest ancestors on record and the most-cited
ancestors across full chains (every predicate, every generation).

"Earliest on record" means the record ends there (no summary on file, a predicate without an FDA number,
a 510(k) Statement, the generation limit, or an ancestor not yet extracted). It does not mean the device is
the true original of its lineage.

Usage:  python orthoparity.py lineage-trees [--top 40]
Writes outputs/Lineage_Trees_by_Segment.html and outputs/lineage/<segment>.svg. Needs Graphviz ("dot").
"""
from __future__ import annotations

import collections
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
from collections import deque

from predicate_chain.config import load_config
from predicate_chain.chains import review_overrides
from predicate_chain.db import connect

TRUNC = "TRUNCATED"
LOW_ONLY = "Only low-confidence predicates (pending review)"
NOT_EXTRACTED = "Not yet extracted"
END_SHORT = {
    "No summary on file (pre-1991)": "no summary on file (pre-1991)",
    "No summary on file (1991-1995)": "no summary on file (1991-95)",
    "Predicate has no FDA number": "cites a predicate with no FDA number",
    "Summary parsed, no predicate found": "no predicate found in its Summary",
    "No Summary PDF available": "no Summary PDF online",
    "Statement only, no predicate data": "510(k) Statement only",
    "PMA (P number)": "PMA device",
    "De Novo (DEN)": "De Novo",
    "K-number not found in any FDA source": "number not in FDA records",
    "Wrong file (PDF is for another number)": "wrong PDF on file",
    TRUNC: "10-generation limit reached",
    LOW_ONLY: "predicates read with low confidence, pending review",
    NOT_EXTRACTED: "outside ortho set, not yet extracted",
}


def vkey(v):
    return tuple(int(x) if x.isdigit() else x for x in v.split("."))


def clean(s, n=None):
    s = re.sub(r"\s+", " ", (s or "").replace("�", "")).strip()
    return (s[: n - 1].rstrip() + "…") if n and len(s) > n else s


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def e(x):
    return html.escape("" if x is None else str(x))


class Graph:
    def __init__(self, con):
        self.version = {}
        for k, v in con.execute("SELECT knumber, parser_version FROM node_status"):
            if k not in self.version or vkey(v) > vkey(self.version[k]):
                self.version[k] = v
        self.stop = {}
        for k, v, sr in con.execute("SELECT knumber, parser_version, stop_reason FROM node_status"):
            if self.version.get(k) == v:
                self.stop[k] = sr
        self.adj = collections.defaultdict(list)       # all numbered predicates
        self.primary = {}                              # child -> (predicate, used_fallback)
        first_any = {}
        self.low_skipped = 0
        self.reviewed_edges = 0
        self.overrides = review_overrides(con)
        self.low_only = set()
        for ch, v, p, role, fam, lo, conf in con.execute(
                "SELECT child_knumber, parser_version, predicate_number, role, family_of, list_order, confidence FROM edges "
                "WHERE predicate_number IS NOT NULL ORDER BY child_knumber, list_order"):
            if self.version.get(ch) != v:
                continue
            ov = self.overrides.get((ch, p))
            if ov:
                self.reviewed_edges += 1
                if ov[0] == "drop":
                    continue
                if ov[0] == "replace":
                    p = ov[1]
                conf = "REVIEWED"  # a reviewed edge is usable whatever its parser confidence
            if conf == "LOW":  # unreviewed LOW edges (often misread numbers) are left out of the trees
                self.low_skipped += 1
                self.low_only.add(ch)
                continue
            self.adj[ch].append(p)
            if fam is None:
                first_any.setdefault(ch, p)
                if role == "primary" and ch not in self.primary:
                    self.primary[ch] = (p, False)
        for ch, p in first_any.items():
            if ch not in self.primary:
                self.primary[ch] = (p, True)
        self.low_only -= set(self.adj)
        self.ident = {}
        for r in con.execute("SELECT knumber, applicant, devicename, decision_year, product_code, unofficial_segment "
                             "FROM clearances"):
            self.ident[r[0]] = {"applicant": r[1], "device": r[2], "year": r[3], "code": r[4], "seg": r[5], "ss": True}
        for r in con.execute("SELECT knumber, applicant, devicename, decision_year, product_code, review_panel "
                             "FROM fda_master"):
            if r[0] not in self.ident:
                self.ident[r[0]] = {"applicant": r[1], "device": r[2], "year": r[3], "code": r[4], "panel": r[5],
                                    "ss": False}
        pma = collections.defaultdict(collections.Counter)
        for b, nm in con.execute("SELECT predicate_base, printed_name FROM edges WHERE predicate_kind='P' "
                                 "AND printed_name IS NOT NULL"):
            nm2 = re.sub(r"^[^A-Za-z]+|^(?:the|x|used\.?)\s+", "", nm or "", flags=re.I).strip()
            if len(nm2) >= 8 and sum(ch.isalpha() for ch in nm2) >= 6:
                pma[b][nm2] += 1
        for b, cnt in pma.items():
            self.ident.setdefault(b, {"applicant": "PMA (not in 510(k) records)", "device": cnt.most_common(1)[0][0]
                                      + " (as printed)", "year": None, "code": None, "ss": False})

    def info(self, k):
        if k not in self.ident and k.startswith("P") and "/" in k:
            k = k.split("/")[0]  # PMA supplement: use the base PMA's printed name
        return self.ident.get(k, {"applicant": None, "device": None, "year": None, "code": None, "ss": False})

    def lineage(self, k, max_gen):
        path = [k]
        fallback_steps = set()
        while True:
            cur = path[-1]
            if cur not in self.version:
                return path, NOT_EXTRACTED, fallback_steps
            nxt = self.primary.get(cur)
            if not nxt:
                if cur in self.low_only:
                    return path, LOW_ONLY, fallback_steps
                return path, self.stop.get(cur) or "no numbered predicate", fallback_steps
            if len(path) - 1 >= max_gen:
                return path, TRUNC, fallback_steps
            p, fb = nxt
            if p in path:
                return path, "cycle in data", fallback_steps
            if fb:
                fallback_steps.add((cur, p))
            path.append(p)

    def ancestors(self, k, max_gen):
        seen = {k: 0}
        dq = deque([k])
        while dq:
            x = dq.popleft()
            if seen[x] >= max_gen:
                continue
            for p in self.adj.get(x, ()):
                if p not in seen:
                    seen[p] = seen[x] + 1
                    dq.append(p)
        del seen[k]
        return seen


def tree_dot(g, kept, parent_of, gaps, through, ends, end_reason, seg_n, fallback_edges):
    L = ['digraph G {', 'graph [rankdir=RL, bgcolor="white", nodesep=0.12, ranksep=0.45, margin=0.1, '
         'fontname="Helvetica"];', 'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, '
         'fillcolor="white", color="#9aa5b1", margin="0.08,0.04"];', 'edge [color="#7b8794", arrowsize=0.55, '
         'penwidth=0.9, fontname="Helvetica", fontsize=8, fontcolor="#5b6876"];']
    rank = {k: r for r, k in enumerate(sorted(kept, key=lambda x: -through[x]))}
    for k in kept:
        i = g.info(k)
        lab = [f"{k}  ({i.get('year') or '?'})", clean(i.get("applicant"), 26), clean(i.get("device"), 30),
               f"{through[k]:,} lineages run through"]
        attrs = {}
        if rank[k] < 5:
            attrs.update(fillcolor="#e07f00", fontcolor="white", color="#9c5700")
        elif rank[k] < 15:
            attrs.update(fillcolor="#f6b042", color="#9c5700")
        else:
            attrs.update(fillcolor="#ffe2ad", color="#c98a1a")
        if not i.get("ss"):
            attrs.update(fillcolor="#dfe7ef", fontcolor="#16212c", color="#7b8794")
        if k in end_reason:
            lab.append(f"{ends[k]:,} lineage{'s' if ends[k] != 1 else ''} stop{'s' if ends[k] == 1 else ''} here: " + END_SHORT.get(end_reason[k], clean(end_reason[k], 30)))
            attrs["penwidth"] = "2.2"
            attrs["color"] = "#123b5e"
        label = "\\n".join(x.replace('"', "'") for x in lab if x)
        a = ", ".join(f'{key}="{val}"' for key, val in attrs.items())
        L.append(f'"{k}" [label="{label}"{", " + a if a else ""}];')
    for k, p in parent_of.items():
        if p is None:
            continue
        lab = f' label=" +{gaps[k]} gen"' if gaps[k] > 1 else ""
        style = " style=dashed" if (k, p) in fallback_edges else ""
        L.append(f'"{k}" -> "{p}" [{lab.strip()}{style}];' if (lab or style) else f'"{k}" -> "{p}";')
    tops = [k for k in kept if parent_of.get(k) is None]
    if tops:  # every earliest-kept ancestor lines up in the left column
        L.append("{rank=max; " + " ".join(f'"{k}"' for k in tops) + "}")
    L.append("}")
    return "\n".join(L)


def main():
    top_n = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 40
    cfg = load_config()
    con = connect(cfg.db_path)
    max_gen = cfg.max_generations
    g = Graph(con)
    devices = [(r[0], r[1] or "Unassigned") for r in con.execute(
        "SELECT knumber, unofficial_segment FROM clearances")]
    by_seg = collections.defaultdict(list)
    for k, s in devices:
        by_seg[s].append(k)
    out_dir = cfg.output_dir / "lineage"
    out_dir.mkdir(parents=True, exist_ok=True)
    have_dot = shutil.which("dot") is not None
    res = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "max_generations": max_gen,
           "segments": [], "low_edges_left_out": g.low_skipped, "reviewed_edges": g.reviewed_edges, "parser_version": max(set(g.version.values()), key=vkey),
           "starting_set": len(devices), "ancestors": 0}
    seedset = {k for k, _ in devices}
    res["ancestors"] = sum(1 for k, v in g.version.items() if v == res["parser_version"] and k not in seedset)
    for seg, ks in sorted(by_seg.items(), key=lambda x: -len(x[1])):
        through = collections.Counter()
        ends = collections.Counter()
        end_reason = {}
        reach_decade = collections.Counter()
        cited = collections.Counter()
        depths = []
        fallback_edges = set()
        with_chain = 0
        end_reasons_all = collections.Counter()
        for k in ks:
            if not g.primary.get(k):
                continue
            with_chain += 1
            path, why, fb = g.lineage(k, max_gen)
            fallback_edges |= fb
            for n in path:
                through[n] += 1
            ends[path[-1]] += 1
            end_reason[path[-1]] = why
            end_reasons_all[why] += 1
            depths.append(len(path) - 1)
            anc = g.ancestors(k, max_gen)
            for n in anc:
                cited[n] += 1
            yrs = [g.info(n).get("year") for n in anc] + [g.info(k).get("year")]
            yrs = [y for y in yrs if y]
            if yrs:
                reach_decade[(min(yrs) // 10) * 10] += 1
        if not with_chain:
            res["segments"].append({"segment": seg, "devices": len(ks), "with_chain": 0})
            continue
        # ---- contracted primary-lineage tree -------------------------------------
        own = set(ks)
        cand = [n for n, c in through.most_common() if c >= 2]
        kept = set(cand[:top_n])
        roots_rank = [n for n, c in ends.most_common() if c >= 2 and through[n] >= 2]
        kept |= set(roots_rank[: max(6, top_n // 5)])
        parent_of, gaps = {}, {}
        for k in kept:
            cur, steps = k, 0
            p = None
            while True:
                nxt = g.primary.get(cur) if cur in g.version else None
                if not nxt:
                    break
                cur = nxt[0]
                steps += 1
                if cur in kept:
                    p = cur
                    break
                if steps > max_gen + 2:
                    break
            parent_of[k], gaps[k] = p, steps
        kept_end = {n: end_reason[n] for n in kept if n in end_reason and (ends[n] >= 3 or parent_of.get(n) is None)}
        svg = None
        if have_dot and kept:
            dot = tree_dot(g, kept, parent_of, gaps, through, ends, kept_end, len(ks), fallback_edges)
            (out_dir / f"{slug(seg)}.dot").write_text(dot, encoding="utf-8")
            svg = subprocess.run(["dot", "-Tsvg"], input=dot.encode("utf-8"), capture_output=True,
                                 check=True).stdout.decode("utf-8")
            svg = svg[svg.find("<svg"):]
            svg = re.sub(r'<svg width="([\d.]+)pt" height="([\d.]+)pt"', r'<svg data-w="\1" data-h="\2"', svg, count=1)
            (out_dir / f"{slug(seg)}.svg").write_text(svg, encoding="utf-8")
        og = []
        for n, c in ends.most_common(15):
            if n in own and through[n] == 1:
                continue  # a device whose own record ends at itself is not an ancestor
            i = g.info(n)
            og.append({"knumber": n, "lineages": c, "year": i.get("year"), "applicant": clean(i.get("applicant")),
                       "device": clean(i.get("device")), "code": i.get("code"),
                       "why": END_SHORT.get(end_reason[n], end_reason[n]), "in_ortho_set": i.get("ss")})
            if len(og) >= 12:
                break
        mc = []
        for n, c in cited.most_common(12):
            i = g.info(n)
            mc.append({"knumber": n, "devices": c, "year": i.get("year"), "applicant": clean(i.get("applicant")),
                       "device": clean(i.get("device")), "code": i.get("code"), "in_ortho_set": i.get("ss")})
        depths.sort()
        res["segments"].append({
            "segment": seg, "devices": len(ks), "with_chain": with_chain,
            "median_lineage_depth": depths[len(depths) // 2], "max_lineage_depth": depths[-1],
            "truncated_lineages": end_reasons_all.get(TRUNC, 0),
            "not_yet_extracted_ends": end_reasons_all.get(NOT_EXTRACTED, 0),
            "low_only_ends": end_reasons_all.get(LOW_ONLY, 0),
            "end_reasons": dict(end_reasons_all.most_common()),
            "reach_decade": {str(k): v for k, v in sorted(reach_decade.items())},
            "earliest_on_record": og, "most_cited": mc, "kept_nodes": len(kept), "svg": svg})
    (out_dir / "lineage_trees.json").write_text(json.dumps({k: v for k, v in res.items()}, indent=1, default=str),
                                               encoding="utf-8")
    page = cfg.output_dir / "Lineage_Trees_by_Segment.html"
    page.write_text(render(res), encoding="utf-8")
    print("Page:", page)
    for s in res["segments"]:
        print(s["segment"], s["devices"], s.get("with_chain"), s.get("median_lineage_depth"), s.get("truncated_lineages"),
              s.get("not_yet_extracted_ends"), s.get("reach_decade"))
    return 0


# ----------------------------------------------------------------------------- page
CSS = """
:root {
  /* Reference-atlas layout: totals and reach chart first, then one section per segment */
  --ink: #16212c; --muted: #5b6876; --line: #d8dee5; --bg: #f5f7f9; --panel: #ffffff;
  --navy: #123b5e; --amber: #e07f00; --amber-soft: #ffe2ad; --red: #b3261e;
  --font-display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --font-body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "IBM Plex Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --ink: #e6ebf0; --muted: #a3b0bd; --line: #2e3a46; --bg: #10161c; --panel: #17202a;
  --navy: #8fbbe3; --amber: #ffad33; --amber-soft: #5a3d0c; --red: #ff8a80; color-scheme: dark; } }
:root[data-theme="dark"] { --ink: #e6ebf0; --muted: #a3b0bd; --line: #2e3a46; --bg: #10161c; --panel: #17202a;
  --navy: #8fbbe3; --amber: #ffad33; --amber-soft: #5a3d0c; --red: #ff8a80; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--font-body); }
header, main, footer { max-width: 1180px; margin: 0 auto; padding: 0 20px; }
header { padding-top: 34px; }
h1, h2, h3 { font-family: var(--font-display); text-wrap: balance; line-height: 1.15; }
h1 { font-size: 34px; margin: 0 0 8px; }
h2 { font-size: 24px; margin: 0 0 4px; }
h3 { font-size: 16px; margin: 22px 0 8px; }
.lede { color: var(--muted); max-width: 72ch; margin: 0 0 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 16px 0; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
.tile b { display: block; font: 600 26px/1.1 var(--font-display); font-variant-numeric: tabular-nums; }
.tile span { color: var(--muted); font-size: 13px; }
.callout { border-left: 4px solid var(--amber); background: var(--panel); padding: 12px 16px; border-radius: 6px;
  border-top: 1px solid var(--line); border-right: 1px solid var(--line); border-bottom: 1px solid var(--line);
  font-size: 14px; max-width: 90ch; }
nav.segs { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line); padding: 10px 0; }
nav.segs div { max-width: 1180px; margin: 0 auto; padding: 0 20px; display: flex; flex-wrap: wrap; gap: 6px; }
nav.segs a { color: var(--ink); text-decoration: none; border: 1px solid var(--line); background: var(--panel);
  border-radius: 999px; padding: 4px 11px; font-size: 13px; }
nav.segs a:hover, nav.segs a:focus-visible { border-color: var(--navy); outline: none; }
nav.segs small { color: var(--muted); font-variant-numeric: tabular-nums; }
section.seg { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 20px; margin: 22px 0; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 4px; }
.chip { font-size: 12.5px; border-radius: 999px; padding: 3px 10px; background: var(--bg); border: 1px solid var(--line); }
.chip.warn { border-color: var(--red); color: var(--red); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--muted); margin: 10px 0; }
.sw { display: inline-block; width: 14px; height: 11px; border-radius: 3px; vertical-align: -1px; margin-right: 5px; border: 1px solid #9aa5b1; }
.tree { overflow: auto; max-height: 820px; background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.tree svg { display: block; height: auto; }
.zoom { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); margin: 6px 0; }
.zoom input { width: 160px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.k { font-family: var(--font-mono); font-size: 12.5px; white-space: nowrap; }
.bar { position: relative; min-width: 110px; }
.bar i { position: absolute; left: 0; top: 5px; height: 20px; background: var(--amber-soft); border-radius: 3px; }
.bar span { position: relative; padding-left: 6px; font-variant-numeric: tabular-nums; }
.tablewrap { overflow-x: auto; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
@media (max-width: 900px) { .two { grid-template-columns: 1fr; } }
.note { font-size: 13.5px; color: var(--muted); max-width: 85ch; }
.reach { display: grid; gap: 6px; margin: 10px 0; }
.reach .row { display: grid; grid-template-columns: 170px 1fr 70px; gap: 10px; align-items: center; font-size: 13px; }
.stack { display: flex; height: 16px; border-radius: 4px; overflow: hidden; background: var(--bg); border: 1px solid var(--line); }
.stack i { display: block; height: 100%; }
.reach .row span:last-child { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
.keys { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12.5px; color: var(--muted); }
footer { padding: 10px 20px 40px; }
footer li { margin: 4px 0; }
"""

JS = """
document.querySelectorAll('.zoom input').forEach(function (inp) {
  var box = document.getElementById(inp.dataset.target); var svg = box && box.querySelector('svg');
  if (!svg) return;
  var w = parseFloat(svg.dataset.w);
  function apply() { var z = inp.value / 100;
    svg.style.width = (inp.value == 100 ? '100%' : (w * 1.333 * z) + 'px');
    inp.nextElementSibling.textContent = inp.value == 100 ? 'fit' : inp.value + '%'; }
  inp.addEventListener('input', apply); apply();
});
"""

DECADE_COLORS = {"1970": "#123b5e", "1980": "#2f6690", "1990": "#5c97bf", "2000": "#a7c5df", "2010": "#e3c27a",
                 "2020": "#e07f00"}


def render(res):
    segs = [s for s in res["segments"] if s.get("with_chain")]
    tot = sum(s["devices"] for s in res["segments"])
    wc = sum(s["with_chain"] for s in segs)
    pre90 = sum(v for s in segs for d, v in s["reach_decade"].items() if int(d) < 1990)
    trunc = sum(s["truncated_lineages"] for s in segs)
    ne = sum(s["not_yet_extracted_ends"] for s in segs)
    o = []
    a = o.append
    a('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">')
    a('<title>Predicate Lineages by Segment</title>')
    a('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    a('<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=IBM+Plex+Mono&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">')
    a(f"<style>{CSS}</style></head><body><header>")
    a("<h1>Predicate lineages by orthopedic segment</h1>")
    a('<p class="lede">Every orthopedic 510(k) clearance from 1976 to 2026 with a predicate on file, traced back through its '
      'primary predicate to the earliest ancestor on record. Built from ' + f'{res["starting_set"]:,} FDA clearances and {res["ancestors"]:,} ancestors (Phases 2 and 3 of the OrthoParity predicate build). '
      'Segments are unofficial (assigned by Claude, not FDA).</p>')
    a('<div class="tiles">')
    for big, small in [(f"{tot:,}", "orthopedic clearances"), (f"{wc:,}", "cite a numbered predicate"),
                       (f"{pre90:,}", "chains that reach a pre-1990 ancestor"),
                       (f"{trunc:,}", "primary lineages hit the 10-generation limit")]:
        a(f'<div class="tile"><b>{big}</b><span>{e(small)}</span></div>')
    a("</div>")
    a('<div class="callout"><b>How to read a tree.</b> Earliest ancestors on record sit on the left; arrows point from a '
      'device to the predicate it cites. Each box is an ancestor that many lineages in the segment run through, and darker '
      'orange marks the ancestors with the most lineages. "+3 gen" on an arrow means three less-common generations were folded '
      'into that line. Boxes with a thick navy border are where lineages stop on record: the paper trail ends there (no '
      'summary on file before 1996, a predicate with no FDA number, a PMA device, the 10-generation limit, or predicates '
      'read with low confidence that are still pending review). A stop does not prove the device is the original '
      'of its lineage.</div>')
    a("<h3>How far back the chains reach</h3>")
    a('<p class="note">Decade of the oldest ancestor anywhere in each device\'s full chain (every predicate, every generation).</p>')
    a('<div class="keys">' + "".join(f'<span><i class="sw" style="background:{c}"></i>{d}s</span>'
                                     for d, c in DECADE_COLORS.items()) + "</div><div class=\"reach\">")
    for s in segs:
        n = sum(s["reach_decade"].values()) or 1
        bars = "".join(f'<i style="width:{100 * v / n:.2f}%;background:{DECADE_COLORS.get(d, "#999")}" '
                       f'title="{d}s: {v:,}"></i>' for d, v in sorted(s["reach_decade"].items()))
        a(f'<div class="row"><span>{e(s["segment"])}</span><div class="stack" role="img" aria-label="{e(s["segment"])} '
          f'reach by decade">{bars}</div><span>{n:,}</span></div>')
    a("</div></header>")
    a('<nav class="segs" aria-label="Segments"><div>' + "".join(
        f'<a href="#{slug(s["segment"])}">{e(s["segment"])} <small>{s["with_chain"]:,}</small></a>' for s in segs) +
      "</div></nav><main>")
    for s in segs:
        sid = slug(s["segment"])
        a(f'<section class="seg" id="{sid}"><h2>{e(s["segment"])}</h2><div class="chips">')
        a(f'<span class="chip">{s["with_chain"]:,} of {s["devices"]:,} clearances cite a numbered predicate</span>')
        a(f'<span class="chip">median primary lineage {s["median_lineage_depth"]} generations (max {s["max_lineage_depth"]})</span>')
        if s["truncated_lineages"]:
            a(f'<span class="chip warn">{s["truncated_lineages"]:,} hit the 10-generation limit</span>')
        if s["not_yet_extracted_ends"]:
            a(f'<span class="chip">{s["not_yet_extracted_ends"]:,} end at an ancestor not yet extracted</span>')
        if s["with_chain"] < 30:
            a('<span class="chip warn">small segment: read as examples</span>')
        a("</div>")
        if s.get("svg"):
            a('<div class="legend"><span><i class="sw" style="background:#e07f00"></i>top 5 ancestors by lineages</span>'
              '<span><i class="sw" style="background:#f6b042"></i>next 10</span>'
              '<span><i class="sw" style="background:#ffe2ad"></i>others shown</span>'
              '<span><i class="sw" style="background:#dfe7ef"></i>outside the orthopedic set</span>'
              '<span><i class="sw" style="background:#fff;border:2px solid #123b5e"></i>lineages stop here (reason shown)</span>'
              '<span>dashed arrow: no numbered primary, first listed predicate followed</span></div>')
            a(f'<div class="zoom"><label for="z-{sid}">Zoom</label><input id="z-{sid}" type="range" min="30" max="140" '
              f'value="100" data-target="t-{sid}"><span></span></div>')
            a(f'<figure style="margin:0"><div class="tree" id="t-{sid}" role="img" aria-label="Main primary-predicate lineages '
              f'in {e(s["segment"])}, earliest ancestors on record on the left">{s["svg"]}</div>'
              f'<figcaption class="note">The {s["kept_nodes"]} ancestors that the most {e(s["segment"])} lineages run through. '
              'Scroll inside the box for large trees.</figcaption></figure>')
        a('<div class="two"><div>')
        a(f'<h3>Earliest ancestors on record</h3><div class="tablewrap"><table><thead><tr><th>Number</th><th>Device (FDA record)</th>'
          '<th class="num">Year</th><th>Lineages ending here</th><th>Why the record stops</th></tr></thead><tbody>')
        mx = max([x["lineages"] for x in s["earliest_on_record"]] or [1])
        for x in s["earliest_on_record"]:
            a(f'<tr><td class="k">{e(x["knumber"])}</td><td>{e(x["device"])}<br><small class="note">{e(x["applicant"])}</small></td>'
              f'<td class="num">{e(x["year"])}</td><td class="bar"><i style="width:{100 * x["lineages"] / mx:.0f}%"></i>'
              f'<span>{x["lineages"]:,}</span></td><td>{e(x["why"])}</td></tr>')
        a("</tbody></table></div></div><div>")
        a(f'<h3>Most-cited ancestors (full chains)</h3><div class="tablewrap"><table><thead><tr><th>Number</th>'
          f'<th>Device (FDA record)</th><th class="num">Year</th><th>Clearances whose chain includes it</th></tr></thead><tbody>')
        for x in s["most_cited"]:
            pct = 100 * x["devices"] / s["with_chain"]
            a(f'<tr><td class="k">{e(x["knumber"])}</td><td>{e(x["device"])}<br><small class="note">{e(x["applicant"])}</small></td>'
              f'<td class="num">{e(x["year"])}</td><td class="bar"><i style="width:{min(pct, 100):.0f}%"></i>'
              f'<span>{x["devices"]:,} ({pct:.0f}%)</span></td></tr>')
        a("</tbody></table></div></div></div></section>")
    a("</main><footer><h3>Method and limitations</h3><ul class=\"note\">")
    for li in [
        "Predicates are what each submitter wrote in its 510(k) Summary, read by the OrthoParity predicate parser (version " + res["parser_version"] + "; "
        "a 40-device hand-check of the pilot (parser 1.1.0) found no errors in 112 edges, consistent with an edge error rate up to about 3%). FDA's "
        "internal review is not verified. Substantial equivalence says nothing about clinical performance, outcomes or price.",
        "A primary lineage follows one predicate per generation: the one labeled primary, or the first listed. Reference "
        "predicates are left out of the trees and counted in the most-cited tables.",
        "Earliest on record is where the paper trail stops, not a claim about the true original. FDA has no posted summaries "
        "before 1996, and 1996-1999 summaries usually name predicates without numbers, so most lineages stop in the late 1990s.",
        f"Ancestors outside the orthopedic product codes ({res['ancestors']:,} devices, mostly general surgery, radiology, dental and "
        "neurology) were extracted in Phase 3 with the same parser and rules.",
        f"LOW-confidence edges ({res['low_edges_left_out']:,}, numbers that may be misread) are left out until reviewed; "
        f"MEDIUM edges are included. {res['reviewed_edges']:,} edges carry a Phase 4 review decision (Claude review): "
        "confirmed, corrected to the number the document meant, or left out as the document's own number misread.",
        "Review rule D: a predicate named without a K-number is ignored, the K-number decides identity even when the "
        "printed name differs, and any other K-number in a Summary counts as a predicate. That last rule also counts "
        "K-numbers cited for compatibility or test comparisons, and a typo in a submitter's K-number is taken as printed.",
        "Company names appear as printed at clearance, with no roll-up to current owners. PMA ancestors are named as printed "
        "in the citing summary. Segments are unofficial labels assigned by Claude.",
        "Independent research built from public FDA data, provided as is; not regulatory advice.",
    ]:
        a(f"<li>{e(li)}</li>")
    a(f'</ul><p class="note">Generated {e(res["generated_utc"])} UTC.</p></footer><script>{JS}</script></body></html>')
    return "".join(o)


if __name__ == "__main__":
    sys.exit(main())
