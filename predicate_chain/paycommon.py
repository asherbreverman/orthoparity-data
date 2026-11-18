"""Shared helpers for the Open Payments and GUDID steps (Benchmark a Vendor)."""
from __future__ import annotations

import datetime as dt
import glob
import os
import time
from pathlib import Path

from .config import Config

# Same rules as lookup_core.company_root (kept here so the payment scripts import nothing heavy).
CO_SUFFIX = {"inc", "incorporated", "corp", "corporation", "llc", "ltd", "limited", "co", "company", "gmbh", "ag",
             "sa", "sas", "sarl", "srl", "spa", "bv", "nv", "plc", "lp", "llp", "kg", "oy", "ab", "pty", "the", "usa",
             "us"}


def company_root(name: str | None) -> str:
    import re
    import unicodedata
    folded = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()  # "Sàrl" -> "Sarl"
    words = [w for w in re.findall(r"[a-z0-9]+", folded.lower()) if w not in CO_SUFFIX and len(w) > 1]
    return "".join(words)


def _split(value: str, sep: str = ",") -> list[str]:
    return [v.strip() for v in value.split(sep) if v.strip()]


class PaySettings:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        g = lambda k: cfg.get("payments", k)
        self.op_dir = self._p(g("OP_DIR"))
        self.year_folder = g("OP_YEAR_FOLDER")
        self.years = [int(y) for y in _split(g("OP_YEARS"))]
        self.globs = {"general": g("OP_GENERAL_GLOB"), "research": g("OP_RESEARCH_GLOB"),
                      "ownership": g("OP_OWNERSHIP_GLOB"), "removed": g("OP_REMOVED_GLOB")}
        self.specialty_regex = g("OP_ORTHO_SPECIALTY_REGEX")
        self.product_regex = g("OP_ORTHO_PRODUCT_REGEX")
        self.gudid_dir = self._p(g("GUDID_DIR"))
        self.gudid_glob = g("GUDID_FILE_GLOB")
        self.gudid_parts = cfg.getint("payments", "GUDID_PARTS")
        self.gudid_expected = cfg.getint("payments", "GUDID_EXPECTED_RECORDS")
        w = g("GUDID_WORKERS")
        self.gudid_workers = int(w) if w else max(1, min(6, (os.cpu_count() or 2) - 1))
        self.db = Path(os.environ.get("PAYMENTS_DB") or self._p(g("PAYMENTS_DB")))
        self.stage = self._p(g("GUDID_STAGE_DIR"))
        self.tmp = self._p(g("DUCKDB_TEMP_DIR"))
        self.memory = g("DUCKDB_MEMORY_LIMIT") or "4GB"

    def _p(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (self.cfg.project_dir / p).resolve()

    def op_file(self, year: int, kind: str) -> Path | None:
        folder = self.op_dir / self.year_folder.format(year=year)
        hits = sorted(glob.glob(str(folder / self.globs[kind].format(year=year))))
        if not hits:
            if kind == "removed":
                return None
            raise FileNotFoundError(f"No {kind} file for {year} in {folder} (pattern {self.globs[kind]})")
        if len(hits) > 1:
            raise RuntimeError(f"More than one {kind} file for {year}: {hits}")
        return Path(hits[0])

    def gudid_files(self) -> list[Path]:
        return [Path(p) for p in sorted(glob.glob(str(self.gudid_dir / self.gudid_glob)))]


def connect_duck(ps: PaySettings):
    import duckdb
    ps.db.parent.mkdir(parents=True, exist_ok=True)
    ps.tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ps.db))
    con.execute(f"SET memory_limit = '{ps.memory}'")
    con.execute(f"SET temp_directory = '{ps.tmp.as_posix()}'")
    con.execute("SET preserve_insertion_order = false")
    con.execute("""CREATE TABLE IF NOT EXISTS run_steps (step VARCHAR PRIMARY KEY, done_utc VARCHAR,
                   rows BIGINT, seconds DOUBLE, detail VARCHAR)""")
    return con


def step_done(con, step: str) -> bool:
    return con.execute("SELECT 1 FROM run_steps WHERE step = ?", [step]).fetchone() is not None


def mark_step(con, step: str, rows: int | None, seconds: float, detail: str = ""):
    con.execute("DELETE FROM run_steps WHERE step = ?", [step])
    con.execute("INSERT INTO run_steps VALUES (?, ?, ?, ?, ?)",
                [step, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), rows, round(seconds, 1),
                 detail])


def keep_awake(on: bool):
    """Stop Windows from sleeping while a run is active (the screen may still turn off)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


class StopRequested(Exception):
    pass


def check_stop(cfg: Config):
    f = cfg.output_dir / "STOP"
    if f.exists():
        raise StopRequested("STOP file found in outputs")


class Progress:
    """Plain-text progress file the user can open in Notepad."""

    def __init__(self, cfg: Config, name: str, title: str):
        self.path = cfg.output_dir / f"progress_{name}.txt"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.title = title
        self.t0 = time.monotonic()
        self.done_session = 0

    def write(self, stage: str, done: int, total: int, last: str = "", count_session: bool = True):
        if count_session:
            self.done_session += 1
        elapsed = time.monotonic() - self.t0
        rate = elapsed / self.done_session if self.done_session else None
        left = (total - done) * rate if rate else None
        fmt = lambda s: str(dt.timedelta(seconds=int(s))) if s is not None else "estimating..."
        pct = 100.0 * done / total if total else 100.0
        lines = [self.title,
                 f"Updated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (your local time)",
                 f"Stage: {stage}",
                 f"Done: {done:,} of {total:,}  ({pct:.1f}%)",
                 f"Elapsed this session: {fmt(elapsed)}    Estimated time left: {fmt(left)}",
                 f"Last step: {last}", "",
                 "To stop safely: close the window or create a file named STOP in outputs. "
                 "Double-click the .bat again to resume."]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self.path)
