"""Patterns for FDA submission numbers: K (510(k)), DEN (De Novo), P (PMA, with optional supplement)."""
from __future__ import annotations

import re
from dataclasses import dataclass

# OCR and typing confusions allowed inside the six digits of a number.
_CONFUSION = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})

# K + optional space/hyphen + six "digit-like" characters.
# K + optional space/hyphen/"(" + six "digit-like" characters; OCR sometimes splits the six with one space
# ("K9335 18", "K(002783"), which is allowed once.
K_RE = re.compile(r"(?<![A-Za-z0-9])K[ \-\(]?([0-9OoIl|](?:[0-9OoIl|]|[ ](?=[0-9OoIl|])){5,6})(?![0-9A-Za-z])")
DEN_RE = re.compile(r"(?<![A-Za-z0-9])DEN[ \-]?([0-9OoIl]{6})(?![0-9A-Za-z])")
P_RE = re.compile(r"(?<![A-Za-z0-9])P[ \-]?(\d{6})(?:\s*/\s*(S\d{1,4}))?(?![0-9A-Za-z])")


@dataclass(frozen=True)
class NumberMatch:
    number: str          # normalized, e.g. K123456, DEN150034, P970051/S020
    base: str            # number without PMA supplement, e.g. P970051
    kind: str            # "K", "DEN" or "P"
    start: int
    end: int
    raw: str
    normalized: bool     # True if OCR-style characters were corrected


def _digits(chunk: str) -> tuple[str, bool] | None:
    spaces = chunk.count(" ")
    if spaces > 1:
        return None
    chunk = chunk.replace(" ", "")
    if len(chunk) != 6:
        return None
    fixed = chunk.translate(_CONFUSION)
    if not fixed.isdigit():
        return None
    real_digits = sum(c.isdigit() for c in chunk)
    if real_digits < 4:  # too many letters to be a believable number
        return None
    return fixed, fixed != chunk


def find_numbers(text: str) -> list[NumberMatch]:
    """Find every K, DEN and P number in text, in reading order."""
    found: list[NumberMatch] = []
    for m in K_RE.finditer(text):
        d = _digits(m.group(1))
        if d:
            found.append(NumberMatch("K" + d[0], "K" + d[0], "K", m.start(), m.end(), m.group(0),
                                     d[1] or " " in m.group(1)))
    for m in DEN_RE.finditer(text):
        d = _digits(m.group(1))
        if d:
            found.append(NumberMatch("DEN" + d[0], "DEN" + d[0], "DEN", m.start(), m.end(), m.group(0), d[1]))
    for m in P_RE.finditer(text):
        base = "P" + m.group(1)
        num = base + ("/" + m.group(2).upper() if m.group(2) else "")
        found.append(NumberMatch(num, base, "P", m.start(), m.end(), m.group(0), False))
    found.sort(key=lambda x: x.start)
    return found


def number_kind(number: str | None) -> str | None:
    if not number:
        return None
    n = number.upper()
    if n.startswith("DEN"):
        return "DEN"
    if n.startswith("K"):
        return "K"
    if n.startswith("P"):
        return "P"
    return None


def normalize_knumber(value: str | None) -> str | None:
    """Normalize a user- or file-supplied number like 'k 241487' -> 'K241487'."""
    if not value:
        return None
    v = re.sub(r"[\s\-]", "", str(value).upper())
    return v or None


def pdf_folder_candidates(knumber: str) -> list[str]:
    """FDA cdrh_docs folder names to try for a K or DEN number.

    K-numbers from 2002 on usually live in pdf{YY} (pdf2 ... pdf9 for 2002-2009,
    pdf10 ... for 2010 on); older ones in "pdf". Verified during the pilot.
    """
    n = knumber.upper()
    if n.startswith("K") and len(n) >= 3 and n[1:3].isdigit():
        yy = int(n[1:3])
        if 2 <= yy <= 75:
            return [f"pdf{yy}", f"pdf{yy:02d}", "pdf"] if yy < 10 else [f"pdf{yy}", "pdf"]
        return ["pdf"]
    if n.startswith("DEN") and len(n) >= 5 and n[3:5].isdigit():
        yy = int(n[3:5])
        return ["reviews", f"pdf{yy}"]
    return ["pdf"]
