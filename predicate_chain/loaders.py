"""Phase 0 loaders: starting set, FDA master release files, product codes. Verifies counts."""
from __future__ import annotations

import collections
import datetime as dt
import sqlite3
from pathlib import Path

from .config import Config
from .numbers import normalize_knumber
from .textclean import clean_field, strip_control_chars


class CountMismatch(RuntimeError):
    pass


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    s = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return s


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return clean_field(str(value))


def era_of(year: int) -> str:
    if year <= 1990:
        return "1976-1990"
    if year <= 1995:
        return "1991-1995"
    return "1996+"


# ---------------------------------------------------------------- starting set
STARTING_SET_COLUMNS = {
    "KNUMBER": "knumber", "APPLICANT": "applicant", "CONTACT": "contact", "STREET1": "street1",
    "STREET2": "street2", "CITY": "city", "STATE": "state", "COUNTRY_CODE": "country_code",
    "ZIP": "zip", "POSTAL_CODE": "postal_code", "DATE RECEIVED": "date_received",
    "DECISION DATE": "decision_date", "DECISION": "decision", "REVIEW ADVISE COMM": "review_advise_comm",
    "510K PRODUCT CODE": "product_code", "Device": "device", "Regulation Description": "regulation_description",
    "Regulation Number": "regulation_number", "Device Class": "device_class", "Life Sustaining": "life_sustaining",
    "Implant": "implant", "STATEORSUMM": "stateorsumm", "CLASSADVISECOMM": "classadvisecomm",
    "SSPINDICATOR": "sspindicator", "TYPE": "type", "THIRDPARTY": "thirdparty", "EXPEDITEDREVIEW": "expeditedreview",
    "DEVICENAME": "devicename", "SEGMENT": "unofficial_segment", "SUB-SEGMENT": "unofficial_sub_segment",
    "SUBMISSION CATEGORY": "submission_category", "INCLUSION BASIS": "inclusion_basis", "SOURCE FILE": "source_file",
}
REQUIRED_STARTING_COLUMNS = ["KNUMBER", "APPLICANT", "DEVICENAME", "510K PRODUCT CODE", "Device",
                             "Regulation Number", "Device Class", "DECISION", "DECISION DATE", "TYPE",
                             "THIRDPARTY", "STATEORSUMM", "SEGMENT", "SUB-SEGMENT", "SUBMISSION CATEGORY",
                             "INCLUSION BASIS"]


def load_starting_set(con: sqlite3.Connection, cfg: Config) -> dict:
    import openpyxl

    path = cfg.starting_set_file
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[cfg.starting_set_sheet]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    missing = [c for c in REQUIRED_STARTING_COLUMNS if c not in header]
    if missing:
        raise CountMismatch(f"Starting set is missing columns: {missing}")
    idx = {h: i for i, h in enumerate(header)}
    now = utcnow()
    records = []
    for r in rows:
        if r is None or all(v is None for v in r):
            continue
        rec = {}
        for col, field in STARTING_SET_COLUMNS.items():
            v = r[idx[col]] if col in idx else None
            if field in ("date_received", "decision_date"):
                rec[field] = _iso(v)
            elif field == "device_class":
                rec[field] = _text(v)
            else:
                rec[field] = _text(v)
        rec["knumber"] = normalize_knumber(rec["knumber"])
        rec["decision_year"] = int(rec["decision_date"][:4]) if rec["decision_date"] else None
        rec["loaded_from"] = path.name
        rec["loaded_at_utc"] = now
        records.append(rec)
    wb.close()

    # ---- verification ------------------------------------------------------
    report: dict = {"rows": len(records)}
    ks = [r["knumber"] for r in records]
    report["duplicates"] = len(ks) - len(set(ks))
    report["den"] = sum(1 for k in ks if k.startswith("DEN"))
    report["blank_product_code"] = sum(1 for r in records if not r["product_code"])
    dates = sorted(r["decision_date"] for r in records if r["decision_date"])
    report["min_date"], report["max_date"] = dates[0], dates[-1]
    era = collections.Counter()
    for r in records:
        era[(era_of(r["decision_year"]), r["stateorsumm"] or "blank")] += 1
    report["stateorsumm_by_era"] = {f"{k[0]}:{k[1]}": v for k, v in sorted(era.items())}

    problems = []
    def check(name, got, want):
        if str(got) != str(want):
            problems.append(f"{name}: expected {want}, found {got}")
    check("rows", report["rows"], cfg.expected("STARTING_SET_ROWS"))
    check("duplicate K-numbers", report["duplicates"], 0)
    check("DEN rows", report["den"], cfg.expected("STARTING_SET_DEN"))
    check("blank product code", report["blank_product_code"], cfg.expected("STARTING_SET_BLANK_PRODUCT_CODE"))
    check("min decision date", report["min_date"], cfg.expected("STARTING_SET_MIN_DATE"))
    check("max decision date", report["max_date"], cfg.expected("STARTING_SET_MAX_DATE"))
    expected_era = cfg.expected_era_counts()
    for key in set(expected_era) | set(era):
        check(f"STATEORSUMM {key[0]} {key[1]}", era.get(key, 0), expected_era.get(key, 0))
    report["problems"] = problems
    if problems:
        raise CountMismatch("Starting set verification failed:\n  " + "\n  ".join(problems))

    cols = list(records[0].keys())
    con.execute("DELETE FROM clearances")
    con.executemany(
        f"INSERT INTO clearances ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in records],
    )
    con.commit()
    return report


# ---------------------------------------------------------------- pipe files
def read_pipe_file(path: Path) -> tuple[list[str], list[list[str]], int]:
    """Read a pipe-delimited FDA file. Splits records on LF only, strips control chars.
    Returns header, rows, and number of lines that had control characters."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.split("\n")
    header = [h.strip() for h in strip_control_chars(lines[0]).replace("\r", "").split("|")]
    rows = []
    dirty = 0
    for line in lines[1:]:
        cleaned = strip_control_chars(line).replace("\r", "")
        if cleaned != line.replace("\r", "") :
            dirty += 1
        if not cleaned.strip():
            continue
        parts = cleaned.split("|")
        if len(parts) > len(header):  # stray pipe inside the last free-text field
            parts = parts[: len(header) - 1] + ["|".join(parts[len(header) - 1:])]
        elif len(parts) < len(header):
            parts += [""] * (len(header) - len(parts))
        rows.append(parts)
    return header, rows, dirty


FDA_MASTER_COLUMNS = {
    "KNUMBER": "knumber", "APPLICANT": "applicant", "CONTACT": "contact", "STREET1": "street1",
    "STREET2": "street2", "CITY": "city", "STATE": "state", "COUNTRY_CODE": "country_code", "ZIP": "zip",
    "POSTAL_CODE": "postal_code", "DATERECEIVED": "date_received", "DECISIONDATE": "decision_date",
    "DECISION": "decision", "REVIEWADVISECOMM": "review_panel", "PRODUCTCODE": "product_code",
    "STATEORSUMM": "stateorsumm", "CLASSADVISECOMM": "classadvisecomm", "SSPINDICATOR": "sspindicator",
    "TYPE": "type", "THIRDPARTY": "thirdparty", "EXPEDITEDREVIEW": "expeditedreview", "DEVICENAME": "devicename",
}


def load_fda_master(con: sqlite3.Connection, cfg: Config) -> dict:
    now = utcnow()
    total = 0
    dirty_total = 0
    per_file = {}
    seen: set[str] = set()
    dupes = 0
    con.execute("DELETE FROM fda_master")
    for path in cfg.fda_master_files:
        header, rows, dirty = read_pipe_file(path)
        idx = {h: i for i, h in enumerate(header)}
        missing = [c for c in FDA_MASTER_COLUMNS if c not in idx]
        if missing:
            raise CountMismatch(f"{path.name} is missing columns {missing}")
        batch = []
        for parts in rows:
            rec = {f: clean_field(parts[idx[c]]) for c, f in FDA_MASTER_COLUMNS.items()}
            rec["knumber"] = normalize_knumber(rec["knumber"])
            if not rec["knumber"]:
                continue
            if rec["knumber"] in seen:
                dupes += 1
                continue
            seen.add(rec["knumber"])
            rec["date_received"] = _iso(rec["date_received"])
            rec["decision_date"] = _iso(rec["decision_date"])
            rec["decision_year"] = int(rec["decision_date"][:4]) if rec["decision_date"] and rec["decision_date"][:4].isdigit() else None
            rec["source_file"] = path.name
            rec["loaded_at_utc"] = now
            batch.append(rec)
        cols = list(batch[0].keys())
        con.executemany(
            f"INSERT INTO fda_master ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [tuple(r[c] for c in cols) for r in batch],
        )
        per_file[path.name] = len(batch)
        total += len(batch)
        dirty_total += dirty
    con.commit()
    report = {"rows": total, "per_file": per_file, "duplicates_skipped": dupes,
              "lines_with_control_chars_stripped": dirty_total}
    want = int(cfg.expected("FDA_MASTER_ROWS"))
    if total != want or dupes:
        raise CountMismatch(f"FDA master: expected {want} unique records, found {total} (duplicates {dupes})")
    return report


PRODUCT_CODE_COLUMNS = {
    "REVIEW_PANEL": "review_panel", "MEDICALSPECIALTY": "medical_specialty", "PRODUCTCODE": "product_code",
    "DEVICENAME": "device_name", "DEVICECLASS": "device_class", "UNCLASSIFIED_REASON": "unclassified_reason",
    "GMPEXEMPTFLAG": "gmp_exempt_flag", "THIRDPARTYFLAG": "third_party_flag", "REVIEWCODE": "review_code",
    "REGULATIONNUMBER": "regulation_number", "SUBMISSION_TYPE_ID": "submission_type_id",
    "DEFINITION": "definition", "PHYSICALSTATE": "physical_state", "TECHNICALMETHOD": "technical_method",
    "TARGETAREA": "target_area", "Implant_Flag": "implant_flag",
    "Life_Sustain_support_flag": "life_sustain_support_flag",
    "SummaryMalfunctionReporting": "summary_malfunction_reporting",
}


def load_product_codes(con: sqlite3.Connection, cfg: Config) -> dict:
    path = cfg.product_code_file
    header, rows, dirty = read_pipe_file(path)
    idx = {h: i for i, h in enumerate(header)}
    now = utcnow()
    batch = {}
    for parts in rows:
        rec = {f: clean_field(parts[idx[c]]) if c in idx else None for c, f in PRODUCT_CODE_COLUMNS.items()}
        if not rec["product_code"]:
            continue
        rec["source_file"] = path.name
        rec["loaded_at_utc"] = now
        batch[rec["product_code"]] = rec
    con.execute("DELETE FROM product_codes")
    cols = list(next(iter(batch.values())).keys())
    con.executemany(
        f"INSERT INTO product_codes ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in batch.values()],
    )
    con.commit()
    report = {"rows": len(batch), "raw_rows": len(rows), "lines_with_control_chars_stripped": dirty}
    want = int(cfg.expected("PRODUCT_CODE_ROWS"))
    if len(batch) != want:
        raise CountMismatch(f"Product codes: expected {want}, found {len(batch)}")
    return report


def cross_counts(con: sqlite3.Connection) -> dict:
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "starting_set_in_fda_master": q("SELECT COUNT(*) FROM clearances c JOIN fda_master m USING(knumber)"),
        "starting_set_not_in_fda_master": q("SELECT COUNT(*) FROM clearances c WHERE knumber NOT IN (SELECT knumber FROM fda_master)"),
        "starting_set_product_code_not_in_classification": q(
            "SELECT COUNT(*) FROM clearances WHERE product_code IS NOT NULL AND product_code NOT IN (SELECT product_code FROM product_codes)"),
        "fda_master_by_panel_OR": q("SELECT COUNT(*) FROM fda_master WHERE review_panel='OR'"),
    }
