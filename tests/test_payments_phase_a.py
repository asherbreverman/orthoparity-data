"""Phase A (GUDID index and Open Payments load) on small synthetic fixtures. No real data."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

GUDID_XML = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<gudid xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" version="1.0" xmlns="http://www.fda.gov/cdrh/gudid">
  <header><database frequency="monthly" id="1" type="FULL"><downloadFile part="1" totalParts="1"/>
  <numberRecordXML>2</numberRecordXML><numberRecordsDatabase>2</numberRecordsDatabase></database></header>
<device xmlns="http://www.fda.gov/cdrh/gudid">
  <deviceRecordStatus>Published</deviceRecordStatus><publicVersionNumber>1</publicVersionNumber>
  <devicePublishDate>2023-02-08</devicePublishDate>
  <deviceCommDistributionStatus>In Commercial Distribution</deviceCommDistributionStatus>
  <identifiers>
    <identifier><deviceId>00812345000011</deviceId><deviceIdType>Primary</deviceIdType><deviceIdIssuingAgency>GS1</deviceIdIssuingAgency></identifier>
    <identifier><deviceId>10812345000018</deviceId><deviceIdType>Package</deviceIdType><deviceIdIssuingAgency>GS1</deviceIdIssuingAgency><pkgQuantity>5</pkgQuantity></identifier>
  </identifiers>
  <brandName>TESTCAGE Cervical</brandName><versionModelNumber>TC-10</versionModelNumber><catalogNumber>TC-10</catalogNumber>
  <dunsNumber>111111111</dunsNumber><companyName>SYNTHETIC SPINE, INC.</companyName><deviceCount>1</deviceCount>
  <deviceDescription>Cervical cage 10 mm</deviceDescription>
  <gmdnTerms><gmdn><gmdnCode>99999</gmdnCode><gmdnPTName>Cervical cage</gmdnPTName><implantable>true</implantable></gmdn></gmdnTerms>
  <productCodes><fdaProductCode><productCode>ODP</productCode><productCodeName>Intervertebral fusion device</productCodeName></fdaProductCode></productCodes>
  <premarketSubmissions><premarketSubmission><submissionNumber>K111111</submissionNumber><supplementNumber>000</supplementNumber></premarketSubmission>
    <premarketSubmission><submissionNumber>K222222</submissionNumber><supplementNumber>000</supplementNumber></premarketSubmission></premarketSubmissions>
</device>
<device xmlns="http://www.fda.gov/cdrh/gudid">
  <identifiers><identifier><deviceId>00899999000019</deviceId><deviceIdType>Primary</deviceIdType><deviceIdIssuingAgency>GS1</deviceIdIssuingAgency></identifier></identifiers>
  <brandName>Resin Tooth</brandName><companyName>SYNTHETIC DENTAL AG</companyName><dunsNumber>222222222</dunsNumber>
  <productCodes><fdaProductCode><productCode>ELM</productCode></fdaProductCode></productCodes>
</device>
</gudid>
"""

GEN_SLOT = ["Covered_or_Noncovered_Indicator_{i}", "Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_{i}",
            "Product_Category_or_Therapeutic_Area_{i}", "Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_{i}",
            "Associated_Drug_or_Biological_NDC_{i}", "Associated_Device_or_Medical_Supply_PDI_{i}"]
PAYER = ["Submitting_Applicable_Manufacturer_or_Applicable_GPO_Name",
         "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID",
         "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name",
         "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_State",
         "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Country"]
GENERAL = (["Change_Type", "Covered_Recipient_Type", "Teaching_Hospital_CCN", "Covered_Recipient_Profile_ID",
            "Covered_Recipient_NPI", "Covered_Recipient_First_Name", "Recipient_State", "Recipient_Country"]
           + [f"Covered_Recipient_Primary_Type_{i}" for i in range(1, 7)]
           + [f"Covered_Recipient_Specialty_{i}" for i in range(1, 7)] + PAYER
           + ["Total_Amount_of_Payment_USDollars", "Date_of_Payment", "Number_of_Payments_Included_in_Total_Amount",
              "Form_of_Payment_or_Transfer_of_Value", "Nature_of_Payment_or_Transfer_of_Value",
              "Physician_Ownership_Indicator", "Third_Party_Payment_Recipient_Indicator", "Charity_Indicator",
              "Third_Party_Equals_Covered_Recipient_Indicator", "Contextual_Information", "Delay_in_Publication_Indicator",
              "Record_ID", "Dispute_Status_for_Publication", "Related_Product_Indicator"]
           + [c.format(i=i) for i in range(1, 6) for c in GEN_SLOT] + ["Program_Year", "Payment_Publication_Date"])
RESEARCH = (["Change_Type", "Covered_Recipient_Type", "Noncovered_Recipient_Entity_Name", "Teaching_Hospital_CCN",
             "Teaching_Hospital_Name", "Covered_Recipient_Profile_ID", "Covered_Recipient_NPI"]
            + [f"Covered_Recipient_Specialty_{i}" for i in range(1, 7)]
            + [f"Principal_Investigator_{j}_NPI" for j in range(1, 6)]
            + [f"Principal_Investigator_1_Specialty_{i}" for i in range(1, 7)] + PAYER + ["Related_Product_Indicator"]
            + [c.format(i=i) for i in range(1, 6) for c in GEN_SLOT]
            + ["Total_Amount_of_Payment_USDollars", "Date_of_Payment", "Form_of_Payment_or_Transfer_of_Value"]
            + [f"Expenditure_Category{i}" for i in range(1, 7)]
            + ["Preclinical_Research_Indicator", "Delay_in_Publication_Indicator", "Name_of_Study",
               "Dispute_Status_for_Publication", "Record_ID", "Program_Year", "ClinicalTrials_Gov_Identifier"])
OWNERSHIP = ["Change_Type", "Physician_Profile_ID", "Physician_NPI", "Physician_Primary_Type", "Physician_Specialty",
             "Record_ID", "Program_Year", "Total_Amount_Invested_USDollars", "Value_of_Interest", "Terms_of_Interest",
             "Submitting_Applicable_Manufacturer_or_Applicable_GPO_Name",
             "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID",
             "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name", "Dispute_Status_for_Publication",
             "Interest_Held_by_Physician_or_an_Immediate_Family_Member"]

ORTHO = "Allopathic & Osteopathic Physicians|Orthopaedic Surgery|Orthopaedic Surgery of the Spine"
CARDIO = "Allopathic & Osteopathic Physicians|Internal Medicine|Cardiovascular Disease"


def _row(cols, **kw):
    return [kw.get(c, "") for c in cols]


def _general_rows():
    base = dict(Change_Type="UNCHANGED", Covered_Recipient_Type="Covered Recipient Physician", Recipient_State="AZ",
                Recipient_Country="United States", Covered_Recipient_First_Name="SHOULD_NOT_LOAD",
                Date_of_Payment="03/15/2025", Number_of_Payments_Included_in_Total_Amount="1",
                Form_of_Payment_or_Transfer_of_Value="Cash or cash equivalent", Program_Year="2025")
    rows = []
    # 1. Ortho device maker, product tagged with a GUDID package DI written with spaces and a (01) prefix.
    rows.append(_row(GENERAL, **base, Record_ID="1", Covered_Recipient_NPI="1000000001", Covered_Recipient_Specialty_1=CARDIO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P1",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Spine, Inc.",
                     Total_Amount_of_Payment_USDollars="1000.50", Nature_of_Payment_or_Transfer_of_Value="Royalty or License",
                     Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1="Device",
                     Product_Category_or_Therapeutic_Area_1="Spine", Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1="TESTCAGE",
                     Associated_Device_or_Medical_Supply_PDI_1="(01) 10812345000018"))
    # 2. Pharma to an orthopedic surgeon: kept by specialty, payer out of scope.
    rows.append(_row(GENERAL, **base, Record_ID="2", Covered_Recipient_NPI="1000000002", Covered_Recipient_Specialty_2=ORTHO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P2",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Pharma LLC",
                     Total_Amount_of_Payment_USDollars="30", Nature_of_Payment_or_Transfer_of_Value="Food and Beverage",
                     Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1="Drug",
                     Product_Category_or_Therapeutic_Area_1="Pain", Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1="PAINAWAY",
                     Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_2="N/A",
                     Associated_Device_or_Medical_Supply_PDI_2="N/A", Associated_Device_or_Medical_Supply_PDI_3="NA"))
    # 3. Cardio device maker to a cardiologist: dropped.
    rows.append(_row(GENERAL, **base, Record_ID="3", Covered_Recipient_NPI="1000000003", Covered_Recipient_Specialty_1=CARDIO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P3",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Heart Co",
                     Total_Amount_of_Payment_USDollars="99", Nature_of_Payment_or_Transfer_of_Value="Consulting Fee",
                     Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1="Device",
                     Product_Category_or_Therapeutic_Area_1="Cardiovascular", Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1="HEARTX"))
    # 4. Text-only orthopedic payer (no device ID) to a non-ortho recipient: kept, payer in scope.
    rows.append(_row(GENERAL, **base, Record_ID="4", Covered_Recipient_NPI="1000000004", Covered_Recipient_Specialty_1=CARDIO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P4",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Knee Works LLC",
                     Total_Amount_of_Payment_USDollars="250", Nature_of_Payment_or_Transfer_of_Value="Travel and Lodging",
                     Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1="Device",
                     Product_Category_or_Therapeutic_Area_1="KNEES, HIPS", Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1="KW Knee"))
    # 5. Wound care with "Recon" in its category: not orthopedic, dropped.
    rows.append(_row(GENERAL, **base, Record_ID="5", Covered_Recipient_NPI="1000000005", Covered_Recipient_Specialty_1=CARDIO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P5",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Wound Inc",
                     Total_Amount_of_Payment_USDollars="40", Nature_of_Payment_or_Transfer_of_Value="Food and Beverage",
                     Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1="Device",
                     Product_Category_or_Therapeutic_Area_1="Recon-Skin and Wound", Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1="WOUNDX"))
    # 6. Same ortho payer, record later removed by CMS.
    rows.append(_row(GENERAL, **base, Record_ID="6", Covered_Recipient_NPI="1000000001", Covered_Recipient_Specialty_1=ORTHO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P1",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Spine, Inc.",
                     Total_Amount_of_Payment_USDollars="77", Nature_of_Payment_or_Transfer_of_Value="Consulting Fee"))
    # 7. Small orthopedic company with no product tags at all: in scope by its 510(k) applicant name.
    rows.append(_row(GENERAL, **base, Record_ID="7", Covered_Recipient_NPI="1000000007", Covered_Recipient_Specialty_1=CARDIO,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P6",
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Tiny Ortho LLC",
                     Total_Amount_of_Payment_USDollars="500", Nature_of_Payment_or_Transfer_of_Value="Consulting Fee"))
    return rows


def _write(path: Path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL)
        w.writerow(cols)
        w.writerows(rows)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "OrthoData"
    proj = root / "predicate-chain"
    (proj / "outputs").mkdir(parents=True)
    gud = root / "GUDID"
    gud.mkdir()
    (gud / "FULLDownload_Part1_Of_1_2026-11-01.xml").write_text(GUDID_XML, encoding="utf-8")
    y = root / "OP" / "CMS Open Payments for 2025"
    _write(y / "OP_DTL_GNRL_PGYR2025_P1_X.csv", GENERAL, _general_rows())
    _write(y / "OP_DTL_RSRCH_PGYR2025_P1_X.csv", RESEARCH, [
        _row(RESEARCH, Record_ID="r1", Program_Year="2025", Total_Amount_of_Payment_USDollars="5000",
             Date_of_Payment="06/01/2025", Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P1",
             Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Spine, Inc.",
             Name_of_Study="Synthetic cage study", ClinicalTrials_Gov_Identifier="NCT00000000",
             Principal_Investigator_1_NPI="1000000001", Principal_Investigator_1_Specialty_1=ORTHO,
             Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_1="Device",
             Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1="TESTCAGE",
             Associated_Device_or_Medical_Supply_PDI_1="00812345000011")])
    _write(y / "OP_DTL_OWNRSHP_PGYR2025_P1_X.csv", OWNERSHIP, [
        _row(OWNERSHIP, Record_ID="o1", Program_Year="2025", Physician_NPI="1000000001",
             Total_Amount_Invested_USDollars="10000", Value_of_Interest="25000",
             Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID="P1",
             Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name="Synthetic Spine, Inc.")])
    _write(y / "OP_REMOVED_DELETED_PGYR2025_P1_X.csv", ["Change_Type", "Program_Year", "Payment_Type", "Record_ID"],
           [["DELETED", "2025", "General Payments", "6"]])
    db = proj / "data" / "predicate_chain.db"
    db.parent.mkdir(parents=True)
    sq = sqlite3.connect(db)
    sq.execute("""CREATE TABLE clearances (knumber TEXT, applicant TEXT, product_code TEXT, decision_year INTEGER,
                  devicename TEXT, decision_date TEXT)""")
    sq.executemany("INSERT INTO clearances VALUES (?,?,?,?,?,?)",
                   [("K111111", "Synthetic Spine, Inc.", "ODP", 2011, "TestCage", "2011-05-01"),
                    ("K333333", "Tiny Ortho, L.L.C.", "MNH", 2013, "Tiny Screw", "2013-02-01")])
    sq.commit(); sq.close()
    ini = proj / "config.ini"
    ini.write_text(f"""[settings]
MAX_GENERATIONS = 10
[paths]
OUTPUT_DIR = outputs
DATA_DIR = data
REVIEW_DIR = reviews
DB_FILE = data/predicate_chain.db
[payments]
OP_DIR = {(root / 'OP').as_posix()}
OP_YEAR_FOLDER = CMS Open Payments for {{year}}
OP_YEARS = 2025
OP_GENERAL_GLOB = OP_DTL_GNRL_PGYR{{year}}_*.csv
OP_RESEARCH_GLOB = OP_DTL_RSRCH_PGYR{{year}}_*.csv
OP_OWNERSHIP_GLOB = OP_DTL_OWNRSHP_PGYR{{year}}_*.csv
OP_REMOVED_GLOB = OP_REMOVED_DELETED_PGYR{{year}}_*.csv
OP_ORTHO_SPECIALTY_REGEX = orthop|podiat|neurological surgery|foot & ankle|hand surgery
OP_ORTHO_PRODUCT_REGEX = spine|spinal|orthop|\\bknee|\\bhip\\b|shoulder|trauma|\\bfusion
GUDID_DIR = {gud.as_posix()}
GUDID_FILE_GLOB = FULLDownload_Part*_Of_*.xml
GUDID_PARTS = 1
GUDID_EXPECTED_RECORDS = 2
GUDID_WORKERS = 1
PAYMENTS_DB = data/payments.duckdb
GUDID_STAGE_DIR = data/gudid_stage
DUCKDB_TEMP_DIR = data/duckdb_tmp
DUCKDB_MEMORY_LIMIT = 1GB
""", encoding="utf-8")
    monkeypatch.delenv("PREDICATE_CHAIN_DB", raising=False)
    monkeypatch.delenv("PAYMENTS_DB", raising=False)
    return proj, ini


def test_phase_a_end_to_end(env):
    from pipeline import index_gudid as build_gudid_index
    from pipeline import load_open_payments
    proj, ini = env
    assert build_gudid_index.main(["--config", str(ini)]) == 0
    assert load_open_payments.main(["--config", str(ini)]) == 0
    con = duckdb.connect(str(proj / "data" / "payments.duckdb"), read_only=True)
    q = lambda s: con.execute(s).fetchall()
    # GUDID
    assert q("SELECT count(*) FROM gudid_devices")[0][0] == 2
    assert sorted(r[0] for r in q("SELECT submission_number FROM gudid_submissions")) == ["K111111", "K222222"]
    assert q("SELECT primary_di FROM gudid_identifiers WHERE di = '10812345000018'")[0][0] == "00812345000011"
    # Scope
    scope = dict(q("SELECT payer_id, in_scope FROM payer_scope"))
    assert scope == {"P1": True, "P2": False, "P3": False, "P4": True, "P5": False, "P6": True}
    # Rows kept: 1 (in-scope payer), 2 (ortho recipient), 4 (text scope), 7 (applicant name); 3, 5 dropped; 6 removed.
    assert sorted(r[0] for r in q("SELECT record_id FROM op_general")) == ["1", "2", "4", "7"]
    assert q("SELECT amount, pay_date::VARCHAR FROM op_general WHERE record_id='1'")[0] == (1000.5, "2025-03-15")
    # Device ID normalized: '(01) 10812345000018' -> 10812345000018
    assert q("SELECT pdi_norm FROM op_products WHERE source='general' AND record_id='1'")[0][0] == "10812345000018"
    # N/A fillers are not product slots.
    assert q("SELECT count(*) FROM op_products WHERE record_id = '2'")[0][0] == 1
    assert q("SELECT count(*) FROM op_research")[0][0] == 1
    assert q("SELECT count(*) FROM op_ownership")[0][0] == 1
    # No recipient names anywhere.
    cols = {r[0] for r in q("SELECT column_name FROM information_schema.columns")}
    assert not any("first_name" in c or "last_name" in c for c in cols)
    report = (proj / "outputs" / "PhaseA2_OpenPayments_Report.txt").read_text(encoding="utf-8")
    assert "removed_from_op_general: 1" in report
    assert "CSV rows DuckDB could not read: 0" in report
    con.close()
    # Re-running is a no-op.
    assert build_gudid_index.main(["--config", str(ini)]) == 0
    assert load_open_payments.main(["--config", str(ini)]) == 0


def test_company_root_matches_lookup_core():
    from predicate_chain.lookup_core import CO_SUFFIX as A, company_root as ra
    from predicate_chain.paycommon import CO_SUFFIX as B, company_root as rb
    assert A == B
    for n in ["Nu Vasive, Incorporated", "Tornier S.A.S.", "Smith & Nephew, Inc.", "Tiny Ortho, L.L.C."]:
        assert ra(n) == rb(n)


def test_phase_b_registry_and_matching(env):
    from pipeline import index_gudid as build_gudid_index
    from pipeline import build_vendor_registry
    from pipeline import load_open_payments
    from pipeline import match_products
    proj, ini = env
    assert build_gudid_index.main(["--config", str(ini)]) == 0
    assert load_open_payments.main(["--config", str(ini)]) == 0
    assert build_vendor_registry.main(["--config", str(ini)]) == 0
    assert match_products.main(["--config", str(ini)]) == 0
    con = duckdb.connect(str(proj / "data" / "payments.duckdb"), read_only=True)
    q = lambda s: con.execute(s).fetchall()
    ents = {(r[0], r[1]): r[2] for r in q("SELECT source, entity_key, vendor_id FROM vendor_entities")}
    # payer P1, applicant and GUDID labeler of Synthetic Spine all land in one vendor
    v = ents[("payer", "P1")]
    assert ents[("applicant", "Synthetic Spine, Inc.")] == v
    assert ents[("labeler", "111111111")] == v
    # record 1 tagged a package DI of the TESTCAGE device: tier 1, linked to both 510(k)s
    assert q("SELECT tier, ortho_product FROM op_product_match WHERE record_id = '1'")[0] == (1, True)
    assert sorted(r[0] for r in q("SELECT knumber FROM op_product_k WHERE record_id = '1'")) == ["K111111", "K222222"]
    # research slot r1 used the primary DI directly
    assert q("SELECT tier FROM op_product_match WHERE record_id = 'r1'")[0][0] == 1
    assert (proj / "reviews" / "Vendor_Registry_REVIEW.xlsx").exists()
    assert (proj / "outputs" / "Product_Match_Sample.xlsx").exists()
    con.close()
    # answers typed in the review workbook survive a re-run and are applied
    from openpyxl import load_workbook
    wb = load_workbook(proj / "reviews" / "Vendor_Registry_REVIEW.xlsx")
    ws = wb["Vendors"]
    hdr = [c.value for c in ws[2]]
    for row in ws.iter_rows(min_row=3):
        if row[0].value == v:
            row[hdr.index("Correct vendor name")].value = "Synthetic Spine (reviewed)"
            row[hdr.index("OK? (Y/N)")].value = "Y"
    wb.save(proj / "reviews" / "Vendor_Registry_REVIEW.xlsx")
    assert build_vendor_registry.main(["--config", str(ini)]) == 0
    con = duckdb.connect(str(proj / "data" / "payments.duckdb"), read_only=True)
    assert con.execute("SELECT display_name, reviewed FROM vendors WHERE vendor_id = ?", [v]).fetchone() == \
        ("Synthetic Spine (reviewed)", True)
    con.close()


def test_phase_c_aggregates(env):
    from pipeline import build_payment_aggregates, build_vendor_registry, load_open_payments, match_products
    from pipeline import index_gudid as build_gudid_index
    proj, ini = env
    for m in (build_gudid_index, load_open_payments, build_vendor_registry, match_products, build_payment_aggregates):
        assert m.main(["--config", str(ini)]) == 0
    con = duckdb.connect(str(proj / "data" / "payments.duckdb"), read_only=True)
    q = lambda s: con.execute(s).fetchall()
    # Knee Works has no 510(k) in the database, so it is not a listed vendor; the pharma payer is not a vendor.
    assert sorted(r[0] for r in q("SELECT record_id FROM pay_fact")) == ["1", "7"]
    v = q("SELECT vendor_id FROM vendor_entities WHERE source = 'payer' AND entity_key = 'P1'")[0][0]
    row = q(f"SELECT total, recipients, royalty_r FROM agg_vendor_profile WHERE mode = 'pit' AND vendor_id = '{v}' AND year = 0")[0]
    assert row == (1000.5, 1, 1)
    assert q("SELECT knumber, tier, amount FROM agg_product ORDER BY 1") == [("K111111", 1, 1000.5), ("K222222", 1, 1000.5)]
    # no NPI in any aggregate table
    for t in ("pay_fact", "agg_relationship", "agg_vendor_profile"):
        cols = {r[0] for r in q(f"SELECT column_name FROM information_schema.columns WHERE table_name = '{t}'")}
        assert "npi" not in cols
    con.close()
    from pipeline import export_payments, validate_payments
    assert validate_payments.main(["--config", str(ini)]) == 0
    assert export_payments.main(["--config", str(ini)]) == 0
    out = proj / "outputs" / "site_data"
    text = "".join(p.read_text(encoding="utf-8") for p in out.glob("pc_*.csv"))
    assert "1000000001" not in text and "SHOULD_NOT_LOAD" not in text  # no NPIs or names exported
    assert "K111111" in (out / "pc_portfolio_510k.csv").read_text(encoding="utf-8")
