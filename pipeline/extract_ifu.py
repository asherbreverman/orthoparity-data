"""Extract the Indications for Use text from each starting-set clearance's cached Summary PDF.

Usage:  python orthoparity.py extract-ifu [--limit N] [--seconds S]
Reads only cached PDFs (and the OCR cache); never downloads. Resumable: results append to outputs/ifu/ifu.jsonl and
K-numbers already there are skipped. Text is kept verbatim (whitespace collapsed), capped at about 1,500 characters.
A clearance whose PDF has no recognizable Indications for Use section is written with found = false.
"""
from __future__ import annotations

import json
import re
import sys
import time

from predicate_chain.chains import latest_versions
from predicate_chain.config import load_config
from predicate_chain.db import connect
from predicate_chain.pdftext import extract_text

MAX_CHARS = 1500
# Where the Indications for Use text starts. Order = preference.
STARTS = [
    ("FDA form", re.compile(r"Indications\s*for\s*Use\s*[({]\s*Desc\w{3,6}\s*[)}]\s*:?", re.I)),
    ("FDA form", re.compile(r"(?:^|\n)[^\n]{0,40}?Indications\s+For\s+Use\s*:", re.I)),
    ("Summary section", re.compile(r"(?:^|\n)\s*(?:[0-9IVX]+[.)]\s*|[A-H][.)]\s*)?(?:Statement\s+of\s+)?"
                                   r"(?:Indications?\s+for\s+Use|Intended\s+Use(?:\s*/\s*Indications?(?:\s+for\s+Use)?)?|"
                                   r"Indications?)\s*(?:and\s+Intended\s+Use)?\s*[:\-–]?\s*(?=\n|[A-Z])", re.I)),
]
STOP = re.compile(
    r"(?:\n\s*(?:[0-9IVX]+[.)]\s*|[A-H][.)]\s*)?(?:Type\s+of\s+Use|Prescription\s+U|Over[- ]The[- ]Counter|"
    r"\(?PLEASE\s+DO\s+NOT\s+WRITE|CONTINUE\s+ON|Concurrence\s+of\s+CDRH|Device\s+Description|Description\s+of\s+(?:the\s+)?"
    r"(?:Subject\s+)?Device|Technolog(?:ical|y)\s+(?:Characteristics|Comparison)|Substantial(?:ly)?\s+Equivalen|"
    r"Predicate\s+Device|Comparison\s+(?:to|of|with)|Performance\s+(?:Data|Testing)|Non-?\s?Clinical|Clinical\s+"
    r"(?:Data|Testing|Performance)|Summary\s+of\s+(?:Non|Clinical|Tech|Perf)|Conclusions?\b|Contraindications|"
    r"Materials?\s*:|Mechanical\s+Testing|Discussion\s+of)|This\s+section\s+applies\s+only|Signature|"
    r"Prescription\s+U[sa][ec]\b|\(Per\s+21\s+CFR\s+801|\(PLEASE\s+DO\s+NOT)", re.I)
DESCRIBE = re.compile(r"[({]\s*Desc\w{3,6}\s*[)}]\s*:?", re.I)
BOILERPLATE = re.compile(r"Please\s+(?:type|provide|describe|select)|textbox|submission\s+number|OMB\s+No|"
                         r"PRA\s+Statement|Form\s+Approved", re.I)
COMMON = re.compile(r"\b(?:the|of|and|for|in|to|with|or|is|are|use|indicated|intended)\b", re.I)


def plausible(body: str) -> bool:
    """Readable English: enough common words (rejects font-shifted gibberish and OCR fragments)."""
    return len(COMMON.findall(body)) >= 2 and not BOILERPLATE.search(body)


LETTER = re.compile(r"Dear\s+(?:Mr|Ms|Mrs|Dr)\.?|We\s+have\s+reviewed\s+your\s+Section\s+510\(k\)", re.I)


def find_ifu(pages: list[str]) -> tuple[str | None, int | None, str | None]:
    best = None
    for pno, page in enumerate(pages, 1):
        if not page or LETTER.search(page[:1500]):
            continue
        for rank, (kind, rx) in enumerate(STARTS):
            for m in rx.finditer(page):
                after = page[m.end():]
                stop = STOP.search(after)
                body = after[:stop.start()] if stop else after[:MAX_CHARS + 200]
                body = re.sub(r"\s+", " ", body).strip(" :-–")
                d = list(DESCRIBE.finditer(body))
                if d:  # the form's own "(Describe)" label sits inside the captured text: start after it
                    body = body[d[-1].end():].strip(" :-–")
                if len(body) < 30 or "stated in the enclosure" in body.lower() or not plausible(body):
                    continue
                cand = (rank, pno, kind, body)
                if best is None or cand[:2] < best[:2]:
                    best = cand
                break
    if not best:
        return None, None, None
    text = best[3]
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS]
        text = cut[:cut.rfind(". ") + 1] if ". " in cut else cut
        text += " [continues in the PDF]"
    return text, best[1], best[2]


def main() -> int:
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    seconds = float(sys.argv[sys.argv.index("--seconds") + 1]) if "--seconds" in sys.argv else None
    cfg = load_config()
    con = connect(cfg.db_path)
    out = cfg.output_dir / "ifu"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "ifu.jsonl"
    done = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["knumber"])
            except (ValueError, KeyError):
                pass
    versions = latest_versions(con)
    todo = []
    for k, v, cache, sha in con.execute(
            "SELECT d.knumber, d.parser_version, d.cache_path, d.sha256 FROM documents d JOIN clearances c ON "
            "c.knumber=d.knumber WHERE d.cache_path IS NOT NULL ORDER BY d.knumber"):
        if versions.get(k) == v and k not in done:
            todo.append((k, cache, sha))
    if limit:
        todo = todo[:limit]
    ocr_dir = cfg.path("OCR_CACHE_DIR") if cfg.get("paths", "OCR_CACHE_DIR") else None
    t0, n, found = time.time(), 0, 0
    with path.open("a", encoding="utf-8") as fh:
        for k, cache, sha in todo:
            if seconds and time.time() - t0 > seconds:
                break
            pdf = cfg.project_dir / cache.replace("\\", "/")
            rec = {"knumber": k, "found": False}
            if pdf.exists():
                txt = extract_text(pdf, use_ocr=True, tesseract_path=cfg.get("ocr", "TESSERACT_PATH"),
                                   dpi=cfg.getint("ocr", "OCR_DPI", 200), max_ocr_pages=cfg.getint("ocr", "OCR_MAX_PAGES", 15),
                                   psm=cfg.getint("ocr", "OCR_PSM", 4), ocr_cache_dir=ocr_dir, sha256=sha)
                text, page, kind = find_ifu(txt.pages)
                rec.update(found=bool(text), text=text, page=page, source=kind, text_method=txt.method)
            else:
                rec["source"] = "PDF missing from cache"
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            found += rec["found"]
    left = len(todo) - n
    print(f"Processed {n:,} ({found:,} with Indications for Use). Left: {left:,}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
