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
    home_price_cny        REAL,
    unit_volume_ml        REAL,
    max_units_per_trip    INTEGER NOT NULL DEFAULT 50,
    purchase_channels     TEXT NOT NULL DEFAULT '[]',
    sell_channels         TEXT NOT NULL DEFAULT '[]',
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
    cn_to_usd_fx    REAL NOT NULL DEFAULT 0.14,
    departure_date  TEXT,
    source_url      TEXT,
    notes           TEXT,
    region          TEXT NOT NULL DEFAULT 'cn-jp',                -- Round 23: 'cn-jp' | 'us-domestic' | 'cn-jp-us'
    transfer_cost_cny REAL NOT NULL DEFAULT 0.0,                 -- 北京 0;上海 +¥600;天津 +¥200 (高铁中转)
    flight_source_url  TEXT,                                     -- 出处机票比价/订票链接
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
    depart_at       TEXT,           -- ISO8601 local time ('YYYY-MM-DDTHH:MM'); nullable for non-timed legs
    arrive_at       TEXT,           -- ISO8601 local time; = depart_at + duration_min (server-computed when both set)
    stops           TEXT NOT NULL DEFAULT '[]',  -- Round 20: JSON list of Day-by-Day shopping stops (only meaningful for kind='shop')
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

-- Round 21: evidence audit trail. Each row is one observed price point
-- (税抜 / 闲鱼挂单 / 京东促销 / etc.) with the URL where it was seen.
-- Channels reference these via ``evidence_ids`` JSON lists stored inside
-- ``opportunities.purchase_channels`` / ``sell_channels`` so the SPA can
-- render an evidence card per channel.
CREATE TABLE IF NOT EXISTS evidence_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL,
    side            TEXT NOT NULL,             -- 'buy' | 'sell'
    channel_name    TEXT NOT NULL,             -- 'Fa-So-La 银座免税' / '闲鱼' / '京东国际' / ...
    channel_url     TEXT,
    price_cny       REAL NOT NULL,
    price_type      TEXT NOT NULL,             -- 'tax-free' | 'retail' | '成交' | '挂单' | '标价' | 'self-use-baseline'
    source_url      TEXT,                      -- URL where this evidence was observed (nullable for self-use baselines)
    observed_at     TEXT NOT NULL,             -- 'YYYY-MM' month of observation
    notes           TEXT,
    verified        INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(sku, side, channel_name, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_evidence_sku_side ON evidence_log(sku, side);

-- Round 24: live competitor price snapshots — daily cron writes here, SPA
-- renders price-diff badges and T-7/T-30 trend charts.  FK to opportunities
-- so deleting an opp also drops its snapshots.
CREATE TABLE IF NOT EXISTS competitor_prices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    sku             TEXT NOT NULL,                  -- denormalized for cheap joins
    source          TEXT NOT NULL,                  -- 'amazon_jp' | 'rakuten' | 'yahoo' | 'mercari' | 'manual'
    price_jpy       REAL,                           -- source-native price (JPY)
    price_cny       REAL,                           -- FX-converted at fetch time
    fx_rate_at_fetch REAL,                          -- JPY per CNY at fetch (e.g. 20.83 means 1 CNY=20.83 JPY)
    fx_source       TEXT,                           -- 'fawazahmed0' | 'manual'
    url             TEXT,                           -- page URL where price was observed
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notes           TEXT,
    UNIQUE(opportunity_id, source, fetched_at)     -- one row per source per day
);

CREATE INDEX IF NOT EXISTS idx_competitor_prices_sku ON competitor_prices(sku, fetched_at);
CREATE INDEX IF NOT EXISTS idx_competitor_prices_source ON competitor_prices(source, fetched_at);

-- Round 24: per-SKU price-diff alert config.  When a fresh competitor_prices
-- row exceeds ±threshold_pct vs the SKU's stored purchase_price_usd (in CNY),
-- promote an alert row.  0% = disabled.
CREATE TABLE IF NOT EXISTS price_alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL,
    source          TEXT NOT NULL,                  -- 'amazon_jp' | 'rakuten' | 'any'
    threshold_pct   REAL NOT NULL,                  -- abs(price_diff_pct) above this → alert
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_triggered_at TEXT,
    notes           TEXT,
    UNIQUE(sku, source)
);

CREATE INDEX IF NOT EXISTS idx_price_alerts_sku ON price_alerts(sku, enabled);

-- Round 24: ¥5,000 / ¥1,000 入境额度累计消费。每次「带一件」记一行,视图按
-- 7/15/30 日窗口聚合剩额。  二次入境 ≤ 15 日则限额 ¥1,000(自动判定)。
CREATE TABLE IF NOT EXISTS china_quota_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date      TEXT NOT NULL,                  -- 'YYYY-MM-DD' 入境日
    sku             TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price_cny  REAL NOT NULL,
    subtotal_cny    REAL NOT NULL,                  -- qty * unit_price
    declared_at     TEXT NOT NULL DEFAULT (datetime('now')),
    trip_label      TEXT,                            -- '2026-09 PEK-NRT' 等
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_china_quota_date ON china_quota_usage(entry_date);

-- Round 24: 退货记录 + 月度毛利归算的源数据。
CREATE TABLE IF NOT EXISTS returns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL,
    sold_at         TEXT NOT NULL,                  -- 'YYYY-MM-DD' 卖出日
    sold_price_cny  REAL NOT NULL,
    sold_channel    TEXT,                           -- '闲鱼' / '朋友圈' / '小红书' / ...
    returned_at     TEXT,                           -- NULL 表示未退货
    return_reason   TEXT,                            -- '客户退货' / '平台下架' / ...
    refund_cny      REAL,                           -- 实退金额
    restocking_cost_cny REAL DEFAULT 0.0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_returns_sku ON returns(sku);
CREATE INDEX IF NOT EXISTS idx_returns_returned ON returns(returned_at);

-- Round 25: 库存表(哥们仓 + 在途 + 已上架 + 我家)
CREATE TABLE IF NOT EXISTS inventory (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL,
    quantity        INTEGER NOT NULL DEFAULT 1,
    location        TEXT NOT NULL,                  -- '哥们仓(JP)' / '在途' / '我家' / '已上架-闲鱼' / '已上架-eBay'
    acquired_at     TEXT NOT NULL,                  -- 'YYYY-MM-DD' 入手日
    acquired_cny    REAL NOT NULL,                  -- 单件成本 (¥)
    total_cny       REAL NOT NULL,                  -- qty * acquired
    listing_url     TEXT,                            -- 上架的 listing URL
    listed_at       TEXT,                            -- 上架日
    sold_at         TEXT,                            -- 售出日 (NULL = 未售)
    sold_price_cny  REAL,
    sold_channel    TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_inventory_sku ON inventory(sku);
CREATE INDEX IF NOT EXISTS idx_inventory_location ON inventory(location);
CREATE INDEX IF NOT EXISTS idx_inventory_sold ON inventory(sold_at);

-- Round 25: 订单状态机 (每 SKU 的下单-到货-上架-售出 全链路追踪)
CREATE TABLE IF NOT EXISTS order_status (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT NOT NULL UNIQUE,
    status          TEXT NOT NULL,                  -- '待下单'/'已下单'/'在途'/'已到货'/'已上架'/'已售出'/'已退货'
    ordered_at      TEXT,                            -- 下单日
    order_url       TEXT,                            -- 订单 URL (buyee / Amazon / 1688 / etc.)
    tracking_url    TEXT,                            -- 物流跟踪 URL
    arrived_at      TEXT,                            -- 到货日
    sold_at         TEXT,                            -- 售出日
    sold_price_cny  REAL,
    sold_channel    TEXT,
    notes           TEXT,
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);


-- T9: trips (行程规划 - 大阪/东京/京都/...) + ¥5,000 跨多趟额度滚动
CREATE TABLE IF NOT EXISTS trips (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    destination     TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    flight_out_cny  REAL DEFAULT 0,
    flight_back_cny REAL DEFAULT 0,
    hotel_total_cny REAL DEFAULT 0,
    notes           TEXT,
    status          TEXT NOT NULL DEFAULT '规划中',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trip_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trip_id         INTEGER NOT NULL,
    day_index       INTEGER NOT NULL DEFAULT 1,
    channel         TEXT NOT NULL,
    sku_slug        TEXT NOT NULL,
    sku_label       TEXT NOT NULL,
    est_cny         REAL NOT NULL,
    location_label  TEXT,
    ordered         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (trip_id) REFERENCES trips(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_trip_items_trip ON trip_items(trip_id);

CREATE TABLE IF NOT EXISTS quota_windows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date      TEXT NOT NULL UNIQUE,
    entry_cny       REAL NOT NULL,
    trip_id         INTEGER,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_order_status_status ON order_status(status);

CREATE TABLE IF NOT EXISTS execution_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    leg TEXT NOT NULL DEFAULT 'D',            -- 'D' 电商带过去 | 'E' 哥们仓
    qty INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'created',
    sell_platform TEXT NOT NULL DEFAULT 'dryrun',
    buy_platform TEXT NOT NULL DEFAULT 'dryrun',
    sell_ext_id TEXT,                          -- 销售平台上架后的外部 ID
    buy_ext_id TEXT,                           -- 采购平台下单后的外部 ID
    sell_price_cny REAL NOT NULL DEFAULT 0,    -- 卖给买家的价格
    buy_price_cny REAL,                        -- 采购价(比价后写入)
    ship_cost_cny REAL NOT NULL DEFAULT 0,     -- 运费预估
    buyer_paid_cny REAL NOT NULL DEFAULT 0,    -- 买家已付(预收确认)
    buy_source_url TEXT,                       -- 采购货源链接(比价选中)
    tracking TEXT,                             -- 发货物流单号
    error TEXT,                                -- 最近一次异常信息
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sku_feedback (
    sku TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'bad',        -- 'ok' 能卖 | 'bad' 不OK(从推荐排除)
    reason TEXT NOT NULL DEFAULT '',           -- 原因: 预设标签或自定义文字
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

"""


# ---------- idempotent column migration (Round 13) ----------

# Schema additions after the initial DDL. Each value is the column DDL
# fragment that follows ``ALTER TABLE <table> ADD COLUMN <name>``. Must be
# a constant ``DEFAULT`` so SQLite permits ``NOT NULL`` for new columns.
# To add a new column: append it here, and add the same line to SCHEMA
# above for fresh installs.  Both must agree.
_EXPECTED_COLUMNS: dict[str, dict[str, str]] = {
    "opportunities": {
        "home_price_cny": "REAL",                              # self-use baseline (天猫/中免/日上)
        "unit_volume_ml": "REAL",                              # physical size hint, display only
        "max_units_per_trip": "INTEGER NOT NULL DEFAULT 50",   # per-SKU carry cap
        "purchase_channels": "TEXT NOT NULL DEFAULT '[]'",     # Round 19: JSON list of buy-side channels
        "sell_channels": "TEXT NOT NULL DEFAULT '[]'",         # Round 19: JSON list of sell-side channels
    },
    "routes": {
        "cn_to_usd_fx": "REAL NOT NULL DEFAULT 0.14",          # CNY→USD for self-use pricing
        "region": "TEXT NOT NULL DEFAULT 'cn-jp'",              # Round 23: cn-jp | us-domestic | cn-jp-us
        "transfer_cost_cny": "REAL NOT NULL DEFAULT 0.0",       # 高铁中转(北京 0;上海 +¥600;天津 +¥200)
        "flight_source_url": "TEXT",                            # 机票出处链接
    },
    "route_legs": {
        # Round 17: per-leg timestamps for itinerary rendering.
        # Both nullable TEXT (ISO8601). arrive_at is server-derived from
        # depart_at + duration_min when both are populated.
        "depart_at": "TEXT",
        "arrive_at": "TEXT",
        # Round 20: Day-by-Day shopping stops (JSON list). Currently only
        # meaningful on shop legs but kept generic so any leg can carry stops.
        "stops": "TEXT NOT NULL DEFAULT '[]'",
    },
}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names currently defined on ``table``."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_columns(conn: sqlite3.Connection, table: str, expected: dict[str, str]) -> None:
    """Idempotently add any missing columns from ``expected`` to ``table``.

    Each value in ``expected`` is the DDL fragment that follows the column
    name, e.g. ``"REAL NOT NULL DEFAULT 0.14"``.  Safe to call on every
    connect() — no-op when the column already exists.
    """
    existing = _table_columns(conn, table)
    added = False
    for col, ddl in expected.items():
        if col in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        added = True
    if added:
        conn.commit()


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
    for table, expected in _EXPECTED_COLUMNS.items():
        _ensure_columns(conn, table, expected)
    conn.commit()
    return conn


def connect_memory() -> sqlite3.Connection:
    """In-memory DB for tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for table, expected in _EXPECTED_COLUMNS.items():
        _ensure_columns(conn, table, expected)
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
    # Round 19: channel lists must be JSON-encoded before going to SQLite.
    row = dict(opp)
    for key in ("purchase_channels", "sell_channels"):
        if key in row and isinstance(row[key], (list, tuple)):
            row[key] = json.dumps(list(row[key]), ensure_ascii=False)
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    update_list = ",".join(f"{c}=excluded.{c}" for c in cols if c != "sku")
    sql = (
        f"INSERT INTO opportunities ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(sku) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, [row[c] for c in cols])
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
    # Round 20: JSON-encode structured fields (stops) so callers can pass
    # native Python lists instead of pre-serializing. Mirrors the channel
    # encoding pattern in upsert_opportunity().
    rows = []
    for l in legs:
        row = dict(l, route_id=route_id)
        for key in ("stops",):
            if key in row and not isinstance(row[key], str):
                row[key] = json.dumps(row[key], ensure_ascii=False)
        rows.append(row)
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


def upsert_evidence(conn: sqlite3.Connection, evidence: dict) -> int:
    """Insert or replace evidence_log row by (sku, side, channel_name, observed_at).
    Returns row id. Idempotent so re-running seed keeps IDs stable for channels
    that reference evidence_ids."""
    cols = list(evidence.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    update_list = ",".join(
        f"{c}=excluded.{c}" for c in cols
        if c not in ("sku", "side", "channel_name", "observed_at")
    )
    sql = (
        f"INSERT INTO evidence_log ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(sku, side, channel_name, observed_at) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, [evidence[c] for c in cols])
    conn.commit()
    row = conn.execute(
        "SELECT id FROM evidence_log WHERE sku=? AND side=? AND channel_name=? AND observed_at=?",
        (evidence["sku"], evidence["side"], evidence["channel_name"], evidence["observed_at"]),
    ).fetchone()
    return row["id"]


def list_evidence(conn: sqlite3.Connection, *, sku: Optional[str] = None,
                  side: Optional[str] = None) -> list[sqlite3.Row]:
    """List evidence_log rows with optional sku / side filter."""
    clauses = []
    params: list = []
    if sku is not None:
        clauses.append("sku = ?")
        params.append(sku)
    if side is not None:
        clauses.append("side = ?")
        params.append(side)
    sql = "SELECT * FROM evidence_log"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id"
    return list(conn.execute(sql, params))


def get_evidence(conn: sqlite3.Connection, evidence_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM evidence_log WHERE id=?", (evidence_id,)
    ).fetchone()


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


# ---------- route leg timing (Round 17) ----------

def _parse_iso_min(s: str) -> int:
    """Parse an ISO local datetime 'YYYY-MM-DDTHH:MM[:SS]' into total minutes
    since 1970-01-01 00:00 LOCAL (naive — purely for arithmetic, never
    compared to wall-clock UTC).
    """
    from datetime import datetime
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            # Use (dt - epoch).total_seconds() via epoch-as-naive: pick 1970-01-01 as anchor.
            epoch = datetime(1970, 1, 1)
            return int((dt - epoch).total_seconds() // 60)
        except ValueError:
            continue
    raise ValueError(f"unparseable ISO time: {s!r}")


def _fmt_iso_min(mins: int) -> str:
    """Format minutes-since-naive-epoch back to 'YYYY-MM-DDTHH:MM'."""
    from datetime import datetime, timedelta
    dt = datetime(1970, 1, 1) + timedelta(minutes=mins)
    return dt.strftime("%Y-%m-%dT%H:%M")


def backfill_route_leg_times(conn, route_id: int) -> int:
    """Stamp depart_at / arrive_at on every leg of ``route_id`` by walking
    forward from ``routes.departure_date`` + 09:00 (assumed local) and
    accumulating ``duration_min`` per leg.  Hotel/shop/transit legs with
    duration_min == 0 leave depart_at NULL (only arrive_at is set as a
    checkpoint marker so the next leg's wall-clock keeps advancing).

    Idempotent: re-running overwrites existing timestamps.  Returns the
    number of legs touched.
    """
    row = conn.execute("SELECT name, departure_date FROM routes WHERE id=?",
                       (route_id,)).fetchone()
    if row is None:
        raise ValueError(f"route id {route_id} not found")
    depart_date = row["departure_date"]
    if not depart_date:
        raise ValueError(f"route {row['name']!r} has no departure_date set")
    legs = list_route_legs(conn, route_id)
    if not legs:
        return 0
    cursor_min = _parse_iso_min(f"{depart_date}T09:00")
    touched = 0
    for leg in legs:
        dur = float(leg["duration_min"])
        if dur <= 0:
            conn.execute(
                "UPDATE route_legs SET depart_at=NULL, arrive_at=? WHERE id=?",
                (_fmt_iso_min(cursor_min), leg["id"]),
            )
            touched += 1
            continue
        depart = _fmt_iso_min(cursor_min)
        arrive_min = cursor_min + int(dur)
        arrive = _fmt_iso_min(arrive_min)
        conn.execute(
            "UPDATE route_legs SET depart_at=?, arrive_at=? WHERE id=?",
            (depart, arrive, leg["id"]),
        )
        cursor_min = arrive_min
        touched += 1
    conn.commit()
    return touched


# ---------- Round 24: competitor_prices (live cross-source snapshots) ----------

def upsert_competitor_price(conn: sqlite3.Connection, row: dict) -> int:
    """Insert or replace one row keyed by (opportunity_id, source, fetched_at)."""
    if "opportunity_id" not in row and "sku" in row:
        opp = get_opportunity(conn, row["sku"])
        if opp is None:
            raise ValueError(f"unknown sku: {row['sku']!r}")
        row = dict(row, opportunity_id=opp["id"])
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    update_list = ",".join(f"{c}=excluded.{c}" for c in cols
                           if c != "id")
    sql = (
        f"INSERT INTO competitor_prices ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(opportunity_id, source, fetched_at) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, [row[c] for c in cols])
    conn.commit()
    return conn.execute(
        "SELECT id FROM competitor_prices WHERE opportunity_id=? AND source=? AND fetched_at=?",
        (row["opportunity_id"], row["source"], row["fetched_at"]),
    ).fetchone()["id"]


def list_competitor_prices(conn: sqlite3.Connection, *, sku: Optional[str] = None,
                           source: Optional[str] = None, days: Optional[int] = None
                           ) -> list[sqlite3.Row]:
    """List snapshots, newest first.  ``days`` limits to last N days."""
    clauses: list[str] = []
    params: list = []
    if sku is not None:
        clauses.append("sku = ?")
        params.append(sku)
    if source is not None:
        clauses.append("source = ?")
        params.append(source)
    if days is not None:
        clauses.append(f"fetched_at >= datetime('now', '-{int(days)} days')")
    sql = "SELECT * FROM competitor_prices"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY fetched_at DESC, id DESC"
    return list(conn.execute(sql, params))


def latest_competitor_price(conn: sqlite3.Connection, sku: str,
                             source: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM competitor_prices WHERE sku=? AND source=? "
        "ORDER BY fetched_at DESC, id DESC LIMIT 1",
        (sku, source),
    ).fetchone()


# ---------- Round 24: price_alerts (per-SKU threshold config) ----------

def upsert_price_alert(conn: sqlite3.Connection, row: dict) -> int:
    """Insert or replace alert config by (sku, source)."""
    cols = list(row.keys())
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    update_list = ",".join(
        f"{c}=excluded.{c}" for c in cols if c not in ("sku", "source")
    )
    sql = (
        f"INSERT INTO price_alerts ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT(sku, source) DO UPDATE SET {update_list}"
    )
    conn.execute(sql, [row[c] for c in cols])
    conn.commit()
    return conn.execute(
        "SELECT id FROM price_alerts WHERE sku=? AND source=?",
        (row["sku"], row["source"]),
    ).fetchone()["id"]


def list_price_alerts(conn: sqlite3.Connection, *, sku: Optional[str] = None,
                      enabled_only: bool = False) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list = []
    if sku is not None:
        clauses.append("sku = ?")
        params.append(sku)
    if enabled_only:
        clauses.append("enabled = 1")
    sql = "SELECT * FROM price_alerts"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sku, source"
    return list(conn.execute(sql, params))


def mark_alert_triggered(conn: sqlite3.Connection, sku: str, source: str) -> None:
    conn.execute(
        "UPDATE price_alerts SET last_triggered_at = datetime('now') "
        "WHERE sku=? AND source=?",
        (sku, source),
    )
    conn.commit()


# ---------- Round 24: china_quota_usage (¥5,000 / ¥1,000 入境额度) ----------

def record_quota_entry(conn: sqlite3.Connection, row: dict) -> int:
    """Add one entry to the quota ledger.  subtotal_cny auto-calculated if absent."""
    row = dict(row)
    if "subtotal_cny" not in row:
        row["subtotal_cny"] = round(float(row["quantity"]) * float(row["unit_price_cny"]), 2)
    cur = conn.execute(
        "INSERT INTO china_quota_usage "
        "(entry_date, sku, quantity, unit_price_cny, subtotal_cny, trip_label, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (row["entry_date"], row["sku"], row["quantity"], row["unit_price_cny"],
         row["subtotal_cny"], row.get("trip_label"), row.get("notes")),
    )
    conn.commit()
    return cur.lastrowid


def list_quota_entries(conn: sqlite3.Connection, *, since: Optional[str] = None,
                       sku: Optional[str] = None) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list = []
    if since is not None:
        clauses.append("entry_date >= ?")
        params.append(since)
    if sku is not None:
        clauses.append("sku = ?")
        params.append(sku)
    sql = "SELECT * FROM china_quota_usage"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY entry_date DESC, id DESC"
    return list(conn.execute(sql, params))



# ---------- Round 24: returns (退货 + 月度毛利归算) ----------

def record_return(conn: sqlite3.Connection, row: dict) -> int:
    cur = conn.execute(
        "INSERT INTO returns (sku, sold_at, sold_price_cny, sold_channel, "
        "returned_at, return_reason, refund_cny, restocking_cost_cny) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (row["sku"], row["sold_at"], row["sold_price_cny"], row.get("sold_channel"),
         row.get("returned_at"), row.get("return_reason"), row.get("refund_cny"),
         row.get("restocking_cost_cny", 0.0)),
    )
    conn.commit()
    return cur.lastrowid


def list_returns(conn: sqlite3.Connection, *, sku: Optional[str] = None,
                 returned_only: bool = False) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list = []
    if sku is not None:
        clauses.append("sku = ?")
        params.append(sku)
    if returned_only:
        clauses.append("returned_at IS NOT NULL")
    sql = "SELECT * FROM returns"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY sold_at DESC, id DESC"
    return list(conn.execute(sql, params))


def monthly_margin(conn: sqlite3.Connection, month: str) -> dict:
    """Monthly margin rollup: sales - returns - restocking - tax estimate.

    ``month`` is 'YYYY-MM'.  USD-CNY rate 0.14 (≈7.14).  Returns totals + per-SKU.
    """
    rows = conn.execute(
        "SELECT r.sku, r.sold_price_cny, r.refund_cny, r.restocking_cost_cny, "
        "r.returned_at, r.sold_channel, o.purchase_price_usd, o.tariff_rate "
        "FROM returns r LEFT JOIN opportunities o ON o.sku = r.sku "
        "WHERE substr(r.sold_at, 1, 7) = ?",
        (month,),
    ).fetchall()
    by_sku: dict[str, dict] = {}
    for r in rows:
        s = by_sku.setdefault(r["sku"], {
            "sku": r["sku"],
            "units_sold": 0, "gross_revenue_cny": 0.0,
            "refund_cny": 0.0, "restocking_cny": 0.0,
            "est_purchase_cny": 0.0, "est_tax_cny": 0.0,
            "return_count": 0, "net_cny": 0.0,
        })
        s["units_sold"] += 1
        s["gross_revenue_cny"] += float(r["sold_price_cny"] or 0)
        if r["returned_at"]:
            s["return_count"] += 1
            s["refund_cny"] += float(r["refund_cny"] or 0)
        s["restocking_cny"] += float(r["restocking_cost_cny"] or 0)
        if r["purchase_price_usd"] is not None:
            purch = float(r["purchase_price_usd"]) * 7.14
            s["est_purchase_cny"] += purch
            s["est_tax_cny"] += purch * float(r["tariff_rate"] or 0)
    for s in by_sku.values():
        s["net_cny"] = round(s["gross_revenue_cny"] - s["refund_cny"] - s["restocking_cny"]
                             - s["est_purchase_cny"] - s["est_tax_cny"], 2)
    return {
        "month": month,
        "totals": {
            "units_sold": sum(s["units_sold"] for s in by_sku.values()),
            "gross_revenue_cny": round(sum(s["gross_revenue_cny"] for s in by_sku.values()), 2),
            "refund_cny": round(sum(s["refund_cny"] for s in by_sku.values()), 2),
            "restocking_cny": round(sum(s["restocking_cny"] for s in by_sku.values()), 2),
            "est_purchase_cny": round(sum(s["est_purchase_cny"] for s in by_sku.values()), 2),
            "est_tax_cny": round(sum(s["est_tax_cny"] for s in by_sku.values()), 2),
            "return_count": sum(s["return_count"] for s in by_sku.values()),
            "net_cny": round(sum(s["net_cny"] for s in by_sku.values()), 2),
        },
        "by_sku": list(by_sku.values()),
    }



# ---------- Round 25: inventory CRUD ----------

def add_inventory(conn: sqlite3.Connection, row: dict) -> int:
    """Add one inventory item. total_cny auto-calculated if absent."""
    row = dict(row)
    if "total_cny" not in row:
        row["total_cny"] = round(float(row["quantity"]) * float(row["acquired_cny"]), 2)
    cur = conn.execute(
        "INSERT INTO inventory "
        "(sku, quantity, location, acquired_at, acquired_cny, total_cny, "
        " listing_url, listed_at, sold_at, sold_price_cny, sold_channel, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["sku"], row["quantity"], row["location"], row["acquired_at"],
         row["acquired_cny"], row["total_cny"],
         row.get("listing_url"), row.get("listed_at"),
         row.get("sold_at"), row.get("sold_price_cny"), row.get("sold_channel"),
         row.get("notes")),
    )
    conn.commit()
    return cur.lastrowid


def list_inventory(conn: sqlite3.Connection, *, location: Optional[str] = None,
                   include_sold: bool = False, sku: Optional[str] = None) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: list = []
    if location is not None:
        clauses.append("location = ?")
        params.append(location)
    if not include_sold:
        clauses.append("sold_at IS NULL")
    if sku is not None:
        clauses.append("sku = ?")
        params.append(sku)
    sql = "SELECT * FROM inventory"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY acquired_at DESC, id DESC"
    return list(conn.execute(sql, params))


def update_inventory(conn: sqlite3.Connection, item_id: int, fields: dict) -> int:
    """Update mutable fields on an inventory row. Returns rowcount."""
    if not fields:
        return 0
    fields = dict(fields)
    fields["updated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    params = list(fields.values()) + [item_id]
    cur = conn.execute(f"UPDATE inventory SET {cols} WHERE id = ?", params)
    conn.commit()
    return cur.rowcount


def delete_inventory(conn: sqlite3.Connection, item_id: int) -> int:
    cur = conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit()
    return cur.rowcount


def inventory_summary(conn: sqlite3.Connection) -> dict:
    """Total value & count by location (excluding sold items)."""
    rows = conn.execute(
        "SELECT location, SUM(quantity) AS qty, SUM(total_cny) AS value_cny "
        "FROM inventory WHERE sold_at IS NULL GROUP BY location"
    ).fetchall()
    by_location = {r["location"]: {"qty": r["qty"] or 0, "value_cny": r["value_cny"] or 0.0} for r in rows}
    total_qty = sum(b["qty"] for b in by_location.values())
    total_cny = sum(b["value_cny"] for b in by_location.values())
    return {
        "by_location": by_location,
        "total_qty": total_qty,
        "total_cny": round(total_cny, 2),
    }


# ---------- Round 25: order_status CRUD ----------

VALID_STATUSES = ('待下单', '已下单', '在途', '已到货', '已上架', '已售出', '已退货')


def set_order_status(conn: sqlite3.Connection, sku: str, status: str, **fields) -> int:
    """Upsert order status. Returns row id.

    Accepts both singular ('note') and plural ('notes') for the notes column,
    and 'tracking' as alias for 'tracking_url' — keeps API forgiving.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"status must be one of {VALID_STATUSES}, got {status!r}")
    # Normalize aliases
    if "note" in fields and "notes" not in fields:
        fields["notes"] = fields.pop("note")
    if "tracking" in fields and "tracking_url" not in fields:
        fields["tracking_url"] = fields.pop("tracking")

    update_fields = dict(fields)
    update_fields["status"] = status
    update_fields["updated_at"] = _dt.datetime.now().isoformat(timespec="seconds")
    cols = ", ".join(f"{k} = ?" for k in update_fields.keys())
    params = list(update_fields.values())
    cur = conn.execute(
        f"INSERT INTO order_status (sku, status, updated_at) VALUES (?, ?, ?) "
        f"ON CONFLICT(sku) DO UPDATE SET {cols}",
        [sku, status, update_fields["updated_at"]] + params,
    )
    conn.commit()
    return cur.lastrowid


def get_order_status(conn: sqlite3.Connection, sku: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM order_status WHERE sku = ?", (sku,))
    return cur.fetchone()


def list_pending_orders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """All orders not yet sold or returned."""
    return list(conn.execute(
        "SELECT * FROM order_status WHERE status NOT IN ('已售出', '已退货') "
        "ORDER BY updated_at DESC"
    ))


def list_all_status(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM order_status ORDER BY updated_at DESC"))


# ---------- T9: trips + trip_items + quota_windows CRUD ----------

def create_trip(conn, destination, start_date, end_date,
                flight_out_cny=0, flight_back_cny=0, hotel_total_cny=0, notes=''):
    cur = conn.execute(
        "INSERT INTO trips (destination, start_date, end_date, flight_out_cny, flight_back_cny, hotel_total_cny, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (destination, start_date, end_date, flight_out_cny, flight_back_cny, hotel_total_cny, notes)
    )
    conn.commit()
    return cur.lastrowid


def list_trips(conn, status=None):
    if status:
        return conn.execute("SELECT * FROM trips WHERE status = ? ORDER BY start_date DESC", (status,)).fetchall()
    return conn.execute("SELECT * FROM trips ORDER BY start_date DESC").fetchall()


def get_trip(conn, trip_id):
    return conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()


def update_trip(conn, trip_id, **fields):
    if not fields: return 0
    fields['updated_at'] = _dt.datetime.now().isoformat(timespec="seconds")
    cols = ", ".join(f"{k} = ?" for k in fields.keys())
    params = list(fields.values()) + [trip_id]
    cur = conn.execute(f"UPDATE trips SET {cols} WHERE id = ?", params)
    conn.commit()
    return cur.rowcount


def delete_trip(conn, trip_id):
    cur = conn.execute("DELETE FROM trips WHERE id = ?", (trip_id,))
    conn.commit()
    return cur.rowcount


def add_trip_item(conn, trip_id, day_index, channel, sku_slug, sku_label, est_cny, location_label=None):
    cur = conn.execute(
        "INSERT INTO trip_items (trip_id, day_index, channel, sku_slug, sku_label, est_cny, location_label) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trip_id, day_index, channel, sku_slug, sku_label, est_cny, location_label)
    )
    conn.commit()
    return cur.lastrowid


def list_trip_items(conn, trip_id, channel=None):
    if channel:
        return conn.execute(
            "SELECT * FROM trip_items WHERE trip_id = ? AND channel = ? ORDER BY day_index, id",
            (trip_id, channel)
        ).fetchall()
    return conn.execute(
        "SELECT * FROM trip_items WHERE trip_id = ? ORDER BY day_index, id",
        (trip_id,)
    ).fetchall()


def delete_trip_item(conn, item_id):
    cur = conn.execute("DELETE FROM trip_items WHERE id = ?", (item_id,))
    conn.commit()
    return cur.rowcount


def quota_summary(conn, days=15, as_of=None):
    """¥5,000 入境额度 — 15 天滚动窗口 + 二次入境 ¥1,000 (Round 24 F3).

    Logic:
    - 每次入境记一条 china_quota_usage.entry(subtotal_cny = 货值)
    - 15 天内有任意先前入境 → 二次入境,上限 ¥1,000;否则 ¥5,000
    - headroom = max(0, limit - 15d 内已用)
    - 另附 7d / 15d / 30d 三个窗口的累计货值
    - as_of: 历史查询(默认今天)
    """
    if as_of is None:
        as_of = _dt.date.today().isoformat()

    def window_sum(days_n: int) -> float:
        row = conn.execute(
            "SELECT COALESCE(SUM(subtotal_cny), 0) AS total FROM china_quota_usage "
            "WHERE entry_date >= date(?, ?)",
            (as_of, f'-{days_n} days'),
        ).fetchone()
        return round(float(row['total']), 2)

    used_7d = window_sum(7)
    used_15d = window_sum(days)
    used_30d = window_sum(30)

    rows = conn.execute(
        "SELECT * FROM china_quota_usage WHERE entry_date >= date(?, ?) "
        "ORDER BY entry_date ASC, id ASC",
        (as_of, f'-{days} days'),
    ).fetchall()
    is_repeat = bool(rows)
    limit = 1000.0 if is_repeat else 5000.0
    headroom = max(0.0, round(limit - used_15d, 2))
    last = rows[-1] if rows else None
    return {
        # Round 24 contract (tests + `arb quota summary`)
        'as_of': as_of,
        'recent_entry_date': last['entry_date'] if last else None,
        'is_repeat_within_15d': is_repeat,
        'limit_cny': limit,
        'headroom_cny': headroom,
        'window_7d_cny': used_7d,
        'window_15d_cny': used_15d,
        'window_30d_cny': used_30d,
        # SPA legacy keys (web/app.js tripPlanner quotaRefresh)
        'window_active': is_repeat,
        'remaining_cny': headroom,
        'next_entry_cny': limit,
        'used_total_cny': used_15d,
        'last_entry_date': last['entry_date'] if last else None,
        'last_entry_cny': last['subtotal_cny'] if last else 0.0,
        'entries': [dict(r) for r in rows],
    }


def add_quota_entry(conn, entry_date, entry_cny, trip_id=None, notes=None):
    cur = conn.execute(
        "INSERT INTO quota_windows (entry_date, entry_cny, trip_id, notes) VALUES (?, ?, ?, ?)",
        (entry_date, entry_cny, trip_id, notes)
    )
    conn.commit()
    return cur.lastrowid


# ---------- M0: execution_orders (执行环订单) ----------

def create_execution_order(conn: sqlite3.Connection, row: dict) -> int:
    """Insert one execution order.  Unknown keys are ignored."""
    fields = ("sku", "leg", "qty", "state", "sell_platform", "buy_platform",
              "sell_ext_id", "buy_ext_id", "sell_price_cny", "buy_price_cny",
              "ship_cost_cny", "buyer_paid_cny", "buy_source_url", "tracking", "error")
    values = {k: row[k] for k in fields if k in row}
    if not values:
        raise ValueError("create_execution_order: row 没有可插入字段")
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO execution_orders ({cols}) VALUES ({marks})",
        tuple(values.values()),
    )
    conn.commit()
    return cur.lastrowid


def get_execution_order(conn: sqlite3.Connection, order_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM execution_orders WHERE id = ?", (order_id,)
    ).fetchone()


def update_execution_order(conn: sqlite3.Connection, order_id: int, **fields) -> None:
    """Patch any subset of columns; bumps updated_at."""
    if not fields:
        return
    fields = {**fields, "updated_at": _dt.datetime.now().isoformat(timespec="seconds")}
    assigns = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE execution_orders SET {assigns} WHERE id = ?",
        (*fields.values(), order_id),
    )
    conn.commit()


def list_execution_orders(conn: sqlite3.Connection, state: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM execution_orders"
    params: tuple = ()
    if state is not None:
        sql += " WHERE state = ?"
        params = (state,)
    sql += " ORDER BY id ASC"
    return list(conn.execute(sql, params))


def sum_paid_cny_on(conn: sqlite3.Connection, date_iso: str) -> float:
    """当日已 PAID 订单的采购款累计(限额守卫用)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(buy_price_cny), 0) AS total FROM execution_orders "
        "WHERE state = 'paid' AND date(updated_at) = date(?)",
        (date_iso,),
    ).fetchone()
    return round(float(row["total"]), 2)


# ---------- SKU 反馈标注 (面板简化: 用户 re 商机机制) ----------

def list_sku_feedback(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """全部反馈标注, 最新在前."""
    return list(conn.execute(
        "SELECT * FROM sku_feedback ORDER BY updated_at DESC"
    ))


def upsert_sku_feedback(conn: sqlite3.Connection, sku: str,
                        status: str, reason: str = "") -> None:
    """插入或覆盖一条标注. status: 'ok' | 'bad'."""
    conn.execute(
        "INSERT INTO sku_feedback (sku, status, reason, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(sku) DO UPDATE SET status = excluded.status, "
        "reason = excluded.reason, updated_at = excluded.updated_at",
        (sku, status, reason, _dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def delete_sku_feedback(conn: sqlite3.Connection, sku: str) -> None:
    conn.execute("DELETE FROM sku_feedback WHERE sku = ?", (sku,))
    conn.commit()
