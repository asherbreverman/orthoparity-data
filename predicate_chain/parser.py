"""Predicate extraction from 510(k) Summary text.

Pure functions over page text so they can be unit-tested with synthetic fixtures and
re-run offline on cached PDFs. Identity lookups are passed in as a callable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .numbers import NumberMatch, find_numbers
from .textclean import snippet, squash_ws

# ------------------------------------------------------------------ headings
_NUMBERING = (r"^[\s\-\u2022\u25cf\u25aa\*\u00b7>\.\u00b0\u00a2\u00ab\u00a9\u00ae|\"']*"   # bullets, incl. OCR-mangled ones
              r"(?:[eo]\s+(?=[A-Z]))?"                                               # OCR reads bullets as "e " / "o "
              r"(?:(?:[0-9]{1,2}|[A-Za-z]|[IVXivx]{1,5})[\.\)]\s*)*")

TIER1 = re.compile(_NUMBERING + r"(?:table\s*[\d][\d\.\-]*\s*:?\s*)?(?:identification\s+of\s+(?:the\s+)?)?(?:"
                   r"(?:primary|secondary|additional|other|legally\s+marketed)?\s*predicate\s*(?:device|devices|device\s*\(s\)|\(s\)|s)?\b"
                   r"|legally\s+marketed\s+(?:predicate\s+)?devices?(?:\s*\(s\))?"
                   r"|devices?(?:\s*\(s\))?\s+to\s+which\s+(?:substantial\s+)?equivalence\s+is\s+claimed"
                   r"|equivalent\s+devices?(?:\s*\(s\))?\s+identification"
                   r"|(?:substantially\s+)?equivalent\s+(?:legally\s+marketed\s+|predicate\s+)?devices?(?:\s*\(s\))?s?\s*(?:[:;]|$)"
                   r"|equivalence\s+to\s+(?:legally\s+)?marketed\s+(?:products?|devices?)"
                   r")", re.I | re.M)
REFERENCE_HEAD = re.compile(_NUMBERING + r"reference\s+(?:device|devices|device\s*\(s\)|predicates?)\b", re.I)
TIER2 = re.compile(_NUMBERING + r"(?:statement\s+of\s+|summary\s+of\s+|basis\s+(?:for|of)\s+)?substantial(?:ly)?\s+e[qg]uivalen[a-z]*(?:\s+(?:comparison|discussion|summary|information|determination))?", re.I)
TIER3 = re.compile(_NUMBERING + r"(?:comparison|technological\s+characteristics|summary\s+of\s+technolog|device\s+description|description\s+of\s+(?:the\s+)?device)", re.I)

TERMINATOR = re.compile(_NUMBERING + r"(?:"
                        r"device\s+description|description\s+of\s+(?:the\s+)?(?:subject\s+)?device|indications?\s+for\s+use|intended\s+use|"
                        r"technological\s+characteristics|summary\s+of\s+technolog|performance\s+(?:data|testing|test)|"
                        r"non-?\s?clinical|clinical\s+(?:data|testing|performance|studies)|conclusions?\b|"
                        r"materials?\s*:|sterili[sz]ation|biocompatib|mechanical\s+test|bench\s+test|"
                        r"date\s+(?:prepared|of\s+preparation|summary\s+prepared)|submitter|sponsor|applicant\s*:|"
                        r"contact\s+(?:person|information)|classification\s*(?:name|regulation|panel)?\s*:|"
                        r"product\s+codes?\s*:|regulation\s+(?:number|name)|trade\s+(?:name|/\s*proprietary)|"
                        r"proprietary\s+name|common\s+(?:or\s+usual\s+)?name|device\s+classification|"
                        r"comparison\s+of|summary\s+of\s+(?:the\s+)?(?:non|perf|test|clin|safety)|"
                        r"substantial(?:ly)?\s+equivalen|statement\s+of\s+substantial|indications\b"
                        r")", re.I)

LABEL_RE = re.compile(r"(primary\s+predicate|main\s+predicate|predicate\s+device\s*\(primary\)|\(primary\)|"
                      r"secondary\s+predicate|additional\s+predicates?|other\s+predicates?|"
                      r"reference\s+(?:device|devices|predicate|predicates)|predicate)", re.I)

TABLE_ROLE_RE = re.compile(r"\b(primary|additional|secondary|reference)(?:\s+(?:predicate|device))?\s*$", re.I)

PREAMEND_RE = re.compile(r"pre-?\s?amendments?\s+device|preamendment", re.I)

SECTION_CAP = 4000


@dataclass
class Section:
    tier: int                  # 1 predicate, 2 substantial equivalence, 3 comparison/description, 9 reference devices
    heading: str
    start: int                 # offset in full text
    end: int


@dataclass
class EdgeOut:
    predicate_number: str | None
    predicate_base: str | None
    predicate_kind: str
    list_order: int
    role: str
    role_basis: str
    printed_label: str | None
    family_of: str | None
    printed_name: str | None
    printed_company: str | None
    in_predicate_section: int
    section_heading: str | None
    page: int | None
    evidence: str
    normalized_number: bool = False
    window: str = ""
    named_item: bool = False
    # filled by cross-check
    identity: dict | None = None
    name_match_score: float | None = None
    company_match: int | None = None
    confidence: str | None = None


@dataclass
class FlagOut:
    flag_type: str
    number: str | None
    detail: str
    page: int | None
    evidence: str


@dataclass
class ParseResult:
    subject: str
    pdf_own_knumber: str | None = None
    is_statement: bool = False
    sections: list[Section] = field(default_factory=list)
    used_tier: int | None = None
    predicate_sections: int = 0
    edges: list[EdgeOut] = field(default_factory=list)
    flags: list[FlagOut] = field(default_factory=list)
    parse_status: str = "AMBIGUOUS"
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers
class PagedText:
    def __init__(self, pages: list[str]):
        self.pages = pages
        self.offsets = []
        parts = []
        pos = 0
        for p in pages:
            self.offsets.append(pos)
            parts.append(p)
            pos += len(p) + 1
        self.text = "\n".join(parts)

    def page_of(self, offset: int) -> int:
        page = 1
        for i, o in enumerate(self.offsets):
            if offset >= o:
                page = i + 1
            else:
                break
        return page


def _lines_with_offsets(text: str):
    pos = 0
    for line in text.split("\n"):
        yield pos, line
        pos += len(line) + 1


def _is_heading_line(rx: re.Pattern, line: str) -> re.Match | None:
    m = rx.match(line)
    if not m:
        return None
    # A heading is short, or the key phrase is followed by ":" or end of line, or sits at line start in title case.
    rest = line[m.end():]
    colon = (rest.lstrip().startswith((":", ";", "-", "\u2013")) or not rest.strip()
             or m.group(0).rstrip().endswith((":", ";"))
             or re.match(r"\s*to\s+which\b", rest, re.I) is not None)
    first = next((c for c in line if c.isalpha()), "")
    if first.islower() and not colon:
        return None  # wrapped paragraph text, not a heading
    if len(line.strip()) <= 60 or colon:
        return m
    return None


def find_sections(text: str) -> list[Section]:
    """Locate predicate-related sections with a simple line state machine."""
    sections: list[Section] = []
    cur: Section | None = None
    for off, line in _lines_with_offsets(text):
        stripped = line.strip()
        if not stripped:
            continue
        t1 = _is_heading_line(TIER1, line)
        ref = _is_heading_line(REFERENCE_HEAD, line)
        t2 = _is_heading_line(TIER2, line)
        t3 = _is_heading_line(TIER3, line)
        term = _is_heading_line(TERMINATOR, line)
        new_tier = 1 if t1 and not ref else 9 if ref else 2 if t2 else 3 if t3 else None
        if cur is not None:
            if term and new_tier is None and cur.tier in (1, 9) and "\n" not in text[cur.start:off].strip() \
                    and ":" not in stripped and "/" in stripped and not find_numbers(text[cur.start:off]):
                term = None  # a column-header line right under the heading, not a new section
            continuing = (cur.tier in (1, 9) and new_tier in (1, 9)) or (new_tier is None and not term)
            if continuing and off - cur.start < SECTION_CAP:
                cur.end = off + len(line)
                if new_tier == 9 and cur.tier == 1:
                    # Reference devices listed inside a predicate block: split so labels stay right.
                    sections.append(cur)
                    cur = Section(9, stripped[:120], off, off + len(line))
                continue
            sections.append(cur)
            cur = None
        if new_tier is not None:
            cur = Section(new_tier, stripped[:120], off, off + len(line))
    if cur is not None:
        sections.append(cur)
    return sections


_COMPANY_STOP = {"inc", "llc", "corp", "corporation", "co", "company", "ltd", "limited", "gmbh", "ag", "sa", "sas",
                 "bv", "nv", "spa", "srl", "plc", "usa", "us", "the", "international", "intl", "holdings", "group",
                 "medical", "of", "and", "de", "surgical"}
_NAME_STOP = {"the", "and", "for", "with", "system", "systems", "device", "devices", "set", "sets", "kit", "kits",
              "of", "or", "in", "to", "by", "model", "models", "family", "line", "series", "instrument",
              "instruments", "various", "modification", "modified", "additional", "new", "type"}


def _tokens(s: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def company_key(applicant: str | None) -> str | None:
    for tok in _tokens(applicant):
        if len(tok) >= 3 and tok not in _COMPANY_STOP:
            return tok
    return None


def company_match(applicant: str | None, window: str) -> bool:
    """First distinctive word of the applicant as a word prefix, or the applicant's words run together
    ("Nu Vasive" vs "NuVasive", "Depuy Synthes" vs "DePuy")."""
    w = window.lower()
    key = company_key(applicant)
    if key and re.search(r"\b" + re.escape(key), w):
        return True
    toks = [t for t in _tokens(applicant) if t not in _COMPANY_STOP]
    squashed = re.sub(r"[^a-z0-9]", "", w)
    for k in ("".join(toks[:2]), "".join(toks[:1]) if toks and len(toks[0]) >= 4 else ""):
        if len(k) >= 5 and k in squashed:
            return True
    return False


def name_match_score(fda_name: str | None, window: str) -> float:
    """Share of the FDA device name's significant words found near the number. Long FDA names that list
    several systems ("X Systems: A System, B System") are also scored segment by segment; the best wins."""
    parts = [fda_name] + [p for p in re.split(r"[:;,/]", fda_name or "") if p.strip()]
    return max(_name_score_one(p, window) for p in parts) if fda_name else 0.0


def _name_score_one(fda_name: str | None, window: str) -> float:
    toks = [t for t in _tokens(fda_name) if len(t) >= 3 and t not in _NAME_STOP]
    if not toks:
        return 0.0
    wtoks = set(_tokens(window))
    wjoined = " " + " ".join(_tokens(window)) + " "
    hit = 0
    for t in toks:
        if t in wtoks or (len(t) >= 5 and t in wjoined):
            hit += 1
    return round(hit / len(toks), 3)


def _clean_printed(s: str) -> str | None:
    s = LABEL_RE.sub(" ", s)
    s = re.sub(r"510\s*\(?k\)?\s*(number|no\.?|#)?", " ", s, flags=re.I)
    s = re.sub(r"[\(\)\[\]:;,–—\-•|]+", " ", s)
    s = re.sub(r"^\s*(by|from|manufactured\s+by|cleared\s+on.*)\s+", " ", s, flags=re.I)
    s = squash_ws(s)
    return s[:150] or None


_OCR_DIGIT = {"0": "[0OoQD]", "1": "[1Il|!]", "5": "[5S]", "8": "[8B]", "2": "[2Z]", "6": "[6G]"}


def _subject_pattern(subject: str) -> re.Pattern:
    """The subject number, tolerating OCR confusions and stray spaces between characters ("KI 11572")."""
    head = re.match(r"[A-Z]+", subject).group(0)
    parts = [re.escape(head)] + [_OCR_DIGIT.get(ch, re.escape(ch)) for ch in subject[len(head):]]
    return re.compile(r"\s?".join(parts), re.I)


def _detect_own_number(text: str, subject: str) -> str | None:
    """The number this PDF belongs to. Only FDA's "Re:" line and the Indications-for-Use form field count;
    a "510(k) number" column in a predicate table does not."""
    if _subject_pattern(subject).search(text):
        return subject
    for p in (r"\bRe:\s*([KD][^\n]{5,12})", r"510\s*\(k\)\s*Number\s*\(if\s+known\)\s*:?\s*([KD][^\n]{5,12})"):
        for m in re.finditer(p, text, re.I):
            cands = find_numbers(m.group(1))
            if cands and not cands[0].normalized:
                cand = cands[0].number
                # one differing digit is OCR noise on the subject's own number, not a different file
                if len(cand) == len(subject) and sum(x != y for x, y in zip(cand, subject)) <= 1:
                    return subject
                return cand
    return None

LETTER_RE = re.compile(r"We have reviewed your Section 510\s*\(k\)|This letter will allow you to begin marketing|"
                       r"Misbranding by reference to premarket notification|general controls provisions of the Act",
                       re.I)
SE_SENTENCE_RE = re.compile(r"substantial(?:ly)?\s+equivalen\w*|\bpredicate|\bequivalent\s+to\b", re.I)
SE_NAMED_RE = re.compile(r"(?:is|are|be|was|were)\s+substantially\s+equivalent\s+(?:in\s+[^.]{0,100}?\s+)?to\s*:?\s*"
                         r"(?:the\s+)?([A-Z0-9][^.]{3,250})", re.S)
GENERIC_SE_RE = re.compile(r"(?:other|devices?\b|legally|commercially|currently|predicate|its\b|their\b|"
                           r"those|similar|existing|previously|marketed)", re.I)
_NAMED_STOP = {"predicate", "predicates", "device", "devices", "substantially", "substantial", "equivalent",
               "equivalence", "legally", "marketed", "primary", "secondary", "additional", "reference", "the", "and",
               "are", "following", "identification", "number", "numbers", "trade", "name", "manufacturer",
               "product", "code", "type", "model", "other"}


def _is_named(s: str) -> bool:
    return any(len(t) >= 3 and t.isalpha() and t not in _NAMED_STOP for t in _tokens(s))


def se_sentences(text: str) -> list[Section]:
    """Sentences that claim substantial equivalence or mention a predicate, as tier-2 pseudo-sections."""
    out: list[Section] = []
    for m in SE_SENTENCE_RE.finditer(text):
        a = max(text.rfind(". ", 0, m.start()), text.rfind(".\n", 0, m.start()), text.rfind("\n\n", 0, m.start()),
                m.start() - 600)
        a = max(a + 1, 0)
        ends = [i for i in (text.find(". ", m.end()), text.find(".\n", m.end()), text.find("\n\n", m.end())) if i != -1]
        # a sentence also ends where the next heading line begins
        nl = text.find("\n", m.end())
        while nl != -1 and nl < m.end() + 600:
            nxt_end = text.find("\n", nl + 1)
            line = text[nl + 1: nxt_end if nxt_end != -1 else len(text)]
            if any(_is_heading_line(rx, line) for rx in (TERMINATOR, TIER1, TIER2, TIER3, REFERENCE_HEAD)):
                ends.append(nl)
                break
            nl = nxt_end
        b = min(ends + [m.end() + 600, len(text)])
        if out and a <= out[-1].end:
            out[-1].end = max(out[-1].end, b)
        else:
            out.append(Section(2, "sentence: " + squash_ws(text[a:a + 80]), a, b))
    return out


def _merge_sections(secs: list[Section]) -> list[Section]:
    secs = sorted(secs, key=lambda x: x.start)
    out: list[Section] = []
    for x in secs:
        if out and x.start <= out[-1].end:
            out[-1].end = max(out[-1].end, x.end)
        else:
            out.append(Section(x.tier, x.heading, x.start, x.end))
    return out


def _same_paren_group(text: str, a_start: int, b_start: int) -> bool:
    """True when both positions sit inside one '( ... )' group, e.g. '(K073291, K081234)'."""
    lp = text.rfind("(", 0, a_start)
    if lp == -1 or a_start - lp > 40:
        return False
    if text.find(")", lp, a_start) != -1:
        return False
    return text.find(")", lp, b_start) == -1


def _is_statement(text: str) -> bool:
    head = text[:6000].lower()
    return ("510(k) statement" in head or "510 (k) statement" in head) and "510(k) summary" not in head \
        and "510 (k) summary" not in head


# ------------------------------------------------------------------ main
IdentityFn = Callable[[str], dict | None]


def parse_predicates(pages: list[str], subject: str, identity: IdentityFn | None = None,
                     review_rule: str = "C", machine_read_pages: set[int] | None = None) -> ParseResult:
    """machine_read_pages: 1-based pages whose text came from OCR or a repaired font encoding (rule D uses it)."""
    subject = subject.upper()
    pt = PagedText(pages)
    text = pt.text
    res = ParseResult(subject=subject)
    res.pdf_own_knumber = _detect_own_number(text, subject)
    if res.pdf_own_knumber and res.pdf_own_knumber != subject:
        res.flags.append(FlagOut("wrong file", res.pdf_own_knumber,
                                 f"PDF appears to be for {res.pdf_own_knumber}, requested {subject}", None, ""))
    res.is_statement = _is_statement(text)

    own_numbers = {subject}
    if res.pdf_own_knumber:
        own_numbers.add(res.pdf_own_knumber)
    all_numbers = [n for n in find_numbers(text) if n.base not in own_numbers and n.number not in own_numbers]
    if review_rule == "D":  # a number one character off the document's own number is a slip, not a predicate
        all_numbers = [n for n in all_numbers if not any(_near(n.base, o) for o in own_numbers)]

    # FDA's clearance letter repeats boilerplate ("legally marketed predicate device ...") that is not the
    # submitter's predicate list; its pages are left out of section finding.
    letter = [(pt.offsets[i], pt.offsets[i] + len(p)) for i, p in enumerate(pages) if LETTER_RE.search(p)]
    in_letter = lambda off: any(a <= off < b for a, b in letter)
    res.sections = [x for x in find_sections(text) if not in_letter(x.start)]
    sentence_secs = [x for x in se_sentences(text) if not in_letter(x.start)]

    def nums_in(sec: Section) -> list[NumberMatch]:
        return [n for n in all_numbers if sec.start <= n.start < sec.end]

    tier1 = [s for s in res.sections if s.tier == 1]
    tier2 = [s for s in res.sections if s.tier == 2] + sentence_secs
    tier3 = [s for s in res.sections if s.tier == 3]
    refsecs = [s for s in res.sections if s.tier == 9]

    used: list[Section] = []
    t1 = [s for s in tier1 if nums_in(s)]
    t2 = [s for s in tier2 if nums_in(s)]
    if t1:
        have = {n.number for s in t1 for n in nums_in(s)}
        extra = []
        for s in sorted(t2, key=lambda x: x.start):
            new_n = [n for n in nums_in(s) if n.number not in have]
            if new_n:
                extra.append(s)
                have |= {n.number for n in new_n}
        used, res.used_tier = t1 + extra, 1
        res.predicate_sections = len(t1) + len(extra)
    elif t2:
        merged = _merge_sections(t2)
        used, res.used_tier = merged, 2
        res.predicate_sections = len(merged)
    else:
        t3 = [s for s in tier3 if nums_in(s)]
        if t3:
            used, res.used_tier = t3, 3
            res.predicate_sections = len(t3)

    # Unnumbered predicate: a labeled predicate section with text but no number.
    unnumbered: list[tuple[Section, int, int]] = []
    if not used:
        for s in tier1:
            body = text[s.start:s.end]
            if len(squash_ws(body)) > len(s.heading) + 8:
                unnumbered.append((s, s.start, s.end))
                break
    # Predicates named in a substantial-equivalence sentence without any number.
    if not used and not unnumbered:
        for sec in sentence_secs:
            m = SE_NAMED_RE.search(text, sec.start, sec.end)
            if m and not GENERIC_SE_RE.match(m.group(1)):
                unnumbered.append((sec, m.start(1), min(sec.end, m.start(1) + 300)))
                break
    # Pre-amendment predicates mentioned inside the sections.
    for s in tier1 + tier2:
        m = PREAMEND_RE.search(text, s.start, s.end)
        if m and not any(u[0].start <= m.start() < u[0].end or u[1] <= m.start() < u[2] for u in unnumbered):
            unnumbered.append((s, m.start(), m.end()))
            break

    # ---- collect candidate predicate mentions (ordered, de-duplicated) --------
    candidates: list[tuple[NumberMatch, Section | None, int]] = []
    if used:
        for s in used:
            for n in nums_in(s):
                candidates.append((n, s, 1 if s.tier in (1, 2) else 0))
    elif not unnumbered:
        # Fallback: numbers within 300 characters of the word "predicate" or "substantially equivalent".
        for n in all_numbers:
            if in_letter(n.start):
                continue
            ctx = text[max(0, n.start - 300): n.end + 300].lower()
            if "predicate" in ctx or "substantially equivalent" in ctx or "equivalence" in ctx:
                candidates.append((n, None, 0))
        if candidates:
            res.notes.append("no labeled predicate section; numbers taken from predicate wording nearby")
    ref_candidates = [(n, s) for s in refsecs for n in nums_in(s)]

    seen: dict[str, EdgeOut] = {}
    ordered: list[EdgeOut] = []
    all_positions = sorted(all_numbers, key=lambda x: x.start)

    SEP = re.compile(r"[\s,;/&#()]*(?:and|&)?[\s,;/&#()]*", re.I)

    def window_for(n: NumberMatch) -> str:
        """Text around a number, bounded by the neighbouring numbers. A run of numbers separated only by
        punctuation ("K143628/K140454/K143375 Medtronic Navigated Instruments") shares one window."""
        idx = next(i for i, m in enumerate(all_positions) if m.start == n.start)
        lo_i = idx
        while lo_i > 0 and SEP.fullmatch(text[all_positions[lo_i - 1].end:all_positions[lo_i].start]):
            lo_i -= 1
        hi_i = idx
        while hi_i + 1 < len(all_positions) and SEP.fullmatch(text[all_positions[hi_i].end:all_positions[hi_i + 1].start]):
            hi_i += 1
        prev_end = all_positions[lo_i - 1].end if lo_i > 0 else 0
        next_start = all_positions[hi_i + 1].start if hi_i + 1 < len(all_positions) else len(text)
        a = max(prev_end, all_positions[lo_i].start - 250)
        b = min(next_start, all_positions[hi_i].end + 250)
        return text[a:b]

    def label_for(n: NumberMatch, sec: Section | None) -> str | None:
        lo = sec.start if sec else max(0, n.start - 200)
        # "(Primary Predicate is listed first)" in eSTAR table headers is an instruction, not a label.
        labels = [m for m in LABEL_RE.finditer(text, lo, n.start)
                  if "listed first" not in text[m.start():m.end() + 30].lower()]
        line_end_ = text.find("\n", n.end)
        line_end_ = len(text) if line_end_ == -1 else line_end_
        tail = TABLE_ROLE_RE.search(text[n.end:line_end_])
        if tail:  # table row ending in "Primary" / "Additional" / "Reference"
            word = tail.group(1).lower()
            return "primary predicate" if word == "primary" else (
                "reference device" if word == "reference" else f"{word} predicate")
        # line-local label wins; otherwise the closest earlier label in the section
        line_start = text.rfind("\n", 0, n.start) + 1
        after_line_end = text.find("\n", n.end)
        after_line_end = len(text) if after_line_end == -1 else after_line_end
        same_line_after = list(LABEL_RE.finditer(text, n.end, min(after_line_end, n.end + 40)))
        for m in reversed(labels):
            if m.start() >= line_start:
                return squash_ws(m.group(1)).lower()
        for m in same_line_after:
            if "primary" in m.group(1).lower():
                return "primary predicate"
        if re.search(r"reference\s+device", text[n.end:after_line_end], re.I):
            return "reference device"
        if labels:
            return squash_ws(labels[-1].group(1)).lower()
        return None

    def printed_parts(n: NumberMatch) -> tuple[str | None, str | None]:
        line_start = text.rfind("\n", 0, n.start) + 1
        line_end = text.find("\n", n.end)
        line_end = len(text) if line_end == -1 else line_end
        before = _clean_printed(re.sub(r"K[ \-]?\d{6}|DEN\d{6}|P\d{6}", " ", text[line_start:n.start]))
        after = _clean_printed(re.sub(r"K[ \-]?\d{6}|DEN\d{6}|P\d{6}", " ", text[n.end:line_end]))
        if before:
            return before, after
        return after, None

    prev_n: NumberMatch | None = None
    for order, (n, sec, insec) in enumerate(candidates):
        if n.number in seen:
            prev_n = n
            continue
        name, comp = printed_parts(n)
        e = EdgeOut(
            predicate_number=n.number, predicate_base=n.base, predicate_kind=n.kind, list_order=len(ordered) + 1,
            role="", role_basis="", printed_label=label_for(n, sec), family_of=None,
            printed_name=name, printed_company=comp, in_predicate_section=insec,
            section_heading=sec.heading if sec else None, page=pt.page_of(n.start),
            evidence=snippet(text, n.start, n.end, 300), normalized_number=n.normalized, window=window_for(n),
        )
        # Family members: "K1, including K2 and K3", several numbers in one parenthetical group, or several
        # numbers listed one after another under one device name ("TSRH Spinal System, K901005, K901587").
        if prev_n is not None and ordered and ordered[-1].predicate_number:
            between = text[prev_n.end:n.start]
            head = ordered[-1].family_of or ordered[-1].predicate_number
            head_e = seen.get(head)
            if len(between) < 120 and "." not in between.replace("No.", ""):
                separators_only = re.fullmatch(r"[\s,;/&#]*(?:and|&)?[\s,;/&#]*", between, re.I) is not None
                if re.search(r"\bincluding\b", between, re.I):
                    e.family_of = head
                elif separators_only and (_same_paren_group(text, prev_n.start, n.start)
                                          or (head_e is not None and head_e.named_item)):
                    e.family_of = head
            if e.family_of and head_e is not None:
                e.window = head_e.window + " " + e.window
        if not e.family_of:
            item_lo = max(prev_n.end if prev_n else 0, sec.start if sec else n.start - 200, n.start - 300)
            e.named_item = _is_named(text[item_lo:n.start])
        seen[n.number] = e
        ordered.append(e)
        prev_n = n

    for n, sec in ref_candidates:
        if n.number in seen:
            continue
        name, comp = printed_parts(n)
        e = EdgeOut(n.number, n.base, n.kind, len(ordered) + 1, "reference", "labeled reference device in PDF",
                    "reference device", None, name, comp, 1, sec.heading, pt.page_of(n.start),
                    snippet(text, n.start, n.end, 300), n.normalized, window_for(n))
        seen[n.number] = e
        ordered.append(e)

    for sec, a, b in unnumbered:
        e = EdgeOut(None, None, "none", len(ordered) + 1, "", "", "predicate", None,
                    _clean_printed(text[a:b])[:150] if _clean_printed(text[a:b]) else None, None, 1, sec.heading,
                    pt.page_of(a), snippet(text, a, min(b, a + 300), 300))
        ordered.append(e)

    assign_roles(ordered)
    res.edges = ordered

    # ---- cross-check -------------------------------------------------------
    captured = {e.predicate_number for e in ordered if e.predicate_number}
    mentioned_flagged = set()
    added = False
    for n in all_numbers:
        if n.number in captured or n.base in captured or n.number in mentioned_flagged:
            continue
        mentioned_flagged.add(n.number)
        if (review_rule == "D" and n.kind in ("K", "DEN") and not in_letter(n.start)
                and not any(_near(n.base, o) for o in own_numbers)):
            # Rule D: any other K-number in the Summary is a predicate.
            e = EdgeOut(n.number, n.base, n.kind, len(ordered) + 1, "", "", "mentioned in Summary", None, None, None,
                        0, None, pt.page_of(n.start), snippet(text, n.start, n.end, 300), n.normalized, window_for(n))
            ordered.append(e)
            captured.add(n.number)
            added = True
            continue
        res.flags.append(FlagOut("mentioned, not classified", n.number,
                                 "number appears in the PDF but was not captured as a predicate",
                                 pt.page_of(n.start), snippet(text, n.start, n.end, 300)))
    if added:
        ment = [e for e in ordered if e.printed_label == "mentioned in Summary"]
        had_numbered = any(e.predicate_number and e.printed_label != "mentioned in Summary" and e.role == "primary"
                           for e in ordered)
        if had_numbered:
            for e in ment:
                e.role, e.role_basis = "reference", "K-number mentioned in Summary (rule D: assumed predicate)"
        else:
            assign_roles(ordered)
            for e in ment:
                e.role_basis = ("first K-number mentioned in Summary (rule D: assumed predicate)" if e.role == "primary"
                                else "K-number mentioned in Summary (rule D: assumed predicate)")
        if not res.predicate_sections:
            res.notes.append("predicates taken from K-numbers mentioned in the Summary (rule D)")

    subject_applicant = None
    if review_rule == "D" and identity:
        me = identity(subject) or {}
        subject_applicant = me.get("applicant") if me.get("found") else None
    for e in ordered:
        score_and_flag(e, identity, res, review_rule, machine_read_pages or set(), subject_applicant)
    if review_rule == "D":
        _drop_own_number_slips(res, ordered, own_numbers)

    res.parse_status = _status(res, review_rule)
    return res


def assign_roles(edges: list[EdgeOut]) -> None:
    """ROLE RULE.
    one predicate listed = primary; several with one labeled primary = that one primary, others reference;
    several with none labeled = first listed primary; family members inherit the role of their head;
    edges labeled 'reference device' are always reference."""
    preds = [e for e in edges if e.printed_label != "reference device" and e.role != "reference"]
    heads = [e for e in preds if not e.family_of]
    labeled = [e for e in heads if e.printed_label and "primary" in e.printed_label]
    if len(heads) == 1:
        primary_head, basis = heads[0], "only predicate listed"
    elif labeled:
        primary_head, basis = labeled[0], "labeled primary in PDF"
    elif heads:
        primary_head, basis = heads[0], "first listed, none labeled primary"
    else:
        primary_head, basis = None, ""
    for e in edges:
        if e.role == "reference" and e.printed_label == "reference device":
            continue
        if e.printed_label == "reference device":
            e.role, e.role_basis = "reference", "labeled reference device in PDF"
            continue
        head_num = e.family_of
        if head_num:
            head = next((h for h in edges if h.predicate_number == head_num), None)
            if head is primary_head:
                e.role, e.role_basis = "primary", f"family member of {head_num} (inherits primary)"
            else:
                e.role, e.role_basis = "reference", f"family member of {head_num}"
            continue
        if e is primary_head:
            e.role, e.role_basis = "primary", basis
        else:
            e.role = "reference"
            e.role_basis = "listed with a labeled primary" if labeled else "listed after the first predicate"
    if len(labeled) > 1 and primary_head is not None:
        primary_head.role_basis += f"; {len(labeled)} predicates labeled primary, first one used"


def score_and_flag(e: EdgeOut, identity: IdentityFn | None, res: ParseResult, review_rule: str = "C",
                   machine_read_pages: set | None = None, subject_applicant: str | None = None) -> None:
    if e.predicate_number is None:
        e.confidence = "NO NUMBER" if review_rule == "D" else "LOW"
        e.name_match_score = None
        return
    ident = identity(e.predicate_base or e.predicate_number) if identity else None
    e.identity = ident
    found = bool(ident and ident.get("found"))
    if found:
        e.name_match_score = name_match_score(ident.get("device_name"), e.window)
        e.company_match = int(company_match(ident.get("applicant"), e.window))
        full = e.name_match_score >= 0.5 or (e.company_match and e.name_match_score >= 0.25)
        partial = e.name_match_score > 0 or e.company_match
        if review_rule == "D":
            # Rule D: the FDA number decides identity; printed names can differ after a rename.
            machine_read = e.normalized_number or (e.page in (machine_read_pages or set()))
            context = partial or bool(
                name_match_score(ident.get("device_name"), e.evidence or "") > 0
                or company_match(ident.get("applicant"), e.evidence or "")
                or (subject_applicant and _same_company(ident.get("applicant"), subject_applicant)))
            if machine_read and not context:
                e.confidence = "LOW"
                res.flags.append(FlagOut("possible OCR misread", e.predicate_number,
                                         "number read by OCR or from a repaired font; neither the device name nor the "
                                         f"company matches the FDA record ({ident.get('applicant')} / "
                                         f"{ident.get('device_name')})", e.page, e.evidence))
            else:
                e.confidence = "HIGH" if e.in_predicate_section else "MEDIUM"
        elif e.in_predicate_section and full:
            e.confidence = "HIGH"
        elif e.in_predicate_section and partial:
            e.confidence = "MEDIUM"
        elif not e.in_predicate_section and full:
            e.confidence = "MEDIUM"
        else:
            e.confidence = "LOW"
        if not partial:
            res.flags.append(FlagOut("name mismatch", e.predicate_number,
                                     f"printed text does not match FDA record: {ident.get('applicant')} / {ident.get('device_name')}",
                                     e.page, e.evidence))
        elif not full:
            res.flags.append(FlagOut("partial name match", e.predicate_number,
                                     f"partial match to FDA record: {ident.get('applicant')} / {ident.get('device_name')}",
                                     e.page, e.evidence))
    else:
        e.name_match_score = None
        e.company_match = None
        e.confidence = "MEDIUM" if e.in_predicate_section else "LOW"
        if e.predicate_kind == "P":
            res.flags.append(FlagOut("PMA predicate", e.predicate_number,
                                     "PMA number; not in 510(k) records, identity not checked", e.page, e.evidence))
        elif ident is not None:  # lookup was attempted and failed everywhere
            detail = "number not found in any FDA source"
            if e.normalized_number:
                detail += " (OCR-style characters were corrected)"
            res.flags.append(FlagOut("probable misread number", e.predicate_number, detail, e.page, e.evidence))


INFORMATIONAL_FLAGS = {"PMA predicate"}
RULE_D_BLOCKING = {"wrong file", "probable misread number", "possible OCR misread"}


_GENERIC_CO = {"inc", "corp", "corporation", "co", "ltd", "llc", "company", "usa", "the", "medical", "international",
               "orthopaedics", "orthopedics", "orthopaedic", "orthopedic", "surgical", "products", "technologies"}


def _same_company(a: str | None, b: str | None) -> bool:
    """First distinctive word of two applicant names ("Medtronic Sofamor Danek" vs "Medtronic Sofamor Danek USA")."""
    def first(x):
        w = [t for t in re.findall(r"[a-z]+", (x or "").lower()) if t not in _GENERIC_CO and len(t) > 2]
        return w[0] if w else None
    fa, fb = first(a), first(b)
    return bool(fa and fa == fb)


def _near2(a: str | None, b: str | None) -> bool:
    """Up to two characters off, or two adjacent characters swapped: an OCR slip on the document's own number."""
    if not a or not b or len(a) != len(b):
        return False
    diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(diff) <= 2:
        return True
    return False


def _drop_own_number_slips(res: ParseResult, ordered: list, own_numbers: set) -> None:
    """Rule D: a number not found in any FDA record that sits in a
    "510(k) Number" field or is within two characters of the document's own number is the document's own number
    misread, not a predicate. The edge is dropped and an informational flag records it."""
    suspicious = {f.number for f in res.flags if f.flag_type == "probable misread number"}
    drop = set()
    for e in ordered:
        if e.predicate_number not in suspicious:
            continue
        ev = (e.evidence or "").lower()
        i = ev.find(e.predicate_number[1:4].lower())
        before = ev[max(0, i - 60):i] if i >= 0 else ""
        in_field = bool(re.search(r"510\s*\(?\s*k\s*\)?\s*number", before))
        if in_field or any(_near2(e.predicate_base, o) for o in own_numbers):
            drop.add(e.predicate_number)
    if not drop:
        return
    res.flags = [f for f in res.flags if not (f.number in drop and f.flag_type in
                                              ("probable misread number", "possible OCR misread"))]
    for n in sorted(drop):
        e = next(x for x in ordered if x.predicate_number == n)
        res.flags.append(FlagOut("own number misread", n, "suspicious number in a 510(k) Number field or within two "
                                 "characters of the document's own number; not counted as a predicate", e.page, e.evidence))
    had_primary = any(e.role == "primary" and e.predicate_number in drop for e in ordered)
    ordered[:] = [e for e in ordered if e.predicate_number not in drop]
    for i, e in enumerate(ordered, 1):
        e.list_order = i
    if had_primary and ordered:
        assign_roles(ordered)
    res.edges = ordered


def _near(a: str | None, b: str | None) -> bool:
    """Same number or one character off (an OCR or typing slip on the document's own number)."""
    if not a or not b:
        return False
    if a == b:
        return True
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def blocking_flags(res: ParseResult, review_rule: str = "C") -> list[FlagOut]:
    """Flags that keep a document out of CLEAN.
    strict: every flag. C (approved at Gate 1): "PMA predicate" is informational; "mentioned, not classified" is
    informational when the document already has a HIGH predicate from a labeled section, and blocking otherwise
    (in a dead-end document a mentioned number usually means a missed predicate)."""
    if review_rule == "strict":
        return list(res.flags)
    if review_rule == "D":
        return [f for f in res.flags if f.flag_type in RULE_D_BLOCKING]
    anchored = any(e.predicate_number and e.in_predicate_section and e.confidence == "HIGH" for e in res.edges)
    return [f for f in res.flags
            if f.flag_type not in INFORMATIONAL_FLAGS
            and not (f.flag_type == "mentioned, not classified" and anchored)]


def _status(res: ParseResult, review_rule: str = "C") -> str:
    if review_rule == "D":
        # Rule D: name-only predicates are ignored, names never block, any other K-number is a predicate.
        # Only a possible misread number or a wrong file needs a person.
        return "AMBIGUOUS" if blocking_flags(res, review_rule) else "CLEAN"
    numbered = [e for e in res.edges if e.predicate_number]
    if (res.predicate_sections == 1 and res.used_tier in (1, 2) and numbered
            and all(e.confidence == "HIGH" for e in res.edges) and not blocking_flags(res, review_rule)):
        return "CLEAN"
    return "AMBIGUOUS"
