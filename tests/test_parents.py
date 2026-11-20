"""Parent-company rules: divestiture splits (synthetic data) and the sourcing rule on the published reference files."""
import csv
import re
from pathlib import Path

from predicate_chain import divestitures

REF = Path(__file__).resolve().parent.parent / "reference"


def _read(name):
    return list(csv.DictReader(open(REF / name, encoding="utf-8")))


def test_divestiture_moves_only_the_sold_line():
    rules = [{"seller": "acme", "buyer": "newco", "codes": {"AAA", "BBB"}, "decided_before": ""},
             {"seller": "acme", "buyer": "spinco", "codes": {"CCC"}, "decided_before": "2015-07-01"}]
    assert divestitures.owner("acme", "AAA", "2010-01-01", rules) == "newco"
    assert divestitures.owner("acme", "aaa", "2026-01-01", rules) == "newco"      # codes match case-insensitively
    assert divestitures.owner("acme", "ZZZ", "2010-01-01", rules) == "acme"       # other lines stay
    assert divestitures.owner("acme", "CCC", "2014-12-31", rules) == "spinco"
    assert divestitures.owner("acme", "CCC", "2015-07-01", rules) == "acme"       # decided after the spin-off
    assert divestitures.owner("other", "AAA", "2010-01-01", rules) == "other"
    assert divestitures.owner(None, "AAA", "2010-01-01", rules) is None


def test_every_ownership_link_has_a_public_source():
    for r in _read("vendor_lineage.csv"):
        assert r["source_url"].startswith("http"), (r["vendor_id"], r["parent"])
    for r in _read("vendor_divestitures.csv"):
        assert r["source_url"].startswith("http") and r["product_codes"], r
    for r in _read("ownership_sources.csv"):
        if r["status"].startswith("applied"):
            assert r["source_url"], r["name_or_company"]


def test_unsourced_names_are_not_folded_into_a_parent():
    not_applied = {r["name_or_company"] for r in _read("ownership_sources.csv")
                   if r["status"].startswith("NOT APPLIED") and re.fullmatch(r"[a-z0-9]+", r["name_or_company"])}
    for f in _read("vendor_families.csv"):
        alts = set(re.findall(r"[a-z0-9]+", f["name_regex"]))
        assert not (alts & not_applied), (f["vendor_id"], alts & not_applied)
