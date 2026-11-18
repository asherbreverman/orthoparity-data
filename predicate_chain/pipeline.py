"""EXTRACTION LAYER: process one number (download once, extract once, store with provenance)."""
from __future__ import annotations

import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import PARSER_VERSION
from .config import Config
from .fetch import FdaClient, choose_summary_link, sha256_file, summary_links, utcnow
from .identity import IdentityResolver, NOT_FOUND_NAME
from .numbers import number_kind
from .parser import ParseResult, parse_predicates
from .pdftext import extract_text, tesseract_available

# ---- stop reasons (exactly one per stopped node) --------------------------------
SR_DEN = "De Novo (DEN)"
SR_PMA = "PMA (P number)"
SR_NO_NUMBER = "Predicate has no FDA number"
SR_STATEMENT = "Statement only, no predicate data"
SR_NO_PDF = "No Summary PDF available"
SR_NO_PDF_PRE1991 = "No summary on file (pre-1991)"
SR_NO_PDF_1991_1995 = "No summary on file (1991-1995)"
SR_NEEDS_OCR = "Needs OCR"
SR_UNREADABLE = "Unreadable PDF after OCR"
SR_NOT_FOUND = "K-number not found in any FDA source"
SR_TRUNCATED = "TRUNCATED (generation limit reached with more predicates available)"
SR_NO_PREDICATE = "Summary parsed, no predicate found"
SR_WRONG_FILE = "Wrong file (PDF is for another number)"

ALL_STOP_REASONS = [SR_DEN, SR_PMA, SR_NO_NUMBER, SR_STATEMENT, SR_NO_PDF, SR_NO_PDF_PRE1991, SR_NO_PDF_1991_1995,
                    SR_NEEDS_OCR,
                    SR_UNREADABLE, SR_NOT_FOUND, SR_TRUNCATED, SR_NO_PREDICATE, SR_WRONG_FILE]


def stop_reason_for_kind(number: str) -> str | None:
    k = number_kind(number)
    if k == "DEN":
        return SR_DEN
    if k == "P":
        return SR_PMA
    return None


@dataclass
class NodeResult:
    knumber: str
    status: str                       # continues | stopped | error
    stop_reason: str | None = None
    stop_detail: str | None = None
    predicates: list[str] = field(default_factory=list)
    downloaded: bool = False
    bytes: int = 0
    download_seconds: float = 0.0
    text_method: str | None = None
    parse_status: str | None = None


class Extractor:
    def __init__(self, con: sqlite3.Connection, cfg: Config, client: FdaClient | None, log, offline: bool = False):
        self.con, self.cfg, self.client, self.log = con, cfg, client, log
        self.offline = offline or client is None
        self.identity = IdentityResolver(con, None if self.offline else client,
                                         cfg.getbool("network", "USE_OPENFDA", True), log)
        self.use_ocr = cfg.getbool("ocr", "USE_OCR", True)
        self.tess_path = cfg.get("ocr", "TESSERACT_PATH")
        self.ocr_ok = self.use_ocr and tesseract_available(self.tess_path)
        self.pre1991_rule = cfg.get("settings", "PRE1991_BLANK_RULE") or "try"
        self.early1990s_rule = cfg.get("settings", "EARLY1990S_RULE") or "try"
        self.review_rule = (cfg.get("settings", "REVIEW_RULE") or "C").strip()
        self.strategy = cfg.get("network", "PDF_URL_STRATEGY") or "detail_first"
        self.starting = {r[0] for r in con.execute("SELECT knumber FROM clearances")}
        manifest = cfg.cache_dir / "_copied_from_previous_run.csv"
        self.copied = set()
        if manifest.exists():
            self.copied = {l.split(",")[0] for l in manifest.read_text(encoding="utf-8").splitlines()[1:] if l}

    # ------------------------------------------------------------------ helpers
    def record(self, knumber: str) -> tuple[dict | None, str]:
        r = self.con.execute("SELECT stateorsumm, decision_year, applicant, devicename FROM clearances WHERE knumber=?",
                             (knumber,)).fetchone()
        if r:
            return dict(r), "starting set"
        r = self.con.execute("SELECT stateorsumm, decision_year, applicant, devicename FROM fda_master WHERE knumber=?",
                             (knumber,)).fetchone()
        if r:
            return dict(r), "FDA master"
        return None, "none"

    def _write_status(self, knumber, rec, status, reason, detail, distance, discovered_from):
        prev = self.con.execute("SELECT distance FROM node_status WHERE knumber=? AND parser_version=?",
                                (knumber, PARSER_VERSION)).fetchone()
        if prev and prev[0] is not None and distance is not None:
            distance = min(prev[0], distance)
        self.con.execute(
            "INSERT OR REPLACE INTO node_status (knumber, parser_version, in_starting_set, stateorsumm, decision_year, "
            "status, stop_reason, stop_detail, distance, discovered_from, updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (knumber, PARSER_VERSION, int(knumber in self.starting), (rec or {}).get("stateorsumm"),
             (rec or {}).get("decision_year"), status, reason, detail, distance, discovered_from, utcnow()))
        if reason:
            self.log.log("stop", knumber, depth=distance, result=reason, reason=detail)

    def _clear_previous(self, knumber):
        """Remove this parser version's earlier rows for a re-run of the same number (older versions are kept)."""
        for t, col in (("edges", "child_knumber"), ("flags", "knumber"), ("review_queue", "knumber")):
            self.con.execute(f"DELETE FROM {t} WHERE {col}=? AND parser_version=?", (knumber, PARSER_VERSION))

    def _doc_row(self, knumber, **kw):
        cols = ["knumber", "parser_version"] + list(kw)
        self.con.execute(
            f"INSERT OR REPLACE INTO documents ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [knumber, PARSER_VERSION] + list(kw.values()))

    def _previous_fetch(self, knumber) -> dict | None:
        r = self.con.execute(
            "SELECT * FROM documents WHERE knumber=? AND fetch_outcome IS NOT NULL AND fetch_outcome != 'skipped' "
            "ORDER BY (url IS NOT NULL) DESC, parsed_at_utc DESC LIMIT 1",
            (knumber,)).fetchone()
        return dict(r) if r else None

    # ------------------------------------------------------------------ fetch
    def get_pdf(self, knumber: str, distance) -> dict:
        """Find the Summary PDF: cache first, then detail-page link / URL pattern. Returns provenance dict."""
        cache = self.cfg.cache_dir / f"{knumber}.pdf"
        prev = self._previous_fetch(knumber)
        info = {"fetch_outcome": None, "url": None, "url_source": "none", "detail_page_url": None,
                "detail_page_status": None, "detail_page_link": None, "detail_page_label": None, "http_status": None,
                "sha256": None, "bytes": None, "retrieved_at_utc": None, "download_seconds": None,
                "file_source": None, "cache_path": None}
        if cache.exists() and cache.stat().st_size > 0:
            info.update(cache_path=str(cache.relative_to(self.cfg.project_dir)) if cache.is_relative_to(self.cfg.project_dir) else str(cache),
                        sha256=sha256_file(cache), bytes=cache.stat().st_size)
            if prev:
                for k in ("url", "url_source", "detail_page_url", "detail_page_status", "detail_page_link",
                          "detail_page_label", "http_status", "retrieved_at_utc", "download_seconds", "file_source"):
                    info[k] = prev.get(k)
                if prev.get("sha256") and prev["sha256"] != info["sha256"]:
                    info["file_source"] = (info["file_source"] or "") + " (hash changed since last record)"
            info["fetch_outcome"] = "cache hit"
            if not info["file_source"]:
                info["file_source"] = "copied from previous run" if knumber in self.copied else "downloaded"
                if knumber in self.copied:
                    info["fetch_outcome"] = "copied from previous run"
            self.log.log("cache hit", knumber, depth=distance, url=info["url"], result="ok", reason=info["sha256"][:16])
            return info
        if self.offline:
            if prev:
                for k in info:
                    if k in prev:
                        info[k] = prev[k]
            info["fetch_outcome"] = (prev or {}).get("fetch_outcome") or "not attempted (offline)"
            if info["fetch_outcome"] in ("downloaded", "cache hit", "copied from previous run"):
                info["fetch_outcome"] = "cache missing (offline)"
            return info

        # detail page
        tried = []
        detail_link = None

        def try_detail():
            nonlocal detail_link
            res, page = self.client.detail_page(knumber)
            info["detail_page_url"] = res.url if res else None
            info["detail_page_status"] = res.status if res else None
            if res is not None and res.status not in (200, 400, 404, 410):  # 400 = FDA cannot serve this record
                info["detail_error"] = res.error or f"HTTP {res.status}"
            if page:
                links = summary_links(page, knumber, res.url)
                link, label = choose_summary_link(links, knumber)
                info["detail_page_link"], info["detail_page_label"] = link, label
                detail_link = link
            return detail_link

        def try_url(url, source):
            if url in tried:
                return False
            tried.append(url)
            res = self.client.download_pdf(url, cache)
            ok = res.status == 200 and cache.exists()
            self.log.log("download", knumber, depth=distance, url=url, http_status=res.status,
                         result="ok" if ok else ("error" if res.error and res.status is None else "miss"),
                         reason=res.error or source, seconds=round(res.seconds, 2))
            info["http_status"] = res.status
            if ok:
                info.update(url=url, url_source=source, retrieved_at_utc=res.retrieved_at,
                            download_seconds=round(res.seconds, 2), file_source="downloaded",
                            fetch_outcome="downloaded", sha256=sha256_file(cache), bytes=cache.stat().st_size,
                            cache_path=str(cache.relative_to(self.cfg.project_dir)))
                return True
            if res.status not in (400, 404, 410, 204):
                # 403, 5xx after retries, timeouts: treat as a transient error, never as "no PDF"
                info["fetch_outcome"] = "error"
                info["error"] = res.error or f"HTTP {res.status}"
            return False

        if self.strategy == "pattern_first":
            for u in self.client.pattern_urls(knumber):
                if try_url(u, "URL pattern"):
                    return info
            if try_detail() and try_url(detail_link, "detail page link"):
                return info
        else:
            if try_detail() and try_url(detail_link, "detail page link"):
                info["pattern_would_match"] = detail_link in self.client.pattern_urls(knumber)
                return info
            for u in self.client.pattern_urls(knumber):
                if try_url(u, "URL pattern"):
                    return info
        if info["fetch_outcome"] != "error" and info.get("detail_error") and not info.get("detail_page_link"):
            # The detail page could not be read and no pattern URL worked: we cannot tell "no PDF" apart.
            info["fetch_outcome"], info["error"] = "error", "detail page: " + info["detail_error"]
        if info["fetch_outcome"] != "error":
            info["fetch_outcome"] = "not found"
        info["retrieved_at_utc"] = utcnow()
        return info

    # ------------------------------------------------------------------ main
    def process(self, knumber: str, distance: int | None = 0, discovered_from: str | None = None) -> NodeResult:
        knumber = knumber.upper()
        self._clear_previous(knumber)
        rec, rec_source = self.record(knumber)

        reason = stop_reason_for_kind(knumber)
        if reason:
            self._write_status(knumber, rec, "stopped", reason, None, distance, discovered_from)
            self._doc_row(knumber, fetch_outcome="skipped", parse_status="NOT PARSED", parse_notes=reason,
                          parsed_at_utc=utcnow())
            self.con.commit()
            return NodeResult(knumber, "stopped", reason)

        if rec is None:
            if self.offline and self.con.execute("SELECT 1 FROM external_lookups WHERE number=?",
                                                 (knumber,)).fetchone() is None:
                self.con.rollback()
                return NodeResult(knumber, "error", None, "needs an online run (identity lookup)")
            ident = self.identity(knumber)
            if not ident.get("found"):
                self._write_status(knumber, None, "stopped", SR_NOT_FOUND,
                                   f"lookup: {ident.get('source')}", distance, discovered_from)
                self._doc_row(knumber, fetch_outcome="skipped", parse_status="NOT PARSED", parse_notes=SR_NOT_FOUND,
                              parsed_at_utc=utcnow())
                self.con.commit()
                return NodeResult(knumber, "stopped", SR_NOT_FOUND)
            rec = {"stateorsumm": None, "decision_year": int(str(ident.get("decision_date") or "0")[:4] or 0) or None}
            rec_source = ident.get("source")

        sos = rec.get("stateorsumm")
        year = rec.get("decision_year") or 0
        if sos == "Statement":
            self._write_status(knumber, rec, "stopped", SR_STATEMENT, f"STATEORSUMM=Statement ({rec_source})",
                               distance, discovered_from)
            self._doc_row(knumber, fetch_outcome="skipped", parse_status="NOT PARSED", parse_notes=SR_STATEMENT,
                          parsed_at_utc=utcnow())
            self.con.commit()
            return NodeResult(knumber, "stopped", SR_STATEMENT)
        status_note = None
        if 1991 <= year <= 1995 and self.early1990s_rule == "stop":
            detail = f"decided {year}; STATEORSUMM {sos or 'blank'}; pilot found no summaries online for 1991-1995"
            self._write_status(knumber, rec, "stopped", SR_NO_PDF_1991_1995, detail, distance, discovered_from)
            self._doc_row(knumber, fetch_outcome="skipped", parse_status="NOT PARSED", parse_notes=SR_NO_PDF_1991_1995,
                          parsed_at_utc=utcnow())
            self.con.commit()
            return NodeResult(knumber, "stopped", SR_NO_PDF_1991_1995)
        if not sos:
            status_note = "summary status unknown (STATEORSUMM blank)"
            if year and year <= 1990 and self.pre1991_rule == "stop":
                self._write_status(knumber, rec, "stopped", SR_NO_PDF_PRE1991, status_note, distance, discovered_from)
                self._doc_row(knumber, fetch_outcome="skipped", parse_status="NOT PARSED",
                              parse_notes=SR_NO_PDF_PRE1991, parsed_at_utc=utcnow())
                self.con.commit()
                return NodeResult(knumber, "stopped", SR_NO_PDF_PRE1991)

        info = self.get_pdf(knumber, distance)
        if self.offline and not info.get("cache_path") and info.get("fetch_outcome") in (
                "not attempted (offline)", "cache missing (offline)"):
            self.con.rollback()
            return NodeResult(knumber, "error", None, "needs an online run (PDF not in cache)")
        if info.get("fetch_outcome") == "error":
            # transient: do not record a stop, so the next run retries
            self.log.log("download", knumber, depth=distance, result="error", reason=info.get("error"))
            self.con.rollback()
            return NodeResult(knumber, "error", None, info.get("error"))
        doc_common = {k: info.get(k) for k in ("fetch_outcome", "url", "url_source", "detail_page_url",
                                                "detail_page_status", "detail_page_link", "detail_page_label",
                                                "http_status", "sha256", "bytes", "retrieved_at_utc",
                                                "download_seconds", "file_source", "cache_path")}
        notes = [n for n in [status_note] if n]
        if info.get("pattern_would_match") is False:
            notes.append("detail-page link differs from URL pattern")

        if not info.get("cache_path"):
            label = (info.get("detail_page_label") or "").lower()
            if "statement" in label:
                reason = SR_STATEMENT
            elif not sos and year and year <= 1990:
                reason = SR_NO_PDF  # proposed SR_NO_PDF_PRE1991 once approved
            else:
                reason = SR_NO_PDF
            detail = "; ".join(notes + [f"fetch: {info.get('fetch_outcome')}"])
            self._write_status(knumber, rec, "stopped", reason, detail, distance, discovered_from)
            self._doc_row(knumber, **doc_common, parse_status="NOT PARSED", parse_notes=detail, parsed_at_utc=utcnow())
            self.con.commit()
            return NodeResult(knumber, "stopped", reason, detail)

        pdf_path = self.cfg.project_dir / info["cache_path"]
        ocr_kw = dict(use_ocr=self.use_ocr, tesseract_path=self.tess_path,
                      dpi=self.cfg.getint("ocr", "OCR_DPI", 200),
                      max_ocr_pages=self.cfg.getint("ocr", "OCR_MAX_PAGES", 15),
                      ocr_cache_dir=self.cfg.path("OCR_CACHE_DIR") if self.cfg.get("paths", "OCR_CACHE_DIR") else None,
                      sha256=info.get("sha256"))
        txt = extract_text(pdf_path, psm=self.cfg.getint("ocr", "OCR_PSM", 4), **ocr_kw)
        if txt.ocr_pages:
            self.log.log("ocr", knumber, depth=distance, result="ok", reason=f"pages {txt.ocr_pages}")
        base_doc = dict(doc_common, page_count=txt.page_count, text_method=txt.method, text_chars=txt.chars)

        if txt.method in ("needs OCR", "unreadable"):
            reason = SR_NEEDS_OCR if txt.method == "needs OCR" else SR_UNREADABLE
            detail = "; ".join(notes + [txt.error or f"{len(txt.empty_pages)} of {txt.page_count} pages without text"])
            self._write_status(knumber, rec, "stopped", reason, detail, distance, discovered_from)
            self._doc_row(knumber, **base_doc, parse_status="NOT PARSED", parse_notes=detail, parsed_at_utc=utcnow())
            self.log.log("parse", knumber, depth=distance, result=reason, reason=detail)
            self.con.commit()
            return NodeResult(knumber, "stopped", reason, detail, downloaded=info["fetch_outcome"] == "downloaded",
                              bytes=info.get("bytes") or 0, download_seconds=info.get("download_seconds") or 0,
                              text_method=txt.method)

        machine = set(txt.ocr_pages or []) | set(getattr(txt, "decoded_pages", None) or [])
        pr: ParseResult = parse_predicates(txt.pages, knumber, self.identity, self.review_rule, machine)
        if (txt.ocr_pages and not any(e.predicate_number for e in pr.edges)
                and any(sec.tier == 1 for sec in pr.sections)):
            # A predicate heading was read but no number: a table row may have been skipped by this OCR
            # layout mode. One retry in mode 6 (uniform block of text).
            txt2 = extract_text(pdf_path, psm=6, **ocr_kw)
            machine2 = set(txt2.ocr_pages or []) | set(getattr(txt2, "decoded_pages", None) or [])
            pr2 = parse_predicates(txt2.pages, knumber, self.identity, self.review_rule, machine2)
            self.log.log("ocr", knumber, depth=distance, result="retry", reason=f"psm 6: {len(pr2.edges)} edges")
            if any(e.predicate_number for e in pr2.edges):
                txt, pr = txt2, pr2
        self.log.log("parse", knumber, depth=distance, result=pr.parse_status,
                     reason=f"{len(pr.edges)} edges, tier {pr.used_tier}, method {txt.method}")
        if pr.notes:
            notes += pr.notes
        if txt.empty_pages and not txt.ocr_pages:
            notes.append(f"{len(txt.empty_pages)} page(s) without text layer and no OCR")
        if getattr(txt, "decoded_pages", None):
            notes.append(f"page(s) {txt.decoded_pages} repaired from a broken font encoding")
        if getattr(txt, "garbled_pages", None):
            notes.append(f"page(s) {txt.garbled_pages} had an unreadable text layer"
                         + (" and were OCR'd" if txt.ocr_pages else ""))

        now = utcnow()
        edge_ids = []
        for e in pr.edges:
            ident = e.identity or {}
            cur = self.con.execute(
                "INSERT INTO edges (child_knumber, parser_version, predicate_number, predicate_base, predicate_kind, "
                "list_order, role, role_basis, printed_label, family_of, printed_name, printed_company, fda_applicant, "
                "fda_device_name, fda_decision_date, fda_product_code, fda_review_panel, identity_source, "
                "identity_retrieved_at_utc, name_match_score, company_match, in_predicate_section, section_heading, "
                "confidence, page, evidence, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (knumber, PARSER_VERSION, e.predicate_number, e.predicate_base, e.predicate_kind, e.list_order, e.role,
                 e.role_basis, e.printed_label, e.family_of, e.printed_name, e.printed_company,
                 (ident.get("applicant") or NOT_FOUND_NAME) if e.predicate_number else None,
                 ident.get("device_name") or ("NOT FOUND" if e.predicate_number else None),
                 ident.get("decision_date"), ident.get("product_code"), ident.get("review_panel"),
                 ident.get("source") if e.predicate_number else "no FDA number", ident.get("retrieved_at"),
                 e.name_match_score, e.company_match, e.in_predicate_section, e.section_heading, e.confidence,
                 e.page, e.evidence[:300], now))
            edge_ids.append(cur.lastrowid)
            if e.confidence == "LOW":
                self.con.execute("INSERT INTO review_queue (knumber, parser_version, item_type, ref_id, reason, created_at_utc) "
                                 "VALUES (?,?,?,?,?,?)", (knumber, PARSER_VERSION, "edge", cur.lastrowid,
                                                          "LOW confidence edge", now))
        for f in pr.flags:
            cur = self.con.execute(
                "INSERT INTO flags (knumber, parser_version, flag_type, number, detail, page, evidence, created_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?)", (knumber, PARSER_VERSION, f.flag_type, f.number, f.detail, f.page,
                                             (f.evidence or "")[:300], now))
            self.log.log("flag", knumber, depth=distance, result=f.flag_type, reason=f"{f.number}: {f.detail}")
            if f.flag_type in ("wrong file", "probable misread number"):
                self.con.execute("INSERT INTO review_queue (knumber, parser_version, item_type, ref_id, reason, created_at_utc) "
                                 "VALUES (?,?,?,?,?,?)", (knumber, PARSER_VERSION, "flag", cur.lastrowid, f.flag_type, now))
        self.log.log("cross-check", knumber, depth=distance, result=pr.parse_status,
                     reason=f"{len(pr.flags)} flags")

        numbered = [e.predicate_number for e in pr.edges if e.predicate_number]
        wrong = any(f.flag_type == "wrong file" for f in pr.flags)
        if pr.is_statement and not pr.edges:
            status, reason, detail = "stopped", SR_STATEMENT, "PDF is a 510(k) Statement"
        elif wrong:
            status, reason, detail = "stopped", SR_WRONG_FILE, f"PDF number {pr.pdf_own_knumber}"
        elif numbered:
            status, reason, detail = "continues", None, None
        elif pr.edges:
            status, reason, detail = "stopped", SR_NO_NUMBER, pr.edges[0].evidence[:200]
        elif txt.empty_pages and not txt.ocr_pages:
            status, reason, detail = "stopped", SR_NEEDS_OCR, "text layer has no predicate section; image pages need OCR"
        else:
            status, reason, detail = "stopped", SR_NO_PREDICATE, "no predicate number or predicate section found"
        if notes:
            detail = "; ".join([d for d in [detail] if d] + notes)

        parse_status = pr.parse_status
        if reason in (SR_NEEDS_OCR,):
            parse_status = "NOT PARSED"
        self._doc_row(knumber, **base_doc, pdf_own_knumber=pr.pdf_own_knumber, predicate_sections=pr.predicate_sections,
                      parse_status=parse_status, parse_notes="; ".join(notes) or None, parsed_at_utc=now)
        if parse_status == "AMBIGUOUS":
            self.con.execute("INSERT INTO review_queue (knumber, parser_version, item_type, ref_id, reason, created_at_utc) "
                             "VALUES (?,?,?,?,?,?)", (knumber, PARSER_VERSION, "document", None,
                                                      "AMBIGUOUS document", now))
        self._write_status(knumber, rec, status, reason, detail, distance, discovered_from)
        self.con.commit()
        return NodeResult(knumber, status, reason, detail, numbered,
                          downloaded=info["fetch_outcome"] == "downloaded", bytes=info.get("bytes") or 0,
                          download_seconds=info.get("download_seconds") or 0, text_method=txt.method,
                          parse_status=parse_status)


def copy_previous_cache(cfg: Config, log=None) -> int:
    """Copy PDFs from the old project's cache (never modifying it). Returns the number copied."""
    old = cfg.path("OLD_PROJECT_DIR") / "cache" / "pdfs"
    if not old.exists():
        return 0
    n = 0
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = cfg.cache_dir / "_copied_from_previous_run.csv"
    new_file = not manifest.exists()
    with open(manifest, "a", encoding="utf-8") as fh:
        if new_file:
            fh.write("knumber,sha256,copied_at_utc,source_path\n")
        for src in sorted(old.glob("*.[pP][dD][fF]")):
            dest = cfg.cache_dir / (src.stem.upper() + ".pdf")
            if dest.exists():
                continue
            shutil.copy2(src, dest)
            digest = sha256_file(dest)
            fh.write(f"{dest.stem},{digest},{utcnow()},{src}\n")
            n += 1
            if log:
                log.log("copy", dest.stem, result="copied from previous run", reason=digest)
    return n
