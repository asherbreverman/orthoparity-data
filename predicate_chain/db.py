"""SQLite schema and connection helpers."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = r"""
PRAGMA foreign_keys = ON;

-- 1. The starting set: one row per clearance in the orthopedic workbook.
CREATE TABLE IF NOT EXISTS clearances (
    knumber              TEXT PRIMARY KEY,
    applicant            TEXT,
    contact              TEXT,
    street1              TEXT,
    street2              TEXT,
    city                 TEXT,
    state                TEXT,
    country_code         TEXT,
    zip                  TEXT,
    postal_code          TEXT,
    date_received        TEXT,
    decision_date        TEXT,
    decision_year        INTEGER,
    decision             TEXT,
    review_advise_comm   TEXT,
    product_code         TEXT,
    device               TEXT,
    regulation_description TEXT,
    regulation_number    TEXT,
    device_class         TEXT,
    life_sustaining      TEXT,
    implant              TEXT,
    stateorsumm          TEXT,
    classadvisecomm      TEXT,
    sspindicator         TEXT,
    type                 TEXT,
    thirdparty           TEXT,
    expeditedreview      TEXT,
    devicename           TEXT,
    unofficial_segment   TEXT,   -- assigned by Claude, not FDA
    unofficial_sub_segment TEXT, -- assigned by Claude, not FDA
    submission_category  TEXT,
    inclusion_basis      TEXT,
    source_file          TEXT,   -- value of the workbook's SOURCE FILE column
    loaded_from          TEXT,   -- workbook name
    loaded_at_utc        TEXT
);

-- 2. Every FDA 510(k)/De Novo record, all review panels, 1976 to present.
CREATE TABLE IF NOT EXISTS fda_master (
    knumber          TEXT PRIMARY KEY,
    applicant        TEXT,
    contact          TEXT,
    street1          TEXT,
    street2          TEXT,
    city             TEXT,
    state            TEXT,
    country_code     TEXT,
    zip              TEXT,
    postal_code      TEXT,
    date_received    TEXT,
    decision_date    TEXT,
    decision_year    INTEGER,
    decision         TEXT,
    review_panel     TEXT,   -- REVIEWADVISECOMM
    product_code     TEXT,
    stateorsumm      TEXT,
    classadvisecomm  TEXT,
    sspindicator     TEXT,
    type             TEXT,
    thirdparty       TEXT,
    expeditedreview  TEXT,
    devicename       TEXT,
    source_file      TEXT,
    loaded_at_utc    TEXT
);
CREATE INDEX IF NOT EXISTS ix_fda_master_applicant ON fda_master(applicant);

-- 3. FDA product code classification.
CREATE TABLE IF NOT EXISTS product_codes (
    product_code       TEXT PRIMARY KEY,
    review_panel       TEXT,
    medical_specialty  TEXT,
    device_name        TEXT,
    device_class       TEXT,
    unclassified_reason TEXT,
    gmp_exempt_flag    TEXT,
    third_party_flag   TEXT,
    review_code        TEXT,
    regulation_number  TEXT,
    submission_type_id TEXT,
    definition         TEXT,
    physical_state     TEXT,
    technical_method   TEXT,
    target_area        TEXT,
    implant_flag       TEXT,
    life_sustain_support_flag TEXT,
    summary_malfunction_reporting TEXT,
    source_file        TEXT,
    loaded_at_utc      TEXT
);

-- 4. One row per K-number per parser version: where the PDF came from and what the parser saw.
CREATE TABLE IF NOT EXISTS documents (
    knumber            TEXT NOT NULL,
    parser_version     TEXT NOT NULL,
    fetch_outcome      TEXT,     -- downloaded | cache hit | copied from previous run | not found | error | skipped
    url                TEXT,
    url_source         TEXT,     -- detail page link | URL pattern | none
    detail_page_url    TEXT,
    detail_page_status INTEGER,
    detail_page_link   TEXT,     -- Summary/Statement link found on the detail page
    detail_page_label  TEXT,     -- "Summary", "Statement", ...
    http_status        INTEGER,
    sha256             TEXT,
    bytes              INTEGER,
    retrieved_at_utc   TEXT,
    download_seconds   REAL,
    file_source        TEXT,     -- "downloaded" | "copied from previous run"
    cache_path         TEXT,
    page_count         INTEGER,
    text_method        TEXT,     -- text layer | OCR | needs OCR | unreadable | none
    text_chars         INTEGER,
    pdf_own_knumber    TEXT,
    predicate_sections INTEGER,
    parse_status       TEXT,     -- CLEAN | AMBIGUOUS | NOT PARSED
    parse_notes        TEXT,
    parsed_at_utc      TEXT,
    PRIMARY KEY (knumber, parser_version)
);

-- 5. Predicate edges: child (subject device) -> predicate it cites.
CREATE TABLE IF NOT EXISTS edges (
    edge_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    child_knumber      TEXT NOT NULL,
    parser_version     TEXT NOT NULL,
    predicate_number   TEXT,     -- NULL when the predicate has no FDA number
    predicate_base     TEXT,     -- number without PMA supplement
    predicate_kind     TEXT,     -- K | DEN | P | none
    list_order         INTEGER,
    role               TEXT,     -- primary | reference
    role_basis         TEXT,     -- why this role was assigned
    printed_label      TEXT,     -- label printed in the PDF (primary predicate, reference device, ...)
    family_of          TEXT,     -- number this edge is a family member of ("including K2, K3")
    printed_name       TEXT,     -- name as printed in the PDF (cross-check only)
    printed_company    TEXT,     -- company as printed in the PDF (cross-check only)
    fda_applicant      TEXT,     -- identity from FDA records by number
    fda_device_name    TEXT,
    fda_decision_date  TEXT,
    fda_product_code   TEXT,
    fda_review_panel   TEXT,
    identity_source    TEXT,     -- starting set | FDA master | openFDA | FDA web database | not found
    identity_retrieved_at_utc TEXT,
    name_match_score   REAL,
    company_match      INTEGER,
    in_predicate_section INTEGER,
    section_heading    TEXT,
    confidence         TEXT,     -- HIGH | MEDIUM | LOW
    page               INTEGER,
    evidence           TEXT,     -- verbatim snippet, max 300 characters
    created_at_utc     TEXT
);
CREATE INDEX IF NOT EXISTS ix_edges_child ON edges(child_knumber, parser_version);
CREATE INDEX IF NOT EXISTS ix_edges_pred ON edges(predicate_number);

-- 6. Exactly one stop reason (or none, when the node continues) per node per parser version.
CREATE TABLE IF NOT EXISTS node_status (
    knumber          TEXT NOT NULL,
    parser_version   TEXT NOT NULL,
    in_starting_set  INTEGER,
    stateorsumm      TEXT,
    decision_year    INTEGER,
    status           TEXT,     -- continues | stopped
    stop_reason      TEXT,
    stop_detail      TEXT,
    distance         INTEGER,  -- generations from the nearest starting-set / pilot device
    discovered_from  TEXT,
    updated_at_utc   TEXT,
    PRIMARY KEY (knumber, parser_version)
);

-- 7. Flags raised by the cross-check.
CREATE TABLE IF NOT EXISTS flags (
    flag_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    knumber          TEXT NOT NULL,
    parser_version   TEXT NOT NULL,
    flag_type        TEXT NOT NULL,
    number           TEXT,
    detail           TEXT,
    page             INTEGER,
    evidence         TEXT,
    created_at_utc   TEXT
);
CREATE INDEX IF NOT EXISTS ix_flags_k ON flags(knumber, parser_version);

-- 8. Items that need a second look.
CREATE TABLE IF NOT EXISTS review_queue (
    queue_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    knumber          TEXT NOT NULL,
    parser_version   TEXT NOT NULL,
    item_type        TEXT,     -- edge | flag | document
    ref_id           INTEGER,  -- edge_id or flag_id (NULL for documents)
    reason           TEXT,
    status           TEXT DEFAULT 'open',
    created_at_utc   TEXT
);

-- 9. Review decisions. Never overwrites parser output.
CREATE TABLE IF NOT EXISTS review_decisions (
    decision_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id         INTEGER,
    knumber          TEXT,
    edge_id          INTEGER,
    decision         TEXT,
    reasoning        TEXT,
    evidence_page    INTEGER,
    decision_source  TEXT,     -- parser | Claude review | human review
    reviewer         TEXT,
    decided_at_utc   TEXT,
    predicate_number TEXT,     -- the number the decision is about (matches edges across parser versions)
    corrected_number TEXT,     -- decision 'corrected': the number the document meant
    parser_version   TEXT      -- parser version the reviewer looked at
);

-- 10. One row per run, pointing at its JSONL log.
CREATE TABLE IF NOT EXISTS run_log_index (
    run_id           TEXT PRIMARY KEY,
    phase            TEXT,
    parser_version   TEXT,
    log_file         TEXT,
    started_at_utc   TEXT,
    ended_at_utc     TEXT,
    targets          INTEGER,
    processed        INTEGER,
    errors           INTEGER,
    ended_how        TEXT,
    notes            TEXT
);

-- Helper: target lists for runs (pilot sample, full run, frontier).
CREATE TABLE IF NOT EXISTS run_targets (
    run_name         TEXT NOT NULL,
    knumber          TEXT NOT NULL,
    stratum          TEXT,
    seq              INTEGER,
    PRIMARY KEY (run_name, knumber)
);

-- Helper: identity lookups that went to openFDA or the FDA web database.
CREATE TABLE IF NOT EXISTS external_lookups (
    number           TEXT PRIMARY KEY,
    source           TEXT,
    found            INTEGER,
    applicant        TEXT,
    device_name      TEXT,
    decision_date    TEXT,
    product_code     TEXT,
    review_panel     TEXT,
    url              TEXT,
    http_status      INTEGER,
    retrieved_at_utc TEXT
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute("PRAGMA table_info(review_decisions)")}
    for col in ("predicate_number", "corrected_number", "parser_version"):
        if col not in have:  # databases built before tool 0.3.0
            con.execute(f"ALTER TABLE review_decisions ADD COLUMN {col} TEXT")
    con.commit()


TABLES = ["clearances", "fda_master", "product_codes", "documents", "edges", "node_status",
          "flags", "review_queue", "review_decisions", "run_log_index"]
