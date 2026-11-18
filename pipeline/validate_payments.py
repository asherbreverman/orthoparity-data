"""Phase C2: validation report for the Open Payments build (outputs/payments_validation.md).

Checks:
  1. Reproduce the Sep 21, 2026 article base (2025 general payments to orthopedic surgeons) under several
     recipient filters, against the published figures.
  2. Same comparison for the article's named reporting entities.
  3. What the orthopedic product filter removes for those entities.
  4. Internal consistency: every aggregate adds back to the fact table, in both roll-up modes.
  5. Roll-up by date (NuVasive into Globus on 2023-09-01).
  6. Product links: share of 2025 dollars tied to a 510(k), top products.
  7. Numbers to spot-check on the CMS Open Payments website.
"""
from __future__ import annotations

import argparse
import sys

from predicate_chain.config import load_config
from predicate_chain.paycommon import PaySettings, connect_duck, mark_step, step_done

ARTICLE = {"transactions": 661667, "amount": 727535622, "companies": 1007, "recipients": 47816}
ARTICLE_NATURE = [("Royalty or License", 13261, 421.9), ("Consulting Fee", 31300, 132.1), ("Acquisitions", 132, 40.8),
                  ("Compensation for services other than consulting%", 6613, 37.2), ("Travel and Lodging", 96891, 35.8),
                  ("Food and Beverage", 504214, 27.6), ("Education", 5224, 11.4), ("Grant", 973, 7.8),
                  ("Debt forgiveness", 553, 7.8), ("Compensation for serving as faculty%", 1110, 2.6),
                  ("Honoraria", 436, 2.0)]
ARTICLE_ENTITIES = [("DePuy Synthes Products, Inc.", 264, 264 * 232816), ("DePuy Synthes Sales Inc.", 9581, 9581 * 196),
                    ("Stryker Corporation", 19180, 102.6e6), ("Arthrex, Inc.", 4267, 102.1e6)]
PHYS = "recipient_type = 'Covered Recipient Physician'"
MDDO = "primary_types IN ('Medical Doctor', 'Doctor of Osteopathy')"
DPM = "primary_types = 'Doctor of Podiatric Medicine'"
FILTERS = [
    ("A: MD/DO orthopaedic + all DPM", f"{PHYS} AND (({MDDO} AND lower(specialties) LIKE '%orthopaedic%') OR {DPM})"),
    ("B: A + neurosurgery", f"{PHYS} AND (({MDDO} AND regexp_matches(lower(specialties), 'orthopaedic|neurological surgery')) OR {DPM})"),
    ("C: B + hand surgery + sports medicine", f"{PHYS} AND (({MDDO} AND regexp_matches(lower(specialties), 'orthopaedic|neurological surgery|hand|sports medicine')) OR {DPM})"),
]


def money(x):
    return f"${x:,.0f}" if x is not None else "n/a"


def pct(a, b):
    return f"{100 * ((a or 0) - b) / b:+.1f}%" if b else ""


def report(con) -> str:
    q = lambda s, p=None: con.execute(s, p or []).fetchall()
    L = ["# Open Payments build: validation report", "",
         "Data: CMS Open Payments program years 2019 to 2025 (published June 30, 2026), GUDID full release November 2026.", ""]

    L += ["## 1. Reproducing the Sep 21, 2026 article base (2025 general payments)", "",
          "The article filtered to MD, DO and DPM recipients with an orthopedic specialty in any of six taxonomy slots. "
          "Without the original script, three readings of that filter are compared with the published figures.", "",
          "| Filter | Payments | Dollars | Companies (payer IDs) | Recipients |", "| --- | --- | --- | --- | --- |",
          f"| Published | {ARTICLE['transactions']:,} | {money(ARTICLE['amount'])} | {ARTICLE['companies']:,} | {ARTICLE['recipients']:,} |"]
    best = None
    for name, w in FILTERS:
        n, amt, co, rc = q(f"""SELECT count(*), coalesce(sum(amount), 0), count(DISTINCT payer_id), count(DISTINCT coalesce(nullif(npi, ''), profile_id))
                               FROM op_general WHERE year = 2025 AND {w}""")[0]
        L.append(f"| {name} | {n:,} ({pct(n, ARTICLE['transactions'])}) | {money(amt)} ({pct(amt, ARTICLE['amount'])}) | "
                 f"{co:,} | {rc:,} ({pct(rc, ARTICLE['recipients'])}) |")
        if best is None or abs(amt - ARTICLE["amount"]) < abs(best[2] - ARTICLE["amount"]):
            best = (name, w, amt)
    L += ["", "Rows for recipients outside orthopedics, neurosurgery, podiatry and hand surgery were only loaded from "
          "orthopedic payers, so a broader filter cannot be tested exactly here.", "",
          f"Nature of payment under the closest filter ({best[0]}):", "",
          "| Nature | Published payments | Here | Published $M | Here $M |", "| --- | --- | --- | --- | --- |"]
    for nat, n_pub, m_pub in ARTICLE_NATURE:
        n, amt = q(f"SELECT count(*), sum(amount) FROM op_general WHERE year = 2025 AND {best[1]} AND nature LIKE ?", [nat])[0]
        L.append(f"| {nat.rstrip('%')} | {n_pub:,} | {n:,} ({pct(n, n_pub)}) | {m_pub} | {(amt or 0) / 1e6:.1f} |")

    L += ["", "## 2. Named reporting entities (2025, closest filter)", "",
          "| Entity | Published recipients | Here | Published $ | Here $ |", "| --- | --- | --- | --- | --- |"]
    for ent, r_pub, a_pub in ARTICLE_ENTITIES:
        rc, amt = q(f"""SELECT count(DISTINCT coalesce(nullif(npi, ''), profile_id)), sum(amount) FROM op_general
                        WHERE year = 2025 AND {best[1]} AND payer_name = ?""", [ent])[0]
        L.append(f"| {ent} | {r_pub:,} | {rc:,} ({pct(rc, r_pub)}) | {money(a_pub)} | {money(amt)} ({pct(amt or 0, a_pub)}) |")

    L += ["", "## 3. What the orthopedic product filter removes (same entities, same recipients)", "",
          "| Entity | All payments | Orthopedic scope | Removed |", "| --- | --- | --- | --- |"]
    for ent, _, _ in ARTICLE_ENTITIES:
        raw = q(f"SELECT sum(amount) FROM op_general WHERE year = 2025 AND {best[1]} AND payer_name = ?", [ent])[0][0] or 0
        kept = q(f"""SELECT sum(f.amount) FROM pay_fact f JOIN op_general g ON g.year = f.year AND g.record_id = f.record_id
                     WHERE f.year = 2025 AND {best[1].replace('recipient_type', 'g.recipient_type')} AND f.payer_name = ?""", [ent])[0][0] or 0
        L.append(f"| {ent} | {money(raw)} | {money(kept)} | {pct(kept, raw) if raw else ''} |")
    kinds = q("""SELECT v.display_name, k.ortho_tags, k.known_tags FROM vendor_kind k JOIN vendors v USING (vendor_id)
                 JOIN listed_vendors USING (vendor_id) WHERE k.kind = 'diversified' ORDER BY k.known_tags DESC LIMIT 15""")
    L += ["", "Diversified vendors (under 80% of matched device tags orthopedic); for these, payments count only when "
          "they name an orthopedic product or go untagged to an orthopedic, neurosurgery or podiatry recipient:", ""]
    L += [f"- {d}: {o:,} of {k:,} tags orthopedic ({100 * o / k:.0f}%)" for d, o, k in kinds]

    L += ["", "## 4. Internal consistency", ""]
    fact = q("SELECT coalesce(sum(amount), 0), count(*) FROM pay_fact")[0]
    for mode in ("pit", "current"):
        s, n = q("SELECT coalesce(sum(amount), 0), coalesce(sum(transactions), 0) FROM agg_vendor_year WHERE mode = ?", [mode])[0]
        ok = abs(s - fact[0]) < 1 and n == fact[1]
        L.append(f"- agg_vendor_year ({mode}) adds back to pay_fact: {'yes' if ok else 'NO'} ({money(s)}, {n:,} payments)")
        s0 = q("SELECT sum(total) FROM agg_vendor_profile WHERE mode = ? AND year = 0", [mode])[0][0]
        L.append(f"- agg_vendor_profile all-years ({mode}) adds back: {'yes' if abs((s0 or 0) - (fact[0] or 0)) < 1 else 'NO'}")
    cols = {r[0] for r in q("SELECT DISTINCT column_name FROM information_schema.columns WHERE table_name LIKE 'agg_%'")}
    L.append(f"- No NPI or name columns in aggregate tables: {'yes' if not any(c in cols for c in ('npi', 'profile_id', 'first_name', 'last_name')) else 'NO'}")

    L += ["", "## 5. Roll-up by date", ""]
    for vp, y, m in q("""SELECT v.display_name, f.year, sum(f.amount) FROM pay_fact f JOIN vendors v ON v.vendor_id = f.vendor_pit
                         WHERE f.vendor_entity = 'nuvasive' AND f.year >= 2022 GROUP BY ALL ORDER BY 2, 1"""):
        L.append(f"- NuVasive payments in {y} counted under {vp} (as owned at the time): {money(m)}")

    L += ["", "## 6. Product links", ""]
    tot, linked = q("""SELECT sum(amount), sum(amount) FILTER (WHERE record_id IN (SELECT record_id FROM op_product_match
                       WHERE source = 'general' AND year = 2025 AND ortho_product)) FROM pay_fact WHERE year = 2025""")[0]
    if tot:
        L.append(f"- 2025 orthopedic-scope dollars naming an orthopedic product: {money(linked or 0)} of {money(tot)} ({100 * (linked or 0) / tot:.0f}%)")
    L += ["", "Top 2025 products by dollars naming them (a payment counts for each product it names):", "",
          "| 510(k) | Brand | Tier | Dollars | Payments |", "| --- | --- | --- | --- | --- |"]
    for k, b, t, a, n in q("""SELECT knumber, any_value(brand), min(tier), sum(amount), sum(transactions) FROM agg_product
                              WHERE year = 2025 GROUP BY knumber ORDER BY 4 DESC LIMIT 15"""):
        L.append(f"| {k} | {b} | {t} | {money(a)} | {n:,} |")

    L += ["", "## 7. Spot-check on the CMS Open Payments website", "",
          "Search each company at openpaymentsdata.cms.gov and compare its 2025 general payments total (all recipients).", "",
          "| Paying entity | 2025 general payments here | Payments |", "| --- | --- | --- |"]
    for ent in ("Arthrex, Inc.", "Globus Medical, Inc.", "TREACE MEDICAL CONCEPTS, INC."):
        a, n = q("SELECT sum(amount), count(*) FROM op_general WHERE year = 2025 AND payer_name = ?", [ent])[0]
        L.append(f"| {ent} | {money(a)} | {n or 0:,} |")

    L += ["", "## 8. Totals", ""]
    for y, a, n, v in q("""SELECT year, sum(amount), count(*), count(DISTINCT vendor_pit) FROM pay_fact GROUP BY 1 ORDER BY 1"""):
        L.append(f"- {y}: {money(a)} in {n:,} payments from {v:,} vendors (orthopedic scope, listed vendors)")
    return "\n".join(L) + "\n"


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
    text = report(con)
    out = cfg.output_dir / "payments_validation.md"
    out.write_text(text, encoding="utf-8")
    mark_step(con, "C2_validation", None, 0, str(out))
    print(text)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
