"""load_add_on_payments.py with synthetic CMS files: no network, no real CMS data."""
import csv
import io
import zipfile

import pytest
from openpyxl import Workbook

from pipeline import load_add_on_payments as la


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def _file8(folder):
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in (("New NTAP_corrected", [["Widget® Cage", 1000, "XRG0001", "Breakthrough Device"]]),
                        ("Continued NTAP", [["Other™ Stent", "2,500.50", "X2V0001", "Breakthrough Device"]]),
                        ("Discontinued NTAP", [])):
        ws = wb.create_sheet(title)
        ws.append([f"MAC Implementation File 8 - {title}"])
        ws.append(["Technology", "Maximum Add-on Payment", "ICD-10-CM/PCS Codes", "Alternative Pathways Status"])
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    with zipfile.ZipFile(folder / "mac_implementation_file_8-fy_2027.zip", "w") as z:
        z.writestr("MAC Implementation File 8 - FY 2027.xlsx", buf.getvalue())


def _addenda(folder, expires="*"):
    rows = [["", "Addendum B.- OPPS Payment by HCPCS Code"], ["", "notes"],
            ["HCPCS Code", "Short Descriptor", " CI", " SI", " APC ", "Relative Weight", "Payment Rate",
             "National Unadjusted Copayment", "Minimum Unadjusted Copayment", "IRA Coinsurance percentage ",
             "Adjusted Beneficiary Copayment", "Drug and Device Pass-Through Expiration during Calendar Year", "Note"],
            ["C1999", "Widget cage", "", "H", "2999", ".", "", "", "", "", "", expires, ""],
            ["C1998", "Heart thing", "", "H", "2998", ".", "", "", "", "", "", "", ""],
            ["27447", "Total knee", "", "J1", "5115", "1", "", "", "", "", "", "", ""]]
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    with zipfile.ZipFile(folder / "508-version-cy-2027-opps-addenda.zip", "w") as z:
        z.writestr("508 Version/2027 FR Addendum B.11.10.26.csv", buf.getvalue().encode("latin-1"))


REF_COLS = ["tech_id", "program", "period", "status", "technology", "company", "vendor_id", "fda_numbers",
            "linked_510ks", "hcpcs", "effective", "pass_through_ends", "fda_source", "note"]


def _setup(tmp_path, ref_rows, expires="*"):
    cms, site, out = tmp_path / "cms", tmp_path / "site", tmp_path / "out"
    cms.mkdir()
    _file8(cms)
    _addenda(cms, expires)
    _write(site / "pc_devices.csv", ["knumber", "product_code", "in_starting_set"],
           [["K000001", "SAI", "true"], ["K000002", "SAI", "true"], ["K000009", "SAI", "false"]])
    _write(site / "pc_portfolio_510k.csv", ["knumber", "vendor_id"], [["K000001", "acme"], ["K000002", "acme"]])
    _write(tmp_path / "ref.csv", REF_COLS, ref_rows)
    return cms, tmp_path / "ref.csv", site, out


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_load_checks_names_and_codes_and_copies_cms_figures(tmp_path):
    cms, ref, site, out = _setup(tmp_path, [
        ["n1", "NTAP", "FY 2027", "new", "Widget Cage", "Acme", "", "K000001", "K000001;K000002", "", "", "", "u", ""],
        ["t1", "TPT", "CY 2027", "continuing", "Widget", "Acme", "", "K000001", "K000001", "C1999", "2025-01-01",
         "during CY 2027", "u", ""],
    ])
    stats = la.load(cms, ref, site, out)
    techs = {r["tech_id"]: r for r in _read(site / "pc_add_on_payment.csv")}
    assert techs["n1"]["max_payment"] == "1000.00" and techs["n1"]["cms_codes"] == "XRG0001"
    assert techs["n1"]["vendor_id"] == "acme"  # from the linked 510(k)s
    assert techs["t1"]["apc"] == "2999" and techs["t1"]["cms_descriptor"] == "Widget cage"
    assert len(_read(site / "pc_add_on_payment_510k.csv")) == 3
    report = (out / "Add_on_Payments_Report.txt").read_text(encoding="utf-8")
    assert "Other™ Stent" in report and "C1998" in report  # what the reference file left out is listed
    assert stats["skipped_ntap"] == 1 and stats["skipped_tpt"] == 1


@pytest.mark.parametrize("row, msg", [
    (["n1", "NTAP", "FY 2027", "continued", "Widget Cage", "", "", "", "", "", "", "", "", ""], "not in the File 8"),
    (["t1", "TPT", "CY 2027", "continuing", "X", "", "", "", "", "C1000", "", "after CY 2027", "", ""], "not a pass-through"),
    (["t1", "TPT", "CY 2027", "continuing", "X", "", "", "", "", "C1999", "", "after CY 2027", "", ""], "expiration flag"),
    (["n1", "NTAP", "FY 2027", "new", "Widget Cage", "", "", "", "K000009", "", "", "", "", ""], "not in the starting set"),
])
def test_load_stops_on_any_mismatch(tmp_path, row, msg):
    cms, ref, site, out = _setup(tmp_path, [row])
    with pytest.raises(SystemExit) as e:
        la.load(cms, ref, site, out)
    assert msg in str(e.value)


def test_names_compare_without_trademark_symbols():
    assert la.norm("aprevo®-C  Cervical™") == la.norm("APREVO-C cervical")
    assert la.money('"$21,125.00"') == "21125.00" and la.money("") == ""
