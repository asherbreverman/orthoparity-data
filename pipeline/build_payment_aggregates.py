"""Phase C1: build every Open Payments number the website shows (Benchmark a Vendor and Benchmark a Product).

Rules, in order:
  Listed vendors   only vendors with at least one orthopedic 510(k) in the predicate database (Asher, 2026-11-17).
  Vendor by date   a payment belongs to its payer's vendor. Two roll-ups are stored side by side:
                     pit      as owned at the time: an acquired vendor's payments move to the buyer from the
                              closing date in vendor_lineage (only buyers that are themselves vendors)
                     current  current owner with history: every payment moves to the final buyer
  Orthopedic scope dedicated orthopedic vendors (80% or more of their matched device tags are orthopedic, or no
                   device tags at all): every payment counts unless all its product tags are non-orthopedic
                   devices or drugs. Diversified vendors (Medtronic, J&J...): a payment counts when it names an
                   orthopedic product, or names no known non-orthopedic product and goes to an orthopedic,
                   neurosurgery or podiatry recipient.
  Nature groups    royalty, consulting, services (non-consulting compensation), speaking (faculty or speaker),
                   travel, food, education, grant, honoraria, acquisitions, debt forgiveness, ownership, other.
  Surgeons         an anonymous key (salted hash of the NPI or CMS profile ID; the salt stays in data/).
                   Specialty buckets follow the Sep 21, 2026 article.
  Products         a payment counts in full for every product it names (so product totals overlap). Tier 1 links
                   go to the device's 510(k)s; tier 2 brand matches go to every 510(k) GUDID lists for that brand.

Writes DuckDB tables pay_fact, agg_vendor_year, agg_vendor_profile, agg_vendor_entity, agg_product,
agg_research, agg_relationship, agg_ownership, agg_vendor_product_top.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import time

from predicate_chain.config import load_config
from predicate_chain.paycommon import PaySettings, connect_duck, mark_step, step_done

ROLLUP_RELATIONS = ("acquired by", "merged into", "owned by", "hardware and biologics assets acquired by", "became part of")
DEDICATED_SHARE = 0.8

NATURE_SQL = """CASE
  WHEN nature = 'Royalty or License' THEN 'royalty'
  WHEN nature = 'Consulting Fee' THEN 'consulting'
  WHEN nature LIKE 'Compensation for services other than consulting%' THEN 'services'
  WHEN nature LIKE 'Compensation for serving as faculty%' THEN 'speaking'
  WHEN nature = 'Travel and Lodging' THEN 'travel'
  WHEN nature = 'Food and Beverage' THEN 'food'
  WHEN nature = 'Education' THEN 'education'
  WHEN nature = 'Grant' THEN 'grant'
  WHEN nature = 'Honoraria' THEN 'honoraria'
  WHEN nature = 'Acquisitions' THEN 'acquisitions'
  WHEN nature = 'Debt forgiveness' THEN 'debt forgiveness'
  WHEN nature LIKE 'Current or prospective ownership%' THEN 'ownership'
  ELSE 'other' END"""

BUCKET_SQL = """CASE
  WHEN lower(specialties) LIKE '%neurological surgery%' THEN 'Neurosurgery'
  WHEN lower(specialties) LIKE '%orthopaedic surgery of the spine%' THEN 'Orthopedic spine'
  WHEN lower(specialties) LIKE '%adult reconstructive%' THEN 'Joints and recon'
  WHEN lower(specialties) LIKE '%orthopaedic surgery%' AND lower(specialties) LIKE '%sports medicine%' THEN 'Sports medicine'
  WHEN lower(specialties) LIKE '%orthopaedic surgery%' AND lower(specialties) LIKE '%hand surgery%' THEN 'Hand and upper extremity'
  WHEN lower(specialties) LIKE '%orthopaedic surgery%' AND lower(specialties) LIKE '%foot and ankle%' THEN 'Foot and ankle (orthopedic)'
  WHEN lower(specialties) LIKE '%orthopaedic trauma%' THEN 'Orthopedic trauma'
  WHEN lower(specialties) LIKE '%pediatric orthopaedic%' THEN 'Pediatric orthopedics'
  WHEN lower(specialties) LIKE '%orthopaedic surgery%' THEN 'General orthopedics'
  WHEN lower(specialties) LIKE '%podiat%' THEN 'Podiatry'
  WHEN recipient_type ILIKE '%teaching hospital%' THEN 'Teaching hospital'
  WHEN recipient_type ILIKE '%non-physician%' THEN 'PA, NP and other practitioners'
  ELSE 'Other physicians' END"""

ORTHO_BUCKETS = ("'Neurosurgery','Orthopedic spine','Joints and recon','Sports medicine','Hand and upper extremity',"
                 "'Foot and ankle (orthopedic)','Orthopedic trauma','Pediatric orthopedics','General orthopedics',"
                 "'Podiatry'")


def salt(cfg) -> str:
    p = cfg.data_dir / "recipient_salt.txt"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


def build(con, cfg) -> dict:
    t0 = time.monotonic()
    s = salt(cfg)
    rel = " OR ".join(f"relation = '{r}'" for r in ROLLUP_RELATIONS)
    con.execute("""CREATE OR REPLACE TABLE listed_vendors AS
                   SELECT vendor_id FROM vendors WHERE clearances > 0""")
    # roll-up edges between listed vendors
    con.execute(f"""CREATE OR REPLACE TEMP TABLE edges AS
        SELECT l.vendor_id AS child, l.parent, coalesce(l.valid_from, DATE '1900-01-01') AS vf,
               coalesce(l.valid_to, DATE '2999-12-31') AS vt
        FROM vendor_lineage l JOIN listed_vendors p ON p.vendor_id = l.parent
        WHERE ({rel})""")
    # current owner: follow open-ended edges up to three levels
    # kept (not temporary): export_payments writes it as pc_vendors.rolls_up_to for every vendor, with or without payments
    con.execute("""CREATE OR REPLACE TABLE cur_parent AS
        WITH e AS (SELECT child, parent FROM edges WHERE vt >= DATE '2999-01-01')
        SELECT v.vendor_id, coalesce(e3.parent, e2.parent, e1.parent, v.vendor_id) AS vendor_current
        FROM vendors v LEFT JOIN e e1 ON e1.child = v.vendor_id LEFT JOIN e e2 ON e2.child = e1.parent
        LEFT JOIN e e3 ON e3.child = e2.parent""")
    # payer -> vendor
    con.execute("""CREATE OR REPLACE TEMP TABLE pv AS
        SELECT e.entity_key AS payer_id, e.vendor_id FROM vendor_entities e WHERE e.source = 'payer'""")
    # product slot summary per payment
    con.execute("""CREATE OR REPLACE TEMP TABLE slotsum AS
        SELECT m.source, m.year, m.record_id,
               count(*) AS n_slots,
               count(*) FILTER (WHERE m.ortho_product) AS n_ortho,
               count(*) FILTER (WHERE NOT m.ortho_product AND (m.tier = 1 OR lower(p.type) = 'drug')) AS n_non_ortho
        FROM op_product_match m JOIN op_products p ON p.source = m.source AND p.year = m.year
             AND p.record_id = m.record_id AND p.slot = m.slot
        GROUP BY ALL""")
    # dedicated or diversified, per vendor (all years)
    con.execute(f"""CREATE OR REPLACE TABLE vendor_kind AS
        SELECT pv.vendor_id, sum(ss.n_ortho) AS ortho_tags, sum(ss.n_ortho + ss.n_non_ortho) AS known_tags,
               CASE WHEN coalesce(sum(ss.n_ortho + ss.n_non_ortho), 0) = 0 THEN 'dedicated'
                    WHEN sum(ss.n_ortho) >= {DEDICATED_SHARE} * sum(ss.n_ortho + ss.n_non_ortho) THEN 'dedicated'
                    ELSE 'diversified' END AS kind
        FROM op_general g JOIN pv ON pv.payer_id = g.payer_id
        LEFT JOIN slotsum ss ON ss.source = 'general' AND ss.year = g.year AND ss.record_id = g.record_id
        GROUP BY 1""")
    # the fact table: one row per general payment from a listed vendor's payer, in orthopedic scope
    con.execute(f"""CREATE OR REPLACE TABLE pay_fact AS
        WITH g AS (
          SELECT g.*, pv.vendor_id AS vendor_entity, {BUCKET_SQL} AS bucket, {NATURE_SQL} AS nature_group,
                 coalesce(ss.n_slots, 0) AS n_slots, coalesce(ss.n_ortho, 0) AS n_ortho,
                 coalesce(ss.n_non_ortho, 0) AS n_non_ortho, vk.kind
          FROM op_general g JOIN pv ON pv.payer_id = g.payer_id
          JOIN listed_vendors lv ON lv.vendor_id = pv.vendor_id
          JOIN vendor_kind vk ON vk.vendor_id = pv.vendor_id
          LEFT JOIN slotsum ss ON ss.source = 'general' AND ss.year = g.year AND ss.record_id = g.record_id)
        SELECT g.year, g.record_id, g.pay_date, g.payer_id, g.payer_name, g.vendor_entity,
               coalesce(e.parent, g.vendor_entity) AS vendor_pit, cp.vendor_current,
               g.nature_group, g.nature, g.amount, g.form, g.third_party, g.physician_ownership,
               g.recipient_type, g.bucket, g.bucket IN ({ORTHO_BUCKETS}) AS ortho_recipient_bucket,
               CASE WHEN g.recipient_type ILIKE '%teaching hospital%' THEN 'TH:' || coalesce(g.teaching_hospital_ccn, '')
                    ELSE md5('{s}' || coalesce(nullif(g.npi, ''), 'P' || g.profile_id)) END AS rkey,
               g.n_slots, g.n_ortho, g.kind
        FROM g
        LEFT JOIN edges e ON e.child = g.vendor_entity AND g.pay_date BETWEEN e.vf AND e.vt
        LEFT JOIN cur_parent cp ON cp.vendor_id = g.vendor_entity
        WHERE (g.kind = 'dedicated' AND NOT (g.n_slots > 0 AND g.n_ortho = 0 AND g.n_non_ortho = g.n_slots))
           OR (g.kind = 'diversified' AND (g.n_ortho > 0 OR (g.n_non_ortho = 0 AND g.bucket IN ({ORTHO_BUCKETS}))))""")
    # both roll-ups as rows
    con.execute("""CREATE OR REPLACE TEMP VIEW pf AS
        SELECT 'pit' AS mode, vendor_pit AS vendor_id, * EXCLUDE (vendor_pit, vendor_current) FROM pay_fact
        UNION ALL
        SELECT 'current' AS mode, vendor_current AS vendor_id, * EXCLUDE (vendor_pit, vendor_current) FROM pay_fact""")
    # vendor x year x nature
    con.execute("""CREATE OR REPLACE TABLE agg_vendor_year AS
        SELECT mode, vendor_id, year, nature_group, count(*) AS transactions, sum(amount) AS amount,
               count(DISTINCT rkey) AS recipients
        FROM pf GROUP BY ALL""")
    # profile per vendor x year (and all years as year 0)
    con.execute("""CREATE OR REPLACE TEMP TABLE pr AS
        SELECT mode, vendor_id, year, rkey, bucket, recipient_type,
               sum(amount) AS amt,
               bool_or(nature_group = 'food') AS f, bool_or(nature_group = 'travel') AS t,
               bool_or(nature_group = 'consulting') AS c, bool_or(nature_group = 'royalty') AS r
        FROM pf WHERE recipient_type NOT ILIKE '%teaching hospital%' GROUP BY ALL
        UNION ALL
        SELECT mode, vendor_id, 0, rkey, any_value(bucket), any_value(recipient_type), sum(amount),
               bool_or(nature_group = 'food'), bool_or(nature_group = 'travel'), bool_or(nature_group = 'consulting'),
               bool_or(nature_group = 'royalty')
        FROM pf WHERE recipient_type NOT ILIKE '%teaching hospital%' GROUP BY mode, vendor_id, rkey""")
    con.execute("""CREATE OR REPLACE TEMP TABLE pr_rank AS
        SELECT *, row_number() OVER (PARTITION BY mode, vendor_id, year ORDER BY amt DESC) AS rk,
               count(*) OVER (PARTITION BY mode, vendor_id, year) AS n
        FROM pr""")
    con.execute("""CREATE OR REPLACE TEMP TABLE money AS
        SELECT mode, vendor_id, year, sum(amount) AS total, count(*) AS transactions,
               sum(amount) FILTER (WHERE third_party = 'Entity') AS to_entities,
               sum(amount) FILTER (WHERE form ILIKE '%stock%' OR form ILIKE '%ownership%' OR form ILIKE 'Dividend%') AS equity_forms,
               sum(amount) FILTER (WHERE nature_group = 'acquisitions') AS acquisitions,
               sum(amount) FILTER (WHERE nature_group = 'debt forgiveness') AS debt_forgiveness,
               sum(amount) FILTER (WHERE recipient_type ILIKE '%teaching hospital%') AS to_teaching_hospitals
        FROM pf GROUP BY 1, 2, 3
        UNION ALL
        SELECT mode, vendor_id, 0, sum(amount), count(*),
               sum(amount) FILTER (WHERE third_party = 'Entity'),
               sum(amount) FILTER (WHERE form ILIKE '%stock%' OR form ILIKE '%ownership%' OR form ILIKE 'Dividend%'),
               sum(amount) FILTER (WHERE nature_group = 'acquisitions'),
               sum(amount) FILTER (WHERE nature_group = 'debt forgiveness'),
               sum(amount) FILTER (WHERE recipient_type ILIKE '%teaching hospital%')
        FROM pf GROUP BY 1, 2""")
    con.execute("""CREATE OR REPLACE TABLE agg_vendor_profile AS
        SELECT m.mode, m.vendor_id, m.year, m.total, m.transactions, m.to_entities, m.equity_forms, m.acquisitions,
               m.debt_forgiveness, m.to_teaching_hospitals,
               r.recipients, r.physicians, r.food_r, r.travel_r, r.consulting_r, r.royalty_r,
               r.top1pct_share, r.top10_share, r.median_per_recipient, b.bucket_json
        FROM money m
        LEFT JOIN (SELECT mode, vendor_id, year, count(*) AS recipients,
                          count(*) FILTER (WHERE recipient_type ILIKE '%physician%' AND recipient_type NOT ILIKE '%non-physician%') AS physicians,
                          count(*) FILTER (WHERE f) AS food_r, count(*) FILTER (WHERE t) AS travel_r,
                          count(*) FILTER (WHERE c) AS consulting_r, count(*) FILTER (WHERE r) AS royalty_r,
                          sum(amt) FILTER (WHERE rk <= greatest(1, ceil(n * 0.01))) / nullif(sum(amt), 0) AS top1pct_share,
                          sum(amt) FILTER (WHERE rk <= 10) / nullif(sum(amt), 0) AS top10_share,
                          median(amt) AS median_per_recipient
                   FROM pr_rank GROUP BY 1, 2, 3) r USING (mode, vendor_id, year)
        LEFT JOIN (SELECT mode, vendor_id, year,
                          to_json(list({'bucket': bucket, 'recipients': nr, 'amount': am} ORDER BY am DESC)) AS bucket_json
                   FROM (SELECT mode, vendor_id, year, bucket, count(*) AS nr, sum(amt) AS am FROM pr GROUP BY ALL)
                   GROUP BY 1, 2, 3) b USING (mode, vendor_id, year)""")
    # reporting entities (payer level), all years and by year
    con.execute("""CREATE OR REPLACE TABLE agg_vendor_entity AS
        SELECT vendor_pit, vendor_current, payer_id, any_value(payer_name) AS payer_name, year,
               sum(amount) AS amount, count(DISTINCT rkey) AS recipients,
               sum(amount) FILTER (WHERE nature_group = 'royalty') AS royalty,
               sum(amount) FILTER (WHERE nature_group = 'food') AS food
        FROM pay_fact GROUP BY vendor_pit, vendor_current, payer_id, year""")
    # products
    con.execute("""CREATE OR REPLACE TEMP TABLE brand_k AS
        SELECT DISTINCT lv.vendor_id, trim(regexp_replace(regexp_replace(regexp_replace(upper(coalesce(d.brand, '')),
                 '[®™©]', '', 'g'), '[^A-Z0-9 ]', ' ', 'g'), '\\s+', ' ', 'g')) AS raw_bkey, s.submission_number AS knumber
        FROM gudid_devices d JOIN (SELECT DISTINCT primary_di FROM gudid_ortho_di) o ON o.primary_di = d.primary_di
        JOIN (SELECT entity_key AS duns, vendor_id FROM vendor_entities WHERE source = 'labeler') lv ON lv.duns = d.duns
        JOIN gudid_submissions s ON s.primary_di = d.primary_di WHERE s.submission_number LIKE 'K%'""")
    con.execute("""CREATE OR REPLACE TEMP TABLE prod_slots AS
        SELECT m.source, m.year, m.record_id, k.knumber, 1 AS tier, d.brand
        FROM op_product_match m JOIN op_product_k k USING (source, year, record_id, slot)
        LEFT JOIN gudid_devices d ON d.primary_di = m.primary_di
        WHERE m.ortho_product
        UNION
        SELECT m.source, m.year, m.record_id, bk.knumber, 2, m.matched_brand
        FROM op_product_match m JOIN brand_k bk ON bk.vendor_id = m.payer_vendor
             AND bk.raw_bkey = trim(regexp_replace(regexp_replace(regexp_replace(upper(coalesce(m.matched_brand, '')),
                 '[®™©]', '', 'g'), '[^A-Z0-9 ]', ' ', 'g'), '\\s+', ' ', 'g'))
        WHERE m.tier = 2""")
    con.execute("""CREATE OR REPLACE TABLE agg_product AS
        SELECT ps.knumber, ps.tier, pf.year, pf.nature_group, any_value(ps.brand) AS brand,
               any_value(pf.vendor_pit) AS vendor_pit, count(DISTINCT pf.record_id) AS transactions,
               sum(pf.amount) AS amount, count(DISTINCT pf.rkey) AS recipients
        FROM (SELECT DISTINCT source, year, record_id, knumber, tier, brand FROM prod_slots WHERE source = 'general') ps
        JOIN pay_fact pf ON pf.year = ps.year AND pf.record_id = ps.record_id
        GROUP BY ps.knumber, ps.tier, pf.year, pf.nature_group""")
    con.execute("""CREATE OR REPLACE TABLE agg_vendor_product_top AS
        SELECT mode, vendor_id, brand, sum(amount) AS amount, count(*) AS transactions,
               sum(amount) FILTER (WHERE nature_group = 'royalty') AS royalty,
               sum(amount) FILTER (WHERE nature_group IN ('travel', 'food', 'education')) AS engagement
        FROM (SELECT DISTINCT pf.mode, pf.vendor_id, pf.record_id, pf.year, pf.amount, pf.nature_group,
                     coalesce(d.brand, m.matched_brand) AS brand
              FROM pf JOIN op_product_match m ON m.source = 'general' AND m.year = pf.year AND m.record_id = pf.record_id
              LEFT JOIN gudid_devices d ON d.primary_di = m.primary_di
              WHERE m.ortho_product)
        WHERE brand IS NOT NULL AND brand <> '' GROUP BY ALL""")
    # research
    con.execute("""CREATE OR REPLACE TABLE agg_research AS
        SELECT pv.vendor_id AS vendor_entity, coalesce(e.parent, pv.vendor_id) AS vendor_pit, cp.vendor_current,
               r.year, coalesce(nullif(trim(r.study_name), ''), '(study name not reported)') AS study_name,
               any_value(r.ct_gov_id) AS ct_gov_id, sum(r.amount) AS amount, count(*) AS payments,
               bool_or(r.preclinical ILIKE 'Yes%') AS preclinical,
               list(DISTINCT k.knumber) FILTER (WHERE k.knumber IS NOT NULL) AS knumbers
        FROM op_research r JOIN pv ON pv.payer_id = r.payer_id JOIN listed_vendors lv ON lv.vendor_id = pv.vendor_id
        LEFT JOIN edges e ON e.child = pv.vendor_id AND r.pay_date BETWEEN e.vf AND e.vt
        LEFT JOIN cur_parent cp ON cp.vendor_id = pv.vendor_id
        LEFT JOIN op_product_k k ON k.source = 'research' AND k.year = r.year AND k.record_id = r.record_id
        GROUP BY ALL""")
    # paid professional relationships (consulting, royalty, speaking, services) per surgeon key
    con.execute("""CREATE OR REPLACE TABLE agg_relationship AS
        SELECT mode, vendor_id, rkey, year, any_value(bucket) AS bucket,
               bool_or(nature_group = 'consulting') AS consulting, bool_or(nature_group = 'royalty') AS royalty,
               bool_or(nature_group IN ('speaking', 'services')) AS speaking_services, sum(amount) AS amount
        FROM pf WHERE nature_group IN ('consulting', 'royalty', 'speaking', 'services')
          AND recipient_type NOT ILIKE '%teaching hospital%'
        GROUP BY ALL""")
    # ownership file
    con.execute("""CREATE OR REPLACE TABLE agg_ownership AS
        SELECT coalesce(e.parent, pv.vendor_id) AS vendor_pit, cp.vendor_current, o.year,
               count(DISTINCT coalesce(nullif(o.npi, ''), o.profile_id)) AS holders,
               sum(o.invested) AS invested, sum(o.value) AS value
        FROM op_ownership o JOIN pv ON pv.payer_id = o.payer_id JOIN listed_vendors lv ON lv.vendor_id = pv.vendor_id
        LEFT JOIN edges e ON e.child = pv.vendor_id AND make_date(o.year, 7, 1) BETWEEN e.vf AND e.vt
        LEFT JOIN cur_parent cp ON cp.vendor_id = pv.vendor_id
        GROUP BY ALL""")
    q = lambda sql: con.execute(sql).fetchone()
    return {"listed_vendors": q("SELECT count(*) FROM listed_vendors")[0],
            "vendors_with_payments": q("SELECT count(DISTINCT vendor_id) FROM agg_vendor_year WHERE mode = 'pit'")[0],
            "pay_fact_rows": q("SELECT count(*) FROM pay_fact")[0],
            "pay_fact_amount": q("SELECT sum(amount) FROM pay_fact")[0],
            "dedicated": q("SELECT count(*) FROM vendor_kind WHERE kind = 'dedicated'")[0],
            "diversified": q("SELECT count(*) FROM vendor_kind WHERE kind = 'diversified'")[0],
            "product_rows": q("SELECT count(*) FROM agg_product")[0],
            "products_with_payments": q("SELECT count(DISTINCT knumber) FROM agg_product")[0],
            "seconds": round(time.monotonic() - t0)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    ps = PaySettings(cfg)
    con = connect_duck(ps)
    if not step_done(con, "B2_match"):
        print("Run build-vendor-registry and match-products first.")
        return 1
    st = build(con, cfg)
    mark_step(con, "C1_aggregates", st["pay_fact_rows"], st["seconds"], "; ".join(f"{k}={v}" for k, v in st.items()))
    for k, v in st.items():
        print(f"{k}: {v:,.0f}" if isinstance(v, (int, float)) else f"{k}: {v}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
