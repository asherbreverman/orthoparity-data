"""Registered clinical trials from ClinicalTrials.gov for orthopedic devices and the companies that make them.

Source (NLM, public): the ClinicalTrials.gov API v2, every study with a device intervention (about 77,000 records,
78 requests at 1 per second). The raw download is cached in outputs/trials/device_trials.jsonl; run with --refresh
to download again.

Three links, all exact, none guessed:
  1. Device links. A registry record that writes one of OrthoParity's FDA numbers (K, DEN, P or H number) in its
     title, summary, description or intervention text is linked to that device. The number must be in OrthoParity.
     Trials whose Open Payments research record names a 510(k) and gives an NCT number are linked the same way.
  2. Company links. A trial's lead sponsor is linked to an OrthoParity company when the sponsor's name matches a name
     in the vendor registry after removing case, punctuation and legal suffixes, and the sponsor is an industry
     sponsor; or when reference/trial_sponsors.csv names it (reviewed aliases such as business unit names). Counts
     roll up to today's parent company.
  3. Orthopedic scope. Company counts include only trials whose conditions fall under the MeSH terms in
     reference/trial_mesh_terms.csv (musculoskeletal diseases, fractures and limb injuries), so a diversified
     company's heart or diabetes trials stay out.

Outputs: outputs/site_data/pc_trial.csv, pc_trial_device.csv, pc_trial_vendor.csv; outputs/Trials_Report.txt and
outputs/trials/unmatched_industry_sponsors.csv (industry sponsors of orthopedic device trials with no company match,
for review).

Usage:  python orthoparity.py fetch-trials [--refresh]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from predicate_chain.config import load_config

API = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ["NCTId", "BriefTitle", "OfficialTitle", "OverallStatus", "StudyType", "Phase", "LeadSponsorName",
          "LeadSponsorClass", "InterventionType", "InterventionName", "InterventionDescription", "InterventionOtherName",
          "Condition", "StartDate", "PrimaryCompletionDate", "CompletionDate", "HasResults", "PrimaryOutcomeMeasure",
          "PrimaryOutcomeTimeFrame", "EnrollmentCount", "BriefSummary", "DetailedDescription", "DesignAllocation",
          "DesignPrimaryPurpose", "LastUpdatePostDate", "ConditionBrowseModule"]
FDA_NUMBER = re.compile(r"\b(K\d{6}|DEN\d{6}|P\d{6}|H\d{6})\b")
LEGAL = (r"\b(inc|incorporated|llc|l l c|ltd|limited|corp|corporation|co|company|gmbh|ag|sa|s a|bv|b v|plc|lp|l p|kg|"
         r"srl|spa|s p a|sas|pty|ab|as|oy|nv|n v|the|holdings?|group|usa|us|america|americas|north america|"
         r"international|intl)\b")
STATUS = {"RECRUITING": "Recruiting", "NOT_YET_RECRUITING": "Not yet recruiting", "ACTIVE_NOT_RECRUITING": "Active, not recruiting",
          "ENROLLING_BY_INVITATION": "Enrolling by invitation", "COMPLETED": "Completed", "TERMINATED": "Terminated",
          "WITHDRAWN": "Withdrawn", "SUSPENDED": "Suspended", "UNKNOWN": "Unknown status", "AVAILABLE": "Available",
          "NO_LONGER_AVAILABLE": "No longer available", "TEMPORARILY_NOT_AVAILABLE": "Temporarily not available",
          "APPROVED_FOR_MARKETING": "Approved for marketing", "WITHHELD": "Withheld"}
TRIAL_COLS = ["nct", "title", "status", "study_type", "phase", "sponsor", "sponsor_class", "start_date",
              "primary_completion", "completion_date", "has_results", "enrollment", "primary_outcome",
              "primary_timeframe", "allocation", "purpose", "conditions", "devices", "musculoskeletal",
              "last_update", "url"]
DEVICE_COLS = ["nct", "number", "basis", "context"]
VENDOR_COLS = ["nct", "vendor_id", "owner_id", "sponsor", "basis"]


ORG_WORDS = re.compile(r"\b(univ|universit|hospital|institut|health|cent(er|re)|clinic|college|foundation|laborator|research|"
                       r"medical|specialists|school|society|group|inc|llc|ltd|gmbh|corp|company|association|ministry|"
                       r"department|network|trust|nhs|hôpital|hospital|klinik|sciences|pharma|biotech|surgical|"
                       r"orthopa?edic|services|agency|council|consortium|academ)", re.I)
PERSON = re.compile(r"\b(dr|prof|md|phd|mbbs|frcs)\b\.?", re.I)


def public_sponsor(name: str, sponsor_class: str) -> str:
    """Industry and organization sponsors as written; a person's name is never stored (no surgeon names)."""
    if sponsor_class == "INDUSTRY" and not PERSON.search(name or ""):
        return name
    if sponsor_class in ("INDIV",) or PERSON.search(name or "") or not ORG_WORDS.search(name or ""):
        return "Individual investigator (name not shown)"
    return name


def norm(name: str) -> str:
    s = str(name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(LEGAL, " ", s)
    return " ".join(s.split())


def download(path: Path, user_agent: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tok, n = None, 0
    with open(tmp, "w", encoding="utf-8") as out:
        while True:
            q = {"filter.advanced": "AREA[InterventionType]DEVICE", "pageSize": 1000, "fields": ",".join(FIELDS),
                 "format": "json"}
            if tok:
                q["pageToken"] = tok
            req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q), headers={"User-Agent": user_agent})
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(req, timeout=120) as r:
                        d = json.load(r)
                    break
                except Exception as e:  # network hiccup: wait and retry
                    if attempt == 3:
                        raise SystemExit(f"ClinicalTrials.gov download failed after 4 tries: {e}")
                    time.sleep(5 * (attempt + 1))
            for s in d.get("studies", []):
                out.write(json.dumps(s) + "\n")
                n += 1
            tok = d.get("nextPageToken")
            print(f"  {n:,} studies", end="\r", flush=True)
            if not tok:
                break
            time.sleep(1)
    tmp.replace(path)
    print()
    return n


def text_fields(ps: dict):
    ident = ps.get("identificationModule", {})
    desc = ps.get("descriptionModule", {})
    yield ident.get("briefTitle", "")
    yield ident.get("officialTitle", "")
    yield desc.get("briefSummary", "")
    yield desc.get("detailedDescription", "")
    for i in ps.get("armsInterventionsModule", {}).get("interventions", []) or []:
        yield i.get("name", "")
        yield i.get("description", "")
        yield " ".join(i.get("otherNames", []) or [])


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def site_rows(site: Path, table: str) -> list[dict]:
    """A site table plus the rows the FDA approvals step adds to it (pc_approval_rows.csv, Phase 5)."""
    rows = read_csv(site / f"{table}.csv")
    extra = site / "pc_approval_rows.csv"
    if extra.exists():
        rows += [{k: ("" if v is None else str(v)) for k, v in json.loads(r["row"]).items()}
                 for r in read_csv(extra) if r["target"] == table]
    return rows


def build(raw: Path, root: Path, site: Path, out_dir: Path) -> dict:
    numbers = {r["knumber"] for r in site_rows(site, "pc_portfolio_510k")}
    vendors = {r["vendor_id"]: r for r in site_rows(site, "pc_vendors")}
    owner = {v: (r.get("rolls_up_to") or v) for v, r in vendors.items()}
    by_name: dict[str, set] = defaultdict(set)
    for r in site_rows(site, "pc_vendor_names"):
        if norm(r["raw_name"]) and r["vendor_id"] in vendors:
            by_name[norm(r["raw_name"])].add(r["vendor_id"])
    aliases = {r["sponsor_name"].strip(): r for r in read_csv(root / "reference" / "trial_sponsors.csv")}
    for a in aliases.values():
        if a["vendor_id"] not in vendors:
            raise SystemExit(f"reference/trial_sponsors.csv: unknown vendor_id {a['vendor_id']}")
    mesh_ids = {r["mesh_id"] for r in read_csv(root / "reference" / "trial_mesh_terms.csv")}
    op_links = defaultdict(set)  # NCT -> 510(k)s, from Open Payments research records
    for r in read_csv(site / "pc_op_research.csv"):
        nct = (r.get("ct_gov_id") or "").strip().upper()
        if re.fullmatch(r"NCT\d{8}", nct):
            for k in (r.get("knumbers") or "").split("|"):
                if k.strip() in numbers:
                    op_links[nct].add(k.strip())

    trials, dev_links, ven_links = {}, [], []
    unmatched, ambiguous = Counter(), set()
    total = msk = 0
    with open(raw, encoding="utf-8") as fh:
        for line in fh:
            s = json.loads(line)
            ps = s.get("protocolSection", {})
            nct = ps.get("identificationModule", {}).get("nctId", "")
            total += 1
            cb = s.get("derivedSection", {}).get("conditionBrowseModule", {})
            mesh = {m.get("id") for m in (cb.get("meshes") or []) + (cb.get("ancestors") or [])}
            is_msk = bool(mesh & mesh_ids)
            msk += is_msk
            # 1. device links: exact FDA numbers in the record's own text
            found = {}
            for t in text_fields(ps):
                for m in FDA_NUMBER.finditer(t or ""):
                    if m.group(1) in numbers and m.group(1) not in found:
                        ctx = " ".join(t[max(0, m.start() - 90):m.end() + 50].split())
                        found[m.group(1)] = "" if PERSON.search(ctx) else ctx
            for k, ctx in sorted(found.items()):
                dev_links.append({"nct": nct, "number": k, "basis": "FDA number written in the registry record",
                                  "context": ctx})
            for k in sorted(op_links.get(nct, set()) - set(found)):
                dev_links.append({"nct": nct, "number": k, "basis": "Open Payments research record names this 510(k) and this trial",
                                  "context": ""})
            # 2. company links
            sp = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
            sponsor, sclass = sp.get("name", ""), sp.get("class", "")
            vid, basis = None, ""
            if sponsor.strip() in aliases:
                vid, basis = aliases[sponsor.strip()]["vendor_id"], "Reviewed sponsor alias (reference/trial_sponsors.csv)"
            elif sclass == "INDUSTRY" and norm(sponsor) in by_name:
                hit = by_name[norm(sponsor)]
                owners = {owner[v] for v in hit}
                if len(owners) == 1:
                    vid, basis = sorted(hit)[0], "Sponsor name matches the company's name in the vendor registry"
                else:
                    ambiguous.add(sponsor)
            elif sclass == "INDUSTRY" and is_msk:
                unmatched[sponsor] += 1
            if vid and is_msk:
                ven_links.append({"nct": nct, "vendor_id": vid, "owner_id": owner[vid], "sponsor": public_sponsor(sponsor, sclass),
                                  "basis": basis})
            if not (found or nct in op_links or (vid and is_msk)):
                continue
            stat = ps.get("statusModule", {})
            design = ps.get("designModule", {})
            outcomes = ps.get("outcomesModule", {}).get("primaryOutcomes", []) or []
            devices = [i.get("name", "") for i in ps.get("armsInterventionsModule", {}).get("interventions", []) or []
                       if i.get("type") == "DEVICE"]
            trials[nct] = {
                "nct": nct, "title": ps.get("identificationModule", {}).get("briefTitle", ""),
                "status": STATUS.get(stat.get("overallStatus", ""), stat.get("overallStatus", "").replace("_", " ").title()),
                "study_type": design.get("studyType", "").title(),
                "phase": ", ".join(p.replace("_", " ").title() for p in design.get("phases", []) or []),
                "sponsor": public_sponsor(sponsor, sclass), "sponsor_class": sclass.title(),
                "start_date": stat.get("startDateStruct", {}).get("date", ""),
                "primary_completion": stat.get("primaryCompletionDateStruct", {}).get("date", ""),
                "completion_date": stat.get("completionDateStruct", {}).get("date", ""),
                "has_results": bool(s.get("hasResults")),
                "enrollment": design.get("enrollmentInfo", {}).get("count", ""),
                "primary_outcome": (outcomes[0].get("measure", "") if outcomes else "")[:500],
                "primary_timeframe": (outcomes[0].get("timeFrame", "") if outcomes else "")[:200],
                "allocation": design.get("designInfo", {}).get("allocation", "").replace("_", " ").title(),
                "purpose": design.get("designInfo", {}).get("primaryPurpose", "").replace("_", " ").title(),
                "conditions": "; ".join(ps.get("conditionsModule", {}).get("conditions", []) or [])[:500],
                "devices": "; ".join(devices)[:500], "musculoskeletal": is_msk,
                "last_update": stat.get("lastUpdatePostDateStruct", {}).get("date", ""),
                "url": f"https://clinicaltrials.gov/study/{nct}"}

    site.mkdir(parents=True, exist_ok=True)
    for name, cols, rows in (("pc_trial", TRIAL_COLS, sorted(trials.values(), key=lambda r: r["nct"])),
                             ("pc_trial_device", DEVICE_COLS, sorted(dev_links, key=lambda r: (r["nct"], r["number"]))),
                             ("pc_trial_vendor", VENDOR_COLS, sorted(ven_links, key=lambda r: r["nct"]))):
        with open(site / f"{name}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
    (out_dir / "trials").mkdir(parents=True, exist_ok=True)
    with open(out_dir / "trials" / "unmatched_industry_sponsors.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["sponsor_name", "musculoskeletal_device_trials", "ambiguous"])
        for n, c in unmatched.most_common():
            w.writerow([n, c, ""])
        for n in sorted(ambiguous):
            w.writerow([n, "", "matches more than one parent company"])

    owners = Counter(l["owner_id"] for l in ven_links)
    lines = [
        "Registered clinical trials (ClinicalTrials.gov)",
        f"Device-intervention studies read: {total:,}; with musculoskeletal conditions: {msk:,}.",
        f"Device links: {len(dev_links)} links from {len({l['nct'] for l in dev_links})} trials to "
        f"{len({l['number'] for l in dev_links})} OrthoParity devices "
        f"({sum(1 for l in dev_links if l['basis'].startswith('FDA number'))} from FDA numbers in the record, "
        f"{sum(1 for l in dev_links if l['basis'].startswith('Open Payments'))} from Open Payments).",
        f"Company links: {len(ven_links):,} musculoskeletal device trials led by {len({l['vendor_id'] for l in ven_links})} "
        f"companies, rolling up to {len(owners)} parent companies.",
        "Top parents: " + "; ".join(f"{vendors[o]['display_name']} {n}" for o, n in owners.most_common(10)),
        f"Industry sponsors of musculoskeletal device trials with no company match: {len(unmatched)} "
        f"({sum(unmatched.values())} trials); sponsors matching more than one parent: {len(ambiguous)}. "
        "See outputs/trials/unmatched_industry_sponsors.csv.",
        f"Trials stored for the site: {len(trials):,}.",
    ]
    (out_dir / "Trials_Report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return {"trials": len(trials), "device_links": len(dev_links), "vendor_links": len(ven_links)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.ini")
    ap.add_argument("--refresh", action="store_true", help="download ClinicalTrials.gov again")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    raw = cfg.output_dir / "trials" / "device_trials.jsonl"
    if args.refresh or not raw.exists():
        print("Downloading every device study from ClinicalTrials.gov (about 78 requests)...")
        download(raw, cfg.get("network", "USER_AGENT", "OrthoParity"))
    build(raw, cfg.project_dir, cfg.site_data_dir, cfg.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
