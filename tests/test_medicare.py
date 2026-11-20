"""load_medicare.py on synthetic Medicare files: made-up hospitals, DRGs and amounts. No real data."""
import csv
import re
from pathlib import Path

import pytest

from pipeline import load_medicare

ROOT = Path(__file__).resolve().parent.parent
IP_HEAD = ["Rndrng_Prvdr_CCN", "Rndrng_Prvdr_Org_Name", "DRG_Cd", "DRG_Desc", "Tot_Dschrgs", "Avg_Submtd_Cvrd_Chrg",
           "Avg_Tot_Pymt_Amt", "Avg_Mdcr_Pymt_Amt"]
OP_HEAD = ["Rndrng_Prvdr_CCN", "Rndrng_Prvdr_Org_Name", "APC_Cd", "APC_Desc", "Bene_Cnt", "CAPC_Srvcs",
           "Avg_Tot_Sbmtd_Chrgs", "Avg_Mdcr_Alowd_Amt", "Avg_Mdcr_Pymt_Amt"]


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def _read(path):
    return list(csv.DictReader(open(path, encoding="utf-8")))


@pytest.fixture
def mcfg(cfg):
    p = cfg.project_dir
    ip = [["900001", "Test Hospital A", "001", "TEST JOINT W/O MCC", "20", "$99,999.00", "$12,000.00", "$10,000.00"],
          ["900002", "Test Hospital B", "001", "TEST JOINT W/O MCC", "1,000", "$999,999.00", "$24,000.00", "$20,000.00"],
          ["900001", "Test Hospital A", "002", "TEST JOINT W MCC", "30", "$5.00", "$30,000.00", "$25,000.00"],
          ["900003", "Test Hospital C", "009", "TEST OTHER", "50", "$1.00", "$1,000.00", "$900.00"]]
    op = [["900001", "Test Hospital A", "5115", "Level 5 Musculoskeletal Procedures", "40", "50", "$1", "$1,200",
           "$1,000"],
          ["900004", "Test Hospital D", "5115", "Level 5 Musculoskeletal Procedures", "140", "150", "$1", "$2,400",
           "$2,000"],
          ["900004", "Test Hospital D", "5021", "Level 1 Type A ED Visits", "500", "500", "$1", "$100", "$80"],
          ["900005", "Test Hospital E", "5115", "Level 5 Musculoskeletal Procedures", "", "", "", "", ""],
          ["900006", "Test Hospital F", "5115", "Level 5 Musculoskeletal Procedures", "", "20", "$1", "$3,000",
           "$2,500"]]
    _write(p / "in" / "ip.csv", IP_HEAD, ip)
    _write(p / "in" / "op.csv", OP_HEAD, op)
    _write(p / "reference" / "procedure_families.csv",
           ["family_id", "sort_order", "name", "description", "drgs", "flagship", "status", "note"],
           [["joint", 1, "Test joint", "A made-up family", "1|2|3", "yes", "approved", ""]])
    _write(p / "reference" / "procedure_devices.csv", ["family_id", "role", "product_code", "status", "note"],
           [["joint", "implant", "AAA", "draft", ""], ["joint", "cement and accessories", "BBB", "draft", ""]])
    _write(p / "reference" / "procedure_outpatient.csv",
           ["family_id", "cpt", "procedure", "outpatient_status_2024", "apc", "source", "source_url"],
           [["joint", "00001", "Test procedure", "Outpatient allowed", "5115", "test", ""],
            ["joint", "00002", "Other test procedure", "NOT FOUND", "NOT FOUND", "test", ""]])
    _write(p / "reference" / "supply_cost_evidence.csv",
           ["source", "procedure", "data_years", "measure", "result", "source_url"],
           [["Test study", "Test joint", "2000", "Implant share", "40%", ""]])
    site = cfg.site_data_dir
    _write(site / "pc_product_codes.csv", ["product_code", "fda_name", "plain_name"],
           [["AAA", "Test implant", "Test implant"], ["BBB", "Test cement", ""]])
    _write(site / "pc_vendors.csv", ["vendor_id", "rolls_up_to"], [["acme", "acme"], ["acme_sub", "acme"],
                                                                     ["beta", "beta"]])
    _write(site / "pc_portfolio_510k.csv", ["vendor_id", "knumber", "product_code", "decision_date"],
           [["acme", "K1", "AAA", "2025-06-01"], ["acme_sub", "K2", "AAA", "2024-01-01"],
            ["beta", "K3", "AAA", "2019-01-01"], ["beta", "K4", "BBB", "2026-01-01"]])
    for k, v in {"IP_FILE": "in/ip.csv", "OP_FILE": "in/op.csv", "IP_EXPECTED_ROWS": "4",
                 "IP_EXPECTED_HOSPITALS": "3", "OP_EXPECTED_ROWS": "5", "OP_EXPECTED_HOSPITALS": "4",
                 "ACTIVE_VENDOR_YEARS": "5", "SUPPLY_SHARES": "0.30, 0.40, 0.50"}.items():
        cfg.raw.set("medicare", k, v)
    return cfg


def _run(cfg, monkeypatch):
    monkeypatch.setattr(load_medicare, "load_config", lambda _=None: cfg)
    return load_medicare.main([])


def test_builds_procedure_tables(mcfg, monkeypatch):
    assert _run(mcfg, monkeypatch) == 0
    site = mcfg.site_data_dir
    fam = _read(site / "pc_procedures.csv")[0]
    # discharge-weighted: Medicare (20*10000 + 1000*20000 + 30*25000) / 1050
    assert fam["discharges"] == "1050" and fam["hospitals"] == "2"
    assert fam["medicare_pays"] == str(round((20 * 10000 + 1000 * 20000 + 30 * 25000) / 1050))
    total = (20 * 12000 + 1000 * 24000 + 30 * 30000) / 1050
    assert fam["total_payment"] == str(round(total))
    assert int(fam["patient_other_pays"]) == round(total - (20 * 10000 + 1000 * 20000 + 30 * 25000) / 1050)
    med = (20 * 10000 + 1000 * 20000 + 30 * 25000) / 1050
    assert fam["supply_medicare_30"] == str(round(med * 0.3)) and fam["supply_medicare_50"] == str(round(med * 0.5))
    assert fam["supply_total_50"] == str(round(total * 0.5))

    drg = {r["drg"]: r for r in _read(site / "pc_procedure_drg.csv")}
    assert drg["1"]["discharges"] == "1020" and drg["1"]["hospitals"] == "2"
    assert drg["3"]["drg_desc"] == "NOT FOUND" and "suppressed" in drg["3"]["note"]   # DRG with no rows
    assert "9" not in drg                                                              # outside every family

    apc = _read(site / "pc_procedure_apc.csv")
    assert [a["apc"] for a in apc] == ["5115"]                                         # ED visit APC left out
    # the blank (suppressed) row is left out; the row with a hidden patient count keeps its services and payments
    assert apc[0]["services"] == "220" and apc[0]["hospitals"] == "3" and apc[0]["patients_reported"] == "180"
    assert apc[0]["medicare_pays"] == str(round((50 * 1000 + 150 * 2000 + 20 * 2500) / 220))
    assert apc[0]["total_allowed"] == str(round((50 * 1200 + 150 * 2400 + 20 * 3000) / 220))

    out = {r["cpt"]: r for r in _read(site / "pc_procedure_outpatient.csv")}
    assert out["00001"]["apc_services"] == "220" and out["00002"]["apc"] == "NOT FOUND"

    dev = {r["product_code"]: r for r in _read(site / "pc_procedure_devices.csv")}
    # data ends 2026-01-01, window starts 2021-01-01: acme (owner of acme_sub) counts once, beta's 2019 clearance is out
    assert dev["AAA"]["clearances_all"] == "3" and dev["AAA"]["clearances_recent"] == "2"
    assert dev["AAA"]["active_vendors"] == "1"
    assert dev["BBB"]["plain_name"] == "Test cement"                                   # falls back to the FDA name
    report = (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")
    assert "Problems: none" in report and "NOT FOUND" in report
    assert "left out: 1 (5115 1)" in report and "patient count hidden (services and payments kept): 1" in report


def test_no_hospital_names_ids_or_charges_written(mcfg, monkeypatch):
    assert _run(mcfg, monkeypatch) == 0
    for f in mcfg.site_data_dir.glob("pc_procedure*.csv"):
        text = f.read_text(encoding="utf-8")
        assert "Test Hospital" not in text and "90000" not in text, f.name
        assert not re.search(r"chrg|\bcharges?\b", text, re.I), f.name
    assert not any("Chrg" in c for c in load_medicare.IP_COLS + load_medicare.OP_COLS)


def test_row_count_mismatch_stops(mcfg, monkeypatch):
    mcfg.raw.set("medicare", "IP_EXPECTED_ROWS", "5")
    assert _run(mcfg, monkeypatch) == 1
    report = (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")
    assert "STOPPED" in report and "IP_EXPECTED_ROWS" in report
    assert not (mcfg.site_data_dir / "pc_procedures.csv").exists()


def test_suppression_floor_stops(mcfg, monkeypatch):
    p = mcfg.project_dir / "in" / "ip.csv"
    rows = list(csv.reader(open(p, encoding="utf-8")))
    rows[1][4] = "10"
    _write(p, rows[0], rows[1:])
    assert _run(mcfg, monkeypatch) == 1
    assert "suppression floor" in (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")


def test_drg_in_two_families_stops(mcfg, monkeypatch):
    p = mcfg.project_dir / "reference" / "procedure_families.csv"
    rows = list(csv.reader(open(p, encoding="utf-8")))
    rows.append(["other", "2", "Other", "x", "2", "no", "approved", ""])
    _write(p, rows[0], rows[1:])
    assert _run(mcfg, monkeypatch) == 1
    assert "two families" in (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")


def test_unknown_product_code_stops(mcfg, monkeypatch):
    p = mcfg.project_dir / "reference" / "procedure_devices.csv"
    rows = list(csv.reader(open(p, encoding="utf-8")))
    rows.append(["joint", "implant", "ZZZ", "draft", ""])
    _write(p, rows[0], rows[1:])
    assert _run(mcfg, monkeypatch) == 1
    assert "ZZZ" in (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")


def test_bad_number_stops(mcfg, monkeypatch):
    p = mcfg.project_dir / "in" / "op.csv"
    rows = list(csv.reader(open(p, encoding="utf-8")))
    rows[1][8] = "n/a"
    _write(p, rows[0], rows[1:])
    assert _run(mcfg, monkeypatch) == 1
    assert "not a number" in (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")


def test_published_reference_files_are_consistent():
    ref = ROOT / "reference"
    fams = _read(ref / "procedure_families.csv")
    ids = {f["family_id"] for f in fams}
    drgs = [d for f in fams for d in f["drgs"].split("|")]
    assert len(drgs) == len(set(drgs))
    assert all(f["drgs"] for f in fams)
    devs = _read(ref / "procedure_devices.csv")
    assert {d["family_id"] for d in devs} <= ids
    assert {d["role"] for d in devs} <= set(load_medicare.ROLES)
    for r in _read(ref / "procedure_outpatient.csv"):
        assert r["family_id"] in ids
        assert r["apc"] == "NOT FOUND" or r["source_url"].startswith("https://"), r["cpt"]


def test_titles_spread_minimum_and_supply_flag(mcfg, monkeypatch):
    ref = mcfg.project_dir / "reference"
    _write(ref / "procedure_families.csv",
           ["family_id", "sort_order", "name", "description", "drgs", "flagship", "supply_range", "status", "note"],
           [["joint", 1, "Test joint", "A made-up family", "3|2|1", "yes", "no", "approved", ""]])
    _write(ref / "drg_titles.csv", ["drg", "mdc", "type", "title", "official_title", "source", "source_url"],
           [["001", "08", "surgical", "Test joint w/o MCC (official)", "TEST JOINT W/O MCC (OFFICIAL)", "test", ""],
            ["009", "08", "surgical", "Test other", "TEST OTHER", "test", ""]])
    mcfg.raw.set("medicare", "SPREAD_MIN_HOSPITALS", "2")
    assert _run(mcfg, monkeypatch) == 0
    site = mcfg.site_data_dir
    fam = _read(site / "pc_procedures.csv")[0]
    assert fam["drgs"] == "1|2|3"                                                     # sorted by number
    assert fam["supply_medicare_30"] == "" and fam["supply_total_50"] == ""          # no published study
    assert fam["supply_note"].startswith("NOT FOUND. Reason:")
    drg = {r["drg"]: r for r in _read(site / "pc_procedure_drg.csv")}
    assert drg["1"]["drg_desc"] == "Test joint w/o MCC (official)"                          # official title wins
    assert drg["2"]["drg_desc"] == "Test joint w MCC"                                 # fallback: CMS text, sentence case
    assert drg["1"]["hospital_medicare_median"] != "" and drg["1"]["spread_note"] == ""   # 2 hospitals, minimum 2
    assert drg["2"]["hospital_medicare_median"] == "" and "only 1 hospital reported" in drg["2"]["spread_note"]
    assert drg["2"]["medicare_pays"] == "25000"                                       # national figures still shown
    report = (mcfg.output_dir / "Medicare_Report.txt").read_text(encoding="utf-8")
    assert "Problems: none" in report
    assert "with hospital rows but in no family: 009" in report
