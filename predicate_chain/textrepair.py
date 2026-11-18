"""Repair text that lost special characters before it reached the database.

The starting-set workbook was saved with Unicode replacement characters (U+FFFD) where the FDA release files
have registered and trademark signs, en dashes, accented letters and similar. The FDA release files themselves
(table fda_master) hold the correct characters. A value is repaired only when the FDA value for the same
510(k) has the same length and matches every character that is not a replacement character, so nothing is
guessed. Values that fail that test are left as they are and reported.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

BAD = "�"

# (table, key column holding a 510(k) number, {column in table: column in fda_master})
SQLITE_TARGETS = [
    ("clearances", "knumber", {"applicant": "applicant", "contact": "contact", "street1": "street1",
                               "street2": "street2", "city": "city", "devicename": "devicename"}),
    ("edges", "predicate_number", {"fda_applicant": "applicant", "fda_device_name": "devicename"}),
]


def pattern_match(broken: str | None, good: str | None) -> bool:
    """True when good could be broken with each replacement character restored (and nothing else differs)."""
    if not broken or not good or BAD not in broken or BAD in good or len(broken) != len(good):
        return False
    return all(b == g or b == BAD for b, g in zip(broken, good))


@dataclass
class RepairResult:
    fixed: dict = field(default_factory=dict)        # (table, column) -> rows fixed
    left: dict = field(default_factory=dict)         # (table, column) -> rows left as they were
    left_examples: list = field(default_factory=list)
    applicant_map: dict = field(default_factory=dict)  # broken applicant -> repaired applicant (unambiguous only)
    portfolio_rows: list = field(default_factory=list)  # (knumber, devicename, applicant) after repair, for changed rows
    characters: dict = field(default_factory=dict)   # restored character -> count


def repair_sqlite(con: sqlite3.Connection, write: bool = True) -> RepairResult:
    res = RepairResult()
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    applicant_seen: dict[str, set] = {}
    changed_k: set[str] = set()
    for table, key, cols in SQLITE_TARGETS:
        if table not in tables:
            continue
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for col, mcol in cols.items():
            if col not in have:
                continue
            rows = con.execute(
                f"""SELECT t.rowid, t.{key}, t.{col}, m.{mcol} FROM {table} t
                    LEFT JOIN fda_master m ON m.knumber = t.{key}
                    WHERE instr(t.{col}, ?) > 0""", (BAD,)).fetchall()
            n_fix = n_left = 0
            for rowid, k, broken, good in rows:
                if pattern_match(broken, good):
                    n_fix += 1
                    for b, g in zip(broken, good):
                        if b == BAD:
                            res.characters[g] = res.characters.get(g, 0) + 1
                    if write:
                        con.execute(f"UPDATE {table} SET {col} = ? WHERE rowid = ?", (good, rowid))
                    if table == "clearances":
                        changed_k.add(k)
                        if col == "applicant":
                            applicant_seen.setdefault(broken, set()).add(good)
                else:
                    n_left += 1
                    if len(res.left_examples) < 20:
                        res.left_examples.append((table, col, k, broken, good))
            if n_fix:
                res.fixed[(table, col)] = n_fix
            if n_left:
                res.left[(table, col)] = n_left
    if write:
        con.commit()
    res.applicant_map = {b: next(iter(g)) for b, g in applicant_seen.items() if len(g) == 1}
    if changed_k and write:
        q = ",".join("?" * len(changed_k))
        res.portfolio_rows = con.execute(
            f"SELECT knumber, devicename, applicant FROM clearances WHERE knumber IN ({q}) ORDER BY knumber",
            sorted(changed_k)).fetchall()
    elif changed_k:
        res.portfolio_rows = [(k, None, None) for k in sorted(changed_k)]
    return res


def repair_duckdb(con, applicant_map: dict, write: bool = True) -> dict:
    """Carry repaired applicant names into the vendor registry (payments.duckdb), so vendor lookups by applicant
    name keep working and display names read correctly. Only exact matches of a broken name are replaced."""
    out = {"vendor_entities": 0, "vendors": 0, "vendor_rows": [], "name_rows": []}
    tables = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if not applicant_map:
        return out
    if "vendor_entities" in tables:
        rows = con.execute("SELECT DISTINCT vendor_id, source, raw_name FROM vendor_entities WHERE raw_name LIKE ?",
                           [f"%{BAD}%"]).fetchall()
        for vid, src, raw in rows:
            new = applicant_map.get(raw)
            if not new:
                continue
            out["name_rows"].append((vid, src, raw, new))
            if write:
                con.execute("UPDATE vendor_entities SET raw_name = ? WHERE raw_name = ?", [new, raw])
                con.execute("UPDATE vendor_entities SET entity_key = ? WHERE source = 'applicant' AND entity_key = ?",
                            [new, raw])
            out["vendor_entities"] += 1
    if "vendors" in tables:
        rows = con.execute("SELECT vendor_id, display_name FROM vendors WHERE display_name LIKE ?", [f"%{BAD}%"]).fetchall()
        for vid, name in rows:
            new = applicant_map.get(name)
            if not new:
                continue
            out["vendor_rows"].append((vid, name, new))
            if write:
                con.execute("UPDATE vendors SET display_name = ? WHERE vendor_id = ?", [new, vid])
            out["vendors"] += 1
    return out


def sql_literal(s: str | None) -> str:
    return "NULL" if s is None else "'" + s.replace("'", "''") + "'"


def supabase_patch(portfolio_rows: list, vendor_rows: list, name_rows: list) -> str:
    """UPDATE statements that apply the same repair to the Supabase tables, so nothing needs re-importing."""
    lines = ["-- OrthoParity text repair: restores registered and trademark signs, dashes and accented letters",
             "-- that were lost before import. Generated by repair_text.py. Safe to run more than once.", ""]
    if portfolio_rows:
        vals = ",\n  ".join(f"({sql_literal(k)}, {sql_literal(n)}, {sql_literal(a)})" for k, n, a in portfolio_rows)
        lines += ["update pc_portfolio_510k p set device_name = v.device_name, applicant = v.applicant",
                  f"from (values\n  {vals}\n) as v(knumber, device_name, applicant)",
                  "where p.knumber = v.knumber;", ""]
    for vid, old, new in vendor_rows:
        lines.append(f"update pc_vendors set display_name = {sql_literal(new)} where vendor_id = {sql_literal(vid)};")
    for vid, src, old, new in name_rows:
        lines.append(f"update pc_vendor_names set raw_name = {sql_literal(new)} where vendor_id = {sql_literal(vid)} "
                     f"and raw_name = {sql_literal(old)};")
    lines += ["", "select count(*) as names_still_broken from pc_portfolio_510k where device_name like '%' || chr(65533) || '%';", ""]
    return "\n".join(lines)
