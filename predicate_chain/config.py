"""Reads config.ini. Every file name and expected count comes from there."""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _split(value: str, sep: str = "|") -> list[str]:
    return [v.strip() for v in value.split(sep) if v.strip()]


@dataclass
class Config:
    raw: configparser.ConfigParser
    project_dir: Path = PROJECT_DIR
    max_generations: int = 10
    pilot_known_cases: list[str] = field(default_factory=list)

    # ---- convenience accessors -------------------------------------------
    def get(self, section: str, key: str, fallback: str = "") -> str:
        return self.raw.get(section, key, fallback=fallback).strip()

    def getint(self, section: str, key: str, fallback: int = 0) -> int:
        return self.raw.getint(section, key, fallback=fallback)

    def getbool(self, section: str, key: str, fallback: bool = False) -> bool:
        return self.raw.getboolean(section, key, fallback=fallback)

    def path(self, key: str) -> Path:
        p = Path(self.get("paths", key))
        return p if p.is_absolute() else (self.project_dir / p).resolve()

    @property
    def input_dir(self) -> Path:
        return self.path("INPUT_DIR")

    @property
    def db_path(self) -> Path:
        # PREDICATE_CHAIN_DB lets a maintainer point at a local copy (for example on a network or
        # virtual drive where SQLite file locking does not work). Normal users never set it.
        override = os.environ.get("PREDICATE_CHAIN_DB")
        return Path(override) if override else self.path("DB_FILE")

    @property
    def site_data_dir(self) -> Path:
        """CSV files for the website database (one per Supabase table)."""
        return self.path("SITE_DATA_DIR") if self.get("paths", "SITE_DATA_DIR") else self.output_dir / "site_data"

    @property
    def review_dir(self) -> Path:
        """Human review decisions live here (published with the code, unlike outputs/)."""
        return self.path("REVIEW_DIR") if self.get("paths", "REVIEW_DIR") else self.output_dir

    @property
    def cache_dir(self) -> Path:
        return self.path("CACHE_DIR")

    @property
    def detail_cache_dir(self) -> Path:
        return self.path("DETAIL_CACHE_DIR")

    @property
    def log_dir(self) -> Path:
        return self.path("LOG_DIR")

    @property
    def output_dir(self) -> Path:
        return self.path("OUTPUT_DIR")

    @property
    def data_dir(self) -> Path:
        return self.path("DATA_DIR")

    @property
    def starting_set_file(self) -> Path:
        return self.input_dir / self.get("inputs", "STARTING_SET_FILE")

    @property
    def starting_set_sheet(self) -> str:
        return self.get("inputs", "STARTING_SET_SHEET")

    @property
    def fda_master_files(self) -> list[Path]:
        return [self.input_dir / f for f in _split(self.get("inputs", "FDA_MASTER_FILES"))]

    @property
    def product_code_file(self) -> Path:
        return self.input_dir / self.get("inputs", "PRODUCT_CODE_FILE")

    def expected(self, key: str) -> str:
        return self.get("expected_counts", key)

    def expected_era_counts(self) -> dict[tuple[str, str], int]:
        out = {}
        for item in _split(self.expected("STATEORSUMM_BY_ERA")):
            left, count = item.split("=")
            era, value = left.split(":")
            out[(era.strip(), value.strip())] = int(count)
        return out


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path) if path else PROJECT_DIR / "config.ini"
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
    cp.optionxform = str  # keep key case
    with open(path, encoding="utf-8") as fh:
        cp.read_file(fh)
    cfg = Config(raw=cp, project_dir=path.resolve().parent)
    cfg.max_generations = cp.getint("settings", "MAX_GENERATIONS", fallback=10)
    cfg.pilot_known_cases = [k.strip().upper() for k in cp.get("settings", "PILOT_KNOWN_CASES", fallback="").split(",") if k.strip()]
    return cfg
