"""LOOKUP LAYER: search, ancestor chain, benchmark table, tree diagram and workbook for one device or a brand family.

Reads only the database (and the run logs for the Audit_Log tab). Never downloads or reads a PDF.
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
import shutil
import subprocess
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import PARSER_VERSION, TOOL_VERSION
from .chains import NOT_EXTRACTED, build_chain, latest_versions, review_overrides
from .pipeline import SR_TRUNCATED

K_RE = re.compile(r"^\s*(K|DEN)\s*-?\s*(\d{6})\s*$", re.I)
P_RE = re.compile(r"^\s*P\s*(\d{6})", re.I)
GENERIC = {"system", "systems", "device", "devices", "the", "and", "with", "for", "of", "spinal", "spine", "set", "kit",
           "implant", "implants", "plate", "plates", "screw", "screws", "modification", "modified", "to", "total",
           "instruments", "instrument", "inc", "corp", "llc", "ltd", "co", "company", "corporation", "usa", "medical",
           "surgical", "orthopedic", "orthopaedic", "orthopedics", "orthopaedics", "international", "technologies",
           "standalone", "lateral", "interbody", "cervical", "lumbar", "anterior", "posterior", "fusion", "cage",
           "spacer", "spacers", "titanium", "peek", "new", "line", "extension", "family", "sterile", "s", "a"}
CO_SUFFIX = {"inc", "incorporated", "corp", "corporation", "llc", "ltd", "limited", "co", "company", "gmbh", "ag",
             "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "plc", "lp", "llp", "kg", "oy", "ab", "pty", "the", "usa",
             "us"}

LIMITATIONS = [
    "Predicates are what the submitter wrote in its 510(k) Summary, read by software. The tool does not verify "
    "FDA's internal review.",
    "Substantial equivalence is a regulatory finding. It says nothing about clinical performance, outcomes, or price.",
    "510(k) summaries were not required before 1990 and FDA posts almost none before 1996, so most chains end in the "
    "1990s whatever the generation limit. Statement-only clearances, predicates printed without a number, and "
    "unreadable PDFs also end a branch.",
    "The starting set is orthopedic product codes only (FDA Orthopedic panel and 21 CFR 888). Non-orthopedic "
    "ancestors are covered through the frontier.",
    "Applicant names appear as printed at clearance and are not rolled up to current owners.",
    "Text extraction can misread layouts and scanned pages. Every edge carries a confidence label; the Flags tab and "
    "Reviewer_Checklist exist for human review.",
    "Review rule D: a predicate named without a K-number is ignored; the K-number decides identity even when the "
    "printed name differs; any other K-number in a Summary counts as a predicate, which also counts K-numbers cited "
    "for compatibility or test comparisons. A typo in a submitter's K-number is taken as printed unless a review "
    "corrected it.",
    "Review decisions marked 'Claude review' were made by an AI reviewer from the document text, with the reasoning "
    "recorded. Edges marked 'parser' were not reviewed by anyone.",
    "A device where a chain stops (no summary, no number, generation limit) is where the paper trail ends. It is not "
    "a claim that the device is the original of its lineage.",
    "Independent research tool built from public FDA data, provided as is, not regulatory advice, and the author's "
    "personal work and views.",
]


def clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("�", "")).strip()


def norm_k(q: str) -> str | None:
    m = K_RE.match(q or "")
    return (m.group(1).upper() + m.group(2)) if m else None


def company_root(name: str | None) -> str:
    """Applicant name without legal suffixes, single letters or spaces ("Nu Vasive, Incorporated" and
    "NuVasive, Inc." both give "nuvasive"; "Tornier S.A.S." gives "tornier"). No parent-company roll-up."""
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()  # "Sàrl" -> "Sarl"
    words = [w for w in re.findall(r"[a-z0-9]+", folded.lower()) if w not in CO_SUFFIX and len(w) > 1]
    return "".join(words)


def brand_token(devicename: str | None) -> str | None:
    # Trademark signs and curly apostrophes are dropped and accents folded first, so "E3D™-C" gives the same brand
    # as "E3D-C" and "PIT’Stop®" the same as "PITStop" (the source files lost these characters before the
    # 2026-11-18 text repair). A plain apostrophe still splits words, as it always has ("O'BRIEN" gives "BRIEN").
    s = re.sub("[\u2122\u00ae\u00a9\u2120\u2019\u2018]", "", clean(devicename))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]+", s):
        if w.lower() not in GENERIC and len(w) >= 3:
            return w.upper()
    return None


# ----------------------------------------------------------------------------- search
def search(con, query: str, limit: int = 60) -> list[dict]:
    """K-number (exact), else product name or company (partial, then fuzzy). Starting-set clearances first."""
    q = clean(query)
    if not q:
        return []
    k = norm_k(q)
    cols = ("knumber, devicename, applicant, decision_date, product_code, unofficial_segment, 1 AS in_starting_set")
    if k:
        rows = con.execute(f"SELECT {cols} FROM clearances WHERE knumber=?", (k,)).fetchall()
        if not rows:
            rows = con.execute("SELECT knumber, devicename, applicant, decision_date, product_code, "
                               "NULL AS unofficial_segment, 0 AS in_starting_set FROM fda_master WHERE knumber=?",
                               (k,)).fetchall()
        return [dict(r) for r in rows]
    words = [w for w in re.split(r"\s+", q) if w]
    where = " AND ".join("(devicename || ' ' || applicant) LIKE ?" for _ in words)
    rows = con.execute(f"SELECT {cols} FROM clearances WHERE {where} ORDER BY decision_date DESC LIMIT ?",
                       [f"%{w}%" for w in words] + [limit]).fetchall()
    out = [dict(r) for r in rows]
    if len(out) < 5:  # fuzzy: close words in device names and applicants
        words = q.lower().split()
        vocab = {}
        for kn, dn, ap in con.execute("SELECT knumber, devicename, applicant FROM clearances"):
            for w in set(re.findall(r"[a-z0-9]{3,}", f"{dn} {ap}".lower())):
                vocab.setdefault(w, []).append(kn)
        hits = Counter()
        for w in words:
            for m in difflib.get_close_matches(w, vocab.keys(), n=5, cutoff=0.8):
                for kn in vocab[m]:
                    hits[kn] += 1
        have = {r["knumber"] for r in out}
        best = [kn for kn, c in hits.most_common() if c >= max(1, len(words) // 2) and kn not in have][:limit - len(out)]
        for kn in best:
            r = con.execute(f"SELECT {cols} FROM clearances WHERE knumber=?", (kn,)).fetchone()
            if r:
                out.append({**dict(r), "fuzzy": 1})
    return out


def brand_family(con, knumber: str) -> tuple[list[dict], list[dict], str | None]:
    """All starting-set clearances for this brand by this applicant (suffix variants such as 'Inc.' ignored),
    plus same-brand clearances by other companies (excluded, with the reason)."""
    r = con.execute("SELECT knumber, devicename, applicant FROM clearances WHERE knumber=?", (knumber,)).fetchone()
    if not r:
        return [], [], None
    brand = brand_token(r["devicename"])
    if not brand:
        return [dict(r)], [], None
    me = company_root(r["applicant"])
    fam, excl = [], []
    for x in con.execute("SELECT knumber, devicename, applicant, decision_date, product_code, unofficial_segment "
                         "FROM clearances WHERE upper(devicename) LIKE ? ORDER BY decision_date", (f"%{brand}%",)):
        if not re.search(rf"\b{re.escape(brand)}\b", clean(x["devicename"]).upper()):
            continue
        if company_root(x["applicant"]) == me:
            fam.append(dict(x))
        else:
            excl.append({**dict(x), "reason": f"same brand word '{brand}', different applicant ({clean(x['applicant'])})"})
    return fam, excl, brand


# ----------------------------------------------------------------------------- chain
@dataclass
class Lookup:
    roots: list
    label: str
    chain: object
    nodes: dict = field(default_factory=dict)        # knumber -> info dict
    edges: list = field(default_factory=list)        # edge dicts with review info
    flags: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    created_utc: str = ""


def _ident(con, k: str) -> dict:
    r = con.execute("SELECT applicant, devicename, decision_date, product_code, regulation_number, device_class, "
                    "unofficial_segment FROM clearances WHERE knumber=?", (k,)).fetchone()
    if r:
        d = dict(r)
        d["source"], d["in_starting_set"] = "starting set", True
    else:
        d = {"applicant": None, "devicename": None, "decision_date": None, "product_code": None,
             "regulation_number": None, "device_class": None, "unofficial_segment": None, "in_starting_set": False,
             "source": None}
        r = con.execute("SELECT applicant, devicename, decision_date, product_code, review_panel FROM fda_master "
                        "WHERE knumber=?", (k,)).fetchone()
        if r:
            d.update(dict(r), source="FDA master file")
        else:
            r = con.execute("SELECT applicant, device_name, decision_date, product_code, review_panel FROM "
                            "external_lookups WHERE number=? AND found=1", (k,)).fetchone()
            if r:
                d.update(applicant=r[0], devicename=r[1], decision_date=r[2], product_code=r[3], review_panel=r[4],
                         source="openFDA / FDA web")
            elif k.startswith("P"):
                names = Counter()
                for (nm,) in con.execute("SELECT printed_name FROM edges WHERE predicate_base=? AND printed_name "
                                         "IS NOT NULL", (k.split("/")[0],)):
                    nm = re.sub(r"^[^A-Za-z]+|^(?:the|x|used\.?)\s+", "", clean(nm), flags=re.I).strip()
                    if len(nm) >= 8 and sum(ch.isalpha() for ch in nm) >= 6 and not re.search(r"\d+/\d+/\d+", nm):
                        names[nm] += 1
                best = names.most_common(1)[0][0] if names else None
                d.update(applicant="PMA (not in 510(k) records)", devicename=(best + " (as printed)") if best else None,
                         source="PMA number")
            else:
                d.update(applicant="No Company Name Found", source="not found in any FDA source")
    pc = d.get("product_code")
    if pc:
        p = con.execute("SELECT review_panel, regulation_number, device_class FROM product_codes WHERE product_code=?",
                        (pc,)).fetchone()
        if p:
            d.setdefault("review_panel", None)
            d["review_panel"] = d.get("review_panel") or p[0]
            d["regulation_number"] = d.get("regulation_number") or p[1]
            d["device_class"] = d.get("device_class") or p[2]
    d.setdefault("review_panel", None)
    d["devicename"], d["applicant"] = clean(d.get("devicename")), clean(d.get("applicant"))
    return d


def _review_sources(con) -> dict:
    out = {}
    try:
        for k, n, dec, corr, src, why in con.execute(
                "SELECT knumber, predicate_number, decision, corrected_number, decision_source, reasoning FROM "
                "review_decisions WHERE predicate_number IS NOT NULL ORDER BY decided_at_utc, decision_id"):
            out[(k, n)] = {"decision": dec, "corrected": corr, "source": src, "reasoning": why}
    except Exception:
        pass
    return out


CONF_RANK = {"HIGH": 4, "MEDIUM": 3, "LOW": 1, "NO NUMBER": 0, None: 0}


def run_lookup(con, roots, max_generations: int, label: str | None = None, excluded=None) -> Lookup:
    roots = [r.upper() for r in ([roots] if isinstance(roots, str) else roots)]
    ch = build_chain(con, roots, max_generations)
    reviews = _review_sources(con)
    res = Lookup(roots, label or roots[0], ch, excluded=excluded or [],
                 created_utc=dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # every edge the walk crossed, plus edges that point at dropped numbers (kept for the record)
    versions = latest_versions(con)
    overrides = review_overrides(con)
    seen_children = set()
    for e in ch.edges:
        seen_children.add(e["child_knumber"])
    for k in seen_children:
        v = versions.get(k)
        for r in con.execute("SELECT * FROM edges WHERE child_knumber=? AND parser_version=? ORDER BY list_order",
                             (k, v)):
            e = dict(r)
            printed = e["predicate_number"]
            rv = reviews.get((k, printed)) if printed else None
            ov = overrides.get((k, printed)) if printed else None
            e["number_as_printed"] = printed
            e["number_used"] = (ov[1] if ov and ov[0] == "replace" else (None if ov and ov[0] == "drop" else printed))
            e["review_decision"] = rv["decision"] if rv else None
            e["review_source"] = rv["source"] if rv else "parser"
            e["review_reasoning"] = rv["reasoning"] if rv else None
            e["generation"] = ch.nodes[k].generation + 1 if k in ch.nodes else None
            e["printed_name"], e["evidence"] = clean(e.get("printed_name")), clean(e.get("evidence"))
            res.edges.append(e)
    for k, n in ch.nodes.items():
        info = _ident(con, k)
        doc = con.execute("SELECT url, url_source, sha256, retrieved_at_utc, file_source, text_method, page_count, "
                          "parse_status, parse_notes, fetch_outcome FROM documents WHERE knumber=? AND parser_version=?",
                          (k, n.parser_version)).fetchone() if n.parser_version else None
        info.update({
            "knumber": k, "generation": n.generation, "status": n.status, "parser_version": n.parser_version,
            "stop_reason": n.stop_reason if n.stop_reason else (None if n.status == "continues" else n.stop_reason),
            "doc": dict(doc) if doc else {},
            "roles": set(), "best_conf": None, "review_source": None,
        })
        res.nodes[k] = info
    for e in res.edges:
        p = e["number_used"]
        if p and p in res.nodes and e["generation"] == res.nodes[p]["generation"]:
            nd = res.nodes[p]
            nd["roles"].add(e["role"] or "predicate")
            if CONF_RANK.get(e["confidence"], 0) > CONF_RANK.get(nd["best_conf"], 0) or nd["best_conf"] is None:
                nd["best_conf"] = e["confidence"]
            if e["review_source"] != "parser":
                nd["review_source"] = e["review_source"]
            elif not nd["review_source"]:
                nd["review_source"] = "parser"
    for k in roots:
        if k in res.nodes:
            res.nodes[k]["roles"] = {"subject"}
    ks = list(res.nodes)
    for i in range(0, len(ks), 500):
        part = ks[i:i + 500]
        for r in con.execute(
                "SELECT f.knumber, f.parser_version, f.flag_type, f.number, f.detail, f.page, f.evidence FROM flags f "
                f"WHERE f.knumber IN ({','.join('?' * len(part))})", part):
            if r["parser_version"] == res.nodes[r["knumber"]]["parser_version"]:
                f = dict(r)
                rv = reviews.get((f["knumber"], f["number"]))
                f["review_decision"] = rv["decision"] if rv else None
                f["review_source"] = rv["source"] if rv else None
                f["evidence"] = clean(f["evidence"])
                res.flags.append(f)
    return res


def role_label(roles: set) -> str:
    if "subject" in roles:
        return "subject (vendor device)"
    r = sorted(x for x in roles if x)
    if r == ["primary"]:
        return "primary predicate"
    if r == ["reference"]:
        return "reference predicate"
    return " + ".join(r) if r else "predicate"


def benchmark_rows(res: Lookup) -> list[dict]:
    rows = []
    for k, n in sorted(res.nodes.items(), key=lambda x: (x[1]["generation"], x[0])):
        rows.append({
            "Generation": n["generation"], "Role": role_label(n["roles"]), "K-number": k,
            "Device name": n["devicename"], "Applicant (as printed)": n["applicant"],
            "Decision date": n["decision_date"], "Product code": n["product_code"],
            "Regulation number": n["regulation_number"], "Device class": n["device_class"],
            "Review panel": n["review_panel"],
            "Unofficial segment": n["unofficial_segment"] or ("outside orthopedic set" if not n["in_starting_set"] else None),
            "Confidence": "n/a (subject)" if "subject" in n["roles"] else n["best_conf"],
            "Review source": "n/a (subject)" if "subject" in n["roles"] else n["review_source"],
            "Where the chain stops": stop_text(n),
        })
    return rows


def stop_text(n: dict) -> str | None:
    if n["stop_reason"]:
        return n["stop_reason"]
    if n["status"] is None:
        return NOT_EXTRACTED
    return None


def earliest_year(res: Lookup):
    ys = [int(str(n["decision_date"])[:4]) for n in res.nodes.values() if n["decision_date"]
          and str(n["decision_date"])[:4].isdigit()]
    return min(ys) if ys else None


# ----------------------------------------------------------------------------- tree
ROLE_FILL = {"subject": "#123b5e", "primary": "#e07f00", "reference": "#a7c5df", "both": "#f6b042"}


def _role_key(roles: set) -> str:
    if "subject" in roles:
        return "subject"
    if "primary" in roles and len(roles - {"primary"}) == 0:
        return "primary"
    if "primary" in roles:
        return "both"
    return "reference"


def tree_scope(res: Lookup, scope: str = "primary") -> tuple[set, set]:
    """Nodes and (child, predicate) pairs to draw. 'full' = every predicate; 'primary' = primary predicates only,
    followed from the subject device(s) generation by generation."""
    pairs = {(e["child_knumber"], e["number_used"]) for e in res.edges
             if e["number_used"] in res.nodes and e["child_knumber"] in res.nodes
             and (scope == "full" or e["role"] == "primary")}
    if scope == "full":
        return set(res.nodes), pairs
    keep, frontier = set(res.roots), list(res.roots)
    nxt = defaultdict(list)
    for c, p in pairs:
        nxt[c].append(p)
    while frontier:
        new = []
        for c in frontier:
            for p in nxt.get(c, ()):
                if p not in keep:
                    keep.add(p)
                    new.append(p)
        frontier = new
    return keep & set(res.nodes), {(c, p) for c, p in pairs if c in keep and p in keep}


def tree_dot(res: Lookup, wrap: int = 30, scope: str = "full") -> str:
    def w(s, n):
        s = clean(s)
        return s if len(s) <= n else s[:n - 1] + "…"
    L = ['digraph chain {', 'graph [rankdir=TB, bgcolor="white", nodesep=0.25, ranksep=0.45, fontname="Helvetica"];',
         'node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=9, margin="0.08,0.04", '
         'color="#5b6876", fillcolor="white"];', 'edge [color="#5b6876", arrowsize=0.6, fontname="Helvetica", fontsize=7];']
    show, pairs = tree_scope(res, scope)
    for k, n in res.nodes.items():
        if k not in show:
            continue
        key = _role_key(n["roles"])
        if scope == "primary" and key != "subject":
            key = "primary"
        year = str(n["decision_date"] or "")[:4] or "?"
        lab = [f"{k} ({year})", w(n["applicant"], wrap), w(n["devicename"], wrap)]
        st = stop_text(n)
        attrs = {"fillcolor": ROLE_FILL[key]}
        if key == "subject":
            attrs["fontcolor"] = "white"
        if st == SR_TRUNCATED:
            lab.append("TRUNCATED: generation limit")
            attrs.update(color="#b3261e", penwidth="2.4")
        elif st == NOT_EXTRACTED:
            lab.append("not extracted")
            attrs.update(style='"rounded,filled,dashed"', fillcolor="#eeeeee")
        elif st:
            lab.append("STOP: " + w(st, 34))
            attrs.update(style='"rounded,filled,dashed"', penwidth="1.8", color="#16212c")
        label = "\\n".join(x.replace('"', "'") for x in lab if x)
        a = ", ".join(f'{kk}={vv}' if vv.startswith('"') else f'{kk}="{vv}"' for kk, vv in attrs.items())
        L.append(f'"{k}" [label="{label}", {a}];')
    drawn = set()
    for e in res.edges:
        p, c = e["number_used"], e["child_knumber"]
        if not p or (c, p) not in pairs or (c, p) in drawn:
            continue
        drawn.add((c, p))
        style = []
        if e["role"] == "reference":
            style.append('style=dashed')
        if e["confidence"] == "LOW" and e["review_source"] == "parser":
            style.append('color="#b3261e"')
            style.append('label=" LOW"')
        if e["review_decision"] == "corrected":
            style.append(f'label=" corrected from {e["number_as_printed"]}"')
        L.append(f'"{c}" -> "{p}"' + (f' [{", ".join(style)}]' if style else "") + ";")
    L.append("}")
    return "\n".join(L)


def render_tree(res: Lookup, base: Path, scope: str = "full") -> tuple[Path, Path, str]:
    """Writes base.png and base.svg. Graphviz if installed, else networkx plus matplotlib."""
    base.parent.mkdir(parents=True, exist_ok=True)
    png, svg = Path(str(base) + ".png"), Path(str(base) + ".svg")
    dot = shutil.which("dot")
    if dot:
        src = tree_dot(res, scope=scope).encode("utf-8")
        subprocess.run([dot, "-Tsvg", "-o", str(svg)], input=src, check=True)
        subprocess.run([dot, "-Tpng", "-Gdpi=110", "-o", str(png)], input=src, check=True)
        return png, svg, "Graphviz"
    _render_matplotlib(res, png, svg, scope)
    return png, svg, "networkx + matplotlib"


def _render_matplotlib(res: Lookup, png: Path, svg: Path, scope: str = "full") -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import networkx as nx
    from matplotlib.patches import FancyBboxPatch
    show, pairs = tree_scope(res, scope)
    g = nx.DiGraph()
    for k in show:
        g.add_node(k, layer=res.nodes[k]["generation"])
    refs = {(e["child_knumber"], e["number_used"]) for e in res.edges if e["role"] == "reference"}
    for c, p in pairs:
        g.add_edge(c, p, ref=(c, p) in refs)
    by_gen = defaultdict(list)
    for k in show:
        by_gen[res.nodes[k]["generation"]].append(k)
    width = max(len(v) for v in by_gen.values())
    pos = {}
    for gen, ks in by_gen.items():
        ks.sort()
        for i, k in enumerate(ks):
            pos[k] = ((i - (len(ks) - 1) / 2) * 3.2, -gen * 1.6)
    fig_w, fig_h = max(8, width * 2.4), max(4, (max(by_gen) + 1) * 1.3)
    fig, ax = plt.subplots(figsize=(min(fig_w, 180), min(fig_h, 120)))
    for c, p, d in g.edges(data=True):
        (x1, y1), (x2, y2) = pos[c], pos[p]
        ax.annotate("", xy=(x2, y2 + 0.35), xytext=(x1, y1 - 0.35),
                    arrowprops=dict(arrowstyle="->", color="#5b6876", lw=0.8, ls="--" if d.get("ref") else "-"))
    for k, (x, y) in pos.items():
        n = res.nodes[k]
        key = _role_key(n["roles"])
        if scope == "primary" and key != "subject":
            key = "primary"
        st = stop_text(n)
        ec = "#b3261e" if st == SR_TRUNCATED else "#16212c"
        ax.add_patch(FancyBboxPatch((x - 1.45, y - 0.35), 2.9, 0.7, boxstyle="round,pad=0.02",
                                    fc=ROLE_FILL[key], ec=ec, lw=2 if st else 0.8, ls="--" if st and st != SR_TRUNCATED else "-"))
        txt = f"{k} ({str(n['decision_date'] or '')[:4] or '?'})\n{clean(n['applicant'])[:26]}\n{clean(n['devicename'])[:28]}"
        if st:
            txt += "\n" + ("TRUNCATED" if st == SR_TRUNCATED else "STOP: " + st[:28])
        ax.text(x, y, txt, ha="center", va="center", fontsize=5.5, color="white" if key == "subject" else "#16212c")
    ax.set_xlim(min(p[0] for p in pos.values()) - 2, max(p[0] for p in pos.values()) + 2)
    ax.set_ylim(min(p[1] for p in pos.values()) - 1, 1)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    fig.savefig(svg)
    plt.close(fig)


# ----------------------------------------------------------------------------- audit log
def audit_lines(cfg, knumbers: set, per_number: int = 40) -> list[dict]:
    out, count = [], Counter()
    pat = re.compile(r'"knumber":\s*"([^"]+)"')
    for f in sorted(cfg.log_dir.glob("run_log_*.jsonl")):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = pat.search(line)
                if not m or m.group(1) not in knumbers or count[m.group(1)] >= per_number:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                count[m.group(1)] += 1
                rec["log_file"] = f.name
                out.append(rec)
    return out


def safe_name(s: str, n: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", clean(s)).strip("_")
    return s[:n].rstrip("_") or "device"
