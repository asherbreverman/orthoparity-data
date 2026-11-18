"""Text cleanup helpers."""
from __future__ import annotations

import re

# C0 control characters except tab (\t), line feed (\n) and carriage return (\r), plus DEL, C1 controls,
# lone surrogates and the non-characters U+FFFE/U+FFFF. FDA release files and some PDFs contain these.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff]")


def strip_control_chars(text: str | None) -> str | None:
    """Remove stray control characters, keeping tabs and line breaks."""
    if text is None:
        return None
    return _CONTROL_RE.sub("", text)


def clean_field(value: str | None) -> str | None:
    """Strip control characters and surrounding whitespace. Empty becomes None."""
    if value is None:
        return None
    value = strip_control_chars(value).replace("\r", " ").replace("\n", " ").strip()
    return value or None


def squash_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def snippet(text: str, start: int, end: int, limit: int = 300) -> str:
    """Return a verbatim-ish evidence snippet (whitespace squashed) of at most `limit` chars
    centred on text[start:end]."""
    core_len = end - start
    pad = max(0, (limit - core_len) // 2)
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    s = squash_ws(text[a:b])
    return s[:limit]
