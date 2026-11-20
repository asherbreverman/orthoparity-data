"""Phase C3: export the vendor and Open Payments tables for Supabase (outputs/site_data/pc_*.csv) and a size report.

Only listed vendors (at least one orthopedic 510(k)) are exported. No NPI, CMS profile ID or recipient name leaves
the PC: surgeons appear only as an anonymous key in pc_op_relationship.
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
import sys

from predicate_chain import divestitures
from predicate_chain.config import load_config
from predicate_chain.paycommon import PaySettings, connect_duck, mark_step, step_done

EXPORTS = {
    "pc_vendors": """
        SELECT v.vendor_id, v.display_name, v.current_parent, v.segment, v.basis, v.reviewed, v.note,
               v.clearances, v.first_clearance_year, v.last_clearance_year, v.gudid_ortho_devices, v.gudid_brands,
               coalesce(k.kind, 'no payments') AS payment_kind, cp.vendor_current AS rolls_up_to
        FROM vendors v JOIN listed_vendors USING (vendor_id)
        LEFT JOIN vendor_kind k USING (vendor_id)
        LEFT JOIN cur_parent cp USING (vendor_id)  -- parent company from sourced ownership history
        ORDER BY v.clearances DESC, v.vendor_id""",
    "pc_vendor_names": """
        SELECT e.vendor_id, e.source, e.raw_name, e.basis FROM vendor_entities e JOIN listed_vendors USING (vendor_id)
        ORDER BY 1, 2, 3""",
    "pc_vendor_lineage": """
        SELECT vendor_id, parent, relation, valid_from, valid_to, source_url, note, reviewed FROM vendor_lineage
        ORDER BY ALL""",
    "pc_portfolio_brands": """
        SELECT lv.vendor_id, d.brand, string_agg(DISTINCT pc.product_code, '|' ORDER BY pc.product_code) AS product_codes,
               string_agg(DISTINCT s.submission_number, '|' ORDER BY s.submission_number) FILTER (WHERE s.submission_number LIKE 'K%') AS knumbers,
               count(DISTINCT d.primary_di) AS devices,
               count(DISTINCT d.primary_di) FILTER (WHERE d.distribution_status = 'In Commercial Distribution') AS in_distribution,
               bool_or(d.implantable = 'true') AS implantable
        FROM gudid_devices d JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o USING (primary_di)
        JOIN (SELECT entity_key AS duns, vendor_id FROM vendor_entities WHERE source = 'labeler') lv ON lv.duns = d.duns
        JOIN listed_vendors USING (vendor_id)
        LEFT JOIN gudid_product_codes pc ON pc.primary_di = d.primary_di
        LEFT JOIN gudid_submissions s ON s.primary_di = d.primary_di
        WHERE coalesce(d.brand, '') <> '' GROUP BY lv.vendor_id, d.brand ORDER BY lv.vendor_id, d.brand""",
    "pc_op_vendor_year": "SELECT * FROM agg_vendor_year JOIN listed_vendors USING (vendor_id) ORDER BY ALL",
    "pc_op_vendor_profile": "SELECT * FROM agg_vendor_profile JOIN listed_vendors USING (vendor_id) ORDER BY ALL",
    "pc_op_entity": "SELECT * FROM agg_vendor_entity ORDER BY ALL",
    "pc_op_product": "SELECT * FROM agg_product ORDER BY ALL",
    "pc_op_product_top": """
        SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY mode, vendor_id ORDER BY amount DESC, brand) AS rank
                       FROM agg_vendor_product_top) WHERE rank <= 50 ORDER BY mode, vendor_id, rank""",
    "pc_op_research": """
        SELECT vendor_entity, vendor_pit, vendor_current, year, study_name, ct_gov_id, amount, payments, preclinical,
               array_to_string(list_sort(knumbers), '|') AS knumbers FROM agg_research ORDER BY ALL""",
    "pc_op_relationship": "SELECT * FROM agg_relationship ORDER BY ALL",
    "pc_op_ownership": "SELECT * FROM agg_ownership ORDER BY ALL",
}


def clearance_rows(con, cfg):
    """pc_portfolio_510k: every orthopedic clearance with its vendor and GUDID brand and device counts."""
    app_vendor = dict(con.execute("""SELECT entity_key, vendor_id FROM vendor_entities WHERE source = 'applicant'""").fetchall())
    gud = {k: (b, n, dist) for k, b, n, dist in con.execute("""
        WITH sd AS (SELECT DISTINCT s.submission_number AS k, d.primary_di, d.brand, d.distribution_status
                    FROM gudid_submissions s JOIN gudid_devices d USING (primary_di)
                    WHERE s.submission_number LIKE 'K%' OR s.submission_number LIKE 'DEN%'),
        b AS (SELECT k, brand, row_number() OVER (PARTITION BY k ORDER BY count(*) DESC, brand) AS rk
              FROM sd WHERE brand IS NOT NULL GROUP BY k, brand)
        SELECT sd.k, any_value(b.brand),  -- most common brand; ties go to the first alphabetically
               count(DISTINCT sd.primary_di),
               count(DISTINCT sd.primary_di) FILTER (WHERE sd.distribution_status = 'In Commercial Distribution')
        FROM sd LEFT JOIN b ON b.k = sd.k AND b.rk = 1 GROUP BY sd.k""").fetchall()}
    sq = sqlite3.connect(str(cfg.db_path))
    rows = []
    rules = divestitures.load()  # a sold business line's clearances belong to the buyer
    for k, app, name, code, date in sq.execute("""SELECT knumber, applicant, devicename, product_code, decision_date
                                                  FROM clearances ORDER BY decision_date"""):
        b, n, dist = gud.get(k, (None, 0, 0))
        rows.append([divestitures.owner(app_vendor.get(app), code, date, rules), k, name, app, code, date, b, n, dist])
    sq.close()
    return ["vendor_id", "knumber", "device_name", "applicant", "product_code", "decision_date", "gudid_brand",
            "gudid_devices", "gudid_in_distribution"], rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    if not step_done(con, "C1_aggregates"):
        print("Run build_payment_aggregates.py first.")
        return 1
    out = cfg.site_data_dir
    out.mkdir(parents=True, exist_ok=True)
    report = ["Open Payments export for Supabase", "", f"{'File':<28}{'Rows':>10}{'MB':>9}"]
    total = 0
    for name, sql in EXPORTS.items():
        path = out / f"{name}.csv"
        con.execute(f"COPY ({sql}) TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
        n = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        mb = path.stat().st_size / 1e6
        total += mb
        report.append(f"{name + '.csv':<28}{n:>10,}{mb:>9.1f}")
    # business lines sold to another company, for the product pages' "now part of" note
    import shutil
    shutil.copyfile(divestitures.PATH, out / "pc_vendor_divestitures.csv")
    report.append(f"{'pc_vendor_divestitures.csv':<28}{len(divestitures.load()):>10,}{0.0:>9.1f}")
    cols, rows = clearance_rows(con, cfg)
    path = out / "pc_portfolio_510k.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(rows)
    mb = path.stat().st_size / 1e6
    total += mb
    report.append(f"{'pc_portfolio_510k.csv':<28}{len(rows):>10,}{mb:>9.1f}")
    report += ["", f"Total CSV size: {total:.1f} MB. Postgres tables with indexes usually take 1.5 to 3 times the CSV size."]
    text = "\n".join(report) + "\n"
    (cfg.output_dir / "Payments_Export_Report.txt").write_text(text, encoding="utf-8")
    mark_step(con, "C3_export", None, 0, f"{total:.1f} MB")
    print(text)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
