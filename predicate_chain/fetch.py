"""Polite HTTP client for FDA sites: global 1 request/second throttle, retries with backoff,
descriptive User-Agent, local caches for detail pages and PDFs."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

from .config import Config
from .numbers import pdf_folder_candidates


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class HttpResult:
    url: str
    status: int | None
    content: bytes | None
    seconds: float
    error: str | None = None
    retrieved_at: str = ""


class Throttle:
    def __init__(self, per_second: float):
        self.min_gap = 1.0 / max(per_second, 0.01)
        self.last = 0.0

    def wait(self):
        gap = time.monotonic() - self.last
        if gap < self.min_gap:
            time.sleep(self.min_gap - gap)
        self.last = time.monotonic()


class FdaClient:
    def __init__(self, cfg: Config, log=None):
        self.cfg = cfg
        self.log = log
        self.session = requests.Session()
        self.session.headers["User-Agent"] = cfg.get("network", "USER_AGENT")
        self.throttle = Throttle(float(cfg.get("network", "REQUESTS_PER_SECOND") or 1))
        self.retries = cfg.getint("network", "MAX_RETRIES", 3)
        self.backoff = float(cfg.get("network", "BACKOFF_SECONDS") or 5)
        self.timeout = float(cfg.get("network", "TIMEOUT_SECONDS") or 60)
        self.openfda_fields_checked = False
        self.requests_made = 0

    def get(self, url: str, **params) -> HttpResult:
        attempt = 0
        last_err = None
        t0 = time.monotonic()
        while attempt <= self.retries:
            self.throttle.wait()
            self.requests_made += 1
            try:
                r = self.session.get(url, params=params or None, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504):
                    last_err = f"HTTP {r.status_code}"
                    attempt += 1
                    if attempt <= self.retries:
                        time.sleep(self.backoff * (2 ** (attempt - 1)))
                        continue
                    return HttpResult(r.url, r.status_code, None, time.monotonic() - t0, last_err, utcnow())
                return HttpResult(r.url, r.status_code, r.content, time.monotonic() - t0, None, utcnow())
            except requests.RequestException as exc:
                last_err = f"{type(exc).__name__}: {exc}"[:300]
                attempt += 1
                if attempt <= self.retries:
                    time.sleep(self.backoff * (2 ** (attempt - 1)))
        return HttpResult(url, None, None, time.monotonic() - t0, last_err, utcnow())

    # ------------------------------------------------------------ detail page
    def detail_page(self, knumber: str) -> tuple[HttpResult | None, str | None]:
        """Return (result, html_text). Uses the local detail-page cache when present."""
        cache = self.cfg.detail_cache_dir / f"{knumber}.html"
        url = self.cfg.get("network", "DETAIL_PAGE_URL").format(knumber=knumber)
        if cache.exists() and cache.stat().st_size > 500:
            return HttpResult(url, 200, None, 0.0, None, "cached"), cache.read_text(encoding="utf-8", errors="replace")
        res = self.get(url)
        if self.log:
            self.log.log("lookup", knumber, url=url, http_status=res.status,
                         result="ok" if res.status == 200 else "error" if res.error else "miss",
                         reason=res.error or "detail page")
        if res.status == 200 and res.content:
            text = res.content.decode("utf-8", errors="replace")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
            return res, text
        return res, None

    # ------------------------------------------------------------ PDF
    def download_pdf(self, url: str, dest: Path) -> HttpResult:
        res = self.get(url)
        if res.status == 200 and res.content and res.content[:5].startswith(b"%PDF"):
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(res.content)
            tmp.replace(dest)
        elif res.status == 200:
            res.error = "response was not a PDF"
            res.status = 204
        return res

    def pattern_urls(self, knumber: str) -> list[str]:
        pat = self.cfg.get("network", "PDF_URL_PATTERN")
        return [pat.format(folder=f, knumber=knumber) for f in pdf_folder_candidates(knumber)]

    # ------------------------------------------------------------ openFDA
    def openfda(self, number: str) -> dict | None:
        url = self.cfg.get("network", "OPENFDA_URL")
        res = self.get(url, search=f'k_number:"{number}"', limit=1)
        out = {"url": res.url, "http_status": res.status, "retrieved_at": res.retrieved_at}
        if res.status != 200 or not res.content:
            out["found"] = False
            return out
        try:
            data = json.loads(res.content)
            rec = (data.get("results") or [None])[0]
        except Exception:
            rec = None
        if not rec:
            out["found"] = False
            return out
        if not self.openfda_fields_checked and self.log:
            expected = {"k_number", "applicant", "device_name", "decision_date", "product_code", "advisory_committee"}
            missing = sorted(expected - set(rec))
            self.log.log("lookup", number, url=res.url, http_status=res.status,
                         result="ok" if not missing else "warning",
                         reason=f"openFDA field check; missing: {missing}" if missing else "openFDA fields verified")
            self.openfda_fields_checked = True
        out.update(found=True, applicant=rec.get("applicant"), device_name=rec.get("device_name"),
                   decision_date=rec.get("decision_date"), product_code=rec.get("product_code"),
                   review_panel=rec.get("advisory_committee"))
        return out


# ---------------------------------------------------------------- HTML parsing
_LINK_RE = re.compile(r"<a\b[^>]*href\s*=\s*[\"']([^\"']*cdrh_docs[^\"']*?\.pdf)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def summary_links(page_html: str, knumber: str, base_url: str) -> list[tuple[str, str]]:
    """All cdrh_docs PDF links on a detail page as (absolute url, label)."""
    out = []
    for href, label in _LINK_RE.findall(page_html):
        lab = re.sub(r"<[^>]+>", " ", label)
        lab = re.sub(r"\s+", " ", html.unescape(lab)).strip()
        out.append((urljoin(base_url, html.unescape(href.strip())), lab))
    return out


def choose_summary_link(links: list[tuple[str, str]], knumber: str) -> tuple[str | None, str | None]:
    for url, lab in links:
        if re.search(r"summary|statement", lab, re.I) and knumber.lower() in url.lower():
            return url, lab
    for url, lab in links:
        if re.search(r"summary|statement", lab, re.I):
            return url, lab
    for url, lab in links:
        if knumber.lower() in url.lower() and "/reviews/" not in url.lower():
            return url, lab or "link"
    return None, None


def detail_page_fields(page_html: str) -> dict:
    """Pull applicant/device/decision date/product code from the FDA detail page HTML."""
    txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page_html, flags=re.S | re.I)
    txt = re.sub(r"<br\s*/?>|</t[dh]>|</tr>|</p>|</div>", "\n", txt, flags=re.I)
    txt = html.unescape(re.sub(r"<[^>]+>", " ", txt))
    lines = [re.sub(r"\s+", " ", l).strip() for l in txt.split("\n")]
    lines = [l for l in lines if l]

    def after(label: str) -> str | None:
        for i, l in enumerate(lines):
            if l.lower().startswith(label.lower()):
                rest = l[len(label):].strip(" :")
                if rest:
                    return rest
                if i + 1 < len(lines):
                    return lines[i + 1]
        return None

    out = {"applicant": after("Applicant"), "device_name": after("Device Name"),
           "decision_date": after("Decision Date"), "product_code": None, "review_panel": after("Review Advisory Committee")}
    m = re.search(r"Product Code\s*:?\s*([A-Z]{3})\b", txt)
    if m:
        out["product_code"] = m.group(1)
    if out["applicant"]:
        out["applicant"] = out["applicant"][:200]
    out["found"] = bool(out["applicant"] or out["device_name"])
    out["summary_or_statement"] = "Summary" if re.search(r">\s*Summary\s*<", page_html, re.I) else (
        "Statement" if re.search(r">\s*Statement\s*<", page_html, re.I) else None)
    return out
