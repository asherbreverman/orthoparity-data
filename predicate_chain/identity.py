"""PREDICATE IDENTITY RULE: company and product name come from FDA records by number, never from PDF text.
Order: starting-set file, FDA master table, openFDA, FDA web database, else not found."""
from __future__ import annotations

import sqlite3

from .fetch import FdaClient, detail_page_fields, utcnow
from .numbers import number_kind

NOT_FOUND_NAME = "No Company Name Found"


class IdentityResolver:
    def __init__(self, con: sqlite3.Connection, client: FdaClient | None = None, use_openfda: bool = True, log=None):
        self.con = con
        self.client = client
        self.use_openfda = use_openfda
        self.log = log
        self._memo: dict[str, dict] = {}

    def __call__(self, number: str) -> dict:
        number = number.upper()
        if number in self._memo:
            return self._memo[number]
        out = self._resolve(number)
        self._memo[number] = out
        return out

    def _resolve(self, number: str) -> dict:
        kind = number_kind(number)
        if kind == "P":
            return {"found": False, "source": "PMA (not in 510(k) records)", "applicant": None, "device_name": None}
        r = self.con.execute(
            "SELECT applicant, devicename, decision_date, product_code, review_advise_comm, loaded_at_utc, loaded_from "
            "FROM clearances WHERE knumber=?", (number,)).fetchone()
        if r:
            return {"found": True, "source": "starting set", "applicant": r[0], "device_name": r[1],
                    "decision_date": r[2], "product_code": r[3], "review_panel": r[4], "retrieved_at": r[5]}
        r = self.con.execute(
            "SELECT applicant, devicename, decision_date, product_code, review_panel, loaded_at_utc, source_file "
            "FROM fda_master WHERE knumber=?", (number,)).fetchone()
        if r:
            return {"found": True, "source": "FDA master", "applicant": r[0], "device_name": r[1],
                    "decision_date": r[2], "product_code": r[3], "review_panel": r[4], "retrieved_at": r[5]}
        r = self.con.execute("SELECT * FROM external_lookups WHERE number=?", (number,)).fetchone()
        if r:
            return {"found": bool(r["found"]), "source": r["source"], "applicant": r["applicant"],
                    "device_name": r["device_name"], "decision_date": r["decision_date"],
                    "product_code": r["product_code"], "review_panel": r["review_panel"],
                    "retrieved_at": r["retrieved_at_utc"]}
        if self.client is None:
            return {"found": False, "source": "not in local FDA files (offline)", "applicant": None,
                    "device_name": None}
        # openFDA, then FDA web database
        if self.use_openfda:
            o = self.client.openfda(number)
            if self.log:
                self.log.log("lookup", number, url=o.get("url"), http_status=o.get("http_status"),
                             result="found" if o.get("found") else "miss", reason="openFDA identity lookup")
            if o.get("found"):
                return self._store(number, "openFDA", o)
        res, page = self.client.detail_page(number)
        if page:
            f = detail_page_fields(page)
            if f.get("found"):
                f["url"], f["http_status"], f["retrieved_at"] = res.url, res.status, res.retrieved_at
                return self._store(number, "FDA web database", f)
        return self._store(number, "not found", {"found": False, "url": res.url if res else None,
                                                 "http_status": res.status if res else None,
                                                 "retrieved_at": utcnow()})

    def _store(self, number: str, source: str, d: dict) -> dict:
        self.con.execute(
            "INSERT OR REPLACE INTO external_lookups (number, source, found, applicant, device_name, decision_date, "
            "product_code, review_panel, url, http_status, retrieved_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (number, source, int(bool(d.get("found"))), d.get("applicant"), d.get("device_name"),
             d.get("decision_date"), d.get("product_code"), d.get("review_panel"), d.get("url"),
             d.get("http_status"), d.get("retrieved_at") or utcnow()))
        self.con.commit()
        out = dict(d)
        out["source"] = source
        return out
