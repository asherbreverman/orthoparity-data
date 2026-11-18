"""Lookup layer: search, brand family, review overrides, benchmark, tree and workbook. Synthetic data only."""
from openpyxl import load_workbook

from predicate_chain import PARSER_VERSION
from predicate_chain.chains import build_chain, pending_nodes
from predicate_chain.lookup_core import (benchmark_rows, brand_family, render_tree, run_lookup, search, tree_dot,
                                         tree_scope)
from predicate_chain.lookup_workbook import write_workbook


def _clear(con, k, name, applicant, date="2020-01-01"):
    con.execute("INSERT INTO clearances (knumber, devicename, applicant, decision_date, decision_year, product_code, "
                "unofficial_segment) VALUES (?,?,?,?,?,?,?)", (k, name, applicant, date, int(date[:4]), "MAX", "Spine"))


def _edge(con, child, pred, role="primary", order=1, conf="HIGH"):
    con.execute("INSERT INTO edges (child_knumber, parser_version, predicate_number, predicate_base, predicate_kind, "
                "role, list_order, confidence, evidence) VALUES (?,?,?,?,?,?,?,?,?)",
                (child, PARSER_VERSION, pred, pred, "K", role, order, conf, f"cites {pred}"))


def _status(con, k, status="continues", reason=None):
    con.execute("INSERT INTO node_status (knumber, parser_version, status, stop_reason) VALUES (?,?,?,?)",
                (k, PARSER_VERSION, status, reason))


def _setup(con):
    _clear(con, "K200001", "ALPHA STANDALONE CAGE", "Alpha Spine, Inc.", "2020-05-01")
    _clear(con, "K210002", "ALPHA LATERAL CAGE", "Alpha Spine LLC", "2021-05-01")
    _clear(con, "K190003", "ALPHA PLATE", "Other Co.", "2019-05-01")
    _clear(con, "K100004", "BETA CAGE", "Beta Inc.", "2010-05-01")
    _edge(con, "K200001", "K100004")
    _edge(con, "K200001", "K999999", role="reference", order=2, conf="LOW")
    _edge(con, "K210002", "K100005", order=1, conf="LOW")
    for k in ("K200001", "K210002"):
        _status(con, k)
    _status(con, "K100004", "stopped", "Summary parsed, no predicate found")
    con.commit()


def test_search_and_brand_family(con):
    _setup(con)
    assert [h["knumber"] for h in search(con, "k200001")] == ["K200001"]
    assert {h["knumber"] for h in search(con, "alpha cage") if not h.get("fuzzy")} == {"K200001", "K210002"}
    fam, excl, brand = brand_family(con, "K200001")
    assert brand == "ALPHA"
    assert {f["knumber"] for f in fam} == {"K200001", "K210002"}       # "Inc." vs "LLC" ignored
    assert [x["knumber"] for x in excl] == ["K190003"] and "different applicant" in excl[0]["reason"]


def test_review_overrides_drop_and_correct(con):
    _setup(con)
    con.execute("INSERT INTO review_decisions (knumber, predicate_number, decision, decision_source, decided_at_utc) "
                "VALUES ('K200001','K999999','own number','Claude review','2026-01-01')")
    con.execute("INSERT INTO review_decisions (knumber, predicate_number, decision, corrected_number, decision_source, "
                "decided_at_utc) VALUES ('K210002','K100005','corrected','K100004','Claude review','2026-01-01')")
    con.commit()
    ch = build_chain(con, ["K200001", "K210002"], 10)
    assert "K999999" not in ch.nodes and "K100005" not in ch.nodes
    assert ch.nodes["K100004"].generation == 1
    assert pending_nodes(con, ["K200001", "K210002"], 10, PARSER_VERSION) == []
    res = run_lookup(con, ["K200001", "K210002"], 10, label="Alpha family")
    e = [x for x in res.edges if x["child_knumber"] == "K210002"][0]
    assert e["number_used"] == "K100004" and e["review_source"] == "Claude review"
    rows = {r["K-number"]: r for r in benchmark_rows(res)}
    assert rows["K200001"]["Role"].startswith("subject")
    assert rows["K100004"]["Where the chain stops"] == "Summary parsed, no predicate found"


def test_tree_and_workbook(con, cfg, tmp_path):
    _setup(con)
    res = run_lookup(con, "K200001", 10, label="Alpha Standalone")
    dot = tree_dot(res, scope="full")
    assert '"K200001" -> "K100004"' in dot and "STOP:" in dot and "K999999" in dot
    shown, _ = tree_scope(res, "primary")
    assert shown == {"K200001", "K100004"}
    png, svg, how = render_tree(res, tmp_path / "tree", scope="primary")
    assert png.exists() and svg.exists() and png.stat().st_size > 0
    xlsx = write_workbook(res, tmp_path / "wb.xlsx", cfg)
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Summary", "Benchmark", "Edges", "Nodes", "Companies", "Flags", "Excluded name matches",
                             "Audit_Log", "Reviewer_Checklist", "Methodology_and_Limitations"]
    assert wb["Summary"]["B9"].value.startswith("=COUNTA(Benchmark!")
    hdr = [c.value for c in wb["Reviewer_Checklist"][2]]
    assert hdr[-4:] == ["Reviewer agrees (Y/N)", "Reviewer notes", "Reviewer name", "Date"]
