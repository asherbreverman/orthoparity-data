"""ASC rates (load_asc) and the part-number lookup (export_catalog), on synthetic files only."""
from __future__ import annotations

import csv
import zipfile

import pytest

from pipeline import load_asc

AA = """Addendum AA -- Final ASC Covered Surgical Procedures for CY 2027 (Including Surgical Procedures),,,,,,,
CPT codes and descriptions only are copyright 2026 American Medical Association.,,,,,,,
,,,,,,,
HCPCS Code,,Short Descriptor,Subject to Multiple Procedure Discounting,Final CY 2027 Comment Indicator,Final CY 2027  Payment Indicator,Final CY 2027  Payment Weight  ,Final CY 2027 Payment Rate
27447,,Desc,Y,,J8,168.9720,"$9,753.23 "
22853,,Desc,N,,N1,,
29881,,Desc,Y,,A2,28.0018,"$1,616.29 "
"""
FF = """Addendum FF -- Final ASC Device Offset Percentages for CY 2027,,,,,,,,
CPT codes and descriptions only are copyright 2026 American Medical Association.,,,,,,,,
,,,,,,,,
HCPCS Code,,Short Descriptor,Final CY 2027  Payment Indicator,Final CY 2027 APC,Final CY 2027 APC Device Offset Percentage,Final CY 2027 OPPS Payment Rate,Final CY 2027 Device Offset Percentage,Final CY 2027 Device Offset Amount / Device Portion
27447,,Desc,J8,5115,45.93%,"$13,886.63",43.84%,"$6,087.90"
"""


def make_zip(tmp_path, title_year="2027"):
    z = tmp_path / "2027-fr-asc-addenda.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("508 Version/2027 FR ASC Addenda AA.csv", AA.replace("2027", title_year).encode("cp1252"))
        f.writestr("508 Version/2027 FR ASC Addenda FF.csv", FF.replace("2027", title_year).encode("cp1252"))
    return z


def make_codes(tmp_path):
    p = tmp_path / "codes.csv"
    p.write_text("family_id,cpt,procedure\nhip_knee_replacement,27447,Total knee replacement\n"
                 "spine,22853,Interbody device\nother,99999,Not on the list\n", encoding="utf-8")
    return p


def test_asc_rows(tmp_path):
    rows, _ = load_asc.build(make_zip(tmp_path), make_codes(tmp_path), 2027)
    tka, packaged, absent = rows
    assert tka["asc_rate"] == "9753.23" and tka["device_portion"] == "6087.90" and tka["device_share"] == "0.4384"
    assert tka["device_intensive"] == "yes" and tka["asc_status"] == "On the ASC list"
    assert packaged["asc_rate"] == "" and packaged["asc_status"].startswith("On the ASC list, packaged")
    assert absent["asc_status"] == "Not on the ASC list" and absent["payment_indicator"] == ""


def test_asc_keeps_cms_descriptions_out(tmp_path):
    rows, _ = load_asc.build(make_zip(tmp_path), make_codes(tmp_path), 2027)
    sql = load_asc.sql_text(rows)
    assert "Desc" not in sql and "American Medical Association" not in sql
    assert "'Total knee replacement'" in sql and "9753.23" in sql


def test_asc_stops_on_wrong_year(tmp_path):
    with pytest.raises(SystemExit):
        load_asc.build(make_zip(tmp_path, "2026"), make_codes(tmp_path), 2027)


def test_catalog_export(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from pipeline import export_catalog
    con = duckdb.connect()
    con.execute("""create table gudid_devices as select * from (values
        ('D1', 'CAT-001', 'CAT-001', 'Brand A', 'In Commercial Distribution'),
        ('D2', 'CAT-001', 'MODEL 9', 'Brand A', 'Not in Commercial Distribution'),
        ('D3', 'N/A', 'AB', 'Brand B', 'In Commercial Distribution'),
        ('D4', 'X-777', null, 'Brand C', 'In Commercial Distribution'))
        t(primary_di, catalog_number, version_model, brand, distribution_status)""")
    con.execute("""create table gudid_submissions as select * from (values
        ('D1', 'K111111', ''), ('D2', 'K111111', ''), ('D3', 'K111111', ''), ('D4', 'K999999', ''))
        t(primary_di, submission_number, supplement_number)""")
    portfolio = tmp_path / "pc_portfolio_510k.csv"
    portfolio.write_text("knumber,vendor_id\nK111111,v1\n", encoding="utf-8")
    site, out = tmp_path / "site", tmp_path / "out"
    out.mkdir()
    stats = export_catalog.export(con, portfolio, site, out)
    with open(site / "pc_catalog_1.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    idents = {(r["ident"], r["n"]) for r in rows}
    # CAT-001 merges across D1 and D2 and stays in distribution; MODEL 9 is its own row; N/A and "AB" are dropped;
    # X-777 belongs to a number that isn't on the site
    assert idents == {("CAT-001", "K111111"), ("MODEL 9", "K111111")}
    assert next(r for r in rows if r["ident"] == "CAT-001")["in_dist"] == "true"
    assert stats["rows"] == 2 and (site / "pc_catalog_brand.csv").exists()
