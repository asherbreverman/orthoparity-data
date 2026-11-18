"""Name keys survive restored characters, and the pre-publish check catches what it should. Synthetic data only."""
from __future__ import annotations

import base64
import json

from predicate_chain import lookup_core, paycommon
from tools import check_before_publish as chk


def test_company_root_folds_accents():
    for f in (lookup_core.company_root, paycommon.company_root):
        assert f("Medos International Sàrl") == f("Medos International Srl") == "medosinternational"
        assert f("Société Exemple S.A.") == "societeexemple"


def test_brand_ignores_trademark_signs():
    assert lookup_core.brand_token("E3D™-C Interbody") == lookup_core.brand_token("E3D-C Interbody") == "E3D-C"
    assert lookup_core.brand_token("Acme® Cage") == "ACME"
    assert lookup_core.brand_token("PIT’Stop® implant") == lookup_core.brand_token("PITStop implant") == "PITSTOP"
    assert lookup_core.brand_token("A’TOMIC™ Nitinol Fixation System") == "ATOMIC"
    assert lookup_core.brand_token("CLICK'X MONOAXIAL SCREWS") == "CLICK"  # unchanged behavior for plain apostrophes


def test_npi_check_digit():
    assert chk.npi_valid("1234567893")  # the CMS example NPI
    assert not chk.npi_valid("1234567890")


def _jwt(role: str) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc({'role': role, 'iss': 'supabase'})}.c2lnbmF0dXJlc2lnbmF0dXJl"


def test_secret_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(chk, "ROOT", tmp_path)
    (tmp_path / "ok.md").write_text(f"anon key {_jwt('anon')}", encoding="utf-8")
    problems, notes = chk.check()
    assert not problems and any("anon" in n for n in notes)
    (tmp_path / "bad.md").write_text(f"service {_jwt('service_role')}", encoding="utf-8")
    (tmp_path / "people.csv").write_text("Physician_First_Name,amount\nX,1\n", encoding="utf-8")
    (tmp_path / "ids.csv").write_text("id\n1234567893\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "recipient_salt.txt").write_text("synthetic-salt-value", encoding="utf-8")
    (tmp_path / "leak.txt").write_text("salt is synthetic-salt-value", encoding="utf-8")
    problems, _ = chk.check()
    text = "\n".join(problems)
    for expected in ("bad.md", "people.csv", "ids.csv", "leak.txt"):
        assert expected in text
