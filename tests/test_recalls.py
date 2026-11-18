"""fetch_recalls.py with a fake openFDA: synthetic fixtures only, no network."""
import csv

from pipeline import fetch_recalls


def _write(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)


def test_fetch_recalls_links_and_cleans(cfg, monkeypatch):
    lov = cfg.site_data_dir
    _write(lov / "pc_portfolio_510k.csv", ["vendor_id", "knumber", "product_code"],
           [["acme", "K000001", "AAA"], ["beta", "K000002", "BBB"]])
    _write(lov / "pc_vendor_names.csv", ["vendor_id", "source", "raw_name", "basis"],
           [["beta", "applicant", "Beta Spine, Inc.", "own name"]])
    recalls = [
        {"product_res_number": "Z-1-2024", "res_event_number": "1", "event_date_initiated": "2024-01-02",
         "recall_status": "Open, Classified", "product_code": "AAA", "k_numbers": ["K000001"],
         "recalling_firm": "Acme Corp", "product_description": "Plate", "reason_for_recall": "Mislabeled"},
        {"product_res_number": "Z-2-2013", "res_event_number": "2", "event_date_initiated": "0013-11-26",
         "recall_status": "Terminated", "product_code": "BBB", "k_numbers": [],
         "recalling_firm": "Beta Spine Inc", "product_description": "Rod", "reason_for_recall": "Burr"},
        {"product_res_number": "Z-3-2010", "res_event_number": "3", "event_date_initiated": "2010-05-05",
         "recall_status": "Terminated", "product_code": "BBB", "k_numbers": [],
         "recalling_firm": "Unknown Firm LLC", "product_description": "Screw", "reason_for_recall": "Thread"},
    ]

    def fake_get(url, params, tries=4):
        if url == fetch_recalls.RECALL_URL and "search" in params:
            return {"results": recalls if params["skip"] == 0 else [], "meta": {"results": {"total": 3}}}
        if url == fetch_recalls.ENFORCE_URL:
            return {"results": [{"recall_number": "Z-1-2024", "classification": "Class II"}]}
        return {"meta": {"last_updated": "2026-01-01"}}

    monkeypatch.setattr(fetch_recalls, "get", fake_get)
    monkeypatch.setattr(fetch_recalls, "load_config", lambda _=None: cfg)
    monkeypatch.setattr(fetch_recalls, "load_families", lambda: [])
    assert fetch_recalls.main([]) == 0
    rows = {r["recall_number"]: r for r in csv.DictReader(open(lov / "pc_recalls.csv", encoding="utf-8"))}
    assert rows["Z-1-2024"]["vendor_id"] == "acme" and rows["Z-1-2024"]["vendor_basis"] == "510(k) number"
    assert rows["Z-1-2024"]["recall_class"] == "Class II"
    assert rows["Z-2-2013"]["vendor_id"] == "beta" and rows["Z-2-2013"]["vendor_basis"] == "firm name"
    assert rows["Z-2-2013"]["initiated"] == ""            # impossible date left blank, not guessed
    assert rows["Z-2-2013"]["recall_class"] == "NOT FOUND"
    assert rows["Z-3-2010"]["vendor_id"] == ""            # no 510(k), no name match: not linked
    report = (cfg.output_dir / "Recalls_Report.txt").read_text(encoding="utf-8")
    assert "impossible date" in report and "Recalls (one row per recalled product): 3" in report
