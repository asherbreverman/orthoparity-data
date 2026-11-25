"""ASC rates (load_asc) and the part-number lookup (export_catalog), on synthetic files only."""
from __future__ import annotations

import csv
import gzip
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
        ('D1', 'CAT-001', 'CAT-001', 'Brand A', 'Co A', 'In Commercial Distribution', '1', 'false', 'HWC'),
        ('D2', 'CAT-001', 'MODEL 9', 'Brand A', 'Co A', 'Not in Commercial Distribution', '1', 'false', 'HWC'),
        ('D3', 'N/A', 'AB', 'Brand B', 'Co B', 'In Commercial Distribution', '1', 'false', 'HWC'),
        ('D4', 'X-777', null, 'Brand C', 'Co C', 'In Commercial Distribution', '1', 'false', 'HWC'),
        ('D5', 'SCR-45', null, 'Brand D', 'Co D', 'In Commercial Distribution', '1', 'true', 'HWC'),
        ('D6', 'SCR-45', null, 'Brand D', 'Co D', 'In Commercial Distribution', '5', 'true', 'HWC'),
        ('D7', 'DENT-1', null, 'Brand E', 'Co E', 'In Commercial Distribution', '1', 'false', 'ELM'),
        ('D8', 'ODD-88', null, 'Brand F', 'Co F', 'In Commercial Distribution', '1', 'false', 'ZZZ'),
        ('D9', 'PMA-9', null, 'Brand G', 'Co G', 'In Commercial Distribution', '1', 'false', 'OJZ'))
        t(primary_di, catalog_number, version_model, brand, company, distribution_status, device_count,
          premarket_exempt, product_codes)""")
    con.execute("""create table gudid_submissions as select * from (values
        ('D1', 'K111111', ''), ('D2', 'K111111', ''), ('D3', 'K111111', ''), ('D4', 'K999999', ''),
        ('D8', 'K111111', ''), ('D9', 'P123456', 'S001'))
        t(primary_di, submission_number, supplement_number)""")
    con.execute("""create table gudid_device_fields as select * from (values
        ('D1', 'true', 'false', 'MR Conditional'), ('D2', 'true', 'false', 'MR Conditional'),
        ('D5', 'false', 'true', 'MR Safe'), ('D6', 'false', 'true', 'MR Unsafe'))
        t(primary_di, sterile, sterilize_before_use, mri_safety)""")
    portfolio = tmp_path / "pc_portfolio_510k.csv"
    portfolio.write_text("knumber,vendor_id,product_code\nK111111,v1,HWC\n", encoding="utf-8")
    (tmp_path / "pc_approvals.csv").write_text("number,product_code\nP123456,OJZ\n", encoding="utf-8")
    site, out = tmp_path / "site", tmp_path / "out"
    out.mkdir()
    stats = export_catalog.export(con, portfolio, site, out)
    with open(site / "pc_catalog_1.csv", newline="", encoding="utf-8") as f:
        rows = {(r["ident"], r["n"]): r for r in csv.DictReader(f)}
    # CAT-001 merges across D1 and D2 and stays in distribution; MODEL 9 is its own row; N/A and "AB" are dropped;
    # X-777 keeps its FDA number even though it isn't on the site; SCR-45 lists no FDA number; DENT-1 is not orthopedic;
    # ODD-88 has a non-orthopedic product code in GUDID but lists a site FDA number, so it stays
    assert set(rows) == {("CAT-001", "K111111"), ("MODEL 9", "K111111"), ("X-777", "K999999"), ("SCR-45", ""),
                         ("ODD-88", "K111111"), ("PMA-9", "P123456")}  # FDA approvals count as on the site
    cat = rows[("CAT-001", "K111111")]
    assert (cat["in_dist"], cat["n_di"], cat["units"], cat["sterile"], cat["mri"]) == ("true", "2", "1", "true", "2")
    assert cat["pc"] == "" and cat["company_id"] == "" and cat["exempt"] == ""
    other = rows[("X-777", "K999999")]
    assert other["pc"] == "HWC" and other["company_id"] != "" and other["sterile"] == "" and other["exempt"] == ""
    none = rows[("SCR-45", "")]
    # two device IDs that disagree: units blank, MRI 9 (mixed), sterile false for both, marked exempt
    assert (none["n_di"], none["units"], none["mri"], none["sterile"], none["exempt"]) == ("2", "", "9", "false", "true")
    assert stats["rows"] == 6 and stats["by_kind"] == {"site": 4, "other": 1, "none": 1}
    assert (site / "pc_catalog_brand.csv").exists() and (site / "pc_catalog_company.csv").exists()
    report = (out / "Catalog_Report.txt").read_text(encoding="utf-8")
    assert "listing no FDA number: 2 (2 marked premarket exempt)" in report


def test_gudid_device_fields(tmp_path):
    from pipeline import gudid_device_fields as g
    xml = tmp_path / "FULLDownload_Part1_Of_1.xml"
    xml.write_text("""<?xml version="1.0"?><gudid xmlns="http://www.fda.gov/cdrh/gudid">
      <device><identifiers><identifier><deviceId>00811111</deviceId><deviceIdType>Package</deviceIdType></identifier>
        <identifier><deviceId>00822222</deviceId><deviceIdType>Primary</deviceIdType></identifier></identifiers>
        <MRISafetyStatus>MR Conditional</MRISafetyStatus>
        <sterilization><deviceSterile>true</deviceSterile><sterilizationPriorToUse>false</sterilizationPriorToUse></sterilization></device>
      <device><identifiers><identifier><deviceId>00833333</deviceId><deviceIdType>Primary</deviceIdType></identifier></identifiers></device>
    </gudid>""", encoding="utf-8")
    name, n = g.parse_part(str(xml), str(tmp_path))
    assert (name, n) == ("FULLDownload_Part1_Of_1", 2)
    with gzip.open(tmp_path / "FULLDownload_Part1_Of_1.fields.csv.gz", "rt", encoding="utf-8") as f:
        got = list(csv.reader(f))
    assert got == [g.COLS, ["00822222", "true", "false", "MR Conditional"], ["00833333", "", "", ""]]
    assert g.parse_part(str(xml), str(tmp_path)) == (name, 2)  # resumable
