"""Stop rules: exactly one stop reason per node."""
from predicate_chain import PARSER_VERSION
from predicate_chain.chains import build_chain, pending_nodes
from predicate_chain.pipeline import (SR_DEN, SR_NO_PDF_1991_1995, SR_NO_PDF_PRE1991, SR_NOT_FOUND, SR_PMA,
                                      SR_STATEMENT, SR_TRUNCATED, Extractor, stop_reason_for_kind)
from predicate_chain.runlog import RunLog


def _add_clearance(con, k, sos, year=2010):
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year, decision_date) VALUES (?,?,?,?)",
                (k, sos, year, f"{year}-01-01"))


def _extractor(con, cfg):
    log = RunLog(cfg.log_dir, "test", con)
    return Extractor(con, cfg, None, log, offline=True)


def test_kind_stop_reasons():
    assert stop_reason_for_kind("DEN150034") == SR_DEN
    assert stop_reason_for_kind("P970051/S020") == SR_PMA
    assert stop_reason_for_kind("K123456") is None


def test_den_and_pma_stop_without_download(con, cfg):
    ex = _extractor(con, cfg)
    assert ex.process("DEN150034").stop_reason == SR_DEN
    assert ex.process("P970051").stop_reason == SR_PMA


def test_statement_stops(con, cfg):
    _add_clearance(con, "K100001", "Statement")
    ex = _extractor(con, cfg)
    r = ex.process("K100001")
    assert r.status == "stopped" and r.stop_reason == SR_STATEMENT


def test_not_found_anywhere(con, cfg):
    con.execute("INSERT INTO external_lookups (number, source, found) VALUES ('K000000','not found',0)")
    ex = _extractor(con, cfg)
    assert ex.process("K000000").stop_reason == SR_NOT_FOUND


def test_one_status_row_per_node(con, cfg):
    _add_clearance(con, "K100001", "Statement")
    ex = _extractor(con, cfg)
    ex.process("K100001")
    ex.process("K100001")
    n = con.execute("SELECT COUNT(*) FROM node_status WHERE knumber='K100001' AND parser_version=?",
                    (PARSER_VERSION,)).fetchone()[0]
    assert n == 1


def _edge(con, child, pred):
    con.execute("INSERT INTO edges (child_knumber, parser_version, predicate_number, role, list_order) "
                "VALUES (?,?,?,?,1)", (child, PARSER_VERSION, pred, "primary"))


def _status(con, k, status="continues", reason=None):
    con.execute("INSERT INTO node_status (knumber, parser_version, status, stop_reason) VALUES (?,?,?,?)",
                (k, PARSER_VERSION, status, reason))


def test_truncated_at_generation_limit(con):
    # A -> B -> C -> D, limit 2: C sits at generation 2 and still has a predicate, so it is TRUNCATED.
    for c, p in (("K000001", "K000002"), ("K000002", "K000003"), ("K000003", "K000004")):
        _edge(con, c, p)
        _status(con, c)
    chain = build_chain(con, "K000001", 2)
    assert chain.nodes["K000003"].stop_reason == SR_TRUNCATED
    assert "K000004" not in chain.nodes
    assert chain.truncated


def test_dead_end_is_not_truncated(con):
    _edge(con, "K000001", "K000002")
    _status(con, "K000001")
    _status(con, "K000002", "stopped", SR_STATEMENT)
    chain = build_chain(con, "K000001", 10)
    assert chain.nodes["K000002"].stop_reason == SR_STATEMENT
    assert not chain.truncated


def test_pending_nodes_respects_limit(con):
    for c, p in (("K000001", "K000002"), ("K000002", "K000003")):
        _edge(con, c, p)
        _status(con, c)
    assert pending_nodes(con, ["K000001"], 10, PARSER_VERSION) == [("K000003", 2, "K000002")]
    assert pending_nodes(con, ["K000001"], 1, PARSER_VERSION) == []


def test_stop_file_ends_run_cleanly(con, cfg):
    from predicate_chain.runner import run
    _add_clearance(con, "K100001", "Statement")
    con.execute("INSERT INTO run_targets (run_name, knumber, seq) VALUES ('t','K100001',0)")
    con.commit()
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    (cfg.output_dir / "STOP").write_text("")
    res = run(cfg, "t", walk_chains=False, offline=True, echo=lambda s: None)
    assert res["ended"].startswith("stopped by STOP file")
    assert not (cfg.output_dir / "STOP").exists()
    assert (cfg.output_dir / "progress_t.txt").exists()


def test_no_summary_on_file_rules(con, cfg):
    cfg.raw.set("settings", "PRE1991_BLANK_RULE", "stop")
    cfg.raw.set("settings", "EARLY1990S_RULE", "stop")
    _add_clearance(con, "K880001", None, 1988)
    _add_clearance(con, "K930001", "Summary", 1993)
    _add_clearance(con, "K940001", None, 1994)
    _add_clearance(con, "K950002", "Statement", 1995)
    ex = _extractor(con, cfg)
    assert ex.process("K880001").stop_reason == SR_NO_PDF_PRE1991
    assert ex.process("K930001").stop_reason == SR_NO_PDF_1991_1995
    assert ex.process("K940001").stop_reason == SR_NO_PDF_1991_1995
    assert ex.process("K950002").stop_reason == SR_STATEMENT
