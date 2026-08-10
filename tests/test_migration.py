"""Migration tests for Round 13's new columns.

The DB used to have no migration mechanism. We added ``_table_columns`` +
``_ensure_columns`` to ``arb.db`` so the four new columns are added
idempotently on every ``connect()``. These tests prove the migration is
safe to run on an old-shape DB (no crashes, no data loss, correct
defaults) and is a no-op when columns already exist.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from arb import db


# Columns added in Round 13, with their expected DDL.
EXPECTED_NEW_COLUMNS: dict[str, dict[str, str]] = {
    "opportunities": {
        "home_price_cny": "REAL",
        "unit_volume_ml": "REAL",
        "max_units_per_trip": "INTEGER",
    },
    "routes": {
        "cn_to_usd_fx": "REAL",
    },
}


def _legacy_opportunities_ddl() -> str:
    """Old DDL with no Round-13 columns."""
    return """
    CREATE TABLE opportunities (
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
    """


def _legacy_routes_ddl() -> str:
    return """
    CREATE TABLE routes (
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
    """


def _make_legacy_db(path: Path) -> None:
    """Create a DB that only has the pre-Round-13 schema."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_legacy_opportunities_ddl())
    conn.executescript(_legacy_routes_ddl())
    # Insert a representative row to ensure we don't lose data.
    conn.execute(
        "INSERT INTO opportunities (sku,name,category,source_market,target_market,"
        " purchase_price_usd,tariff_rate,sell_price_usd,data_freshness_ts) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("LEGACY-001", "Legacy", "misc", "JP", "US", 10.0, 0.0, 20.0, "2026-01-01"),
    )
    conn.execute(
        "INSERT INTO routes (name,origin_city,dest_city,flight_cost_usd,hotel_cost_usd) "
        "VALUES (?,?,?,?,?)",
        ("LEGACY-RT", "PVG", "LAX", 100.0, 100.0),
    )
    conn.commit()
    conn.close()


def test_migration_adds_columns_to_old_shape_db(tmp_path):
    """Connecting to a pre-Round-13 DB must add the new columns idempotently."""
    db_file = tmp_path / "legacy.sqlite"
    _make_legacy_db(db_file)

    # Sanity: before migration, the columns are missing.
    raw = sqlite3.connect(db_file)
    raw.row_factory = sqlite3.Row
    cols_before = {r["name"] for r in raw.execute("PRAGMA table_info(opportunities)").fetchall()}
    raw.close()
    assert "home_price_cny" not in cols_before
    assert "max_units_per_trip" not in cols_before

    # Connect via arb.db → should add columns.
    conn = db.connect(db_file)
    try:
        cols = db._table_columns(conn, "opportunities")
        for col in EXPECTED_NEW_COLUMNS["opportunities"]:
            assert col in cols, f"opportunities.{col} missing after connect()"
        route_cols = db._table_columns(conn, "routes")
        for col in EXPECTED_NEW_COLUMNS["routes"]:
            assert col in route_cols, f"routes.{col} missing after connect()"
    finally:
        conn.close()


def test_migration_preserves_legacy_data(tmp_path):
    """Migration must not delete or alter existing rows."""
    db_file = tmp_path / "legacy.sqlite"
    _make_legacy_db(db_file)
    conn = db.connect(db_file)
    try:
        opp = conn.execute(
            "SELECT sku,name,purchase_price_usd FROM opportunities WHERE sku='LEGACY-001'"
        ).fetchone()
        assert opp["sku"] == "LEGACY-001"
        assert opp["name"] == "Legacy"
        assert opp["purchase_price_usd"] == 10.0
        route = conn.execute(
            "SELECT name,flight_cost_usd FROM routes WHERE name='LEGACY-RT'"
        ).fetchone()
        assert route["flight_cost_usd"] == 100.0
    finally:
        conn.close()


def test_migration_sets_correct_defaults(tmp_path):
    """The DEFAULT clause on each added column must apply to existing rows."""
    db_file = tmp_path / "legacy.sqlite"
    _make_legacy_db(db_file)
    conn = db.connect(db_file)
    try:
        # max_units_per_trip is NOT NULL with DEFAULT 50 → existing rows get 50.
        row = conn.execute(
            "SELECT max_units_per_trip FROM opportunities WHERE sku='LEGACY-001'"
        ).fetchone()
        assert row["max_units_per_trip"] == 50

        # cn_to_usd_fx is NOT NULL with DEFAULT 0.14 → existing route gets 0.14.
        row = conn.execute(
            "SELECT cn_to_usd_fx FROM routes WHERE name='LEGACY-RT'"
        ).fetchone()
        assert abs(row["cn_to_usd_fx"] - 0.14) < 1e-9

        # home_price_cny / unit_volume_ml are NULL-able with no default → NULL.
        row = conn.execute(
            "SELECT home_price_cny, unit_volume_ml FROM opportunities WHERE sku='LEGACY-001'"
        ).fetchone()
        assert row["home_price_cny"] is None
        assert row["unit_volume_ml"] is None
    finally:
        conn.close()


def test_migration_is_idempotent(tmp_path):
    """Connecting twice must not raise (no-op on the second call)."""
    db_file = tmp_path / "legacy.sqlite"
    _make_legacy_db(db_file)
    conn1 = db.connect(db_file)
    conn1.close()
    # Second call must not raise "duplicate column" or similar.
    conn2 = db.connect(db_file)
    try:
        # Still has the columns
        cols = db._table_columns(conn2, "opportunities")
        assert "home_price_cny" in cols
        assert "max_units_per_trip" in cols
    finally:
        conn2.close()


def test_migration_works_on_in_memory_db():
    """connect_memory() must also include the new columns from the start."""
    conn = db.connect_memory()
    try:
        for col in EXPECTED_NEW_COLUMNS["opportunities"]:
            assert col in db._table_columns(conn, "opportunities")
        for col in EXPECTED_NEW_COLUMNS["routes"]:
            assert col in db._table_columns(conn, "routes")
    finally:
        conn.close()


def test_ensure_columns_helper_unit(tmp_path):
    """Direct test of the _ensure_columns helper with a small legacy table."""
    db_file = tmp_path / "t.sqlite"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE foo (id INTEGER PRIMARY KEY, x TEXT)")
    conn.commit()
    db._ensure_columns(conn, "foo", {"y": "REAL DEFAULT 0.0", "z": "TEXT"})
    cols = db._table_columns(conn, "foo")
    assert cols == {"id", "x", "y", "z"}
    # Default applied to existing rows? Add a row first.
    conn.execute("INSERT INTO foo (id, x) VALUES (1, 'a')")
    conn.commit()
    row = conn.execute("SELECT y FROM foo WHERE id=1").fetchone()
    assert row["y"] == 0.0
    # Re-invoking with the same set is a no-op.
    db._ensure_columns(conn, "foo", {"y": "REAL DEFAULT 0.0", "z": "TEXT"})
    cols2 = db._table_columns(conn, "foo")
    assert cols2 == {"id", "x", "y", "z"}
    # Adding a new column to the same call works on a second invocation.
    db._ensure_columns(conn, "foo", {"y": "REAL", "z": "TEXT", "w": "INTEGER"})
    cols3 = db._table_columns(conn, "foo")
    assert "w" in cols3
    conn.close()
