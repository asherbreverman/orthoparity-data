"""Resumable background runner with a plain-text progress file."""
from __future__ import annotations

import datetime as dt
import json
import os
import signal
import sys
import time

from . import PARSER_VERSION
from .chains import pending_nodes
from .config import Config
from .db import connect, init_schema
from .fetch import FdaClient
from .pipeline import Extractor
from .runlog import RunLog


class Progress:
    def __init__(self, cfg: Config, run_name: str):
        self.path = cfg.output_dir / f"progress_{run_name}.txt"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_name = run_name
        self.t0 = time.monotonic()
        self.done_this_run = 0
        self.downloaded = 0
        self.bytes = 0
        self.errors = 0
        self.last = ""
        self.stage = ""

    def write(self, done: int, total: int, note: str = ""):
        elapsed = time.monotonic() - self.t0
        rate = elapsed / self.done_this_run if self.done_this_run else None
        left = (total - done) * rate if rate else None
        pct = 100.0 * done / total if total else 100.0
        fmt = lambda s: str(dt.timedelta(seconds=int(s))) if s is not None else "estimating..."
        lines = [
            f"OrthoParity progress  (run: {self.run_name}, parser {PARSER_VERSION})",
            f"Updated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (your local time)",
            f"Stage: {self.stage}",
            f"Done: {done:,} of {total:,}  ({pct:.1f}%)",
            f"Elapsed this session: {fmt(elapsed)}    Estimated time left: {fmt(left)}",
            f"PDFs downloaded this session: {self.downloaded:,} ({self.bytes / 1e6:.1f} MB)    Errors: {self.errors}",
            f"Last item: {self.last}",
            "",
            note or "To stop safely: press Ctrl+C or close the window. Double-click the .bat again to resume.",
        ]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self.path)


_STATE = {"stop": False, "saved": False, "handler": None}


def _install_windows_close_handler():
    """Closing the console window (or logoff/shutdown) asks the run to stop after the current document.
    Windows allows a few seconds; whatever is unfinished is rolled back, so the next run resumes cleanly."""
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        HANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

        def handler(ctrl_type):
            if ctrl_type in (2, 5, 6):  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
                _STATE["stop"] = True
                for _ in range(45):
                    if _STATE["saved"]:
                        break
                    time.sleep(0.1)
                return True
            return False  # Ctrl+C / Ctrl+Break: Python raises KeyboardInterrupt

        _STATE["handler"] = HANDLER(handler)  # keep a reference so it is not garbage-collected
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_STATE["handler"], True)
    except Exception:
        pass


def _keep_awake(on: bool):
    """Stop Windows from sleeping while a run is active (the screen may still turn off)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


def _checkpoint(cfg: Config, run_name: str, done: int, total: int, last: str, prog):
    f = cfg.output_dir / f"checkpoint_{run_name}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"run": run_name, "parser_version": PARSER_VERSION, "done": done, "total": total,
                               "last": last, "downloaded_this_session": prog.downloaded,
                               "errors_this_session": prog.errors,
                               "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}, indent=1),
                   encoding="utf-8")
    tmp.replace(f)


def _install_signal_handlers():
    def handler(signum, frame):
        raise KeyboardInterrupt
    for name in ("SIGBREAK", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


def run(cfg: Config, run_name: str, *, walk_chains: bool, max_chain_docs: int | None = None,
        phase: str = "pilot", offline: bool = False, echo=print) -> dict:
    _install_signal_handlers()
    _install_windows_close_handler()
    _keep_awake(True)
    _STATE["stop"] = _STATE["saved"] = False
    con = connect(cfg.db_path)
    init_schema(con)
    seeds = [r[0] for r in con.execute("SELECT knumber FROM run_targets WHERE run_name=? ORDER BY seq", (run_name,))]
    if not seeds:
        raise SystemExit(f"No targets found for run '{run_name}'. Run the setup step first.")
    log = RunLog(cfg.log_dir, phase, con)
    client = None if offline else FdaClient(cfg, log)
    ex = Extractor(con, cfg, client, log, offline=offline)
    prog = Progress(cfg, run_name)
    errored: set[str] = set()
    ended = "completed"
    chain_docs = 0
    try:
        log.log("run", None, result="start", reason=f"{run_name}: {len(seeds)} seeds, walk_chains={walk_chains}")
        # ---- stage A: seeds -------------------------------------------------
        done_set = {r[0] for r in con.execute("SELECT knumber FROM node_status WHERE parser_version=?", (PARSER_VERSION,))}
        todo = [s for s in seeds if s not in done_set]
        total = len(seeds)
        prog.stage = f"Stage 1 of {'2' if walk_chains else '1'}: starting devices"
        done = total - len(todo)
        prog.write(done, total)
        for i, k in enumerate(todo, 1):
            _check_stop(cfg)
            r = ex.process(k, 0, None)
            _account(prog, r, errored, not offline)
            done += 1
            prog.last = f"{k} -> {r.stop_reason or r.status} ({len(r.predicates)} predicates)"
            if i % 5 == 0 or i == len(todo):
                prog.write(done, total)
            if i % 100 == 0:
                log.log("run", None, result="checkpoint", reason=f"{done} of {total}")
                _checkpoint(cfg, run_name, done, total, k, prog)
            echo(f"[{done}/{total}] {prog.last}")
        # ---- stage B: chain walk ----------------------------------------------
        if walk_chains:
            prog.stage = "Stage 2 of 2: walking predicate chains"
            while True:
                pend = pending_nodes(con, seeds, cfg.max_generations, PARSER_VERSION, errored)
                if not pend:
                    break
                if max_chain_docs is not None and chain_docs >= max_chain_docs:
                    log.log("run", None, result="cap reached", reason=f"chain walk cap {max_chain_docs}")
                    ended = f"chain-walk cap of {max_chain_docs} documents reached ({len(pend)} nodes still pending)"
                    break
                gen = pend[0][1]
                level = [p for p in pend if p[1] == gen]
                for idx, (k, d, parent) in enumerate(level, 1):
                    if max_chain_docs is not None and chain_docs >= max_chain_docs:
                        break
                    _check_stop(cfg)
                    r = ex.process(k, d, parent)
                    _account(prog, r, errored, not offline)
                    chain_docs += 1
                    prog.last = f"{k} (generation {d}, from {parent}) -> {r.stop_reason or r.status}"
                    prog.stage = f"Stage 2 of 2: walking predicate chains, generation {d} of {cfg.max_generations}"
                    if chain_docs % 5 == 0:
                        prog.write(chain_docs, chain_docs + len(pend) - idx, "Chain-walk total grows as new predicates are found.")
                    if chain_docs % 100 == 0:
                        log.log("run", None, result="checkpoint", reason=f"chain docs {chain_docs}")
                        _checkpoint(cfg, run_name, chain_docs, chain_docs + len(pend) - idx, k, prog)
                    echo(f"[chain {chain_docs}] {prog.last}")
    except TooManyErrors as exc:
        ended = f"paused after repeated errors ({exc}). Check your internet connection, then run again"
        echo("\n" + ended)
    except StopRequested:
        ended = ("stopped because the window was closed (resumable)" if _STATE["stop"]
                 else "stopped by STOP file (resumable)")
        echo("\nStopped. Everything finished so far is saved. Run again to resume.")
    except KeyboardInterrupt:
        ended = "stopped by user (resumable)"
        echo("\nStopped. Everything finished so far is saved. Double-click the .bat again to resume.")
    finally:
        con.commit()
        processed = con.execute("SELECT COUNT(*) FROM node_status WHERE parser_version=?", (PARSER_VERSION,)).fetchone()[0]
        seed_done = con.execute("SELECT COUNT(*) FROM node_status n JOIN run_targets t ON t.knumber=n.knumber "
                                "WHERE t.run_name=? AND n.parser_version=?", (run_name, PARSER_VERSION)).fetchone()[0]
        prog.stage = f"Finished: {ended}"
        if walk_chains and seed_done == len(seeds):
            prog.write(processed, processed, f"Run ended: {ended}.")
        else:
            prog.write(seed_done, len(seeds), f"Run ended: {ended}." + (
                "" if seed_done == len(seeds) else " Double-click the .bat again to finish the rest."))
        log.log("run", None, result="end", reason=ended)
        log.close(targets=len(seeds), processed=processed, ended_how=ended)
        _checkpoint(cfg, run_name, seed_done, len(seeds), f"run ended: {ended}", prog)
        con.close()
        _keep_awake(False)
        _STATE["saved"] = True
    return {"ended": ended, "chain_docs": chain_docs, "errors": len(errored)}


class TooManyErrors(RuntimeError):
    pass


class StopRequested(RuntimeError):
    pass


def _check_stop(cfg: Config):
    """Create an empty file named STOP in the outputs folder to end a background run cleanly."""
    if _STATE["stop"]:
        raise StopRequested
    f = cfg.output_dir / "STOP"
    if f.exists():
        try:
            f.unlink()
        except OSError:
            pass
        raise StopRequested


def _account(prog: Progress, r, errored: set, strict: bool = True):
    prog.done_this_run += 1
    if r.status == "error":
        prog.errors += 1
        errored.add(r.knumber)
        prog.consecutive_errors = getattr(prog, "consecutive_errors", 0) + 1
        if strict and prog.consecutive_errors >= 10:
            raise TooManyErrors(f"10 errors in a row; last: {r.stop_detail}")
    else:
        prog.consecutive_errors = 0
    if r.downloaded:
        prog.downloaded += 1
        prog.bytes += r.bytes
