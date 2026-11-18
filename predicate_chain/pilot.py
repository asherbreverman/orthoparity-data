"""Phase 1 pilot sample: seeded, stratified."""
from __future__ import annotations

import random
import sqlite3

from .config import Config

ERA_STRATA = [("1976-1990", 1976, 1990), ("1991-1995", 1991, 1995), ("1996-1999", 1996, 1999),
              ("2000-2009", 2000, 2009), ("2010-2019", 2010, 2019), ("2020-2026", 2020, 2026)]
SPECIAL = "Statement / blank status / DEN"


def era_label(year: int | None) -> str:
    for name, a, b in ERA_STRATA:
        if year is not None and a <= year <= b:
            return name
    return "unknown"


def select_pilot(con: sqlite3.Connection, cfg: Config, run_name: str = "pilot") -> list[tuple[str, str]]:
    seed = cfg.getint("settings", "PILOT_SEED", 20261116)
    n = cfg.getint("settings", "PILOT_PER_STRATUM", 20)
    rng = random.Random(seed)
    known = [k for k in cfg.pilot_known_cases]
    chosen: list[tuple[str, str]] = [(k, "Known case") for k in known]
    taken: set[str] = set(known)
    for name, a, b in ERA_STRATA:
        pool = sorted(r[0] for r in con.execute(
            "SELECT knumber FROM clearances WHERE decision_year BETWEEN ? AND ?", (a, b)) if r[0] not in taken)
        pick = rng.sample(pool, min(n, len(pool)))
        chosen += [(k, name) for k in pick]
        taken.update(pick)
    pool = sorted(r[0] for r in con.execute(
        "SELECT knumber FROM clearances WHERE stateorsumm='Statement' OR stateorsumm IS NULL OR knumber LIKE 'DEN%'")
        if r[0] not in taken)
    pick = rng.sample(pool, min(n, len(pool)))
    chosen += [(k, SPECIAL) for k in pick]
    con.execute("DELETE FROM run_targets WHERE run_name=?", (run_name,))
    con.executemany("INSERT INTO run_targets (run_name, knumber, stratum, seq) VALUES (?,?,?,?)",
                    [(run_name, k, s, i) for i, (k, s) in enumerate(chosen)])
    con.commit()
    return chosen
