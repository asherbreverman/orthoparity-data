"""Load Medicare's TEAM model (Transforming Episode Accountability Model) for the procedure view and the Medicare box.

Sources (CMS, public), saved unopened in the folder named by [cms_team] DIR in config.ini:
  - Preliminary Target Prices PY2 (team-py2-prlim-target-prices.xlsx): CMS's preliminary target price for every
    MS-DRG/HCPCS episode type and census division for 2027, with its components.
  - Preliminary Target Prices PY1 (team-py1-prlim-target-prices.xlsx): the same for 2026.
  - Participant List (XLSX, from https://www.cms.gov/team-model-participant-list): every hospital in TEAM by CCN,
    mandatory or voluntary, with its CBSA and participation dates.
  - TEAM DRG Mapping Specifications (team-drg-mapping-specs.xlsx): how CMS renumbered TEAM MS-DRGs from FY 2020 to
    FY 2027. Used as the source for reference/team_episode_families.csv; this step only checks the file is there.
All four are linked from https://www.cms.gov/priorities/innovation/innovation-models/team-model.

Two reviewed reference files say what counts:
  - reference/team_triggers.csv: the MS-DRGs and HCPCS codes that start an episode, copied from 42 CFR 512.525(d),
    with the MS-DRG each HCPCS code is priced under (42 CFR 512.540(b)(1)(ii)).
  - reference/team_episode_families.csv: which OrthoParity procedure families are TEAM episodes, and why.
This step stops if the target price workbooks list an MS-DRG the regulation doesn't, or miss one it does.

Target prices are preliminary, regional and in CMS standardized dollars. Each hospital's own target price adjusts
them for its patients and is reconciled after the year ends; CMS doesn't publish hospital target prices or which
track a hospital chose.

Outputs: outputs/site_data/pc_team_trigger.csv, pc_team_family.csv, pc_team_target_price.csv,
pc_team_participant.csv; supabase/17_team_data.sql (tables plus rows, ready to run in Supabase); outputs/TEAM_Report.txt

Usage:  python orthoparity.py load-team
"""
from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

from predicate_chain.config import load_config

MODEL_URL = "https://www.cms.gov/priorities/innovation/innovation-models/team-model"
PRICE_FILES = {1: (2026, r"py1.*target|py1.*prlim", "https://www.cms.gov/priorities/innovation/files/team-py1-prlim-target-prices.xlsx"),
               2: (2027, r"py2.*target|py2.*prlim", "https://www.cms.gov/priorities/innovation/files/team-py2-prlim-target-prices.xlsx")}
PARTICIPANT_URL = "https://www.cms.gov/team-model-participant-list"
MAPPING_PATTERN = r"drg.*mapping"
# CMS's category labels in the target price workbooks, by reference category_id
CATEGORY_LABELS = {"LEJR": "lower extremity joint replacement", "SHFFT": "surgical hip/femur fracture treatment",
                   "SPINE": "spinal fusion", "CABG": "coronary artery bypass graft", "BOWEL": "major bowel procedure"}
REGIONS = 9
DUPLICATES: dict[int, int] = {}  # identical repeated rows found in each CMS price file, for the report

TRIGGER_COLS = ["category_id", "category", "code_type", "code", "price_drg", "setting", "note", "source", "source_url"]
FAMILY_COLS = ["family_id", "category_id", "price_drgs", "family_drgs_in_team", "family_drgs_not_in_team", "note", "basis"]
PRICE_COLS = ["py", "year", "category_id", "drg", "region", "region_name", "benchmark_price", "trend_factor",
              "discount_factor", "target_price", "source_file", "source_url"]
PART_COLS = ["ccn", "hospital", "participation", "cbsa", "cbsa_name", "state", "start_date", "end_date",
             "newly_identified", "as_of", "source_url"]


def find(folder: Path, pattern: str) -> Path:
    hits = sorted(p for p in folder.glob("*.xlsx") if re.search(pattern, p.name, re.I))
    if not hits:
        raise SystemExit(f"No .xlsx matching '{pattern}' in {folder}. See pipeline/load_team.py for the files to save.")
    return hits[-1]


def category_id(label: str) -> str:
    low = re.sub(r"^(ip|ms|op)-", "", str(label or "").strip().lower())
    for cid, text in CATEGORY_LABELS.items():
        if low == text:
            return cid
    raise SystemExit(f"Unknown TEAM episode category in a CMS file: '{label}'")


def num(v, places: int) -> str:
    try:
        return f"{float(v):.{places}f}"
    except (TypeError, ValueError):
        return ""


def read_prices(path: Path, py: int, year: int, url: str) -> list[dict]:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = next(w for w in wb.worksheets if w.title.lower().startswith("prelim_tp"))
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    h = next(i for i, r in enumerate(rows) if r and str(r[0]).strip() == "Initial Sort Order")
    head = [str(c or "").strip().lower() for c in rows[h]]
    col = {"cat": next(i for i, c in enumerate(head) if "episode" in c and ("category" in c or "type" in c) and "ms-drg" not in c),
           "drg": next(i for i, c in enumerate(head) if "ms-drg" in c),
           "region": head.index("region"), "region_name": head.index("region description"),
           "benchmark": head.index("benchmark price"), "trend": head.index("prospective trend factor"),
           "discount": head.index("cms discount factor"), "target": head.index("preliminary target price")}
    out, seen = [], {}
    for r in rows[h + 1:]:
        if not r or not isinstance(r[0], (int, float)):
            continue  # the description and "Filter" rows under the header
        drg = str(r[col["drg"]]).strip()
        drg = drg.zfill(3) if drg.isdigit() else drg
        m = re.match(r"cens_div_(\d)", str(r[col["region"]]).strip().lower())
        if not m:
            raise SystemExit(f"{path.name}: unexpected region '{r[col['region']]}'")
        row = {"py": py, "year": year, "category_id": category_id(r[col["cat"]]), "drg": drg,
               "region": m.group(1), "region_name": str(r[col["region_name"]]).strip(),
               "benchmark_price": num(r[col["benchmark"]], 2), "trend_factor": num(r[col["trend"]], 6),
               "discount_factor": num(r[col["discount"]], 4), "target_price": num(r[col["target"]], 2),
               "source_file": path.name, "source_url": url}
        key = (row["category_id"], drg, row["region"])
        if key in seen:
            # the PY1 workbook repeats some rows word for word (sort orders 261-278); keep one, stop if they differ
            if seen[key] != row:
                raise SystemExit(f"{path.name}: MS-DRG {drg} region {row['region']} appears twice with different values")
            DUPLICATES[py] = DUPLICATES.get(py, 0) + 1
            continue
        seen[key] = row
        out.append(row)
    return out


def read_participants(path: Path) -> list[dict]:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    wb.close()
    intro = " ".join(str(c) for r in rows[:3] for c in r if c)
    m = re.search(r"as of ([A-Z][a-z]+ \d{1,2}, \d{4})", intro)
    if not m:
        raise SystemExit(f"{path.name}: can't find the 'as of' date in the title row")
    as_of = datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
    h = next(i for i, r in enumerate(rows) if r and str(r[0] or "").strip().lower().startswith("mandatory or voluntary"))
    head = [str(c or "").strip().lower() for c in rows[h]]
    ix = {k: next(i for i, c in enumerate(head) if c.startswith(k)) for k in
          ("mandatory or voluntary", "hospital ccn", "hospital name", "cbsa", "cbsa name", "cbsa state",
           "participation start", "participation end", "newly identified")}

    def date(v) -> str:
        if isinstance(v, datetime):
            return v.date().isoformat()
        s = str(v or "").strip()
        return datetime.strptime(s, "%m/%d/%Y").date().isoformat() if s else ""

    out = []
    for r in rows[h + 1:]:
        if not r or not r[ix["hospital ccn"]]:
            continue
        ccn = str(r[ix["hospital ccn"]]).strip()
        ccn = ccn.zfill(6) if ccn.isdigit() else ccn
        out.append({"ccn": ccn, "hospital": str(r[ix["hospital name"]]).strip(),
                    "participation": str(r[ix["mandatory or voluntary"]]).strip().title(),
                    "cbsa": str(r[ix["cbsa"]] or "").strip(), "cbsa_name": str(r[ix["cbsa name"]] or "").strip(),
                    "state": str(r[ix["cbsa state"]] or "").strip(),
                    "start_date": date(r[ix["participation start"]]), "end_date": date(r[ix["participation end"]]),
                    "newly_identified": str(r[ix["newly identified"]] or "").strip().upper() == "Y",
                    "as_of": as_of, "source_url": PARTICIPANT_URL})
    return out


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def sql_value(v) -> str:
    if v is None or v == "":
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path: Path, triggers, families, prices, parts) -> None:
    def inserts(table: str, cols: list[str], rows: list[dict], numeric: set[str] = frozenset()) -> str:
        if not rows:
            return f"delete from {table};\n"
        vals = []
        for r in rows:
            vals.append("(" + ", ".join(str(r[c]) if (c in numeric and r[c] != "") else sql_value(r[c]) for c in cols) + ")")
        chunks = [vals[i:i + 500] for i in range(0, len(vals), 500)]
        return f"delete from {table};\n" + "".join(
            f"insert into {table} ({', '.join(cols)}) values\n  " + ",\n  ".join(c) + ";\n" for c in chunks)

    text = f"""-- 17_team_data.sql: Medicare TEAM model data (Phase 7): episode trigger codes, the procedure families that are TEAM
-- episodes, CMS preliminary regional target prices for 2026 and 2027, and the hospital participant list.
-- Written by `python orthoparity.py load-team` from CMS's TEAM files and reference/team_*.csv. Don't edit by hand;
-- rerun the step. Safe to run again. Run 18_team_functions.sql after it, then 05.

create table if not exists pc_team_trigger (
  category_id text not null, category text, code_type text not null, code text not null, price_drg text, setting text,
  note text, source text, source_url text, primary key (code_type, code));
create table if not exists pc_team_family (
  family_id text primary key, category_id text, price_drgs text, family_drgs_in_team text, family_drgs_not_in_team text, note text, basis text);
create table if not exists pc_team_target_price (
  py int not null, year int, category_id text, drg text not null, region text not null, region_name text,
  benchmark_price numeric, trend_factor numeric, discount_factor numeric, target_price numeric, source_file text,
  source_url text, primary key (py, drg, region));
create table if not exists pc_team_participant (
  ccn text primary key, hospital text, participation text, cbsa text, cbsa_name text, state text, start_date date,
  end_date date, newly_identified boolean, as_of date, source_url text);
create index if not exists pc_team_participant_name on pc_team_participant using gin (lower(hospital || ' ' || coalesce(cbsa_name, '')) gin_trgm_ops);

-- Public read rules: the same rules Lovable's security scan set live on Nov 24 (every row has these keys, so every
-- row stays public to read; nobody can write).
alter table pc_team_trigger enable row level security;
alter table pc_team_family enable row level security;
alter table pc_team_target_price enable row level security;
alter table pc_team_participant enable row level security;
drop policy if exists "public read" on pc_team_trigger;
drop policy if exists "public read" on pc_team_family;
drop policy if exists "public read" on pc_team_target_price;
drop policy if exists "public read" on pc_team_participant;
create policy "public read" on pc_team_trigger for select to anon, authenticated using (category_id is not null and code is not null);
create policy "public read" on pc_team_family for select to anon, authenticated using (family_id is not null);
create policy "public read" on pc_team_target_price for select to anon, authenticated using (drg is not null and region is not null);
create policy "public read" on pc_team_participant for select to anon, authenticated using (ccn is not null);
grant select on pc_team_trigger, pc_team_family, pc_team_target_price, pc_team_participant to anon, authenticated;

{inserts("pc_team_trigger", TRIGGER_COLS, triggers)}
{inserts("pc_team_family", FAMILY_COLS, families)}
{inserts("pc_team_target_price", PRICE_COLS, prices, {"py", "year", "benchmark_price", "trend_factor", "discount_factor", "target_price"})}
{inserts("pc_team_participant", PART_COLS, parts)}
-- Empty the page cache so no page shows answers made before this file ran.
do $$ begin if to_regclass('public.pc_cache') is not null then truncate pc_cache; end if; end $$;
"""
    path.write_text(text, encoding="utf-8", newline="\n")


def load(folder: Path, root: Path, site: Path, out_dir: Path) -> dict:
    triggers = read_csv(root / "reference" / "team_triggers.csv")
    families = read_csv(root / "reference" / "team_episode_families.csv")
    known_families = {r["family_id"] for r in read_csv(root / "reference" / "procedure_families.csv")}
    find(folder, MAPPING_PATTERN)  # the source for team_episode_families.csv must sit beside the other files

    problems = []
    trig_drgs = {r["code"] for r in triggers if r["code_type"] == "MS-DRG"}
    for r in triggers:
        if r["code_type"] == "HCPCS" and r["price_drg"] not in trig_drgs:
            problems.append(f"HCPCS {r['code']} is priced under MS-DRG {r['price_drg']}, which is not a trigger")
    for f in families:
        if f["family_id"] not in known_families:
            problems.append(f"team_episode_families.csv: unknown family {f['family_id']}")
        if f["category_id"] and f["category_id"] not in CATEGORY_LABELS:
            problems.append(f"team_episode_families.csv: unknown category {f['category_id']}")
        for d in [x for x in f["price_drgs"].split("|") if x]:
            t = next((t for t in triggers if t["code_type"] == "MS-DRG" and t["code"] == d), None)
            if not t or t["category_id"] != f["category_id"]:
                problems.append(f"team_episode_families.csv: {f['family_id']} prices under MS-DRG {d}, "
                                f"which is not a {f['category_id']} trigger")

    prices = []
    for py, (year, pattern, url) in PRICE_FILES.items():
        rows = read_prices(find(folder, pattern), py, year, url)
        drgs = {r["drg"] for r in rows if r["drg"] != "All"}
        cat_of = {r["code"]: r["category_id"] for r in triggers if r["code_type"] == "MS-DRG"}
        for r in rows:
            if r["drg"] != "All" and cat_of.get(r["drg"]) != r["category_id"]:
                problems.append(f"PY{py}: MS-DRG {r['drg']} is '{r['category_id']}' in the CMS file but "
                                f"'{cat_of.get(r['drg'])}' in team_triggers.csv")
        extra = drgs - trig_drgs
        missing = trig_drgs - drgs
        if extra:
            problems.append(f"PY{py}: CMS prices MS-DRGs that 42 CFR 512.525(d) doesn't list: {sorted(extra)}")
        if missing and py == max(PRICE_FILES):
            problems.append(f"PY{py}: no CMS price for trigger MS-DRGs {sorted(missing)}")
        for d in drgs | {"All"}:
            for cid in {r["category_id"] for r in rows if r["drg"] == d}:
                n = sum(1 for r in rows if r["drg"] == d and r["category_id"] == cid)
                if n != REGIONS:
                    problems.append(f"PY{py}: MS-DRG {d} ({cid}) has {n} regions, expected {REGIONS}")
        # the "All" rows are per category; keep them under a category-specific key so the primary key holds
        for r in rows:
            if r["drg"] == "All":
                r["drg"] = "All " + r["category_id"]
        prices += rows
    parts = read_participants(find(folder, r"particip"))
    if len({p["ccn"] for p in parts}) != len(parts):
        problems.append("Participant list repeats a CCN")
    if problems:
        raise SystemExit("TEAM files don't match the reference files:\n  " + "\n  ".join(problems))

    site.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("pc_team_trigger", TRIGGER_COLS, triggers), ("pc_team_family", FAMILY_COLS, families),
                             ("pc_team_target_price", PRICE_COLS, prices), ("pc_team_participant", PART_COLS, parts)):
        with open(site / f"{name}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    write_sql(root / "supabase" / "17_team_data.sql", triggers, families, prices, parts)

    py2 = [r for r in prices if r["py"] == 2 and not r["drg"].startswith("All")]
    ortho = [r for r in py2 if r["category_id"] in ("LEJR", "SHFFT", "SPINE")]
    lo = min(ortho, key=lambda r: float(r["target_price"]))
    hi = max(ortho, key=lambda r: float(r["target_price"]))
    as_of = parts[0]["as_of"] if parts else "NOT FOUND"
    lines = [
        "Medicare TEAM model",
        f"Trigger codes (42 CFR 512.525(d)): {sum(1 for t in triggers if t['code_type'] == 'MS-DRG')} MS-DRGs and "
        f"{sum(1 for t in triggers if t['code_type'] == 'HCPCS')} HCPCS codes in 5 episode categories.",
        f"Procedure families that are TEAM episodes: {sum(1 for f in families if f['category_id'])} "
        f"({', '.join(f['family_id'] for f in families if f['category_id'])}); "
        f"checked and not TEAM: {', '.join(f['family_id'] for f in families if not f['category_id']) or 'none'}.",
        f"Preliminary target prices: {sum(1 for r in prices if r['py'] == 1)} PY1 (2026) rows and "
        f"{sum(1 for r in prices if r['py'] == 2)} PY2 (2027) rows, MS-DRG by census division."
        + "".join(f" CMS's PY{k} file repeats {v} rows word for word; each was kept once." for k, v in sorted(DUPLICATES.items())),
        f"PY2 orthopedic range: ${float(lo['target_price']):,.0f} (MS-DRG {lo['drg']}, region {lo['region']}) to "
        f"${float(hi['target_price']):,.0f} (MS-DRG {hi['drg']}, region {hi['region']}).",
        f"Participants as of {as_of}: {len(parts)} hospitals "
        f"({sum(1 for p in parts if p['participation'] == 'Mandatory')} mandatory, "
        f"{sum(1 for p in parts if p['participation'] == 'Voluntary')} voluntary) in "
        f"{len({p['cbsa'] for p in parts})} CBSAs and {len({p['state'] for p in parts})} states.",
        "Not published by CMS: hospital-specific target prices and each hospital's track. Both are NOT FOUND on the site.",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "TEAM_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return {"triggers": len(triggers), "families": len(families), "prices": len(prices), "participants": len(parts)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.ini")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    d = Path(cfg.get("cms_team", "DIR", "../CMS TEAM"))
    folder = d if d.is_absolute() else (cfg.project_dir / d).resolve()
    if not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}. Save the four CMS TEAM files there (see pipeline/load_team.py).")
    load(folder, cfg.project_dir, cfg.site_data_dir, cfg.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
