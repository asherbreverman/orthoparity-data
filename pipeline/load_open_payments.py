"""Phase A2: load CMS Open Payments (program years 2019 to 2025) into data/payments.duckdb.

Runs after index-gudid (it needs the GUDID index to find orthopedic payers). Steps, each resumable:

  1. Scan   every general and research file for the products each payer tagged (op_payer_products).
  2. Scope  mark orthopedic payers (payer_scope): a payer is in scope when device IDs that GUDID maps to an
            orthopedic product code make up 1% or more of its product tags (or 500 tags or more); or 5% or more
            of its tags are devices, supplies or biologics whose category or name reads as orthopedic; or it
            shares a name with a 510(k) applicant in the predicate database and either has under 1,000 tags or
            1% or more orthopedic tags. The share rules keep out companies like a pharma affiliate that tags a
            sister company's implant a handful of times. Pharma, wound care, dental and neurostimulation wording never counts.
            This only decides which rows to keep; the vendor registry (Phase B) decides who is a vendor.
  3. Load   op_general and op_research: every row from an in-scope payer, plus every row to a recipient with
            an orthopedic, neurosurgery or podiatry specialty (kept for validation against published figures).
            op_ownership: every row. op_products: one row per product slot (up to 5 per payment).
  4. Remove records listed in the CMS removed or deleted files.
  5. Report outputs/PhaseA2_OpenPayments_Report.txt

No names of individual recipients are loaded.
Usage:  python orthoparity.py load-open-payments   (after index-gudid)
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from predicate_chain.config import load_config
from predicate_chain.paycommon import (PaySettings, company_root, Progress, StopRequested, check_stop, connect_duck,
                                       keep_awake, mark_step, step_done)

# Bump when the load logic changes: earlier A2 steps are then redone automatically on the next run.
LOADER_VERSION = "1.3"

EXCLUDE_PRODUCT_REGEX = r"wound|skin|dental|orthodont|denture|cardi|vascular|neurostim|spinal cord stim|dorsal root|pain pump|diabet|insulin|ophthal|hearing"

CSV_OPTS = "header=true, all_varchar=true, delim=',', quote='\"', escape='\"', max_line_size=20000000, store_rejects=true"


def _cat(prefix: str, n: int = 6, sep: str = "|") -> str:
    cols = ", ".join(f"nullif(trim({prefix}{i}), '')" for i in range(1, n + 1))
    return f"concat_ws('{sep}', {cols})"


def _slots(source: str) -> str:
    """List of up to five product-slot structs for unnest()."""
    items = []
    for i in range(1, 6):
        items.append(f"{{'slot': {i}, 'covered': Covered_or_Noncovered_Indicator_{i}, "
                     f"'type': Indicate_Drug_or_Biological_or_Device_or_Medical_Supply_{i}, "
                     f"'category': Product_Category_or_Therapeutic_Area_{i}, "
                     f"'name': Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_{i}, "
                     f"'pdi': Associated_Device_or_Medical_Supply_PDI_{i}}}")
    return "[" + ", ".join(items) + "]"


_PDI_CLEAN = "regexp_replace(upper(trim(coalesce({c}, ''))), '^\\(01\\)|[\\s\\-]', '', 'g')"
# Blank, N/A, NONE, NOT APPLICABLE, UNKNOWN or all zeros -> NULL; 8 to 14 digits -> 14-digit GTIN; else as written.
PDI_NORM = ("CASE WHEN regexp_full_match(" + _PDI_CLEAN + ", '(N/?A|NONE|NOTAPPLICABLE|UNKNOWN|0*)') THEN NULL "
            "WHEN regexp_full_match(" + _PDI_CLEAN + ", '[0-9]{{8,14}}') THEN lpad(" + _PDI_CLEAN + ", 14, '0') "
            "ELSE " + _PDI_CLEAN + " END")
# A product slot counts only when it holds something other than blanks or N/A fillers (2019 and 2020 files fill
# every empty slot with N/A).
SLOT_USED = ("(NOT op_blank(s.type) OR NOT op_blank(s.name) OR NOT op_blank(s.category) "
             "OR " + PDI_NORM.format(c='s.pdi') + " IS NOT NULL)")


def rejects(con) -> int:
    try:
        return con.execute("SELECT count(*) FROM reject_errors").fetchone()[0]
    except Exception:
        return 0


def create_tables(con):
    con.execute("""CREATE OR REPLACE TEMP MACRO op_blank(x) AS
                   regexp_full_match(upper(trim(coalesce(x, ''))), '(N/?A|NONE|NOT APPLICABLE|UNKNOWN|)')""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_payer_products (year INT, source VARCHAR, payer_id VARCHAR,
        payer_name VARCHAR, type VARCHAR, category VARCHAR, name VARCHAR, pdi VARCHAR, pdi_norm VARCHAR,
        n BIGINT, amount DOUBLE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_payers (year INT, source VARCHAR, payer_id VARCHAR,
        payer_name VARCHAR, rows BIGINT, amount DOUBLE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_general (year INT, record_id VARCHAR, change_type VARCHAR,
        recipient_type VARCHAR, teaching_hospital_ccn VARCHAR, profile_id VARCHAR, npi VARCHAR,
        recipient_state VARCHAR, recipient_country VARCHAR, primary_types VARCHAR, specialties VARCHAR,
        submitting_name VARCHAR, payer_id VARCHAR, payer_name VARCHAR, payer_state VARCHAR, payer_country VARCHAR,
        amount DOUBLE, pay_date DATE, n_payments INT, form VARCHAR, nature VARCHAR, physician_ownership VARCHAR,
        third_party VARCHAR, charity VARCHAR, third_party_is_recipient VARCHAR, delayed VARCHAR, dispute VARCHAR,
        related_product VARCHAR, ortho_recipient BOOLEAN, payer_in_scope BOOLEAN)""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_research (year INT, record_id VARCHAR, change_type VARCHAR,
        recipient_type VARCHAR, noncovered_entity VARCHAR, teaching_hospital_ccn VARCHAR,
        teaching_hospital_name VARCHAR, profile_id VARCHAR, npi VARCHAR, specialties VARCHAR,
        pi1_npi VARCHAR, pi2_npi VARCHAR, pi3_npi VARCHAR, pi4_npi VARCHAR, pi5_npi VARCHAR, pi1_specialties VARCHAR,
        submitting_name VARCHAR, payer_id VARCHAR, payer_name VARCHAR, payer_state VARCHAR, payer_country VARCHAR,
        amount DOUBLE, pay_date DATE, form VARCHAR, expenditure VARCHAR, preclinical VARCHAR, delayed VARCHAR,
        study_name VARCHAR, dispute VARCHAR, ct_gov_id VARCHAR, related_product VARCHAR,
        ortho_recipient BOOLEAN, payer_in_scope BOOLEAN)""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_ownership (year INT, record_id VARCHAR, change_type VARCHAR,
        profile_id VARCHAR, npi VARCHAR, primary_type VARCHAR, specialty VARCHAR, invested DOUBLE, value DOUBLE,
        terms VARCHAR, interest_holder VARCHAR, submitting_name VARCHAR, payer_id VARCHAR, payer_name VARCHAR,
        dispute VARCHAR)""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_products (source VARCHAR, year INT, record_id VARCHAR, slot INT,
        covered VARCHAR, type VARCHAR, category VARCHAR, name VARCHAR, pdi VARCHAR, pdi_norm VARCHAR)""")
    con.execute("""CREATE TABLE IF NOT EXISTS op_removed (year INT, payment_type VARCHAR, change_type VARCHAR,
        record_id VARCHAR)""")


def scan_products(con, ps: PaySettings, year: int, kind: str) -> int:
    path = ps.op_file(year, kind).as_posix()
    source = "general" if kind == "general" else "research"
    con.execute("DELETE FROM op_payer_products WHERE year = ? AND source = ?", [year, source])
    con.execute(f"""
        INSERT INTO op_payer_products
        SELECT {year}, '{source}', payer_id, any_value(payer_name), s.type, s.category, s.name, s.pdi,
               {PDI_NORM.format(c='s.pdi')}, count(*), sum(amount)
        FROM (SELECT Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID AS payer_id,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name AS payer_name,
                     try_cast(Total_Amount_of_Payment_USDollars AS DOUBLE) AS amount,
                     unnest({_slots(source)}) AS s
              FROM read_csv('{path}', {CSV_OPTS}))
        WHERE {SLOT_USED}
        GROUP BY ALL""")
    con.execute("DELETE FROM op_payers WHERE year = ? AND source = ?", [year, source])
    con.execute(f"""
        INSERT INTO op_payers
        SELECT {year}, '{source}', Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID,
               any_value(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name), count(*),
               sum(try_cast(Total_Amount_of_Payment_USDollars AS DOUBLE))
        FROM read_csv('{path}', {CSV_OPTS}) GROUP BY ALL""")
    return con.execute("SELECT count(*) FROM op_payer_products WHERE year = ? AND source = ?",
                       [year, source]).fetchone()[0]


def build_scope(con, cfg, ps: PaySettings) -> dict:
    db = cfg.db_path
    sq = sqlite3.connect(str(db))
    codes = [r[0] for r in sq.execute("SELECT DISTINCT product_code FROM clearances WHERE product_code IS NOT NULL")]
    roots = {company_root(r[0]) for r in sq.execute("SELECT DISTINCT applicant FROM clearances")}
    sq.close()
    roots.discard("")
    con.execute("CREATE OR REPLACE TABLE ortho_codes (product_code VARCHAR PRIMARY KEY)")
    con.executemany("INSERT INTO ortho_codes VALUES (?)", [[c] for c in codes])
    con.execute("""CREATE OR REPLACE TABLE gudid_ortho_di AS
        SELECT DISTINCT i.di AS di, i.primary_di
        FROM gudid_identifiers i JOIN gudid_product_codes p ON p.primary_di = i.primary_di
        JOIN ortho_codes o ON o.product_code = p.product_code""")
    payers = con.execute("""SELECT payer_id, arg_max(payer_name, year) FROM op_payers GROUP BY payer_id""").fetchall()
    con.execute("CREATE OR REPLACE TABLE payer_names (payer_id VARCHAR, payer_name VARCHAR, applicant_match BOOLEAN)")
    con.executemany("INSERT INTO payer_names VALUES (?, ?, ?)",
                    [[pid, name, company_root(name) in roots] for pid, name in payers])
    inc, exc = ps.product_regex.lower(), EXCLUDE_PRODUCT_REGEX
    con.execute(f"""CREATE OR REPLACE TABLE payer_scope AS
        WITH pp AS (
          SELECT p.*, (g.di IS NOT NULL) AS pdi_ortho,
                 (lower(coalesce(p.type, '')) IN ('device', 'medical supply', 'biological')
                  AND regexp_matches(lower(coalesce(p.category, '') || ' ' || coalesce(p.name, '')), '{inc}')
                  AND NOT regexp_matches(lower(coalesce(p.category, '') || ' ' || coalesce(p.name, '')), '{exc}')) AS text_ortho,
                 lower(coalesce(p.type, '')) IN ('device', 'medical supply') AS is_device
          FROM op_payer_products p LEFT JOIN (SELECT DISTINCT di FROM gudid_ortho_di) g ON g.di = p.pdi_norm)
        , agg AS (
          SELECT n.payer_id, n.payer_name, n.applicant_match,
                 coalesce(sum(pp.n), 0) AS slots,
                 coalesce(sum(pp.n) FILTER (WHERE pp.is_device), 0) AS device_slots,
                 coalesce(sum(pp.n) FILTER (WHERE lower(coalesce(pp.type, '')) IN ('device', 'medical supply', 'biological')), 0) AS device_bio_slots,
                 coalesce(sum(pp.n) FILTER (WHERE pp.pdi_ortho), 0) AS pdi_ortho_slots,
                 coalesce(sum(pp.n) FILTER (WHERE pp.text_ortho), 0) AS text_ortho_slots
          FROM payer_names n LEFT JOIN pp ON pp.payer_id = n.payer_id
          GROUP BY n.payer_id, n.payer_name, n.applicant_match)
        SELECT *, CASE
            WHEN pdi_ortho_slots > 0 AND (pdi_ortho_slots >= 0.01 * slots OR pdi_ortho_slots >= 500)
                THEN 'device ID maps to an orthopedic product code'
            WHEN text_ortho_slots > 0 AND text_ortho_slots >= 0.05 * slots THEN 'orthopedic product wording (5% or more of tags)'
            WHEN applicant_match AND (slots < 1000 OR pdi_ortho_slots + text_ortho_slots >= 0.01 * slots)
                THEN 'same name as a 510(k) applicant'
            END AS scope_reason,
          scope_reason IS NOT NULL AS in_scope
        FROM agg""")
    q = lambda s: con.execute(s).fetchone()[0]
    return {"payers_seen": q("SELECT count(*) FROM payer_scope"),
            "payers_in_scope": q("SELECT count(*) FROM payer_scope WHERE in_scope"),
            "in_scope_by_device_id": q("SELECT count(*) FROM payer_scope WHERE scope_reason LIKE 'device ID%'"),
            "in_scope_by_wording": q("SELECT count(*) FROM payer_scope WHERE scope_reason LIKE 'orthopedic product wording%'"),
            "in_scope_by_applicant_name": q("SELECT count(*) FROM payer_scope WHERE scope_reason LIKE 'same name%'"),
            "out_of_scope_with_some_orthopedic_tags": q("SELECT count(*) FROM payer_scope WHERE NOT in_scope AND pdi_ortho_slots + text_ortho_slots > 0"),
            "ortho_product_codes": len(codes), "gudid_ortho_identifiers": q("SELECT count(*) FROM gudid_ortho_di")}


def load_general(con, ps: PaySettings, year: int) -> int:
    path = ps.op_file(year, "general").as_posix()
    rx = ps.specialty_regex.lower()
    con.execute("DELETE FROM op_general WHERE year = ?", [year])
    con.execute("DELETE FROM op_products WHERE year = ? AND source = 'general'", [year])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE g AS
        SELECT r.*, regexp_matches(lower(r.specialties), '{rx}') AS ortho_recipient,
               (s.payer_id IS NOT NULL) AS payer_in_scope
        FROM (SELECT Record_ID AS record_id, Change_Type AS change_type, Covered_Recipient_Type AS recipient_type,
                     Teaching_Hospital_CCN AS teaching_hospital_ccn, Covered_Recipient_Profile_ID AS profile_id,
                     Covered_Recipient_NPI AS npi, Recipient_State AS recipient_state,
                     Recipient_Country AS recipient_country, {_cat('Covered_Recipient_Primary_Type_')} AS primary_types,
                     {_cat('Covered_Recipient_Specialty_', sep=' || ')} AS specialties,
                     Submitting_Applicable_Manufacturer_or_Applicable_GPO_Name AS submitting_name,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID AS payer_id,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name AS payer_name,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_State AS payer_state,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Country AS payer_country,
                     try_cast(Total_Amount_of_Payment_USDollars AS DOUBLE) AS amount,
                     try_strptime(Date_of_Payment, ['%m/%d/%Y', '%Y-%m-%d'])::DATE AS pay_date,
                     try_cast(Number_of_Payments_Included_in_Total_Amount AS INT) AS n_payments,
                     Form_of_Payment_or_Transfer_of_Value AS form, Nature_of_Payment_or_Transfer_of_Value AS nature,
                     Physician_Ownership_Indicator AS physician_ownership,
                     Third_Party_Payment_Recipient_Indicator AS third_party, Charity_Indicator AS charity,
                     Third_Party_Equals_Covered_Recipient_Indicator AS third_party_is_recipient,
                     Delay_in_Publication_Indicator AS delayed, Dispute_Status_for_Publication AS dispute,
                     Related_Product_Indicator AS related_product, {_slots('general')} AS slots
              FROM read_csv('{path}', {CSV_OPTS})) r
        LEFT JOIN (SELECT payer_id FROM payer_scope WHERE in_scope) s ON s.payer_id = r.payer_id
        WHERE s.payer_id IS NOT NULL OR regexp_matches(lower(r.specialties), '{rx}')""")
    con.execute(f"""INSERT INTO op_general SELECT {year}, record_id, change_type, recipient_type, teaching_hospital_ccn,
        profile_id, npi, recipient_state, recipient_country, primary_types, specialties, submitting_name, payer_id,
        payer_name, payer_state, payer_country, amount, pay_date, n_payments, form, nature, physician_ownership,
        third_party, charity, third_party_is_recipient, delayed, dispute, related_product, ortho_recipient,
        payer_in_scope FROM g""")
    con.execute(f"""INSERT INTO op_products
        SELECT 'general', {year}, record_id, s.slot, s.covered, s.type, s.category, s.name, s.pdi,
               {PDI_NORM.format(c='s.pdi')}
        FROM (SELECT record_id, unnest(slots) AS s FROM g)
        WHERE {SLOT_USED}""")
    n = con.execute("SELECT count(*) FROM g").fetchone()[0]
    con.execute("DROP TABLE g")
    return n


def load_research(con, ps: PaySettings, year: int) -> int:
    path = ps.op_file(year, "research").as_posix()
    rx = ps.specialty_regex.lower()
    con.execute("DELETE FROM op_research WHERE year = ?", [year])
    con.execute("DELETE FROM op_products WHERE year = ? AND source = 'research'", [year])
    con.execute(f"""CREATE OR REPLACE TEMP TABLE r AS
        SELECT x.*, (regexp_matches(lower(x.specialties), '{rx}') OR regexp_matches(lower(x.pi1_specialties), '{rx}'))
                    AS ortho_recipient,
               (s.payer_id IS NOT NULL) AS payer_in_scope
        FROM (SELECT Record_ID AS record_id, Change_Type AS change_type, Covered_Recipient_Type AS recipient_type,
                     Noncovered_Recipient_Entity_Name AS noncovered_entity, Teaching_Hospital_CCN AS teaching_hospital_ccn,
                     Teaching_Hospital_Name AS teaching_hospital_name, Covered_Recipient_Profile_ID AS profile_id,
                     Covered_Recipient_NPI AS npi, {_cat('Covered_Recipient_Specialty_', sep=' || ')} AS specialties,
                     Principal_Investigator_1_NPI AS pi1_npi, Principal_Investigator_2_NPI AS pi2_npi,
                     Principal_Investigator_3_NPI AS pi3_npi, Principal_Investigator_4_NPI AS pi4_npi,
                     Principal_Investigator_5_NPI AS pi5_npi,
                     {_cat('Principal_Investigator_1_Specialty_', sep=' || ')} AS pi1_specialties,
                     Submitting_Applicable_Manufacturer_or_Applicable_GPO_Name AS submitting_name,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID AS payer_id,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name AS payer_name,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_State AS payer_state,
                     Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Country AS payer_country,
                     try_cast(Total_Amount_of_Payment_USDollars AS DOUBLE) AS amount,
                     try_strptime(Date_of_Payment, ['%m/%d/%Y', '%Y-%m-%d'])::DATE AS pay_date,
                     Form_of_Payment_or_Transfer_of_Value AS form,
                     concat_ws(' | ', {", ".join(f"nullif(trim(Expenditure_Category{i}), '')" for i in range(1, 7))}) AS expenditure,
                     Preclinical_Research_Indicator AS preclinical, Delay_in_Publication_Indicator AS delayed,
                     Name_of_Study AS study_name, Dispute_Status_for_Publication AS dispute,
                     ClinicalTrials_Gov_Identifier AS ct_gov_id, Related_Product_Indicator AS related_product,
                     {_slots('research')} AS slots
              FROM read_csv('{path}', {CSV_OPTS})) x
        LEFT JOIN (SELECT payer_id FROM payer_scope WHERE in_scope) s ON s.payer_id = x.payer_id
        WHERE s.payer_id IS NOT NULL OR regexp_matches(lower(x.specialties), '{rx}')
              OR regexp_matches(lower(x.pi1_specialties), '{rx}')""")
    con.execute(f"""INSERT INTO op_research SELECT {year}, record_id, change_type, recipient_type, noncovered_entity,
        teaching_hospital_ccn, teaching_hospital_name, profile_id, npi, specialties, pi1_npi, pi2_npi, pi3_npi,
        pi4_npi, pi5_npi, pi1_specialties, submitting_name, payer_id, payer_name, payer_state, payer_country, amount,
        pay_date, form, expenditure, preclinical, delayed, study_name, dispute, ct_gov_id, related_product,
        ortho_recipient, payer_in_scope FROM r""")
    con.execute(f"""INSERT INTO op_products
        SELECT 'research', {year}, record_id, s.slot, s.covered, s.type, s.category, s.name, s.pdi,
               {PDI_NORM.format(c='s.pdi')}
        FROM (SELECT record_id, unnest(slots) AS s FROM r)
        WHERE {SLOT_USED}""")
    n = con.execute("SELECT count(*) FROM r").fetchone()[0]
    con.execute("DROP TABLE r")
    return n


def load_ownership(con, ps: PaySettings, year: int) -> int:
    path = ps.op_file(year, "ownership").as_posix()
    con.execute("DELETE FROM op_ownership WHERE year = ?", [year])
    con.execute(f"""INSERT INTO op_ownership
        SELECT {year}, Record_ID, Change_Type, Physician_Profile_ID, Physician_NPI, Physician_Primary_Type,
               Physician_Specialty, try_cast(Total_Amount_Invested_USDollars AS DOUBLE),
               try_cast(Value_of_Interest AS DOUBLE), Terms_of_Interest,
               Interest_Held_by_Physician_or_an_Immediate_Family_Member,
               Submitting_Applicable_Manufacturer_or_Applicable_GPO_Name,
               Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_ID,
               Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name, Dispute_Status_for_Publication
        FROM read_csv('{path}', {CSV_OPTS})""")
    return con.execute("SELECT count(*) FROM op_ownership WHERE year = ?", [year]).fetchone()[0]


def apply_removed(con, ps: PaySettings) -> dict:
    con.execute("DELETE FROM op_removed")
    for year in ps.years:
        f = ps.op_file(year, "removed")
        if f is None:
            continue
        con.execute(f"""INSERT INTO op_removed SELECT try_cast(Program_Year AS INT), Payment_Type, Change_Type, Record_ID
                        FROM read_csv('{f.as_posix()}', {CSV_OPTS})""")
    out = {"removed_listed": con.execute("SELECT count(*) FROM op_removed").fetchone()[0]}
    for table, ptype in (("op_general", "General Payments"), ("op_research", "Research Payments"),
                         ("op_ownership", "Ownership")):
        n = con.execute(f"""SELECT count(*) FROM {table} t WHERE EXISTS (SELECT 1 FROM op_removed x
                            WHERE x.record_id = t.record_id AND x.year = t.year AND x.payment_type ILIKE '{ptype}%')""").fetchone()[0]
        con.execute(f"""DELETE FROM {table} t WHERE EXISTS (SELECT 1 FROM op_removed x
                        WHERE x.record_id = t.record_id AND x.year = t.year AND x.payment_type ILIKE '{ptype}%')""")
        out[f"removed_from_{table}"] = n
    con.execute("""DELETE FROM op_products p WHERE p.source = 'general' AND NOT EXISTS
                   (SELECT 1 FROM op_general g WHERE g.record_id = p.record_id AND g.year = p.year)""")
    con.execute("""DELETE FROM op_products p WHERE p.source = 'research' AND NOT EXISTS
                   (SELECT 1 FROM op_research g WHERE g.record_id = p.record_id AND g.year = p.year)""")
    return out


def write_report(con, cfg, ps: PaySettings, scope: dict, removed: dict, rej: int) -> str:
    q = lambda s: con.execute(s).fetchall()
    lines = ["OrthoParity: Phase A2, Open Payments load", ""]
    lines.append("Rows kept by year (general = in-scope payers plus orthopedic, neurosurgery and podiatry recipients)")
    lines.append(f"{'Year':<6}{'General':>12}{'  ortho recip':>14}{'  in-scope payer':>17}{'Research':>11}{'Ownership':>11}{'Products':>11}")
    for (y,) in q("SELECT DISTINCT year FROM op_general ORDER BY 1"):
        g = q(f"SELECT count(*), count(*) FILTER (WHERE ortho_recipient), count(*) FILTER (WHERE payer_in_scope) FROM op_general WHERE year={y}")[0]
        r = q(f"SELECT count(*) FROM op_research WHERE year={y}")[0][0]
        o = q(f"SELECT count(*) FROM op_ownership WHERE year={y}")[0][0]
        p = q(f"SELECT count(*) FROM op_products WHERE year={y}")[0][0]
        lines.append(f"{y:<6}{g[0]:>12,}{g[1]:>14,}{g[2]:>17,}{r:>11,}{o:>11,}{p:>11,}")
    lines.append("")
    lines.append("Product tags on device or medical supply slots, in-scope payers (general payments)")
    for y, n, with_pdi, gudid in q("""SELECT p.year, count(*), count(*) FILTER (WHERE p.pdi_norm IS NOT NULL),
            count(*) FILTER (WHERE i.di IS NOT NULL)
            FROM op_products p JOIN op_general g ON g.record_id = p.record_id AND g.year = p.year AND g.payer_in_scope
            LEFT JOIN (SELECT DISTINCT di FROM gudid_identifiers) i ON i.di = p.pdi_norm
            WHERE p.source = 'general' AND lower(p.type) IN ('device', 'medical supply') GROUP BY 1 ORDER BY 1"""):
        lines.append(f"  {y}: {n:,} device tags, {with_pdi:,} with a device ID ({100*with_pdi/max(n,1):.0f}%), "
                     f"{gudid:,} found in GUDID ({100*gudid/max(n,1):.0f}%)")
    lines.append("")
    lines.append("  CMS did not collect device IDs before program year 2021; 2019 and 2020 product links rely on names.")
    lines.append("")
    lines.append("Payer scope")
    lines += [f"  {k}: {v:,}" for k, v in scope.items()]
    lines.append("")
    lines.append("Removed or deleted records")
    lines += [f"  {k}: {v:,}" for k, v in removed.items()]
    if not any(v for k, v in removed.items() if k.startswith("removed_from")):
        lines.append("  None of the listed records were in the published files (CMS had already dropped them).")
    lines.append("")
    lines.append(f"CSV rows DuckDB could not read: {rej:,}" + ("" if rej == 0 else "  (tell Claude)"))
    a = q("""SELECT count(*), sum(amount), count(DISTINCT payer_id), count(DISTINCT coalesce(npi, profile_id))
             FROM op_general WHERE year = 2025 AND ortho_recipient""")
    if a and a[0][0]:
        lines.append("")
        lines.append("2025 preview, recipients matching the specialty filter (broader than the article's filter; "
                     "Phase C reproduces the article exactly):")
        lines.append(f"  {a[0][0]:,} payments, ${a[0][1]:,.0f}, {a[0][2]:,} payers, {a[0][3]:,} recipients")
    size = ps.db.stat().st_size if ps.db.exists() else 0
    lines.append("")
    lines.append(f"payments.duckdb size: {size/1e9:.2f} GB")
    text = "\n".join(lines) + "\n"
    (cfg.output_dir / "PhaseA2_OpenPayments_Report.txt").write_text(text, encoding="utf-8")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", help="alternative config.ini (tests)")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    if not step_done(con, "A1_gudid"):
        print("Run index-gudid first: python orthoparity.py index-gudid")
        return 1
    create_tables(con)
    v = con.execute("SELECT detail FROM run_steps WHERE step = 'A2_version'").fetchone()
    if v is None or v[0] != LOADER_VERSION:
        n_old = con.execute("SELECT count(*) FROM run_steps WHERE step LIKE 'A2_%'").fetchone()[0]
        if n_old:
            print(f"Loader updated to {LOADER_VERSION}: redoing the Open Payments steps (the GUDID index is kept).")
        con.execute("DELETE FROM run_steps WHERE step LIKE 'A2_%'")
        mark_step(con, "A2_version", None, 0, LOADER_VERSION)
    for y in ps.years:  # fail early on a missing file
        for kind in ("general", "research", "ownership"):
            ps.op_file(y, kind)
    steps = ([(f"A2_scan_{y}_{k}", "scan", y, k) for y in ps.years for k in ("general", "research")]
             + [("A2_scope", "scope", None, None)]
             + [(f"A2_load_{y}_{k}", "load", y, k) for y in ps.years for k in ("general", "research", "ownership")]
             + [("A2_removed", "removed", None, None)])
    prog = Progress(cfg, "payments_phase_a", "OrthoParity: Phase A2, Open Payments load")
    keep_awake(True)
    scope, removed, rej = {}, {}, 0
    try:
        for i, (name, kind, year, part) in enumerate(steps):
            check_stop(cfg)
            if step_done(con, name):
                continue
            prog.write("Loading Open Payments", i, len(steps), f"starting {name}", count_session=False)
            print(f"[{i+1}/{len(steps)}] {name} ...", flush=True)
            t0, before = time.monotonic(), rejects(con)
            if kind == "scan":
                n, detail = scan_products(con, ps, year, part), ""
            elif kind == "scope":
                scope = build_scope(con, cfg, ps)
                n, detail = scope["payers_in_scope"], "; ".join(f"{k}={v}" for k, v in scope.items())
            elif kind == "load":
                n = {"general": load_general, "research": load_research, "ownership": load_ownership}[part](con, ps, year)
                detail = ""
            else:
                removed = apply_removed(con, ps)
                n, detail = removed["removed_listed"], "; ".join(f"{k}={v}" for k, v in removed.items())
            bad = rejects(con) - before
            if bad:
                detail = (detail + f"; unreadable_rows={bad}").strip("; ")
            mark_step(con, name, n, time.monotonic() - t0, detail)
            prog.write("Loading Open Payments", i + 1, len(steps), f"{name}: {n:,} rows in {time.monotonic()-t0:.0f}s")
            print(f"    {n:,} rows, {time.monotonic()-t0:.0f}s" + (f", {bad} unreadable rows" if bad else ""), flush=True)
    except StopRequested as e:
        print(f"Stopped: {e}. Run the same step again to resume.")
        return 2
    finally:
        keep_awake(False)
    if not scope:
        scope = dict(x.split("=") for x in con.execute("SELECT detail FROM run_steps WHERE step='A2_scope'").fetchone()[0].split("; "))
        scope = {k: int(v) for k, v in scope.items()}
    if not removed:
        d = con.execute("SELECT detail FROM run_steps WHERE step='A2_removed'").fetchone()[0]
        removed = {k: int(v) for k, v in (x.split("=") for x in d.split("; ") if not x.startswith("unreadable"))}
    rej = sum(int(x.split("unreadable_rows=")[1]) for (x,) in
              con.execute("SELECT detail FROM run_steps WHERE detail LIKE '%unreadable_rows=%'").fetchall())
    con.execute("CHECKPOINT")
    print(write_report(con, cfg, ps, scope, removed, rej))
    mark_step(con, "A2_report", None, 0, "")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
