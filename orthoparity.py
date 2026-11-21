"""OrthoParity data pipeline: one command for every step.

    python orthoparity.py                  list every step and group
    python orthoparity.py <step> [args]    run one step, for example: python orthoparity.py load-fda
    python orthoparity.py <group>          run a group of steps in order: predicates, payments, recalls, maude, supplier, addon, medicare, site-data, all

On Windows you can double-click run.bat instead; it sets up Python and then runs this file.
Every step reads its settings from config.ini and is safe to run again. Long downloads resume where they stopped.
To stop a long download cleanly, create an empty file named STOP in the outputs folder (or close the window).
"""
from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# (step name, module, what it does). Build steps are listed in the order they run.
PREDICATE_STEPS = [
    ("load-fda", "pipeline.load_fda",
     "Load the FDA 510(k) release files and product codes, check every row count against config.ini."),
    ("extract-predicates", "pipeline.extract_predicates",
     "Download each orthopedic 510(k) Summary PDF (1 request per second) and read its predicates. Resumable."),
    ("walk-ancestors", "pipeline.walk_ancestors",
     "Follow every predicate chain back, up to 10 generations, reading each ancestor's Summary. Resumable."),
    ("import-review", "pipeline.import_review",
     "Apply the predicate review decisions in reviews/predicate_review."),
    ("extract-ifu", "pipeline.extract_ifu",
     "Pull the Indications for Use text from the cached Summary PDFs (no downloads)."),
    ("product-dictionary", "pipeline.product_dictionary",
     "Refresh the plain-English product code workbook in reviews/ (keeps reviewed answers)."),
    ("export-predicates", "pipeline.export_predicates",
     "Write the device, predicate, flag, IFU and product code CSVs for the website."),
]
PAYMENT_STEPS = [
    ("index-gudid", "pipeline.index_gudid",
     "Index the FDA GUDID full release (device IDs, brands, 510(k) numbers). Resumable."),
    ("load-open-payments", "pipeline.load_open_payments",
     "Load CMS Open Payments 2019-2025 for orthopedic payers. No surgeon names are loaded."),
    ("build-vendor-registry", "pipeline.build_vendor_registry",
     "Group company names into vendors, with dated ownership (reviews/Vendor_Registry_REVIEW.xlsx)."),
    ("match-products", "pipeline.match_products",
     "Link Open Payments product tags to devices, brands and 510(k) numbers."),
    ("build-payment-aggregates", "pipeline.build_payment_aggregates",
     "Build every payment total the website shows."),
    ("validate-payments", "pipeline.validate_payments",
     "Check the payment build against published figures and itself (outputs/payments_validation.md)."),
    ("repair-text", "pipeline.repair_text",
     "Restore trademark signs, dashes and accented letters lost in the source files."),
    ("export-payments", "pipeline.export_payments",
     "Write the vendor and payment CSVs for the website."),
]
RECALL_STEPS = [
    ("fetch-recalls", "pipeline.fetch_recalls",
     "Download FDA device recalls for every orthopedic product code from openFDA and link them to vendors."),
]
SUPPLIER_STEPS = [
    ("fetch-establishments", "pipeline.fetch_establishments",
     "Download FDA establishment registrations that list orthopedic devices and link each site to its 510(k)s."),
    ("load-fda-compliance", "pipeline.load_fda_compliance",
     "Load FDA inspections, 483 citations and warning letters (FDA Data Dashboard exports) for those sites."),
]
ADD_ON_STEPS = [
    ("load-add-on-payments", "pipeline.load_add_on_payments",
     "Check reference/add_on_payments.csv against the CMS NTAP and device pass-through files and write the tables."),
]
MAUDE_STEPS = [
    ("fetch-maude", "pipeline.fetch_maude",
     "Count FDA adverse event reports (MAUDE) for every orthopedic 510(k) from openFDA (free API key recommended)."),
]
MEDICARE_STEPS = [
    ("load-medicare-hospitals", "pipeline.load_medicare",
     "Build the procedure view from CMS Medicare inpatient and outpatient hospital payments (national, no charges)."),
]
TOOL_STEPS = [
    ("lookup", "tools.lookup", "Look up one device's ancestor chain from the command line."),
    ("lookup-app", None, "Open the local lookup app in your browser (Streamlit)."),
    ("review-packet", "tools.review_packet", "Write the next batch of flagged documents for review."),
    ("import-handcheck", "tools.import_handcheck", "Record a filled hand-check workbook."),
    ("pilot", "tools.run_pilot", "Run the 2026-11-16 pilot sample (validation history)."),
    ("pilot-report", "tools.pilot_report", "Write the pilot report and hand-check workbook."),
    ("make-validation", "tools.make_validation", "Draw a fresh validation sample and write its hand-check workbook."),
    ("accuracy-report", "tools.accuracy_report", "Score a filled validation workbook (error rates with 95% intervals)."),
    ("export-master", "tools.export_master", "Export every database table to CSV plus a summary workbook."),
    ("lineage-trees", "tools.make_lineage_trees", "Draw lineage trees by segment (HTML)."),
    ("segment-visuals", "tools.make_segment_visuals", "Draw predicate tree visuals by segment (needs Graphviz)."),
    ("reparse-offline", "tools.reparse_offline", "Re-read cached PDFs after a parser change (no downloads)."),
    ("check", "tools.check_before_publish", "Scan the folder for anything that must never be published."),
    ("test", None, "Run the unit tests (synthetic data only)."),
]
GROUPS = {
    "predicates": PREDICATE_STEPS,
    "payments": PAYMENT_STEPS,
    "recalls": RECALL_STEPS,
    "maude": MAUDE_STEPS,
    "supplier": SUPPLIER_STEPS,
    "addon": ADD_ON_STEPS,
    "medicare": MEDICARE_STEPS,
    "site-data": [s for s in PREDICATE_STEPS if s[0] == "export-predicates"]
                 + [s for s in PAYMENT_STEPS if s[0] == "export-payments"] + MEDICARE_STEPS,
    "all": PREDICATE_STEPS + PAYMENT_STEPS + RECALL_STEPS + MAUDE_STEPS + SUPPLIER_STEPS + ADD_ON_STEPS + MEDICARE_STEPS,
}
STEPS = {name: (module, what) for name, module, what
         in PREDICATE_STEPS + PAYMENT_STEPS + RECALL_STEPS + MAUDE_STEPS + SUPPLIER_STEPS + ADD_ON_STEPS + MEDICARE_STEPS + TOOL_STEPS}


def show_help() -> None:
    print(__doc__.strip().splitlines()[0])
    for title, steps in (("Build the predicate data", PREDICATE_STEPS), ("Build the vendor and payment data",
                         PAYMENT_STEPS), ("Recalls", RECALL_STEPS), ("Adverse event reports", MAUDE_STEPS),
                         ("Manufacturing sites and inspections", SUPPLIER_STEPS),
                         ("Medicare add-on payments", ADD_ON_STEPS),
                         ("Medicare procedure view", MEDICARE_STEPS),
                         ("Tools", TOOL_STEPS)):
        print(f"\n{title}:")
        for name, _, what in steps:
            print(f"  {name:<26}{what}")
    print("\nGroups (run every step in order):")
    for g, steps in GROUPS.items():
        print(f"  {g:<26}{', '.join(s[0] for s in steps)}")
    print("\nExample:  python orthoparity.py predicates")


def run_step(name: str, args: list[str]) -> int:
    module, _ = STEPS[name]
    outputs = ROOT / "outputs"
    stop = outputs / "STOP"
    if stop.exists():
        stop.unlink()  # a STOP left over from an earlier run would end this one at once
    if name == "test":
        return subprocess.call([sys.executable, "-m", "pytest", "-q", *args], cwd=ROOT)
    if name == "lookup-app":
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(ROOT / "tools" / "lookup_app.py"),
                                "--browser.gatherUsageStats", "false", *args], cwd=ROOT)
    mod = importlib.import_module(module)
    sys.argv = [f"orthoparity.py {name}", *args]
    started = time.time()
    print(f"\n=== {name} ===")
    try:
        rc = mod.main(args) if inspect.signature(mod.main).parameters else mod.main()
    except KeyboardInterrupt:
        print(f"\n{name} interrupted. Run it again to continue where it stopped.")
        return 130
    except Exception:
        outputs.mkdir(parents=True, exist_ok=True)
        err = outputs / f"ERROR_{name}.txt"
        err.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"{name} stopped on an error, saved to {err}. Attach that file to a GitHub issue if you need help.")
        return 1
    rc = 0 if rc is None else int(rc)
    print(f"=== {name} finished in {time.time() - started:,.0f} s (exit code {rc}) ===")
    return rc


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help", "list"):
        show_help()
        return 0
    name, args = argv[0], argv[1:]
    if name in GROUPS:
        for step, _, _ in GROUPS[name]:
            rc = run_step(step, [])
            if rc != 0:
                print(f"\nStopped the '{name}' group at {step}. Fix the problem and run the group again; "
                      "finished steps are quick to repeat.")
                return rc
        return 0
    if name not in STEPS:
        print(f"Unknown step '{name}'.\n")
        show_help()
        return 2
    return run_step(name, args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
