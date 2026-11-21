"""fetch_maude.py with a fake openFDA: synthetic fixtures only, no network."""
import csv
import json

from pipeline import fetch_maude


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def fake_get(table):
    """Answer count queries from a dict keyed by (search, count)."""
    calls = []

    def get(params):
        calls.append(params)
        return {"results": table.get((params["search"], params["count"]), [])}
    get.calls = calls
    return get


def test_count_one_splits_types_years_and_window():
    q = 'pma_pmn_number:("K000001" "PK000001")'
    q5 = q + " AND date_received:[20210101 TO 20260101]"
    get = fake_get({
        (q, "event_type.exact"): [{"term": "Injury", "count": 5}, {"term": "Malfunction", "count": 2},
                                  {"term": "Death", "count": 1}, {"term": "No answer provided", "count": 1}],
        (q, "date_received"): [{"time": "20180305", "count": 4}, {"time": "20180901", "count": 1},
                               {"time": "20230102", "count": 4}],
        (q5, "event_type.exact"): [{"term": "Injury", "count": 3}, {"term": "Death", "count": 1}],
    })
    rec = fetch_maude.count_one(get, "K000001", "20210101", "20260101")
    assert rec["by_year"] == {"2018": 5, "2023": 4}
    assert fetch_maude.split_types(rec["by_type"]) == {"deaths": 1, "injuries": 5, "malfunctions": 2, "other": 1,
                                                        "reports": 9}
    assert fetch_maude.split_types(rec["by_type_last5"])["reports"] == 4


def test_count_one_skips_follow_up_queries():
    # no reports at all: one query only
    get = fake_get({})
    rec = fetch_maude.count_one(get, "K000002", "20210101", "20260101")
    assert rec["by_type"] == {} and len(get.calls) == 1
    # reports, but none in the five-year window: no window query
    q = 'pma_pmn_number:("K000003" "PK000003")'
    get = fake_get({(q, "event_type.exact"): [{"term": "Injury", "count": 2}],
                    (q, "date_received"): [{"time": "20120101", "count": 2}]})
    rec = fetch_maude.count_one(get, "K000003", "20210101", "20260101")
    assert rec["by_type_last5"] == {} and len(get.calls) == 2


def test_export_writes_only_products_with_reports(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    cache = {
        "K000001": {"knumber": "K000001", "by_type": {"Injury": 3, "Death": 1}, "by_type_last5": {"Injury": 1},
                    "by_year": {"2019": 3, "2024": 1}},
        "K000002": {"knumber": "K000002", "by_type": {}, "by_type_last5": {}, "by_year": {}},
    }
    meta = {"window_start": "2021-11-20", "data_through": "2026-11-11"}
    fetch_maude.export(cache, ["K000001", "K000002", "K000003"], site, tmp_path, meta)
    rows = list(csv.DictReader(open(site / "pc_maude_product.csv", encoding="utf-8")))
    assert len(rows) == 1
    r = rows[0]
    assert (r["knumber"], r["reports"], r["deaths"], r["injuries"], r["reports_last5"]) == ("K000001", "4", "1", "3", "1")
    assert (r["first_year"], r["last_year"], r["data_through"]) == ("2019", "2024", "2026-11-11")
    years = list(csv.DictReader(open(site / "pc_maude_year.csv", encoding="utf-8")))
    assert [(y["year"], y["reports"]) for y in years] == [("2019", "3"), ("2024", "1")]
    report = (tmp_path / "MAUDE_Report.txt").read_text(encoding="utf-8")
    assert "510(k)s not yet downloaded: 1" in report and "not proof" in report


def test_starting_set_and_key_file(tmp_path, monkeypatch):
    _write(tmp_path / "pc_devices.csv", ["knumber", "in_starting_set"],
           [["K000001", "true"], ["K000002", "false"], ["DEN000001", "true"]])
    assert fetch_maude.starting_set(tmp_path) == ["DEN000001", "K000001"]
    monkeypatch.delenv("OPENFDA_API_KEY", raising=False)
    assert fetch_maude.api_key(tmp_path) == ""
    (tmp_path / ".env.txt").write_text("OPENFDA_API_KEY=abc123\n", encoding="utf-8")
    assert fetch_maude.api_key(tmp_path) == "abc123"
    monkeypatch.setenv("OPENFDA_API_KEY", "fromenv")
    assert fetch_maude.api_key(tmp_path) == "fromenv"


def test_resume_reads_cache(tmp_path):
    p = tmp_path / "maude_counts.jsonl"
    p.write_text(json.dumps({"knumber": "K1", "by_type": {}, "by_type_last5": {}, "by_year": {}}) + "\n\n",
                 encoding="utf-8")
    assert list(fetch_maude.load_cache(p)) == ["K1"]
