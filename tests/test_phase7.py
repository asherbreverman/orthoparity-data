"""Phase 7: TEAM loader (load_team) and registered trials (fetch_trials), on synthetic files only."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from pipeline import fetch_trials, load_team

ROOT = Path(__file__).resolve().parent.parent
openpyxl = pytest.importorskip("openpyxl")

REGIONS = [("CENS_DIV_%d" % i, "Region %d (AZ, CO)" % i if i == 8 else "Region %d (XX)" % i) for i in range(1, 10)]


def price_book(path: Path, drgs: dict[str, str], py: int, dup: bool = False) -> None:
    wb = openpyxl.Workbook()
    wb.active.title = "Overview"
    ws = wb.create_sheet("Prelim_TP_DRG_Reg")
    ws.append(["Preliminary Target Price and Target Price Components"])
    ws.append(["Initial Sort Order", "Episode Category", "MS-DRG/HCPCS Episode Type", "Region", "Region Description",
               "Benchmark Price", "Prospective Trend Factor", "CMS Discount Factor", "Preliminary Target Price"])
    ws.append(["Initial Sort Order", "Episode Category", "Trigger MS-DRG code.", "Census Division", "desc", "b", "t", "d", "p"])
    ws.append(["Filter"] * 9)
    n = 0
    for drg, cat in drgs.items():
        for code, name in REGIONS:
            n += 1
            ws.append([n, cat, drg, code, name, 20000.0 + n, 1.03, 0.02, 20000.0 + n])
            if dup and n == 1:
                ws.append([n + 100, cat, drg, code, name, 20000.0 + n, 1.03, 0.02, 20000.0 + n])
    wb.save(path)


def participants(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Acute care hospitals, as of August 18, 2026, identified by CMS Certification Number (CCN) ..."])
    ws.append(["Mandatory or Voluntary Participant", "Hospital CCN", "Hospital Name", "CBSA", "CBSA Name", "CBSA State",
               "Participation Start Date", "Participation End Date", "Newly Identified TEAM Participant Relative to Previous List"])
    ws.append(["Mandatory", "30006", "TEST HOSPITAL", "46060", "Tucson, AZ", "AZ", "01/01/2026", "12/31/2030", "N"])
    ws.append(["Voluntary", "010039", "OTHER HOSPITAL", "26620", "Huntsville, AL", "AL", "01/01/2026", "12/31/2030", "Y"])
    wb.save(path)


@pytest.fixture
def team_root(tmp_path):
    root = tmp_path / "repo"
    (root / "reference").mkdir(parents=True)
    (root / "supabase").mkdir()
    for f in ("team_triggers.csv", "team_episode_families.csv", "procedure_families.csv"):
        shutil.copy(ROOT / "reference" / f, root / "reference" / f)
    folder = tmp_path / "CMS TEAM"
    folder.mkdir()
    with open(root / "reference" / "team_triggers.csv", encoding="utf-8") as fh:
        trig = [r for r in csv.DictReader(fh) if r["code_type"] == "MS-DRG"]
    label = {"LEJR": "MS-Lower extremity joint replacement", "SHFFT": "IP-Surgical hip/femur fracture treatment",
             "SPINE": "MS-Spinal fusion", "CABG": "IP-Coronary artery bypass graft", "BOWEL": "IP-Major bowel procedure"}
    drgs = {r["code"]: label[r["category_id"]] for r in trig}
    price_book(folder / "team-py2-prlim-target-prices.xlsx", drgs, 2)
    price_book(folder / "team-py1-prlim-target-prices.xlsx",
               {d: c for d, c in drgs.items() if d not in ("523", "524", "525")}, 1, dup=True)
    participants(folder / "team-participant-list.xlsx")
    openpyxl.Workbook().save(folder / "team-drg-mapping-specs.xlsx")
    return root, folder


def test_team_loads_and_writes_sql(team_root, tmp_path):
    root, folder = team_root
    out = load_team.load(folder, root, tmp_path / "site", tmp_path / "out")
    assert out["participants"] == 2
    sql = (root / "supabase" / "17_team_data.sql").read_text(encoding="utf-8")
    assert "insert into pc_team_participant" in sql and "'030006'" in sql  # CCN padded to 6 digits
    with open(tmp_path / "site" / "pc_team_target_price.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["py"] for r in rows} == {"1", "2"}
    assert sum(1 for r in rows if r["py"] == "1" and r["drg"] == "469" and r["region"] == "1") == 1  # repeat kept once
    assert "repeats 1 rows" in (tmp_path / "out" / "TEAM_Report.txt").read_text(encoding="utf-8")


def test_team_stops_on_a_drg_the_regulation_does_not_list(team_root, tmp_path):
    root, folder = team_root
    price_book(folder / "team-py2-prlim-target-prices.xlsx", {"469": "MS-Lower extremity joint replacement",
                                                             "999": "MS-Lower extremity joint replacement"}, 2)
    with pytest.raises(SystemExit) as e:
        load_team.load(folder, root, tmp_path / "site", tmp_path / "out")
    assert "999" in str(e.value)


def test_team_family_prices_must_be_triggers(team_root, tmp_path):
    root, folder = team_root
    p = root / "reference" / "team_episode_families.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("469|470,", "469|466,", 1), encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        load_team.load(folder, root, tmp_path / "site", tmp_path / "out")
    assert "466" in str(e.value)


def study(nct, sponsor, cls, text, mesh, title="A study"):
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": title},
        "statusModule": {"overallStatus": "COMPLETED", "startDateStruct": {"date": "2021-01"}},
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor, "class": cls}},
        "descriptionModule": {"briefSummary": text},
        "designModule": {"studyType": "INTERVENTIONAL", "enrollmentInfo": {"count": 40}},
        "armsInterventionsModule": {"interventions": [{"type": "DEVICE", "name": "Implant"}]}},
        "derivedSection": {"conditionBrowseModule": {"meshes": [{"id": m} for m in mesh]}},
        "hasResults": True}


@pytest.fixture
def trial_root(tmp_path):
    root = tmp_path / "repo"
    (root / "reference").mkdir(parents=True)
    for f in ("trial_mesh_terms.csv",):
        shutil.copy(ROOT / "reference" / f, root / "reference" / f)
    (root / "reference" / "trial_sponsors.csv").write_text(
        "sponsor_name,vendor_id,basis,reviewed\nAcme Spine Unit,acme,test,draft\n", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()

    def w(name, cols, rows):
        with open(site / f"{name}.csv", "w", encoding="utf-8", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=cols)
            wr.writeheader()
            wr.writerows(rows)
    w("pc_portfolio_510k", ["knumber"], [{"knumber": "K181947"}, {"knumber": "K111111"}])
    w("pc_vendors", ["vendor_id", "display_name", "rolls_up_to"],
      [{"vendor_id": "acme", "display_name": "Acme", "rolls_up_to": ""},
       {"vendor_id": "smallco", "display_name": "SmallCo", "rolls_up_to": "acme"},
       {"vendor_id": "bigdiv", "display_name": "BigDiv", "rolls_up_to": ""}])
    w("pc_vendor_names", ["vendor_id", "source", "raw_name", "basis"],
      [{"vendor_id": "smallco", "source": "applicant", "raw_name": "SmallCo, Inc.", "basis": ""},
       {"vendor_id": "bigdiv", "source": "applicant", "raw_name": "BigDiv Corporation", "basis": ""}])
    w("pc_op_research", ["ct_gov_id", "knumbers"], [{"ct_gov_id": "NCT00000003", "knumbers": "K111111"}])
    raw = tmp_path / "raw.jsonl"
    studies = [
        study("NCT00000001", "SmallCo Inc", "INDUSTRY", "Cleared under 510(k) K181947 and K999999.", ["D009140"]),
        study("NCT00000002", "BigDiv Corp", "INDUSTRY", "A heart study.", ["D006331"]),
        study("NCT00000003", "University", "OTHER", "No numbers here.", []),
        study("NCT00000004", "Acme Spine Unit", "INDUSTRY", "Spine.", ["D013122"]),
        study("NCT00000005", "BigDiv Corporation", "OTHER", "Knee.", ["D007718"]),
    ]
    raw.write_text("\n".join(json.dumps(s) for s in studies) + "\n", encoding="utf-8")
    return root, site, raw


def read(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_trials_exact_links_only(trial_root, tmp_path):
    root, site, raw = trial_root
    fetch_trials.build(raw, root, site, tmp_path / "out")
    dev = read(site / "pc_trial_device.csv")
    assert {(d["nct"], d["number"]) for d in dev} == {("NCT00000001", "K181947"), ("NCT00000003", "K111111")}
    assert "K999999" not in {d["number"] for d in dev}  # numbers OrthoParity doesn't have are ignored


def test_trials_company_links(trial_root, tmp_path):
    root, site, raw = trial_root
    fetch_trials.build(raw, root, site, tmp_path / "out")
    ven = {(v["nct"], v["vendor_id"], v["owner_id"]) for v in read(site / "pc_trial_vendor.csv")}
    assert ("NCT00000001", "smallco", "acme") in ven          # legal suffix ignored, rolls up to the parent
    assert ("NCT00000004", "acme", "acme") in ven             # reviewed alias
    assert not any(n == "NCT00000002" for n, _, _ in ven)     # not musculoskeletal: left out
    assert not any(n == "NCT00000005" for n, _, _ in ven)     # not an industry sponsor: no automatic match
    trials = {t["nct"] for t in read(site / "pc_trial.csv")}
    assert trials == {"NCT00000001", "NCT00000003", "NCT00000004"}


def test_norm_strips_legal_suffixes():
    assert fetch_trials.norm("Smith & Nephew, Inc.") == fetch_trials.norm("Smith and Nephew")
    assert fetch_trials.norm("Medacta International SA") == "medacta"


def test_person_sponsors_are_never_stored():
    assert fetch_trials.public_sponsor("Prof. Dr Jane Example", "OTHER") == "Individual investigator (name not shown)"
    assert fetch_trials.public_sponsor("Jane Example", "INDIV") == "Individual investigator (name not shown)"
    assert fetch_trials.public_sponsor("Jane Example", "OTHER") == "Individual investigator (name not shown)"
    assert fetch_trials.public_sponsor("Hartford Hospital", "OTHER") == "Hartford Hospital"
    assert fetch_trials.public_sponsor("Zimmer Biomet", "INDUSTRY") == "Zimmer Biomet"
