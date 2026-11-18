"""JSONL run log: one line per action."""
from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

from . import PARSER_VERSION

ACTIONS = {"lookup", "download", "cache hit", "parse", "ocr", "cross-check", "flag", "stop",
           "review decision", "load", "run", "copy"}


class RunLog:
    def __init__(self, log_dir: Path, phase: str, con=None):
        log_dir.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now(dt.timezone.utc)
        self.run_id = f"{phase}-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        self.path = log_dir / f"run_log_{now.strftime('%Y-%m-%d')}.jsonl"
        self.phase = phase
        self.con = con
        self.count = 0
        self.errors = 0
        self.started = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if con is not None:
            con.execute(
                "INSERT OR REPLACE INTO run_log_index (run_id, phase, parser_version, log_file, started_at_utc) VALUES (?,?,?,?,?)",
                (self.run_id, phase, PARSER_VERSION, str(self.path.name), self.started))
            con.commit()

    def log(self, action: str, knumber: str | None = None, *, depth=None, url=None, http_status=None,
            result=None, reason=None, **extra):
        rec = {
            "ts_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "run_id": self.run_id,
            "parser_version": PARSER_VERSION,
            "action": action,
            "knumber": knumber,
            "depth": depth,
            "url": url,
            "http_status": http_status,
            "result": result,
            "reason": (reason or "")[:300] if reason else reason,
        }
        rec.update(extra)
        if result == "error":
            self.errors += 1
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.count += 1

    def close(self, *, targets=None, processed=None, ended_how="completed", notes=None):
        if self.con is None:
            return
        self.con.execute(
            "UPDATE run_log_index SET ended_at_utc=?, targets=?, processed=?, errors=?, ended_how=?, notes=? WHERE run_id=?",
            (dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), targets, processed, self.errors,
             ended_how, notes, self.run_id))
        self.con.commit()
