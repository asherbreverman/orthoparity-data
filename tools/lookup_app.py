"""OrthoParity lookup app (Streamlit). Start it with: python orthoparity.py lookup-app

Type a K-number, product name or company; pick a clearance (or its whole brand family); see the ancestor
chain instantly from the database. Never downloads or reads a PDF.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, so the package imports work under Streamlit

import datetime as dt
from collections import Counter

import pandas as pd
import streamlit as st

from predicate_chain import PARSER_VERSION, TOOL_VERSION
from predicate_chain.config import load_config
from predicate_chain.db import connect
from predicate_chain.lookup_core import (LIMITATIONS, benchmark_rows, brand_family, clean, earliest_year, render_tree,
                                         run_lookup, safe_name, search, stop_text, tree_dot, tree_scope)
from predicate_chain.lookup_workbook import write_workbook
from predicate_chain.runlog import RunLog

st.set_page_config(page_title="OrthoParity lookup", page_icon=None, layout="wide")
cfg = load_config()


def db():
    return connect(cfg.db_path)


with st.sidebar:
    st.markdown("### OrthoParity")
    st.caption(f"Parser {PARSER_VERSION} · tool {TOOL_VERSION} · generation limit {cfg.max_generations}")
    st.markdown("Ancestor chains for FDA 510(k) clearances in orthopedics, built from public FDA data. "
                "Ancestors only: what a device cites, what those devices cite, and so on.")
    with st.expander("Limitations (read before using)"):
        for t in LIMITATIONS:
            st.markdown(f"- {t}")

st.title("Predicate chain lookup")
q = st.text_input("K-number, product name, or company", placeholder="K241487, Interwedge, Globus ...")
if not q:
    st.info("Type a K-number for an exact match, or part of a product or company name.")
    st.stop()

con = db()
hits = search(con, q)
if not hits:
    st.warning(f"No orthopedic clearance matches '{q}'. Check the spelling or try fewer words.")
    st.stop()

fuzzy = any(h.get("fuzzy") for h in hits)
st.caption(f"{len(hits)} match(es){' (including close spellings)' if fuzzy else ''}.")
labels = [f"{h['knumber']} · {clean(h['devicename'])} · {clean(h['applicant'])} · {str(h['decision_date'])[:10]}"
          + (" · close spelling" if h.get("fuzzy") else "") for h in hits]
pick = st.selectbox("Pick a clearance", range(len(hits)), format_func=lambda i: labels[i])
k = hits[pick]["knumber"]

fam, excluded, brand = brand_family(con, k)
roots, label = [k], clean(hits[pick]["devicename"]) or k
if len(fam) > 1:
    choice = st.radio("Scope", [f"This clearance only ({k})",
                                f"All {len(fam)} clearances for the {brand} brand by this applicant"], horizontal=True)
    if choice.startswith("All"):
        roots = [f["knumber"] for f in fam]
        label = f"{brand} family ({clean(hits[pick]['applicant'])})"
        with st.expander(f"The {len(fam)} clearances in this brand family"):
            st.dataframe(pd.DataFrame([{"K-number": f["knumber"], "Device name": clean(f["devicename"]),
                                        "Applicant": clean(f["applicant"]), "Decision date": f["decision_date"]}
                                       for f in fam]), hide_index=True, width="stretch")
if excluded:
    with st.expander(f"Excluded name matches: {len(excluded)} same-brand clearance(s) by other companies"):
        st.dataframe(pd.DataFrame([{"K-number": x["knumber"], "Device name": clean(x["devicename"]),
                                    "Applicant": clean(x["applicant"]), "Why excluded": x["reason"]}
                                   for x in excluded]), hide_index=True, width="stretch")

res = run_lookup(con, roots, cfg.max_generations, label=label, excluded=excluded if len(roots) > 1 else [])
bench = benchmark_rows(res)
stops = Counter(stop_text(n) for n in res.nodes.values() if stop_text(n))
low = sum(1 for e in res.edges if e["confidence"] == "LOW" and e["review_source"] == "parser")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Devices in chain", f"{len(res.nodes):,}")
c2.metric("Deepest generation", res.chain.depth)
c3.metric("Earliest year reached", earliest_year(res) or "n/a")
c4.metric("Branches stopped", f"{sum(stops.values()):,}")
c5.metric("Unreviewed LOW edges", low)
if res.chain.truncated:
    st.warning(f"Some branches reached the {cfg.max_generations}-generation limit (marked TRUNCATED).")

tab_b, tab_t, tab_f, tab_s, tab_e = st.tabs(["Benchmark", "Tree", "Flags", "Where branches stop", "Edges"])
with tab_b:
    st.caption("One row per device, at its nearest generation. Applicant as printed at clearance (no parent "
               "roll-up). Confidence is the best label among the edges that reach the device.")
    st.dataframe(pd.DataFrame(bench), hide_index=True, width="stretch", height=520)
with tab_t:
    scope = st.radio("Show", ["Primary predicates only", "Full chain (every predicate)"], horizontal=True)
    sc = "primary" if scope.startswith("Primary") else "full"
    shown, _ = tree_scope(res, sc)
    st.caption(f"{len(shown)} devices shown. Vendor device on top, arrows point to the predicate it cites. "
               "Navy: subject. Orange: primary predicate. Light blue: reference predicate (dashed arrow). Dashed box: "
               "the chain stops there (reason in the box). Red border: generation limit (TRUNCATED). Red arrow: "
               "LOW confidence, not reviewed.")
    if len(shown) > 300:
        st.info("This diagram is large. Use the SVG download below and zoom in your browser.")
    st.graphviz_chart(tree_dot(res, scope=sc), width="content")
with tab_f:
    if res.flags:
        st.dataframe(pd.DataFrame([{"K-number": f["knumber"], "Flag": f["flag_type"], "Number": f["number"],
                                    "Detail": f["detail"], "Page": f["page"], "Review decision": f["review_decision"],
                                    "Review source": f["review_source"]} for f in res.flags]),
                     hide_index=True, width="stretch")
    else:
        st.write("No flags on any document in this chain.")
with tab_s:
    st.caption("Where the paper trail ends. A stop says nothing about whether the device is the original of its "
               "lineage.")
    st.dataframe(pd.DataFrame([{"Where the chain stops": r, "Devices": n} for r, n in stops.most_common()]),
                 hide_index=True)
with tab_e:
    st.dataframe(pd.DataFrame([{"Generation": e["generation"], "Child": e["child_knumber"],
                                "Number as printed": e["number_as_printed"], "Number used": e["number_used"],
                                "Role": e["role"], "Confidence": e["confidence"], "Review": e["review_decision"],
                                "Review source": e["review_source"], "Page": e["page"], "Evidence": e["evidence"][:200]}
                               for e in res.edges]), hide_index=True, width="stretch", height=520)

st.subheader("Downloads")
key = "|".join(roots)
if st.button("Prepare workbook and tree files"):
    out = cfg.output_dir / "lookups"
    stem = f"Predicate_Chain_{safe_name(label)}_{dt.date.today().isoformat()}"
    with st.spinner("Writing the workbook and drawing the trees..."):
        xlsx = write_workbook(res, out / f"{stem}.xlsx", cfg)
        files = [xlsx]
        for sc in ("primary", "full"):
            png, svg, how = render_tree(res, out / f"{stem}_tree_{sc}", scope=sc)
            files += [png, svg]
        RunLog(cfg.log_dir, "lookup", con).log("lookup", roots[0], result="ok",
                                               reason=f"{len(roots)} subject(s), {len(res.nodes)} devices; {label}")
    st.session_state["files"] = (key, [str(f) for f in files], how)
if st.session_state.get("files", (None,))[0] == key:
    _, files, how = st.session_state["files"]
    st.caption(f"Saved in outputs\\lookups. Trees drawn with {how}.")
    mime = {".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".png": "image/png",
            ".svg": "image/svg+xml"}
    cols = st.columns(len(files))
    for c, f in zip(cols, files):
        name = f.replace("\\", "/").split("/")[-1]
        with open(f, "rb") as fh:
            lab = "Workbook (.xlsx)"
            if "_tree_" in name:
                sc_, ext = name.rsplit("_tree_", 1)[1].split(".")
                lab = f"Tree, {'primary predicates' if sc_ == 'primary' else 'full chain'} ({ext.upper()})"
            c.download_button(lab, fh.read(), file_name=name,
                              mime=mime[name[name.rfind("."):]], key=f"dl-{name}")
st.caption("Independent research tool built from public FDA data, provided as is, not regulatory advice. "
           "MIT License, Copyright (c) 2026 Asher Breverman.")
