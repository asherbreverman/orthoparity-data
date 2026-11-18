"""LOOKUP LAYER: build ancestor chains from stored edges. Never downloads or reads a PDF."""
from __future__ import annotations

import sqlite3
from collections import deque
from dataclasses import dataclass, field

from .pipeline import SR_TRUNCATED

NOT_EXTRACTED = "Not yet extracted"


@dataclass
class ChainNode:
    knumber: str
    generation: int
    status: str | None = None          # continues | stopped | None (not extracted)
    stop_reason: str | None = None     # chain-level: includes TRUNCATED / Not yet extracted
    parser_version: str | None = None
    via_roles: set = field(default_factory=set)


@dataclass
class Chain:
    root: str
    max_generations: int
    nodes: dict = field(default_factory=dict)    # knumber -> ChainNode
    roots: list = field(default_factory=list)
    edges: list = field(default_factory=list)    # sqlite rows (dict) with 'generation' = child generation

    @property
    def truncated(self) -> bool:
        return any(n.stop_reason == SR_TRUNCATED for n in self.nodes.values())

    @property
    def depth(self) -> int:
        return max((n.generation for n in self.nodes.values()), default=0)


DROP_DECISIONS = {"own number", "not a predicate"}


def review_overrides(con: sqlite3.Connection) -> dict:
    """Phase 4 decisions keyed by (child, printed number), newest first wins.
    Values: ("drop", None) | ("replace", number) | ("keep", None). Parser rows are never changed."""
    out: dict = {}
    try:
        rows = con.execute("SELECT knumber, predicate_number, decision, corrected_number FROM review_decisions "
                           "WHERE predicate_number IS NOT NULL AND decision_source IN ('Claude review','human review') "
                           "ORDER BY decided_at_utc DESC, decision_id DESC").fetchall()
    except sqlite3.OperationalError:  # database from before tool 0.3.0
        return out
    for k, n, d, c in rows:
        key = (k, n)
        if key in out:
            continue
        if d in DROP_DECISIONS:
            out[key] = ("drop", None)
        elif d == "corrected" and c:
            out[key] = ("replace", c)
        else:
            out[key] = ("keep", None)
    return out


def latest_versions(con: sqlite3.Connection) -> dict[str, str]:
    """Newest parser version recorded for each node (string compare on dotted version)."""
    out: dict[str, str] = {}
    for k, v in con.execute("SELECT knumber, parser_version FROM node_status"):
        if k not in out or _vkey(v) > _vkey(out[k]):
            out[k] = v
    return out


def _vkey(v: str):
    return tuple(int(x) if x.isdigit() else x for x in v.split("."))


def build_chain(con: sqlite3.Connection, root, max_generations: int, versions: dict | None = None) -> Chain:
    """Breadth-first walk of ancestors from one K-number or a list of them (a brand family).
    Each node appears once, at its smallest generation."""
    versions = versions if versions is not None else latest_versions(con)
    overrides = review_overrides(con)
    roots = [r.upper() for r in ([root] if isinstance(root, str) else root)]
    chain = Chain(roots[0], max_generations)
    chain.roots = roots
    q = deque()
    for r in roots:
        if r not in chain.nodes:
            chain.nodes[r] = ChainNode(r, 0)
            q.append((r, 0))
    while q:
        k, g = q.popleft()
        node = chain.nodes[k]
        v = versions.get(k)
        if v is None:
            node.stop_reason = NOT_EXTRACTED
            continue
        st = con.execute("SELECT status, stop_reason FROM node_status WHERE knumber=? AND parser_version=?",
                         (k, v)).fetchone()
        node.parser_version = v
        node.status = st["status"]
        node.stop_reason = st["stop_reason"]
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM edges WHERE child_knumber=? AND parser_version=? ORDER BY list_order", (k, v))]
        numbered = [r for r in rows if r["predicate_number"]]
        if g >= max_generations:
            if numbered and node.stop_reason is None:
                node.stop_reason = SR_TRUNCATED
            for r in rows:
                r["generation"] = g + 1
                r["beyond_limit"] = 1
            continue
        for r in rows:
            r["generation"] = g + 1
            r["beyond_limit"] = 0
            ov = overrides.get((k, r["predicate_number"])) if r["predicate_number"] else None
            if ov:
                r["review"] = ov[0] if ov[0] != "replace" else f"corrected from {r['predicate_number']}"
                if ov[0] == "drop":
                    continue
                if ov[0] == "replace":
                    r["printed_number"], r["predicate_number"] = r["predicate_number"], ov[1]
                    r["predicate_base"] = ov[1]
            chain.edges.append(r)
            p = r["predicate_number"]
            if not p:
                continue
            if p not in chain.nodes:
                chain.nodes[p] = ChainNode(p, g + 1)
                q.append((p, g + 1))
            chain.nodes[p].via_roles.add(r["role"])
    return chain


def pending_nodes(con: sqlite3.Connection, seeds: list[str], max_generations: int, current_version: str,
                  skip: set | None = None) -> list[tuple[str, int, str]]:
    """Nodes reachable from seeds within max_generations that have no result for current_version.
    Returns (knumber, distance, discovered_from) sorted by distance."""
    skip = skip or set()
    overrides = review_overrides(con)
    done = {r[0] for r in con.execute("SELECT knumber FROM node_status WHERE parser_version=?", (current_version,))}
    dist: dict[str, int] = {}
    parent: dict[str, str] = {}
    q = deque()
    for s in seeds:
        dist[s] = 0
        q.append(s)
    pending = []
    while q:
        k = q.popleft()
        d = dist[k]
        if k not in done:
            if k not in skip:
                pending.append((k, d, parent.get(k)))
            continue
        if d >= max_generations:
            continue
        for (p,) in con.execute("SELECT DISTINCT predicate_number FROM edges WHERE child_knumber=? AND parser_version=? "
                                "AND predicate_number IS NOT NULL", (k, current_version)):
            ov = overrides.get((k, p))
            if ov and ov[0] == "drop":
                continue
            if ov and ov[0] == "replace":
                p = ov[1]
            if p not in dist:
                dist[p] = d + 1
                parent[p] = k
                q.append(p)
    pending.sort(key=lambda x: x[1])
    return pending
