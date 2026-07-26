"""SQLite persistence for opportunities, routes, and decision records.

Single-file database at data/db.sqlite under the project root.  Tables are
created idempotently on connect().  All public functions take a sqlite3
Connection so they compose cleanly with tests (use :func:`connect` for the
real path, or :func:`connect_memory` for unit tests).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "db.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    source_market   TEXT NOT NULL,
    target_market   TEXT NOT NULL,
    purchase_price_usd    REAL NOT NULL,
    tariff_rate           REAL NOT NULL DEFAULT 0.0,
    sell_price_usd        REAL NOT NULL,
    shipping_per_unit_usd REAL NOT NULL DEFAULT 0.0,
    platform_fee_rate     REAL NOT NULL DEFAULT 0.13,
    minutes_per_unit      REAL NOT NULL DEFAULT 30.0,
    success_rate          REAL NOT NULL DEFAULT 0.7,
    purchase_source_url   TEXT,
    sell_source_url       TEXT,
    notes                 TEXT,
    data_freshness_ts     TEXT NOT NULL,
    verified              INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS routes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    origin_city     TEXT NOT NULL,
    dest_city       TEXT NOT NULL,
    flight_cost_usd REAL NOT NULL,
    hotel_cost_usd  REAL NOT NULL,
    other_cost_usd  REAL NOT NULL DEFAULT 0.0,
    hours_available REAL NOT NULL DEFAULT 32.0,
    target_hourly_usd REAL NOT NULL DEFAULT 20.0,
    target_roi_pct  REAL NOT NULL DEFAULT 15.0,
    min_roi_pct     REAL NOT NULL DEFAULT 10.0,
    departure_date  TEXT,
    source_url      TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS route_legs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id        INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL,  -- 'flight' | 'hotel' | 'shop' | 'transit'
    label           TEXT NOT NULL,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    duration_min    REAL NOT NULL DEFAULT 0.0,
    location        TEXT,
    notes           TEXT,
    UNIQUE(route_id, seq)
);

CREATE TABLE IF NOT EXISTS decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id),
    route_id        INTEGER NOT NULL REFERENCES routes(id),
    num_units       INTEGER NOT NULL,
    decision_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_route_legs_route ON route_legs(route_id);
CREATE INDEX IF NOT EXISTS idx_decisions_opp ON decisions(opportunity_id);

CREATE TABLE IF NOT EXISTS proposed_prices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id    INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    field             TEXT NOT NULL,             -- 'purchase_price_usd' | 'sell_price_usd'
    stored_value      REAL NOT NULL,             -- what was in DB when proposal was staged
    proposed_value    REAL NOT NULL,             -- value extracted from the scrape
    detected_currency TEXT NOT NULL,             -- currency of the detected hint ('USD', 'JPY', ...)
    detected_raw      TEXT NOT NULL,             -- raw hint string (e.g., 'JPY 12800')
    source_url        TEXT NOT NULL,             -- which URL the hint came from
    drift_pct         REAL NOT NULL,             -- abs(proposed - stored) / stored * 100
    status            TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'applied' | 'rejected'
    detected_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_proposed_status ON proposed_prices(status, opportunity_id);
"""


# ---------- connection helpers ----------

def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (and migrate) the production DB at path / DB_PATH.

    Resolution order: explicit ``path`` arg → ``ARB_DB_PATH`` env var →
    ``DB_PATH`` default.  Tests set ``ARB_DB_PATH`` so subprocess CLI runs
    inside the test fixture use the tmp DB instead of the real one.
    """
    if path is None:
        env = os.environ.get("ARB_DB_PATH")
        p = Path(env) if env else DB_PATH
    else:
        p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def connect_memory() -> sqlite3.Connection:
    """In-memory DB for tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Tiny transaction context manager."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ---------- typed repositories ----------

def upsert_opportunity(conn: sqlite3.Connection, opp: dict) -> int:
    """Insert or replace an opportunity by sku.  Returns row id."""
    cols = list(opp.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    update_list = ",".join(f"{c}=excluded.{c}" for c in cols if c != "sku")
    sql = (
        f"INSERT INTO opportunities ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(sku) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, [opp[c] for c in cols])
    conn.commit()
    # Always look up the existing row's id — ``cur.lastrowid`` is unreliable
    # after ON CONFLICT DO UPDATE (Python sqlite3 returns the prior autoinc
    # counter rather than the actual row's PK).
    return _fetch_id(conn, "opportunities", "sku", opp["sku"])


def upsert_route(conn: sqlite3.Connection, route: dict) -> int:
    cols = list(route.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    update_list = ",".join(f"{c}=excluded.{c}" for c in cols if c != "name")
    sql = (
        f"INSERT INTO routes ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(name) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, [route[c] for c in cols])
    conn.commit()
    return _fetch_id(conn, "routes", "name", route["name"])


def add_route_legs(conn: sqlite3.Connection, route_id: int, legs: Iterable[dict]) -> None:
    rows = [dict(l, route_id=route_id) for l in legs]
    for r in rows:
        cols = list(r.keys())
        placeholders = ",".join(["?"] * len(cols))
        col_list = ",".join(cols)
        conn.execute(
            f"INSERT OR REPLACE INTO route_legs ({col_list}) VALUES ({placeholders})",
            [r[c] for c in cols],
        )
    conn.commit()


def _fetch_id(conn, table, key_col, key_val) -> int:
    row = conn.execute(f"SELECT id FROM {table} WHERE {key_col}=?", (key_val,)).fetchone()
    return row["id"]


def list_opportunities(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM opportunities ORDER BY id"))


def list_routes(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM routes ORDER BY id"))


def list_route_legs(conn: sqlite3.Connection, route_id: int) -> list[sqlite3.Row]:
    return list(conn.execute(
        "SELECT * FROM route_legs WHERE route_id=? ORDER BY seq", (route_id,)
    ))


def get_opportunity(conn: sqlite3.Connection, sku: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM opportunities WHERE sku=?", (sku,)).fetchone()


def get_route(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM routes WHERE name=?", (name,)).fetchone()


def record_decision(conn: sqlite3.Connection, opportunity_id: int, route_id: int,
                    num_units: int, decision_obj) -> int:
    """Persist a Decision row (decision_obj must be JSON-serializable)."""
    payload = json.dumps(decision_obj.as_dict() if hasattr(decision_obj, "as_dict")
                          else decision_obj, ensure_ascii=False)
    cur = conn.execute(
        "INSERT INTO decisions (opportunity_id, route_id, num_units, decision_json) "
        "VALUES (?, ?, ?, ?)",
        (opportunity_id, route_id, num_units, payload),
    )
    conn.commit()
    return cur.lastrowid


# ---------- proposed_prices (Round 4) ----------

def add_proposed_price(conn: sqlite3.Connection, opportunity_id: int,
                       field: str, *, stored_value: float, proposed_value: float,
                       detected_currency: str, detected_raw: str, source_url: str,
                       drift_pct: float, status: str = "pending") -> int:
    """Stage one proposed-price row.  Returns the new row id."""
    if field not in ("purchase_price_usd", "sell_price_usd"):
        raise ValueError(f"unsupported field: {field!r}")
    cur = conn.execute(
        "INSERT INTO proposed_prices "
        "(opportunity_id, field, stored_value, proposed_value, detected_currency, "
        " detected_raw, source_url, drift_pct, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (opportunity_id, field, stored_value, proposed_value, detected_currency,
         detected_raw, source_url, drift_pct, status),
    )
    conn.commit()
    return cur.lastrowid


def list_proposed_prices(conn: sqlite3.Connection, *, sku: Optional[str] = None,
                         status: Optional[str] = None) -> list[sqlite3.Row]:
    """List proposal rows, joined with sku for convenience.  Filterable."""
    sql = (
        "SELECT p.*, o.sku AS sku FROM proposed_prices p "
        "JOIN opportunities o ON o.id = p.opportunity_id "
    )
    clauses = []
    params: list = []
    if sku is not None:
        clauses.append("o.sku = ?")
        params.append(sku)
    if status is not None:
        clauses.append("p.status = ?")
        params.append(status)
    if clauses:
        sql += "WHERE " + " AND ".join(clauses) + " "
    sql += "ORDER BY p.detected_at DESC, p.id DESC"
    return list(conn.execute(sql, params))


def get_proposed_price(conn: sqlite3.Connection, proposal_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT p.*, o.sku AS sku FROM proposed_prices p "
        "JOIN opportunities o ON o.id = p.opportunity_id WHERE p.id = ?",
        (proposal_id,),
    ).fetchone()


def resolve_proposed_price(conn: sqlite3.Connection, proposal_id: int,
                           action: str, *, today: Optional[str] = None) -> dict:
    """Apply or reject a proposal.  Returns the resulting state.

    ``action='apply'`` overwrites the opportunity's stored price and marks the
    proposal as 'applied'.  ``action='reject'`` just marks it 'rejected'.
    Returns ``{"applied": bool, "field": str|None, "new_value": float|None,
    "proposal_status": str, "message": str}``.
    """
    if action not in ("apply", "reject"):
        raise ValueError(f"action must be 'apply' or 'reject', got {action!r}")
    row = conn.execute(
        "SELECT p.*, o.sku AS sku FROM proposed_prices p "
        "JOIN opportunities o ON o.id = p.opportunity_id WHERE p.id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        return {"applied": False, "proposal_status": None,
                "field": None, "new_value": None,
                "message": f"proposal {proposal_id} not found"}
    if row["status"] != "pending":
        return {"applied": False, "proposal_status": row["status"],
                "field": row["field"], "new_value": None,
                "message": f"proposal already {row['status']}"}
    today_str = today or _dt.date.today().isoformat()
    if action == "apply":
        conn.execute(
            f"UPDATE opportunities SET {row['field']} = ?, data_freshness_ts = ? WHERE id = ?",
            (row["proposed_value"], today_str, row["opportunity_id"]),
        )
        new_status = "applied"
    else:
        new_status = "rejected"
    conn.execute(
        "UPDATE proposed_prices SET status = ?, resolved_at = ? WHERE id = ?",
        (new_status, today_str, proposal_id),
    )
    conn.commit()
    if action == "apply":
        return {"applied": True, "proposal_status": "applied",
                "field": row["field"], "new_value": row["proposed_value"],
                "message": f"已将 {row['sku']} 的 {row['field']} 覆盖为 {row['proposed_value']:.2f} (来源 {row['source_url']})"}
    return {"applied": False, "proposal_status": "rejected",
            "field": row["field"], "new_value": None,
            "message": f"已拒绝提案 {proposal_id} ({row['sku']} · {row['field']})"}
