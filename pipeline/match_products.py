"""Phase B2: link Open Payments product tags to devices, brands and 510(k) numbers.

Every product slot on a kept payment (op_products) gets one tier:
  1 device ID   its device ID (PDI) is in GUDID; the device's 510(k) numbers, product codes and brand follow
  2 brand       no usable device ID, but the product name matches a GUDID brand name of the same vendor
                (cleaned of generic words like System, Implant or Primary): exact match, or the brand appears
                inside the reported name, or the reported name starts the brand (6 or more letters). Brands that
                are only the company's own name (for example "Integra" or "Biomet") never match, and neither do
                reported names that are only the company's name ("Zimmer Biomet Instruments and Implants").
  3 name only   a product name or category that ties to no device or brand (counted at vendor level only)
Tier 1 and 2 never guess across vendors: a brand match only looks at the paying vendor's own labelers.

Writes op_product_match (one row per product slot), op_product_k (slot -> 510(k) number, tier 1 only) and
outputs/Product_Match_Report.txt plus outputs/Product_Match_Sample.xlsx (100 random rows per tier to check).
Needs build-vendor-registry first.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

from predicate_chain.config import load_config
from predicate_chain.paycommon import PaySettings, connect_duck, mark_step, step_done

BRAND_STOP = ["SYSTEM", "SYSTEMS", "IMPLANT", "IMPLANTS", "INSTRUMENT", "INSTRUMENTS", "SET", "KIT", "THE", "AND",
              "WITH", "FOR", "PLATFORM", "TECHNOLOGY", "DEVICE", "DEVICES", "FAMILY", "PLATE", "PLATES", "SCREW",
              "SCREWS", "SPINAL", "SPINE", "KNEE", "HIP", "SHOULDER", "TOTAL", "ORTHOPEDIC", "ORTHOPAEDIC",
              "PRIMARY", "REVISION", "TRAUMA", "EXTREMITY", "EXTREMITIES", "SPORTS", "MEDICINE", "FOOT", "ANKLE",
              "HAND", "WRIST", "ELBOW", "CERVICAL", "LUMBAR", "THORACIC", "FIXATION", "PEDICLE", "INTERBODY",
              "CAGE", "BONE", "GRAFT", "PRODUCT", "PRODUCTS", "ACCESSORIES", "GENERAL", "REPLACEMENT",
              "ARTHROPLASTY", "SURGICAL", "MEDICAL", "NA"]
NA_NAMES = ["NA", "N/A", "NONE", "NOT APPLICABLE", "UNKNOWN", "OTHER", "MISC", "MISCELLANEOUS", "GENERAL"]


def brand_key_sql(col: str) -> str:
    """SQL expression: upper case, drop trademark signs and punctuation, drop generic words, squeeze spaces."""
    stop = "|".join(BRAND_STOP)
    return (f"trim(regexp_replace(regexp_replace(regexp_replace(upper(coalesce({col}, '')), '[®™©]', '', 'g'), "
            f"'[^A-Z0-9 ]', ' ', 'g'), '\\b({stop})\\b', ' ', 'g'))")


def squeeze(expr: str) -> str:
    return f"regexp_replace(trim({expr}), '\\s+', ' ', 'g')"


def run(con) -> dict:
    t0 = time.monotonic()
    con.execute("""CREATE OR REPLACE TEMP TABLE payer_vendor AS
                   SELECT entity_key AS payer_id, vendor_id FROM vendor_entities WHERE source = 'payer'""")
    con.execute("""CREATE OR REPLACE TEMP TABLE labeler_vendor AS
                   SELECT entity_key AS duns, vendor_id FROM vendor_entities WHERE source = 'labeler'""")
    # payer for every product slot (general and research)
    con.execute("""CREATE OR REPLACE TEMP TABLE slots AS
        SELECT p.*, g.payer_id FROM op_products p JOIN op_general g ON g.record_id = p.record_id AND g.year = p.year
        WHERE p.source = 'general'
        UNION ALL
        SELECT p.*, r.payer_id FROM op_products p JOIN op_research r ON r.record_id = p.record_id AND r.year = p.year
        WHERE p.source = 'research'""")
    # tier 1: device ID found in GUDID
    con.execute("""CREATE OR REPLACE TEMP TABLE t1 AS
        SELECT s.source, s.year, s.record_id, s.slot, i.primary_di
        FROM slots s JOIN gudid_identifiers i ON i.di = s.pdi_norm""")
    con.execute("CREATE OR REPLACE TEMP TABLE t1u AS SELECT source, year, record_id, slot, min(primary_di) AS primary_di FROM t1 GROUP BY ALL")
    # brand index per vendor (orthopedic devices only)
    bk = squeeze(brand_key_sql("d.brand"))
    con.execute(f"""CREATE OR REPLACE TEMP TABLE brands AS
        SELECT lv.vendor_id, {bk} AS bkey, mode(d.brand) AS brand, count(DISTINCT d.primary_di) AS devices
        FROM gudid_devices d JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o ON o.primary_di = d.primary_di
        JOIN labeler_vendor lv ON lv.duns = d.duns
        WHERE {bk} <> '' GROUP BY 1, 2""")
    nk = squeeze(brand_key_sql("s.name"))
    na = "', '".join(NA_NAMES)
    con.execute(f"""CREATE OR REPLACE TEMP TABLE named AS
        SELECT s.source, s.year, s.record_id, s.slot, pv.vendor_id, {nk} AS nkey
        FROM slots s JOIN payer_vendor pv ON pv.payer_id = s.payer_id
        LEFT JOIN t1u ON t1u.source = s.source AND t1u.year = s.year AND t1u.record_id = s.record_id AND t1u.slot = s.slot
        WHERE t1u.primary_di IS NULL AND upper(trim(coalesce(s.name, ''))) NOT IN ('{na}') AND {nk} <> ''""")
    # words of the vendor's own company names: a brand made only of them (for example "Integra" or "Biomet")
    # names the company, not a product, and never matches
    con.execute("""CREATE OR REPLACE TEMP TABLE vendor_words AS
        SELECT DISTINCT vendor_id, w FROM (
          SELECT vendor_id, unnest(string_split(regexp_replace(upper(raw_name), '[^A-Z0-9]+', ' ', 'g'), ' ')) AS w
          FROM vendor_entities) WHERE length(w) >= 3""")
    con.execute("""CREATE OR REPLACE TEMP TABLE brand_ok AS
        SELECT b.vendor_id, b.bkey FROM brands b
        WHERE EXISTS (SELECT 1 FROM (SELECT unnest(string_split(b.bkey, ' ')) AS w) x
                      WHERE x.w <> '' AND NOT EXISTS (SELECT 1 FROM vendor_words v
                                                      WHERE v.vendor_id = b.vendor_id AND v.w = x.w))""")
    # exact match first; else the brand inside the reported name (brand 6+ letters); else the reported name as
    # the start of a brand (name 6+ letters). Longest brand wins.
    con.execute("""CREATE OR REPLACE TEMP TABLE t2 AS
        WITH c AS (
          SELECT n.source, n.year, n.record_id, n.slot, b.vendor_id, b.bkey, b.brand,
                 CASE WHEN n.nkey = b.bkey THEN 0 ELSE 1 END AS rank_exact, length(b.bkey) AS blen
          FROM named n JOIN brands b ON b.vendor_id = n.vendor_id
          JOIN brand_ok k ON k.vendor_id = b.vendor_id AND k.bkey = b.bkey
          WHERE EXISTS (SELECT 1 FROM (SELECT unnest(string_split(n.nkey, ' ')) AS w) x
                        WHERE x.w <> '' AND NOT EXISTS (SELECT 1 FROM vendor_words v
                                                        WHERE v.vendor_id = n.vendor_id AND v.w = x.w))
            AND (
                n.nkey = b.bkey
             OR (length(b.bkey) >= 6 AND contains(' ' || n.nkey || ' ', ' ' || b.bkey || ' '))
             OR (length(n.nkey) >= 6 AND starts_with(b.bkey || ' ', n.nkey || ' '))))
        SELECT source, year, record_id, slot, arg_min(bkey, rank_exact * 1000 - blen) AS bkey,
               arg_min(brand, rank_exact * 1000 - blen) AS brand, any_value(vendor_id) AS vendor_id
        FROM c GROUP BY ALL""")
    con.execute("""CREATE OR REPLACE TABLE op_product_match AS
        SELECT s.source, s.year, s.record_id, s.slot, s.payer_id, pv.vendor_id AS payer_vendor,
               CASE WHEN t1u.primary_di IS NOT NULL THEN 1 WHEN t2.bkey IS NOT NULL THEN 2 ELSE 3 END AS tier,
               t1u.primary_di, d.brand AS device_brand, lv.vendor_id AS device_vendor, t2.bkey AS brand_key,
               t2.brand AS matched_brand,
               (o.primary_di IS NOT NULL OR t2.bkey IS NOT NULL) AS ortho_product
        FROM slots s
        LEFT JOIN payer_vendor pv ON pv.payer_id = s.payer_id
        LEFT JOIN t1u ON t1u.source = s.source AND t1u.year = s.year AND t1u.record_id = s.record_id AND t1u.slot = s.slot
        LEFT JOIN gudid_devices d ON d.primary_di = t1u.primary_di
        LEFT JOIN labeler_vendor lv ON lv.duns = d.duns
        LEFT JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o ON o.primary_di = t1u.primary_di
        LEFT JOIN t2 ON t2.source = s.source AND t2.year = s.year AND t2.record_id = s.record_id AND t2.slot = s.slot""")
    con.execute("""CREATE OR REPLACE TABLE op_product_k AS
        SELECT DISTINCT m.source, m.year, m.record_id, m.slot, g.submission_number AS knumber
        FROM op_product_match m JOIN gudid_submissions g ON g.primary_di = m.primary_di
        WHERE m.tier = 1 AND (g.submission_number LIKE 'K%' OR g.submission_number LIKE 'DEN%')""")
    q = lambda sql: con.execute(sql).fetchall()
    stats = {"slots": q("SELECT count(*) FROM op_product_match")[0][0],
             "by_year_tier": q("""SELECT year, tier, count(*), count(*) FILTER (WHERE ortho_product)
                                  FROM op_product_match GROUP BY ALL ORDER BY 1, 2"""),
             "k_links": q("SELECT count(*), count(DISTINCT knumber) FROM op_product_k")[0],
             "seconds": time.monotonic() - t0}
    return stats


def write_outputs(con, cfg, stats):
    lines = ["OrthoParity: Phase B2, product matching", "",
             f"Product slots: {stats['slots']:,}",
             f"Tier 1 links to 510(k) numbers: {stats['k_links'][0]:,} slot-to-K links, {stats['k_links'][1]:,} distinct K-numbers",
             "", f"{'Year':<6}{'Tier':>5}{'Slots':>12}{'Orthopedic':>12}"]
    for y, t, n, o in stats["by_year_tier"]:
        lines.append(f"{y:<6}{t:>5}{n:>12,}{o:>12,}")
    lines += ["", "Tier 1 = device ID found in GUDID; 2 = brand name of the same vendor; 3 = name or category only.",
              "CMS did not collect device IDs before 2021, so 2019 and 2020 rely on tier 2.",
              "Check outputs/Product_Match_Sample.xlsx (100 random rows per tier) before Phase C."]
    (cfg.output_dir / "Product_Match_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "Sample"
    ws.append(["Random sample of product tags and what they matched. Type Y or N in the yellow column: is the match right?"])
    cols = ["Tier", "Year", "Paying company", "Product name as reported", "Category as reported", "Device ID reported",
            "Matched brand (GUDID)", "Matched device company", "510(k) numbers", "Right? (Y/N)", "Notes"]
    ws.append(cols)
    for c in ws[2]:
        c.font = Font(name="Arial", bold=True)
    rows = con.execute("""
        WITH s AS (SELECT * FROM op_product_match WHERE tier IN (1, 2) AND ortho_product
                   UNION ALL SELECT * FROM op_product_match WHERE tier = 3)
        SELECT tier, year, payer_id, record_id, slot, source, primary_di, matched_brand, device_brand
        FROM (SELECT *, row_number() OVER (PARTITION BY tier ORDER BY hash(record_id || slot::VARCHAR || '2026')) AS rn FROM s)
        WHERE rn <= 100 ORDER BY tier, rn""").fetchall()
    for tier, year, pid, rid, slot, source, pdi, mbrand, dbrand in rows:
        p = con.execute("""SELECT p.name, p.category, p.pdi FROM op_products p
                           WHERE p.record_id = ? AND p.year = ? AND p.slot = ? AND p.source = ?""",
                        [rid, year, slot, source]).fetchone()
        payer = con.execute("SELECT payer_name FROM payer_scope WHERE payer_id = ?", [pid]).fetchone()
        dev = con.execute("SELECT company FROM gudid_devices WHERE primary_di = ?", [pdi]).fetchone() if pdi else None
        ks = [r[0] for r in con.execute("""SELECT knumber FROM op_product_k WHERE record_id = ? AND year = ? AND slot = ?
                                            AND source = ? ORDER BY 1 LIMIT 6""", [rid, year, slot, source]).fetchall()]
        ws.append([tier, year, payer[0] if payer else pid, p[0] if p else "", p[1] if p else "", p[2] if p else "",
                   mbrand or dbrand or "", dev[0] if dev else "", ", ".join(ks), None, None])
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for i in range(2, ws.max_row + 1):
        for j in (10, 11):
            ws.cell(row=i, column=j).fill = yellow
    for j, w in enumerate([6, 6, 30, 40, 26, 18, 30, 30, 30, 10, 30], start=1):
        ws.column_dimensions[ws.cell(row=2, column=j).column_letter].width = w
    path = cfg.output_dir / "Product_Match_Sample.xlsx"
    wb.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    if not step_done(con, "B1_registry"):
        print("Run build_vendor_registry.py first.")
        return 1
    stats = run(con)
    write_outputs(con, cfg, stats)
    mark_step(con, "B2_match", stats["slots"], stats["seconds"], f"k_links={stats['k_links'][0]}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
