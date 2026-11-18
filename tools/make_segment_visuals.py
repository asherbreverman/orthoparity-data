"""Predicate tree visuals by unofficial segment.

For every segment it draws a PRIMARY LINEAGE TREE: each device follows its primary predicate back,
generation by generation, and lineages merge where devices share an ancestor. Ancestors shared by two
or more devices are highlighted. It also ranks the MOST-SHARED ANCESTORS across the full chains
(every role, every generation).

Usage:  python orthoparity.py segment-visuals [--run pilot | --all]
        --run pilot  uses the pilot devices (default); --all uses every starting-set device with a chain.
Writes outputs/visuals/<segment>.svg, outputs/visuals/segment_visuals.json and
outputs/Predicate_Trees_by_Segment.html. Needs Graphviz (the "dot" program) for the tree drawings.
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

from predicate_chain.chains import build_chain, latest_versions
from predicate_chain.config import load_config
from predicate_chain.db import connect

STOP_SHORT = {
    "No summary on file (pre-1991)": "no summary on file (pre-1991)",
    "No summary on file (1991-1995)": "no summary on file (1991-95)",
    "Predicate has no FDA number": "predicate has no FDA number",
    "Summary parsed, no predicate found": "no predicate found in Summary",
    "No Summary PDF available": "no Summary PDF online",
    "Statement only, no predicate data": "510(k) Statement only",
    "PMA (P number)": "PMA",
    "De Novo (DEN)": "De Novo",
    "K-number not found in any FDA source": "number not in FDA records",
    "Wrong file (PDF is for another number)": "wrong file",
    "Needs OCR": "needs OCR",
    "Unreadable PDF after OCR": "unreadable PDF",
}
TRUNC = "TRUNCATED at generation limit"


def clean(s, n=None):
    s = (s or "").replace("�", "").strip()
    s = re.sub(r"\s+", " ", s)
    if n and len(s) > n:
        s = s[: n - 1].rstrip() + "…"
    return s


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def identity(con, k):
    r = con.execute("SELECT applicant, devicename, decision_year, product_code, unofficial_segment "
                    "FROM clearances WHERE knumber=?", (k,)).fetchone()
    if r:
        return dict(r) | {"in_starting_set": True}
    r = con.execute("SELECT applicant, devicename, decision_year, product_code, review_panel FROM fda_master "
                    "WHERE knumber=?", (k,)).fetchone()
    if r:
        return dict(r) | {"in_starting_set": False}
    out = {"applicant": None, "devicename": None, "decision_year": None, "product_code": None,
           "in_starting_set": False}
    if k.startswith("P"):
        names = con.execute("SELECT printed_name, COUNT(*) n FROM edges WHERE predicate_base=? AND printed_name IS NOT NULL "
                            "GROUP BY 1 ORDER BY n DESC, LENGTH(printed_name) DESC", (k,)).fetchall()
        for row in names:
            nm = re.sub(r"^[^A-Za-z]+|^(?:the|x|used\.?)\s+", "", row[0] or "", flags=re.I).strip()
            if len(nm) >= 8 and sum(ch.isalpha() for ch in nm) >= 6:
                out["devicename"] = nm + " (as printed)"
                break
        out["applicant"] = "PMA, not in 510(k) records"
    return out


fallback: set = set()  # (child, predicate) lineage steps that used a non-primary predicate


def primary_lineage(con, seed, versions, max_gen):
    """Seed -> its primary predicate -> that one's primary predicate ... up to max_gen steps.
    Returns the path and why it ends (a stop reason, TRUNCATED, or "not extracted")."""
    def status(k):
        v = versions.get(k)
        if v is None:
            return None, None
        st = con.execute("SELECT stop_reason FROM node_status WHERE knumber=? AND parser_version=?", (k, v)).fetchone()
        return v, (st["stop_reason"] if st else None)

    path = [seed]
    k = seed
    while True:
        v, stop = status(k)
        if v is None:
            return path, "not extracted"
        e = con.execute("SELECT predicate_number FROM edges WHERE child_knumber=? AND parser_version=? AND role='primary' "
                        "AND family_of IS NULL AND predicate_number IS NOT NULL ORDER BY list_order LIMIT 1",
                        (k, v)).fetchone()
        if not e:  # no numbered primary: follow the first numbered predicate listed, drawn dashed
            e = con.execute("SELECT predicate_number FROM edges WHERE child_knumber=? AND parser_version=? "
                            "AND family_of IS NULL AND predicate_number IS NOT NULL ORDER BY list_order LIMIT 1",
                            (k, v)).fetchone()
            if e:
                fallback.add((k, e[0]))
        if not e:
            return path, stop or "no numbered primary predicate"
        if len(path) - 1 >= max_gen:
            return path, TRUNC
        if e[0] in path:
            return path, "cycle in data"
        path.append(e[0])
        k = e[0]


def dot_for_segment(con, seg, seeds, lineages, shared, max_gen):
    lines = ['digraph G {', 'graph [rankdir=TB, bgcolor="white", nodesep=0.25, ranksep=0.42, fontname="Helvetica", '
             'margin=0.1];', 'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, '
             'fillcolor="white", color="#9aa5b1", penwidth=1, margin="0.08,0.04"];',
             'edge [color="#7b8794", arrowsize=0.6, penwidth=0.9];']
    nodes = {}
    for s, (path, note) in lineages.items():
        for i, k in enumerate(path):
            nodes.setdefault(k, {"gen": i, "terminal": None})
            nodes[k]["gen"] = min(nodes[k]["gen"], i)
        nodes[path[-1]]["terminal"] = note
    for k, meta in nodes.items():
        idn = identity(con, k)
        year = idn.get("decision_year") or ""
        lab = [f"{k}  ({year})", clean(idn.get("applicant"), 26), clean(idn.get("devicename"), 30)]
        attrs = {}
        if k in seeds:
            attrs.update(fillcolor="#123b5e", fontcolor="white", color="#123b5e")
        elif shared.get(k, 0) >= 2:
            strong = shared[k] >= max(3, len(seeds) // 3)
            attrs.update(fillcolor="#f08c00" if strong else "#ffd27a", color="#9c5700", penwidth="1.8" if strong else "1.2",
                         fontcolor="#1d1d1d")
            lab.append(f"in {shared[k]} of {len(seeds)} device chains")
        elif not idn.get("in_starting_set"):
            attrs.update(fillcolor="#eef2f6")
        term = meta["terminal"]
        if term:
            lab.append("■ " + STOP_SHORT.get(term, clean(term, 32)) if term != TRUNC else "▲ TRUNCATED (10 generations)")
            if term == TRUNC:
                attrs.update(color="#c0392b", penwidth="2")
            else:
                attrs.setdefault("style", "rounded,filled,dashed")
        label = "\\n".join(x.replace('"', "'") for x in lab if x)
        a = ", ".join(f'{key}="{val}"' for key, val in attrs.items())
        lines.append(f'"{k}" [label="{label}"{", " + a if a else ""}];')
    seen = set()
    for s, (path, _) in lineages.items():
        for a, b in zip(path, path[1:]):
            if (a, b) not in seen:
                seen.add((a, b))
                style = ' [style=dashed, label=" ref", fontsize=8, fontcolor="#7b8794"]' if (a, b) in fallback else ""
                lines.append(f'"{a}" -> "{b}"{style};')
    lines.append('{ rank=min; ' + " ".join(f'"{s}";' for s in lineages) + " }")
    lines.append("}")
    return "\n".join(lines)


def main():
    cfg = load_config()
    con = connect(cfg.db_path)
    versions = latest_versions(con)
    max_gen = cfg.max_generations
    all_mode = "--all" in sys.argv
    if all_mode:
        seed_rows = con.execute("SELECT knumber, unofficial_segment seg, unofficial_sub_segment sub, applicant, "
                                "devicename, decision_year FROM clearances").fetchall()
    else:
        seed_rows = con.execute("SELECT c.knumber, c.unofficial_segment seg, c.unofficial_sub_segment sub, c.applicant, "
                                "c.devicename, c.decision_year FROM run_targets r JOIN clearances c USING(knumber) "
                                "WHERE r.run_name='pilot' ORDER BY r.seq").fetchall()
    by_seg = collections.defaultdict(list)
    for r in seed_rows:
        by_seg[r["seg"] or "Unassigned"].append(dict(r))

    out_dir = cfg.output_dir / "visuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    have_dot = shutil.which("dot") is not None
    result = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "scope": "all starting-set devices" if all_mode else "pilot sample (142 devices)",
              "max_generations": max_gen, "segments": []}
    cross = collections.defaultdict(set)  # ancestor -> segments whose chains include it
    for seg, rows in sorted(by_seg.items(), key=lambda x: -len(x[1])):
        chains = {}
        for r in rows:
            ch = build_chain(con, r["knumber"], max_gen, versions)
            if len(ch.nodes) > 1:
                chains[r["knumber"]] = (r, ch)
        if not chains:
            result["segments"].append({"segment": seg, "devices": len(rows), "devices_with_chains": 0})
            continue
        # most-shared ancestors across full chains
        counts = collections.Counter()
        gens = collections.defaultdict(list)
        for k, (r, ch) in chains.items():
            for n, node in ch.nodes.items():
                if n != k:
                    counts[n] += 1
                    gens[n].append(node.generation)
                    cross[n].add(seg)
        top = []
        for n, c in counts.most_common(12):
            if c < 2:
                break
            idn = identity(con, n)
            top.append({"knumber": n, "devices": c, "applicant": clean(idn.get("applicant")),
                        "device": clean(idn.get("devicename")), "year": idn.get("decision_year"),
                        "product_code": idn.get("product_code"), "in_starting_set": idn.get("in_starting_set"),
                        "generations": f"{min(gens[n])}-{max(gens[n])}" if min(gens[n]) != max(gens[n]) else str(min(gens[n]))})
        # primary lineages
        lineages = {k: primary_lineage(con, k, versions, max_gen) for k in chains}
        through = collections.Counter()
        for k, (path, _) in lineages.items():
            for n in path[1:]:
                through[n] += 1
        svg = None
        if have_dot:
            dot = dot_for_segment(con, seg, set(lineages), lineages, counts, max_gen)
            (out_dir / f"{slug(seg)}.dot").write_text(dot, encoding="utf-8")
            svg = subprocess.run(["dot", "-Tsvg"], input=dot.encode("utf-8"), capture_output=True, check=True).stdout.decode("utf-8")
            svg = svg[svg.find("<svg"):]
            (out_dir / f"{slug(seg)}.svg").write_text(svg, encoding="utf-8")
        devs = []
        for k, (r, ch) in chains.items():
            path, note = lineages[k]
            years = [identity(con, n).get("decision_year") for n in ch.nodes]
            years = [y for y in years if y]
            devs.append({"knumber": k, "applicant": clean(r["applicant"]), "device": clean(r["devicename"]),
                         "year": r["decision_year"], "sub_segment": r["sub"], "chain_nodes": len(ch.nodes) - 1,
                         "depth": ch.depth, "truncated": ch.truncated, "earliest_year": min(years) if years else None,
                         "primary_lineage_length": len(path) - 1, "lineage_end": note})
        devs.sort(key=lambda d: -(d["year"] or 0))
        result["segments"].append({
            "segment": seg, "devices": len(rows), "devices_with_chains": len(chains),
            "ancestors": len(set().union(*[set(ch.nodes) for _, ch in chains.values()]) - set(chains)),
            "shared_in_lineage_tree": sum(1 for v in through.values() if v >= 2),
            "lineage_nodes_shared_by_2plus_chains": sum(1 for n in set().union(*[set(p[1:]) for p, _ in lineages.values()]) if counts.get(n, 0) >= 2),
            "ancestors_shared_by_2plus": sum(1 for v in counts.values() if v >= 2),
            "top_shared": top, "device_list": devs, "svg": svg})
    multi = [(n, sorted(s)) for n, s in cross.items() if len(s) >= 2]
    multi.sort(key=lambda x: (-len(x[1]), x[0]))
    result["cross_segment"] = []
    for n, segs in multi[:15]:
        idn = identity(con, n)
        result["cross_segment"].append({"knumber": n, "segments": segs, "applicant": clean(idn.get("applicant")),
                                        "device": clean(idn.get("devicename")), "year": idn.get("decision_year"),
                                        "product_code": idn.get("product_code")})
    (out_dir / "segment_visuals.json").write_text(json.dumps({k: v for k, v in result.items()}, indent=1,
                                                             default=str), encoding="utf-8")
    page = cfg.output_dir / "Predicate_Trees_by_Segment.html"
    page.write_text(render_html(result, cfg), encoding="utf-8")
    print("Page:", page)
    print(json.dumps([{k: s[k] for k in s if k not in ("svg", "device_list", "top_shared")} for s in result["segments"]], indent=1))
    print("cross-segment ancestors:", len(multi))
    if not have_dot:
        print("Graphviz 'dot' not found: tree drawings skipped. Install Graphviz from https://graphviz.org/download/")
    return 0



# ----------------------------------------------------------------------------- page
PAGE_CSS = """
:root {
  /* Field-notes layout: summary first, then one section per segment with its lineage tree and shared-ancestor table */
  --ink: #16212c; --muted: #5b6876; --line: #d8dee5; --bg: #f6f8fa; --panel: #ffffff;
  --navy: #123b5e; --amber: #e07f00; --amber-soft: #ffe2ad; --red: #b3261e;
  --font-display: "Archivo", "Helvetica Neue", Arial, sans-serif;
  --font-body: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "IBM Plex Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --ink: #e6ebf0; --muted: #a3b0bd; --line: #2e3a46; --bg: #10161c; --panel: #17202a;
  --navy: #8fbbe3; --amber: #ffad33; --amber-soft: #5a3d0c; --red: #ff8a80; color-scheme: dark; } }
:root[data-theme="dark"] {
  --ink: #e6ebf0; --muted: #a3b0bd; --line: #2e3a46; --bg: #10161c; --panel: #17202a;
  --navy: #8fbbe3; --amber: #ffad33; --amber-soft: #5a3d0c; --red: #ff8a80; color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.55 var(--font-body); }
header, main, footer { max-width: 1180px; margin: 0 auto; padding: 0 20px; }
header { padding-top: 36px; }
h1, h2, h3 { font-family: var(--font-display); text-wrap: balance; line-height: 1.15; }
h1 { font-size: 34px; margin: 0 0 8px; letter-spacing: -0.01em; }
h2 { font-size: 24px; margin: 0 0 4px; }
h3 { font-size: 16px; margin: 22px 0 8px; }
.lede { color: var(--muted); max-width: 70ch; margin: 0 0 18px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 18px 0; }
.tile { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
.tile b { display: block; font: 600 26px/1.1 var(--font-display); font-variant-numeric: tabular-nums; }
.tile span { color: var(--muted); font-size: 13px; }
nav.segs { position: sticky; top: 0; z-index: 5; background: var(--bg); border-bottom: 1px solid var(--line);
  padding: 10px 0; display: flex; flex-wrap: wrap; gap: 6px; }
nav.segs a { color: var(--ink); text-decoration: none; border: 1px solid var(--line); background: var(--panel);
  border-radius: 999px; padding: 4px 11px; font-size: 13px; }
nav.segs a:hover, nav.segs a:focus-visible { border-color: var(--navy); outline: none; }
nav.segs a small { color: var(--muted); font-variant-numeric: tabular-nums; }
section.seg { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 20px; margin: 22px 0; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 4px; }
.chip { font-size: 12.5px; border-radius: 999px; padding: 3px 10px; background: var(--bg); border: 1px solid var(--line); }
.chip.warn { border-color: var(--red); color: var(--red); }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12.5px; color: var(--muted); margin: 10px 0; }
.sw { display: inline-block; width: 14px; height: 11px; border-radius: 3px; vertical-align: -1px; margin-right: 5px;
  border: 1px solid #9aa5b1; }
.tree { overflow-x: auto; background: #ffffff; border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
.tree svg { display: block; height: auto; }
.zoom { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--muted); margin: 6px 0; }
.zoom input { width: 160px; }
table { border-collapse: collapse; width: 100%; font-size: 13.5px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .03em; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.k { font-family: var(--font-mono); font-size: 12.5px; white-space: nowrap; }
.bar { position: relative; min-width: 120px; }
.bar i { position: absolute; left: 0; top: 7px; bottom: 7px; background: var(--amber-soft); border-radius: 3px; }
.bar span { position: relative; padding-left: 6px; font-variant-numeric: tabular-nums; }
.pill { font-size: 11.5px; border-radius: 999px; padding: 1px 8px; border: 1px solid var(--line); white-space: nowrap; }
.pill.trunc { border-color: var(--red); color: var(--red); }
.tablewrap { overflow-x: auto; }
.note { font-size: 13.5px; color: var(--muted); max-width: 80ch; }
.callout { border-left: 4px solid var(--amber); background: var(--panel); padding: 12px 16px; border-radius: 6px;
  border-top: 1px solid var(--line); border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
footer { padding: 10px 20px 40px; }
footer li { margin: 4px 0; }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
"""

PAGE_JS = """
document.querySelectorAll('.zoom input').forEach(function (inp) {
  var svg = document.getElementById(inp.dataset.target).querySelector('svg');
  if (!svg) return;
  var w = parseFloat(svg.getAttribute('width')), h = parseFloat(svg.getAttribute('height'));
  function apply() {
    var z = inp.value / 100;
    svg.style.width = (w * 1.333 * z) + 'px';
    svg.style.height = (h * 1.333 * z) + 'px';
    inp.nextElementSibling.textContent = inp.value + '%';
  }
  inp.addEventListener('input', apply);
  apply();
});
"""


def e(x):
    return html.escape("" if x is None else str(x))


def render_html(result, cfg) -> str:
    segs = [s for s in result["segments"] if s.get("devices_with_chains")]
    empty = [s for s in result["segments"] if not s.get("devices_with_chains")]
    total_dev = sum(s["devices"] for s in result["segments"])
    with_chains = sum(s["devices_with_chains"] for s in result["segments"])
    trunc = sum(1 for s in segs for d in s["device_list"] if d["truncated"])
    pilot = result["scope"].startswith("pilot")
    out = []
    a = out.append
    a('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width, initial-scale=1">')
    a('<title>Predicate Trees by Segment</title>')
    a('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    a('<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;700&family=IBM+Plex+Mono&'
      'family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">')
    a(f"<style>{PAGE_CSS}</style></head><body>")
    a("<header>")
    a("<h1>Predicate trees by orthopedic segment</h1>")
    scope = ("Pilot sample of 142 FDA 510(k) orthopedic clearances, drawn at random across eras. "
             "This view will be rebuilt on all 18,224 clearances after the full extraction." if pilot
             else "All starting-set clearances with an extracted chain.")
    a(f'<p class="lede">How each device\'s cited predicates trace back through earlier clearances, and which ancestors '
      f'many devices in a segment share. {e(scope)} Segments are unofficial (assigned by Claude, not FDA).</p>')
    a('<div class="tiles">')
    for big, small in [(total_dev, "devices in this view"), (with_chains, "cite at least one predicate"),
                       (len(segs), "segments with chains"), (trunc, "chains truncated at 10 generations")]:
        a(f'<div class="tile"><b>{big:,}</b><span>{e(small)}</span></div>')
    a("</div>")
    a('<div class="callout note"><b>How to read a tree.</b> Each pilot device sits at the top (navy). The line below it '
      'follows its <b>primary</b> predicate, then that device\'s primary predicate, back until the record ends. Orange '
      'marks ancestors that appear in the full chains (every predicate, every generation) of two or more devices in the '
      'segment; darker orange means a larger share. The table under each tree ranks those shared ancestors.</div>')
    a("</header>")
    a('<nav class="segs" aria-label="Segments"><div style="max-width:1180px;margin:0 auto;padding:0 20px;display:flex;'
      'flex-wrap:wrap;gap:6px">')
    for s in segs:
        a(f'<a href="#{slug(s["segment"])}">{e(s["segment"])} <small>{s["devices_with_chains"]}</small></a>')
    a('<a href="#across">Across segments</a></div></nav><main>')
    for s in segs:
        sid = slug(s["segment"])
        a(f'<section class="seg" id="{sid}"><h2>{e(s["segment"])}</h2>')
        a('<div class="chips">')
        a(f'<span class="chip">{s["devices_with_chains"]} of {s["devices"]} pilot devices cite a predicate</span>')
        a(f'<span class="chip">{s["ancestors"]:,} distinct ancestors</span>')
        a(f'<span class="chip">{s["ancestors_shared_by_2plus"]:,} shared by 2+ devices</span>')
        tr = sum(1 for d in s["device_list"] if d["truncated"])
        if tr:
            a(f'<span class="chip warn">{tr} truncated at 10 generations</span>')
        if s["devices_with_chains"] < 5:
            a('<span class="chip warn">small sample: read as examples, not a pattern</span>')
        a("</div>")
        if s.get("svg"):
            a('<div class="legend"><span><i class="sw" style="background:#123b5e"></i>pilot device</span>'
              '<span><i class="sw" style="background:#f08c00"></i>in many device chains</span>'
              '<span><i class="sw" style="background:#ffd27a"></i>in 2+ device chains</span>'
              '<span><i class="sw" style="background:#eef2f6"></i>outside the orthopedic starting set</span>'
              '<span><i class="sw" style="background:#fff;border-style:dashed"></i>lineage ends here (reason shown)</span>'
              '<span><i class="sw" style="background:#fff;border-color:#c0392b;border-width:2px"></i>truncated</span>'
              '<span>dashed arrow = no numbered primary; first listed predicate followed</span></div>')
            a(f'<div class="zoom"><label for="z-{sid}">Zoom</label><input id="z-{sid}" type="range" min="30" max="120" '
              f'value="{60 if s["devices_with_chains"] > 8 else 80}" data-target="t-{sid}"><span></span></div>')
            a(f'<figure style="margin:0"><div class="tree" id="t-{sid}" role="img" aria-label="Primary predicate lineage '
              f'tree for {e(s["segment"])} pilot devices">{s["svg"]}</div>'
              f'<figcaption class="note">Primary lineages of {s["devices_with_chains"]} {e(s["segment"])} pilot devices. '
              f'Scroll sideways for wide trees.</figcaption></figure>')
        if s["top_shared"]:
            n = s["devices_with_chains"]
            a(f'<h3>Most-shared ancestors in {e(s["segment"])}</h3><div class="tablewrap"><table><thead><tr>'
              '<th>Number</th><th>Device (FDA record)</th><th>Applicant</th><th class="num">Year</th><th>Code</th>'
              f'<th>In device chains (of {n})</th><th class="num">Generations back</th></tr></thead><tbody>')
            for t in s["top_shared"][:10]:
                pct = 100 * t["devices"] / n
                a(f'<tr><td class="k">{e(t["knumber"])}</td><td>{e(t["device"])}</td><td>{e(t["applicant"])}</td>'
                  f'<td class="num">{e(t["year"])}</td><td class="k">{e(t["product_code"])}</td>'
                  f'<td class="bar"><i style="width:{pct:.0f}%"></i><span>{t["devices"]}</span></td>'
                  f'<td class="num">{e(t["generations"])}</td></tr>')
            a("</tbody></table></div>")
        else:
            a('<p class="note">No ancestor is shared by two or more devices in this segment of the pilot.</p>')
        a(f'<h3>Pilot devices in {e(s["segment"])}</h3><div class="tablewrap"><table><thead><tr><th>Number</th>'
          '<th>Device</th><th>Applicant</th><th class="num">Year</th><th>Sub-segment</th><th class="num">Ancestors</th>'
          '<th class="num">Depth</th><th class="num">Oldest ancestor</th><th>Primary lineage ends</th></tr></thead><tbody>')
        for d in s["device_list"]:
            end = d["lineage_end"] or ""
            endtxt = "truncated at 10 generations" if end == TRUNC else STOP_SHORT.get(end, end)
            pill = ' <span class="pill trunc">truncated</span>' if d["truncated"] else ""
            a(f'<tr><td class="k">{e(d["knumber"])}</td><td>{e(d["device"])}{pill}</td><td>{e(d["applicant"])}</td>'
              f'<td class="num">{e(d["year"])}</td><td>{e(d["sub_segment"])}</td><td class="num">{d["chain_nodes"]:,}</td>'
              f'<td class="num">{d["depth"]}</td><td class="num">{e(d["earliest_year"])}</td><td>{e(endtxt)}</td></tr>')
        a("</tbody></table></div></section>")
    a('<section class="seg" id="across"><h2>Ancestors shared across segments</h2>')
    a('<p class="note">Older clearances that sit in the chains of devices from several segments. Spine systems from '
      'around 2000 show up under Enabling Technology and Extremities because navigation instruments and some '
      'implant systems cite spine predicates.</p>')
    a('<div class="tablewrap"><table><thead><tr><th>Number</th><th>Device (FDA record)</th><th>Applicant</th>'
      '<th class="num">Year</th><th>Code</th><th>Segments whose chains include it</th></tr></thead><tbody>')
    for c in result["cross_segment"]:
        a(f'<tr><td class="k">{e(c["knumber"])}</td><td>{e(c["device"])}</td><td>{e(c["applicant"])}</td>'
          f'<td class="num">{e(c["year"])}</td><td class="k">{e(c["product_code"])}</td><td>{e(", ".join(c["segments"]))}</td></tr>')
    a("</tbody></table></div></section>")
    if empty:
        a('<p class="note">Segments with no predicate chain in the pilot: ' +
          e("; ".join(f'{s["segment"]} ({s["devices"]} devices)' for s in empty)) + ".</p>")
    a("</main><footer><h3>Method and limitations</h3><ul class=\"note\">")
    for li in [
        "Predicates are what each submitter wrote in its 510(k) Summary, read by the OrthoParity predicate parser (version "
        "1.1.0). FDA's internal review is not verified, and substantial equivalence says nothing about clinical "
        "performance, outcomes or price.",
        "Company and device names come from FDA records by number. PMA ancestors are not in the 510(k) records; their "
        "names are shown as printed in the citing Summary.",
        "Lineages end where the record ends: no summary on file (none was found online for any pilot clearance decided before 1996), a 510(k) Statement, a "
        "predicate with no FDA number, a PDF with no predicate found, or the 10-generation limit. An end point is not "
        "the original of its lineage.",
        f"The pilot is a random sample: {with_chains} devices with chains, as few as 1 per segment. Shared-ancestor "
        "counts describe this sample only and will change on the full dataset.",
        "Some edges are still in the review queue (MEDIUM or LOW confidence, or flagged); this page does not filter them.",
        "Segments are unofficial labels assigned by Claude, not FDA. Applicant names are as printed at clearance, "
        "without roll-up to current owners.",
        "Independent research built from public FDA data, provided as is; not regulatory advice.",
    ]:
        a(f"<li>{e(li)}</li>")
    a(f'</ul><p class="note">Generated {e(result["generated_utc"])} UTC.</p></footer>')
    a(f"<script>{PAGE_JS}</script></body></html>")
    return "".join(out)


if __name__ == "__main__":
    sys.exit(main())
