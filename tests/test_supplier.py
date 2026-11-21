"""fetch_establishments.py and load_fda_compliance.py: synthetic fixtures only, no network."""
import csv
import json
from collections import Counter
from datetime import datetime

from openpyxl import Workbook

from pipeline import fetch_establishments as fe
from pipeline import load_fda_compliance as lc


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _site_data(site):
    _write(site / "pc_devices.csv", ["knumber", "product_code", "in_starting_set"],
           [["K000001", "AAA", "true"], ["K000002", "AAA", "true"], ["K000003", "BBB", "true"],
            ["K000009", "BBB", "false"]])
    _write(site / "pc_vendors.csv", ["vendor_id", "display_name", "rolls_up_to"],
           [["acme", "Acme Ortho", "acme"], ["acme_sub", "Bolt Implants", "acme"], ["other", "Other Spine", "other"]])
    _write(site / "pc_vendor_names.csv", ["vendor_id", "source", "raw_name", "basis"],
           [["acme", "applicant", "ACME ORTHO, INC.", "own name"], ["acme_sub", "applicant", "Bolt Implants LLC", "own name"],
            ["other", "applicant", "Other Spine Corp", "own name"]])
    _write(site / "pc_portfolio_510k.csv", ["knumber", "vendor_id"],
           [["K000001", "acme"], ["K000002", "acme_sub"], ["K000003", "other"]])


def test_owner_company_matches_names_not_distributors():
    tokens = {"acme": {"ACME", "BOLT"}, "other": {"OTHER"}}
    cores = {"acme": {"ACMEORTHO", "BOLTIMPLANTS"}, "other": {"OTHERSPINE"}}
    assert fe.owner_company("ACME ORTHO CORP.", Counter({"acme": 3}), tokens, cores) == "acme"
    # a logistics firm holding the listings matches no company name
    assert fe.owner_company("Exel Inc. dba DHL Supply Chain (USA)", Counter({"acme": 50}), tokens, cores) == ""
    # generic words alone never match
    assert fe.owner_company("Spine Medical Products LLC", Counter({"other": 9}), tokens, cores) == ""
    # a squashed spelling still matches the full name
    assert fe.owner_company("BoltImplants Americas DFE", Counter({"acme": 2}), tokens, cores) == "acme"
    # the company with the most listings wins only when its name matches
    assert fe.owner_company("Other Spine Corp", Counter({"acme": 5, "other": 1}), tokens, cores) == "other"


def test_fetch_code_pages_until_total():
    pages = {0: [{"registration": {"fei_number": "1"}, "k_number": "K000001"}] * 2,
             2: [{"registration": {"fei_number": "2"}, "k_number": "K000002"}]}

    def get(params):
        return {"results": pages.get(params["skip"], []), "meta": {"results": {"total": 3}}}
    fe.PAGE, old = 2, fe.PAGE
    try:
        rows = fe.fetch_code(get, "AAA")
    finally:
        fe.PAGE = old
    assert [r["fei_number"] for r in rows] == ["1", "1", "2"]


def test_slim_drops_contact_people():
    r = {"registration": {"fei_number": "1", "name": "ACME", "us_agent": {"name": "Jane Roe"},
                          "owner_operator": {"firm_name": "ACME ORTHO, INC.", "official_correspondent": {"first_name": "Jo"}}},
         "establishment_type": ["Manufacture Medical Device"], "products": [{"product_code": "AAA"}]}
    out = json.dumps(fe.slim(r))
    assert "Jane" not in out and "Jo" not in out and "ACME ORTHO" in out


def test_export_links_sites_and_marks_company(tmp_path):
    site, out, cache = tmp_path / "site", tmp_path / "out", tmp_path / "cache"
    _site_data(site)
    cache.mkdir()
    base = {"registration_number": "", "city": "Town", "state": "IN", "country": "US", "status_code": "1",
            "reg_expiry_year": "2027", "pma_number": "", "proprietary_name": ["Widget"]}
    rows = [
        dict(base, fei_number="100", name="ACME ORTHO", owner_operator_number="9", owner_operator_name="ACME ORTHO, INC.",
             k_number="K000001", establishment_type=["Manufacture Medical Device"], product_codes=["AAA"]),
        dict(base, fei_number="100", name="ACME ORTHO", owner_operator_number="9", owner_operator_name="ACME ORTHO, INC.",
             k_number="PK000002", establishment_type=["Develop Specifications But Do Not Manufacture At This Facility"],
             product_codes=["AAA"]),
        dict(base, fei_number="200", name="STERI-CO", owner_operator_number="8", owner_operator_name="Steri-Co LLC",
             k_number="K000001", establishment_type=["Sterilize Medical Device for Another Party (Contract Sterilizer)"],
             product_codes=["AAA"]),
        dict(base, fei_number="0", registration_number="555", name="NOFEI", owner_operator_number="7",
             owner_operator_name="Other Spine Corp", k_number="K000009", establishment_type=["Repack or Relabel Medical Device"],
             product_codes=["BBB"]),
    ]
    (cache / "AAA.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows[:3]), encoding="utf-8")
    (cache / "BBB.jsonl").write_text(json.dumps(rows[3]) + "\n", encoding="utf-8")
    ks, codes = fe.starting_set(site)
    stats = fe.export(cache, ks, codes, site, out)
    sites = {r["fei_number"]: r for r in _read(site / "pc_establishment.csv")}
    links = _read(site / "pc_establishment_510k.csv")
    assert sites["100"]["company_vendor_id"] == "acme" and sites["100"]["knumbers"] == "2"
    assert sites["200"]["company_vendor_id"] == "" and sites["200"]["makes_devices"] == "True"
    assert sites["R555"]["knumbers"] == "0"  # K000009 is outside the starting set
    assert {(r["fei_number"], r["knumber"]) for r in links} == {("100", "K000001"), ("100", "K000002"), ("200", "K000001")}
    assert stats["sites_with_510k"] == 2 and stats["company_sites"] == 1
    assert (out / "Establishments_Report.txt").exists()


def _xlsx(path, title, heads, rows):
    wb = Workbook()
    ws = wb.active
    if title:
        ws.append([title])
        ws.append([])
    ws.append(heads)
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_load_keeps_orthopedic_sites_and_finds_files_by_heading(tmp_path):
    site, out, dash = tmp_path / "site", tmp_path / "out", tmp_path / "dash"
    dash.mkdir()
    _write(site / "pc_establishment.csv", ["fei_number"], [["100"], ["200"]])
    d = datetime(2024, 3, 28)
    _xlsx(dash / "a.xlsx", "Inspections export", ["FEI Number", "Legal Name", "City", "Fiscal Year", "Inspection ID",
          "Posted Citations", "Inspection End Date", "Classification", "Project Area", "Product Type"],
          [[100, "ACME", "Town", 2024, "11", "Yes", d, "Voluntary Action Indicated (VAI)", "Compliance: Devices", "Devices"],
           [100, "ACME", "Town", 2024, "11", "Yes", d, "Voluntary Action Indicated (VAI)", "Compliance: Devices", "Devices"],
           [999, "Food Co", "Town", 2024, "12", "No", d, "No Action Indicated (NAI)", "Foods", "Food/Cosmetics"]])
    _xlsx(dash / "b.xlsx", None, ["Inspection ID", "FEI Number", "Legal Name", "Inspection End Date", "Program Area",
          "Act/CFR Number", "Short Description", "Long Description"],
          [["11", "100", "ACME", d, "Devices", "21 CFR 820.100(a)", "Lack of or inadequate procedures", "long text"]])
    _xlsx(dash / "c.xlsx", None, ["FEI Number", "Legal Name", "State", "Country/Area", "Product Type",
          "Action Taken Date", "Action Type", "Case/Injunction ID"],
          [[200, "Steri-Co", "Ohio", "United States", "Devices", "11/13/2025", "Warning Letter", 7001],
           [999, "Food Co", "-", "France", "Food/Cosmetics", d, "Warning Letter", 7002]])
    stats = lc.load(dash, site, out)
    insp = _read(site / "pc_inspection.csv")
    assert len(insp) == 1 and insp[0]["end_date"] == "2024-03-28" and insp[0]["posted_citations"] == "True"
    assert _read(site / "pc_inspection_citation.csv")[0]["cfr"] == "21 CFR 820.100(a)"
    acts = _read(site / "pc_compliance_action.csv")
    assert acts == [{"case_id": "7001", "fei_number": "200", "legal_name": "Steri-Co", "action_date": "2025-11-13",
                     "action_type": "Warning Letter", "product_type": "Devices"}]
    assert stats["inspections"]["read"] == 3 and (out / "FDA_Compliance_Report.txt").exists()


def test_load_stops_when_an_export_is_missing(tmp_path):
    site, dash = tmp_path / "site", tmp_path / "dash"
    dash.mkdir()
    _write(site / "pc_establishment.csv", ["fei_number"], [["100"]])
    try:
        lc.load(dash, site, tmp_path / "out")
    except SystemExit as e:
        assert "inspections" in str(e)
    else:
        raise AssertionError("expected a stop")


def test_publish_check_skips_fda_id_columns_only():
    from tools.check_before_publish import npi_valid, without_fda_ids
    npi_shaped = "1000086912"  # an FEI from the data that happens to pass the NPI check digit
    assert npi_valid(npi_shaped)
    text = f"fei_number,name,note\n{npi_shaped},ACME,see {npi_shaped}\n"
    scan, ids = without_fda_ids(text)
    assert ids == {npi_shaped}
    assert scan.count(npi_shaped) == 1  # still caught when it appears outside an FDA ID column
