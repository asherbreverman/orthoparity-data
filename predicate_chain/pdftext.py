"""PDF text extraction: text layer first, Tesseract OCR for image-only pages when available."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .textclean import strip_control_chars

MIN_PAGE_CHARS = 40  # fewer printable characters than this = page has no usable text layer


@dataclass
class PdfText:
    pages: list[str] = field(default_factory=list)   # index 0 = page 1
    page_count: int = 0
    method: str = "none"          # text layer | OCR | needs OCR | unreadable
    ocr_pages: list[int] = field(default_factory=list)
    empty_pages: list[int] = field(default_factory=list)  # pages still without text
    error: str | None = None
    psm: int | None = None
    decoded_pages: list[int] = field(default_factory=list)   # broken-font pages repaired by un-shifting
    garbled_pages: list[int] = field(default_factory=list)   # unreadable text layer, sent to OCR

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    @property
    def chars(self) -> int:
        return sum(len(p.strip()) for p in self.pages)


_TESS_CHECKED: dict = {}


def tesseract_available(tesseract_path: str = "") -> bool:
    key = tesseract_path or "auto"
    if key in _TESS_CHECKED:
        return _TESS_CHECKED[key]
    ok = False
    try:
        import pytesseract
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            ok = Path(tesseract_path).exists()
        else:
            ok = shutil.which("tesseract") is not None
            if not ok:
                for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                             r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
                    if Path(cand).exists():
                        pytesseract.pytesseract.tesseract_cmd = cand
                        ok = True
                        break
        if ok:
            pytesseract.get_tesseract_version()
    except Exception:
        ok = False
    _TESS_CHECKED[key] = ok
    return ok


def _printable_len(s: str) -> int:
    return sum(1 for c in s if c.isalnum())


_COMMON = re.compile(r"(?i)\b(?:the|and|of|to|for|with|is|are|device|devices|in|on|510|fda|system|use)\b")


def readable(text: str) -> bool:
    """A page of real text has common English words, spaces and mostly letters or digits; a page from a font
    with a broken character map ("7KHUHVXOWV...", "') +* %#,+C)-") does not. Tables with few words but
    normal spacing still count as readable."""
    body = text.strip()
    if len(body) < 150 or len(_COMMON.findall(body)) >= 3:
        return True
    visible = [c for c in body if not c.isspace()]
    alnum_ratio = sum(c.isalnum() for c in visible) / max(1, len(visible))
    space_ratio = body.count(" ") / len(body)
    return alnum_ratio >= 0.6 and space_ratio >= 0.04


def _unshift(raw: str, k: int = 29) -> str:
    """Undo the common broken-font encoding where every character is stored k code points too low
    (so "The" appears as "7KH" and spaces as control character 3)."""
    out = []
    for ch in raw:
        o = ord(ch)
        if ch in "\r\n":
            out.append(ch)
        elif 3 <= o <= 93:
            out.append(chr(o + k))
        else:
            out.append(ch)
    return "".join(out)


_LOOSE = re.compile(r"(?i)the|and|device|with|for|tion")


def _clean_page(raw: str) -> tuple[str, str]:
    """Return (text, status): ok | decoded | decoded_nospace | garbled.
    decoded_nospace = the font repair worked but the PDF stores no space characters, so words run together;
    such pages are sent to OCR when Tesseract is available and the run-together text is kept otherwise."""
    norm = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = strip_control_chars(norm)
    if readable(text):
        return text, "ok"
    decoded = strip_control_chars(_unshift(norm))
    if readable(decoded):
        return decoded, "decoded"
    if len(_LOOSE.findall(decoded)) >= max(5, len(decoded) // 200):
        return decoded, "decoded_nospace"
    return "", "garbled"


def _text_layer(path: Path) -> tuple[list[str], int]:
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(path))
        pages = []
        for i in range(len(pdf)):
            page = pdf[i]
            tp = page.get_textpage()
            pages.append(tp.get_text_range() or "")
            tp.close()
            page.close()
        n = len(pdf)
        pdf.close()
        return pages, n
    except Exception:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
            return pages, len(pages)


def _ocr_pages(path: Path, page_numbers: list[int], dpi: int, psm: int = 4) -> dict[int, str]:
    import pypdfium2 as pdfium
    import pytesseract
    out = {}
    pdf = pdfium.PdfDocument(str(path))
    try:
        for pno in page_numbers:
            page = pdf[pno - 1]
            img = page.render(scale=dpi / 72).to_pil()
            out[pno] = strip_control_chars(pytesseract.image_to_string(img.convert("L"), config=f"--psm {psm}"))
            page.close()
    finally:
        pdf.close()
    return out


def extract_text(path: Path, *, use_ocr: bool = True, tesseract_path: str = "", dpi: int = 200,
                 max_ocr_pages: int = 15, psm: int = 4, ocr_cache_dir: Path | None = None,
                 sha256: str | None = None) -> PdfText:
    """psm 4 (single column, variable sizes) reads boxed eSTAR form rows that the default layout mode skips."""
    res = PdfText()
    try:
        pages, n = _text_layer(path)
    except Exception as exc:  # corrupt or encrypted PDF
        res.method = "unreadable"
        res.error = f"{type(exc).__name__}: {exc}"[:300]
        return res
    cleaned = [_clean_page(p) for p in pages]
    res.pages, res.page_count = [c[0] for c in cleaned], n
    res.decoded_pages = [i + 1 for i, c in enumerate(cleaned) if c[1] in ("decoded", "decoded_nospace")]
    res.garbled_pages = [i + 1 for i, c in enumerate(cleaned) if c[1] in ("garbled", "decoded_nospace")]
    pages = res.pages
    empty = sorted({i + 1 for i, p in enumerate(pages) if _printable_len(p) < MIN_PAGE_CHARS} | set(res.garbled_pages))
    if not empty:
        res.method = "text layer"
        return res
    todo = empty[:max_ocr_pages]
    cache_file = None
    if ocr_cache_dir is not None and sha256:
        cache_file = Path(ocr_cache_dir) / f"{path.stem}_{sha256[:16]}_psm{psm}_dpi{dpi}.json"
        if cache_file.exists():
            try:
                cached = {int(k): v for k, v in json.loads(cache_file.read_text(encoding="utf-8")).items()}
                if set(todo) <= set(cached):
                    for pno in todo:
                        res.pages[pno - 1] = cached[pno]
                    res.ocr_pages, res.psm = sorted(todo), psm
                    res.empty_pages = [p for p in empty if _printable_len(res.pages[p - 1]) < MIN_PAGE_CHARS]
                    res.method = "unreadable" if res.chars < 100 else "OCR"
                    return res
            except Exception:
                pass
    if use_ocr and tesseract_available(tesseract_path):
        try:
            ocr = _ocr_pages(path, todo, dpi, psm)
        except Exception as exc:
            res.error = f"OCR failed: {type(exc).__name__}: {exc}"[:300]
            ocr = {}
        if cache_file is not None and ocr:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(ocr), encoding="utf-8")
            except Exception:
                pass
        for pno, txt in ocr.items():
            res.pages[pno - 1] = txt
        res.ocr_pages = sorted(ocr)
        res.psm = psm
        res.empty_pages = [p for p in empty if _printable_len(res.pages[p - 1]) < MIN_PAGE_CHARS]
        if res.chars < 100:
            res.method = "unreadable"
        else:
            res.method = "OCR" if res.ocr_pages else "text layer"
        return res
    res.empty_pages = empty
    res.method = "needs OCR" if len(empty) == n or res.chars < 100 else "text layer"
    return res
