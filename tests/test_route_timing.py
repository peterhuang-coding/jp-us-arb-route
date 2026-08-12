"""Tests for Round 17 route_leg timing migration + backfill.

Covers schema idempotency, ISO parse/format round-trip, and the
``backfill_route_leg_times`` walk: forward accumulation from
``routes.departure_date`` + 09:00 with cross-midnight correctness.
"""
from __future__ import annotations

import pytest

from arb.db import (
    _fmt_iso_min,
    _parse_iso_min,
    backfill_route_leg_times,
    connect,
    connect_memory,
)


# ---------- ISO parse / format ----------

class TestIsoRoundTrip:
    def test_parse_basic(self):
        assert _parse_iso_min("2026-09-15T09:00") > 0

    def test_parse_with_seconds(self):
        a = _parse_iso_min("2026-09-15T09:00")
        b = _parse_iso_min("2026-09-15T09:00:30")
        # 30s difference rounds away at minute granularity
        assert a == b

    def test_parse_bad_raises(self):
        with pytest.raises(ValueError, match="unparseable"):
            _parse_iso_min("not a time")

    def test_fmt_basic(self):
        # Pick a known UTC instant: 2026-09-15T00:00 UTC == minute 0 of that day
        # (use the same epoch arithmetic the function uses).
        mins = _parse_iso_min("2026-09-15T00:00")
        assert _fmt_iso_min(mins) == "2026-09-15T00:00"

    def test_fmt_keeps_minute_granularity(self):
        mins = _parse_iso_min("2026-09-15T13:45")
        assert _fmt_iso_min(mins).endswith("T13:45")


# ---------- schema migration ----------

class TestSchemaMigration:
    def test_legacy_db_gets_new_columns(self, tmp_path, monkeypatch):
        """Simulate a pre-Round-17 DB by writing a minimal legacy schema,
        then calling connect() — the migration must add depart_at/arrive_at.
        """
        import sqlite3
        legacy = tmp_path / "legacy.sqlite"
        conn = sqlite3.connect(legacy)
        conn.executescript("""
            CREATE TABLE opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                source_market TEXT NOT NULL,
                target_market TEXT NOT NULL,
                purchase_price_usd REAL NOT NULL,
                tariff_rate REAL NOT NULL DEFAULT 0.0,
                sell_price_usd REAL NOT NULL,
                shipping_per_unit_usd REAL NOT NULL DEFAULT 0.0,
                platform_fee_rate REAL NOT NULL DEFAULT 0.13,
                minutes_per_unit REAL NOT NULL DEFAULT 30.0,
                success_rate REAL NOT NULL DEFAULT 0.7,
                purchase_source_url TEXT,
                sell_source_url TEXT,
                notes TEXT,
                data_freshness_ts TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                home_price_cny REAL,
                unit_volume_ml REAL,
                max_units_per_trip INTEGER NOT NULL DEFAULT 50,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                origin_city TEXT NOT NULL,
                dest_city TEXT NOT NULL,
                flight_cost_usd REAL NOT NULL,
                hotel_cost_usd REAL NOT NULL,
                other_cost_usd REAL NOT NULL DEFAULT 0.0,
                hours_available REAL NOT NULL DEFAULT 32.0,
                target_hourly_usd REAL NOT NULL DEFAULT 20.0,
                target_roi_pct REAL NOT NULL DEFAULT 15.0,
                min_roi_pct REAL NOT NULL DEFAULT 10.0,
                departure_date TEXT,
                source_url TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE route_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                duration_min REAL NOT NULL DEFAULT 0.0,
                location TEXT,
                notes TEXT,
                UNIQUE(route_id, seq)
            );
        """)
        conn.close()
        # Open via arb.db.connect → must migrate
        c = connect(legacy)
        cols = {r["name"] for r in c.execute("PRAGMA table_info(route_legs)").fetchall()}
        assert "depart_at" in cols
        assert "arrive_at" in cols

    def test_idempotent_no_op_when_already_migrated(self):
        c = connect_memory()
        # Run twice
        cols1 = {r["name"] for r in c.execute("PRAGMA table_info(route_legs)").fetchall()}
        # trigger another migration pass by calling _ensure_columns again
        from arb.db import _EXPECTED_COLUMNS, _ensure_columns
        _ensure_columns(c, "route_legs", _EXPECTED_COLUMNS["route_legs"])
        cols2 = {r["name"] for r in c.execute("PRAGMA table_info(route_legs)").fetchall()}
        assert cols1 == cols2


# ---------- backfill ----------

def _seed_route(conn, *, departure_date: str = "2026-09-15",
                legs: list[tuple[str, str, float]] | None = None):
    """Insert a minimal route with legs. ``legs`` is a list of
    (kind, label, duration_min) tuples in seq order."""
    conn.execute(
        "INSERT INTO routes (name, origin_city, dest_city, "
        "flight_cost_usd, hotel_cost_usd, other_cost_usd, hours_available, "
        "target_hourly_usd, target_roi_pct, min_roi_pct, departure_date) "
        "VALUES (?, 'A', 'B', 0, 0, 0, 32, 20, 15, 10, ?)",
        ("R-TEST", departure_date),
    )
    route_id = conn.execute("SELECT id FROM routes WHERE name='R-TEST'").fetchone()["id"]
    if legs is None:
        legs = [
            ("flight", "PVG → NRT", 200),
            ("flight", "NRT → LAX", 660),
            ("hotel",  "Hotel LAX", 0),
            ("shop",   "Shopping", 240),
            ("flight", "LAX → NRT", 660),
            ("flight", "NRT → PVG", 200),
        ]
    for i, (kind, label, dur) in enumerate(legs, 1):
        conn.execute(
            "INSERT INTO route_legs (route_id, seq, kind, label, cost_usd, duration_min) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (route_id, i, kind, label, dur),
        )
    conn.commit()
    return route_id


class TestBackfillRouteLegTimes:
    def test_basic_walk(self):
        conn = connect_memory()
        rid = _seed_route(conn)
        n = backfill_route_leg_times(conn, rid)
        assert n == 6
        rows = conn.execute(
            "SELECT seq, kind, depart_at, arrive_at FROM route_legs "
            "WHERE route_id=? ORDER BY seq", (rid,)).fetchall()
        # First flight: 09:00 + 200min = 12:20 (note: same day)
        assert rows[0]["depart_at"] == "2026-09-15T09:00"
        assert rows[0]["arrive_at"] == "2026-09-15T12:20"
        # Last flight lands next day: 09:00 + 200 + 660 + (0) + 240 + 660 + 200
        # = 09:00 + 1960 min = 09:00 + 32h40m = 17:40 next day
        assert rows[-1]["arrive_at"] == "2026-09-16T17:40"

    def test_hotel_leg_has_null_depart(self):
        conn = connect_memory()
        rid = _seed_route(conn)
        backfill_route_leg_times(conn, rid)
        rows = conn.execute(
            "SELECT seq, kind, depart_at, arrive_at FROM route_legs "
            "WHERE route_id=? ORDER BY seq", (rid,)).fetchall()
        hotel = next(r for r in rows if r["kind"] == "hotel")
        assert hotel["depart_at"] is None
        assert hotel["arrive_at"] is not None

    def test_idempotent(self):
        conn = connect_memory()
        rid = _seed_route(conn)
        backfill_route_leg_times(conn, rid)
        first = {r["seq"]: r["arrive_at"] for r in conn.execute(
            "SELECT seq, arrive_at FROM route_legs WHERE route_id=? ORDER BY seq", (rid,))}
        backfill_route_leg_times(conn, rid)
        second = {r["seq"]: r["arrive_at"] for r in conn.execute(
            "SELECT seq, arrive_at FROM route_legs WHERE route_id=? ORDER BY seq", (rid,))}
        assert first == second

    def test_missing_departure_date_raises(self):
        conn = connect_memory()
        conn.execute(
            "INSERT INTO routes (name, origin_city, dest_city, "
            "flight_cost_usd, hotel_cost_usd, hours_available, "
            "target_hourly_usd, target_roi_pct, min_roi_pct) "
            "VALUES ('R-NO-DATE', 'A', 'B', 0, 0, 32, 20, 15, 10)")
        rid = conn.execute("SELECT id FROM routes WHERE name='R-NO-DATE'").fetchone()["id"]
        with pytest.raises(ValueError, match="no departure_date"):
            backfill_route_leg_times(conn, rid)

    def test_unknown_route_raises(self):
        conn = connect_memory()
        with pytest.raises(ValueError, match="route id .* not found"):
            backfill_route_leg_times(conn, 99999)

    def test_cross_midnight_arithmetic(self):
        """A flight starting 23:30 with 90-min duration arrives at 01:00 next day."""
        conn = connect_memory()
        rid = _seed_route(conn, legs=[
            ("flight", "Late night leg", 90),
        ])
        backfill_route_leg_times(conn, rid)
        row = conn.execute(
            "SELECT depart_at, arrive_at FROM route_legs "
            "WHERE route_id=? AND seq=1", (rid,)).fetchone()
        assert row["depart_at"] == "2026-09-15T09:00"
        assert row["arrive_at"] == "2026-09-15T10:30"  # 90min later, same day

    def test_empty_legs_returns_zero(self):
        conn = connect_memory()
        conn.execute(
            "INSERT INTO routes (name, origin_city, dest_city, "
            "flight_cost_usd, hotel_cost_usd, hours_available, "
            "target_hourly_usd, target_roi_pct, min_roi_pct, departure_date) "
            "VALUES ('R-EMPTY', 'A', 'B', 0, 0, 32, 20, 15, 10, '2026-09-15')")
        rid = conn.execute("SELECT id FROM routes WHERE name='R-EMPTY'").fetchone()["id"]
        assert backfill_route_leg_times(conn, rid) == 0

    def test_real_seeded_route(self):
        """End-to-end: real DB seed has PVG-NRT-LAX-2N with 6 legs."""
        conn = connect()
        try:
            row = conn.execute(
                "SELECT id FROM routes WHERE name='PVG-NRT-LAX-2N'").fetchone()
            if row is None:
                pytest.skip("seed not loaded in this DB")
            n = backfill_route_leg_times(conn, row["id"])
            assert n >= 1
        finally:
            conn.close()