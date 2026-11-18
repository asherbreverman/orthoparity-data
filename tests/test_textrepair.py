"""Text repair: synthetic fixtures only."""
import sqlite3

import duckdb

from predicate_chain.textrepair import BAD, pattern_match, repair_duckdb, repair_sqlite, supabase_patch


def test_pattern_match_rules():
    assert pattern_match(f"ANTHEM{BAD} Plate", "ANTHEM™ Plate")
    assert not pattern_match(f"ANTHEM{BAD} Plate", "ANTHEM Plate")          # length differs
    assert not pattern_match(f"ANTHEM{BAD} Plate", "ANTHEM® Screw")         # other characters differ
    assert not pattern_match("No damage", "No damage")                       # nothing to repair
    assert not pattern_match(f"A{BAD}", None)                                # no FDA value
    assert not pattern_match(f"A{BAD}", f"A{BAD}")                           # FDA value broken too


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE fda_master (knumber TEXT, applicant TEXT, contact TEXT, street1 TEXT, street2 TEXT, city TEXT, devicename TEXT)")
    con.execute("CREATE TABLE clearances (knumber TEXT, applicant TEXT, contact TEXT, street1 TEXT, street2 TEXT, city TEXT, devicename TEXT)")
    con.execute("CREATE TABLE edges (child_knumber TEXT, predicate_number TEXT, fda_applicant TEXT, fda_device_name TEXT)")
    con.executemany("INSERT INTO fda_master VALUES (?,?,?,?,?,?,?)", [
        ("K000001", "Acme Ortopédicos SA", "", "", "", "Mühlheim", "WIDGET® Plate"),
        ("K000002", "Beta Spine", "", "", "", "Town", "ROD™ System"),
        ("K000003", "Gamma", "", "", "", "Town", "Totally Different Name"),
    ])
    con.executemany("INSERT INTO clearances VALUES (?,?,?,?,?,?,?)", [
        ("K000001", f"Acme Ortop{BAD}dicos SA", "", "", "", f"M{BAD}hlheim", f"WIDGET{BAD} Plate"),
        ("K000002", "Beta Spine", "", "", "", "Town", f"ROD{BAD} System"),
        ("K000003", "Gamma", "", "", "", "Town", f"Name{BAD}"),
        ("K000004", "Delta", "", "", "", "Town", f"Orphan{BAD}"),
    ])
    con.execute("INSERT INTO edges VALUES ('K000009', 'K000002', 'Beta Spine', ?)", (f"ROD{BAD} System",))
    return con


def test_repair_sqlite_fixes_only_exact_matches():
    con = _db()
    res = repair_sqlite(con)
    assert con.execute("SELECT devicename FROM clearances WHERE knumber='K000001'").fetchone()[0] == "WIDGET® Plate"
    assert con.execute("SELECT city FROM clearances WHERE knumber='K000001'").fetchone()[0] == "Mühlheim"
    assert con.execute("SELECT fda_device_name FROM edges").fetchone()[0] == "ROD™ System"
    assert con.execute("SELECT devicename FROM clearances WHERE knumber='K000003'").fetchone()[0] == f"Name{BAD}"
    assert res.fixed[("clearances", "devicename")] == 2
    assert res.left[("clearances", "devicename")] == 2
    assert res.applicant_map == {f"Acme Ortop{BAD}dicos SA": "Acme Ortopédicos SA"}
    assert any(e[2] == "K000004" and e[4] is None for e in res.left_examples)
    assert {k for k, _, _ in res.portfolio_rows} == {"K000001", "K000002"}


def test_dry_run_changes_nothing():
    con = _db()
    res = repair_sqlite(con, write=False)
    assert res.fixed[("clearances", "devicename")] == 2
    assert con.execute("SELECT devicename FROM clearances WHERE knumber='K000001'").fetchone()[0] == f"WIDGET{BAD} Plate"


def test_repair_duckdb_and_patch():
    dc = duckdb.connect()
    dc.execute("CREATE TABLE vendors (vendor_id VARCHAR, display_name VARCHAR)")
    dc.execute("CREATE TABLE vendor_entities (source VARCHAR, entity_key VARCHAR, raw_name VARCHAR, vendor_id VARCHAR)")
    bad = f"Acme Ortop{BAD}dicos SA"
    dc.execute("INSERT INTO vendors VALUES ('n_acme', ?)", [bad])
    dc.execute("INSERT INTO vendor_entities VALUES ('applicant', ?, ?, 'n_acme')", [bad, bad])
    out = repair_duckdb(dc, {bad: "Acme Ortopédicos SA"})
    assert dc.execute("SELECT display_name FROM vendors").fetchone()[0] == "Acme Ortopédicos SA"
    assert dc.execute("SELECT entity_key, raw_name FROM vendor_entities").fetchone() == ("Acme Ortopédicos SA",) * 2
    sql = supabase_patch([("K000001", "WIDGET® Plate", "O'Brien Ortho")], out["vendor_rows"], out["name_rows"])
    assert "update pc_portfolio_510k" in sql and "O''Brien" in sql and "update pc_vendors" in sql
    assert "update pc_vendor_names" in sql
