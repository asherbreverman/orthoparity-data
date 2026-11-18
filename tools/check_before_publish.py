"""Scan this folder for anything that must never be published, before you push to GitHub or attach a release.

    python orthoparity.py check             checks every file git would publish
    python orthoparity.py check --release   also checks outputs/site_data (the CSVs you attach to a release)

It fails (exit code 1) on any of these:
  - a file that must stay private: the surgeon-key salt (data/recipient_salt.txt), databases, .env files
  - a file over 50 MB (GitHub refuses files over 100 MB; large data belongs in a release, not the repo)
  - text that looks like a secret: a Supabase service-role key, a private key, an AWS or Stripe key
  - a number that passes the NPI check digit (a surgeon's National Provider Identifier)
  - a column header that names an individual recipient (first name, last name, NPI, CMS profile ID)
  - the salt's own value anywhere in a published file
A public Supabase "anon" key is fine to publish; the check reports it as a note.
"""
from __future__ import annotations

import base64
import fnmatch
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 50 * 1024 * 1024
NEVER = ["recipient_salt.txt", "*.db", "*.db-journal", "*.duckdb", "*.duckdb.wal", ".env", ".env.*", "*.pem", "*.key",
         "credentials.toml", "secrets.toml"]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "data", "cache", "logs", "outputs", "_to_delete"}
TEXT_EXT = {".py", ".md", ".txt", ".csv", ".sql", ".ini", ".json", ".yml", ".yaml", ".toml", ".bat", ".sh", ".html",
            ".svg", ".cfg", ".gitignore", ".gitattributes"}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Stripe secret key": re.compile(r"\bsk_live_[0-9A-Za-z]{10,}"),
    "Supabase secret key": re.compile(r"\bsb_secret_[0-9A-Za-z_\-]{10,}"),
    "service-role variable": re.compile(r"SERVICE_ROLE_KEY\s*[=:]\s*['\"]?[A-Za-z0-9_\-\.]{20,}"),
}
JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")
TEN_DIGITS = re.compile(r"(?<![\w.])([12]\d{9})(?![\w.])")
PERSON_HEADERS = re.compile(r"(first_name|last_name|middle_name|\bnpi\b|_npi\b|profile_id|recipient_name|"
                            r"physician_name|investigator_name)", re.I)
# Allowed header names that contain those words but hold no person data.
HEADER_OK = {"npi_present"}


def npi_valid(s: str) -> bool:
    """True when a 10-digit number passes the NPI Luhn check (prefix 80840, per CMS)."""
    digits = [int(c) for c in "80840" + s[:9]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(s[9])


def jwt_role(token: str) -> str | None:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part)).get("role")
    except Exception:
        return None


def files_to_publish(include_release: bool) -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.splitlines()
        files = [ROOT / f for f in out if f]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in ROOT.rglob("*") if p.is_file()
                 and not any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts)]
    if include_release:
        site = ROOT / "outputs" / "site_data"
        files += [p for p in site.rglob("*") if p.is_file()] if site.exists() else []
    return sorted(set(p for p in files if p.exists()))


def text_of(p: Path) -> str | None:
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            with zipfile.ZipFile(p) as z:
                return "\n".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
        except zipfile.BadZipFile:
            return None
    if p.suffix.lower() in TEXT_EXT or p.name in (".gitignore", ".gitattributes", "LICENSE"):
        return p.read_text(encoding="utf-8", errors="replace")
    return None


def check(include_release: bool = False) -> tuple[list[str], list[str]]:
    problems, notes = [], []
    salt_file = ROOT / "data" / "recipient_salt.txt"
    salt = salt_file.read_text(encoding="utf-8").strip() if salt_file.exists() else ""
    for p in files_to_publish(include_release):
        rel = p.relative_to(ROOT).as_posix()
        if rel == "tools/check_before_publish.py":
            continue  # this file names the patterns it looks for
        if any(fnmatch.fnmatch(p.name, pat) for pat in NEVER):
            problems.append(f"{rel}: this kind of file must never be published")
            continue
        if p.stat().st_size > MAX_BYTES:
            problems.append(f"{rel}: {p.stat().st_size / 1e6:,.0f} MB, over the 50 MB limit (attach data to a release)")
        text = text_of(p)
        if text is None:
            continue
        if salt and len(salt) >= 8 and salt in text:
            problems.append(f"{rel}: contains the surgeon-key salt from data/recipient_salt.txt")
        for label, rx in SECRET_PATTERNS.items():
            if rx.search(text):
                problems.append(f"{rel}: looks like a {label}")
        for tok in JWT.findall(text):
            role = jwt_role(tok)
            if role == "anon":
                notes.append(f"{rel}: a Supabase anon (public) key, which is fine to publish")
            else:
                problems.append(f"{rel}: a signed token with role '{role}' (never publish a service-role key)")
        if p.suffix.lower() in (".csv", ".xlsx", ".xlsm"):
            first = text.split("\n", 1)[0] if p.suffix.lower() == ".csv" else ""
            bad = [h for h in re.split(r"[,\t]", first) if PERSON_HEADERS.search(h) and h.strip().lower() not in HEADER_OK]
            if bad:
                problems.append(f"{rel}: column header names an individual ({', '.join(bad[:3])})")
        hits = sorted({n for n in TEN_DIGITS.findall(text) if npi_valid(n)})
        if hits and rel.startswith("tests/"):
            notes.append(f"{rel}: {len(hits)} NPI-shaped number(s) in synthetic test fixtures")
        elif hits:
            problems.append(f"{rel}: {len(hits)} number(s) pass the NPI check digit, for example {hits[0]} "
                            "(check that no surgeon identifier is in this file)")
    return problems, notes


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    problems, notes = check("--release" in argv)
    for n in sorted(set(notes)):
        print("note:", n)
    if problems:
        print(f"\nNOT SAFE TO PUBLISH: {len(problems)} problem(s).")
        for p in problems:
            print("  -", p)
        return 1
    print("\nSafe to publish: no private files, secrets or surgeon identifiers found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
