"""End-to-end extraction from a cached PDF (synthetic, generated in the test; no real PDFs committed)."""
import pytest

from predicate_chain import PARSER_VERSION
from predicate_chain.pipeline import SR_NO_PDF, Extractor
from predicate_chain.runlog import RunLog

reportlab = pytest.importorskip("reportlab")


def _make_pdf(path, lines):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 740
    for line in lines:
        c.drawString(72, y, line)
        y -= 16
    c.showPage()
    c.save()


def test_cached_pdf_end_to_end(con, cfg):
    cfg.cache_dir.mkdir(parents=True)
    _make_pdf(cfg.cache_dir / "K999999.pdf", [
        "510(k) Summary for K999999",
        "Predicate Device:",
        "Alpha Interbody System (K111111) - Alpha Spine, Inc.",
        "Device Description:",
        "The device is a cage.",
    ])
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K999999','Summary',2020)")
    con.execute("INSERT INTO fda_master (knumber, applicant, devicename, decision_date) "
                "VALUES ('K111111','Alpha Spine, Inc.','ALPHA INTERBODY SYSTEM','2011-01-01')")
    ex = Extractor(con, cfg, None, RunLog(cfg.log_dir, "test", con), offline=True)
    r = ex.process("K999999")
    assert r.status == "continues" and r.predicates == ["K111111"]
    doc = con.execute("SELECT * FROM documents WHERE knumber='K999999'").fetchone()
    assert doc["text_method"] == "text layer" and doc["sha256"] and doc["parse_status"] == "CLEAN"
    e = con.execute("SELECT * FROM edges WHERE child_knumber='K999999'").fetchone()
    assert e["role"] == "primary" and e["confidence"] == "HIGH" and e["page"] == 1
    assert e["fda_applicant"] == "Alpha Spine, Inc." and e["identity_source"] == "FDA master"
    assert e["parser_version"] == PARSER_VERSION


def test_offline_without_cache_waits_for_online_run(con, cfg):
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K888888','Summary',2020)")
    ex = Extractor(con, cfg, None, RunLog(cfg.log_dir, "test", con), offline=True)
    r = ex.process("K888888")
    assert r.status == "error"
    assert con.execute("SELECT COUNT(*) FROM node_status WHERE knumber='K888888'").fetchone()[0] == 0


def test_offline_reuses_previous_not_found(con, cfg):
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K777777','Summary',2020)")
    con.execute("INSERT INTO documents (knumber, parser_version, fetch_outcome, parsed_at_utc) "
                "VALUES ('K777777','0.9.0','not found','2026-01-01T00:00:00Z')")
    ex = Extractor(con, cfg, None, RunLog(cfg.log_dir, "test", con), offline=True)
    assert ex.process("K777777").stop_reason == SR_NO_PDF


class FakeClient:
    """Stands in for FdaClient: detail page links to a Summary PDF; pattern URLs 404."""
    def __init__(self, cfg, pdf_lines, link=True, status=200):
        self.cfg, self.pdf_lines, self.link, self.status = cfg, pdf_lines, link, status
        self.calls = []

    def detail_page(self, k):
        from predicate_chain.fetch import HttpResult
        url = f"https://example.test/pmn.cfm?ID={k}"
        self.calls.append(("detail", k))
        if self.status != 200:
            return HttpResult(url, self.status, None, 0.1, f"HTTP {self.status}", "t"), None
        body = f'<a href="/cdrh_docs/pdf24/{k}.pdf" target="_blank">Summary</a>' if self.link else "<p>none</p>"
        return HttpResult(url, 200, None, 0.1, None, "t"), body

    def download_pdf(self, url, dest):
        from predicate_chain.fetch import HttpResult
        self.calls.append(("pdf", url))
        if "pdf24" in url and self.link and self.status == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _make_pdf(dest, self.pdf_lines)
            return HttpResult(url, 200, b"%PDF", 0.2, None, "2026-11-16T00:00:00Z")
        return HttpResult(url, self.status if self.status != 200 else 404, None, 0.1, None, "t")

    def pattern_urls(self, k):
        return [f"https://example.test/cdrh_docs/pdf24/{k}.pdf"]


def _online(con, cfg, client):
    ex = Extractor(con, cfg, None, RunLog(cfg.log_dir, "test", con), offline=False)
    ex.client, ex.offline = client, False
    return ex


def test_detail_page_link_download(con, cfg):
    cfg.raw.set("network", "PDF_URL_STRATEGY", "detail_first")
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K241111','Summary',2024)")
    fc = FakeClient(cfg, ["Predicate Device:", "Thing (K155555)", "Device Description: x"])
    r = _online(con, cfg, fc).process("K241111")
    doc = con.execute("SELECT * FROM documents WHERE knumber='K241111'").fetchone()
    assert doc["url_source"] == "detail page link" and doc["fetch_outcome"] == "downloaded"
    assert doc["detail_page_label"] == "Summary" and doc["url"].endswith("/cdrh_docs/pdf24/K241111.pdf")
    assert r.predicates == ["K155555"]


def test_no_link_and_404_means_no_pdf(con, cfg):
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K241112','Summary',2024)")
    fc = FakeClient(cfg, [], link=False)
    assert _online(con, cfg, fc).process("K241112").stop_reason == SR_NO_PDF


def test_blocked_403_is_error_not_stop(con, cfg):
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K241113','Summary',2024)")
    fc = FakeClient(cfg, [], status=403)
    r = _online(con, cfg, fc).process("K241113")
    assert r.status == "error"
    assert con.execute("SELECT COUNT(*) FROM node_status WHERE knumber='K241113'").fetchone()[0] == 0


def test_ocr_cache_is_used_without_tesseract(tmp_path):
    import json
    from predicate_chain.pdftext import extract_text
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "K123456.pdf"
    c = canvas.Canvas(str(pdf))
    c.rect(100, 100, 50, 50)  # an image-like page with no text layer
    c.showPage()
    c.save()
    cache = tmp_path / "ocr"
    cache.mkdir()
    (cache / "K123456_abcdef0123456789_psm4_dpi200.json").write_text(
        json.dumps({"1": "510(k) Summary. Predicate Device: Alpha Interbody System (K111111) by Alpha Spine. " * 2}), encoding="utf-8")
    t = extract_text(pdf, use_ocr=False, ocr_cache_dir=cache, sha256="abcdef0123456789ffff")
    assert t.method == "OCR" and "K111111" in t.pages[0]


def test_pattern_first_skips_detail_page(con, cfg):
    cfg.raw.set("network", "PDF_URL_STRATEGY", "pattern_first")
    con.execute("INSERT INTO clearances (knumber, stateorsumm, decision_year) VALUES ('K241114','Summary',2024)")
    fc = FakeClient(cfg, ["Predicate Device:", "Thing (K111111)", "Device Description: x"])
    _online(con, cfg, fc).process("K241114")
    doc = con.execute("SELECT * FROM documents WHERE knumber='K241114'").fetchone()
    assert doc["url_source"] == "URL pattern"
    assert not any(c[0] == "detail" for c in fc.calls)
