"""Round 7 — end-to-end regression for proposed_prices.apply / reject.

The round-6 research handoff held two proposals pending because their
research confidence was ``low`` / losing-money:

* ``JP-WS-YAMAZAKI12``  sell_price: stored $320 → proposed $120
* ``JP-ANIME-GK2024``    sell_price: stored $290 → proposed $150

Round-7 applies both.  These tests pin the contract that must hold
forever after:

1. ``arb.db.resolve_proposed_price('apply')`` overwrites the parent's
   stored price and flips the proposal row to ``applied``.
2. ``arb.db.resolve_proposed_price('reject')`` leaves the parent's
   stored price alone and flips the row to ``rejected``.
3. After applying, the decision engine surfaces 不建议 at 1, 5, and 20
   units, and the breakeven sell price remains above the (now stored)
   sell price — i.e. applying the proposal is what makes the engine's
   verdict honest.
"""
from __future__ import annotations

import sqlite3

import pytest

import arb.db as arb_db
import arb.decision as arb_dec


# ---------- helpers ----------

def _seed_proposal(conn: sqlite3.Connection, *, sku: str, stored: float,
                   proposed: float) -> int:
    """Stage a sell_price_usd proposal for ``sku``.  Returns row id."""
    opp = arb_db.get_opportunity(conn, sku)
    assert opp is not None, f"missing seed SKU {sku}"
    return arb_db.add_proposed_price(
        conn, opp["id"], "sell_price_usd",
        stored_value=stored, proposed_value=proposed,
        detected_currency="USD",
        detected_raw=f"{proposed:.2f} (round-7 fixture)",
        source_url="https://example.invalid/round-7-fixture",
        drift_pct=abs(stored - proposed) / stored * 100.0,
    )


def _opp_inputs(opp_row: sqlite3.Row, num_units: int,
                route_flight: float = 720.0,
                route_hotel: float = 240.0) -> arb_dec.DecisionInputs:
    return arb_dec.DecisionInputs(
        num_units=num_units,
        purchase_price_usd=float(opp_row["purchase_price_usd"]),
        sell_price_usd=float(opp_row["sell_price_usd"]),
        tariff_rate=float(opp_row["tariff_rate"]),
        shipping_per_unit_usd=float(opp_row["shipping_per_unit_usd"]),
        platform_fee_rate=float(opp_row["platform_fee_rate"]),
        minutes_per_unit=float(opp_row["minutes_per_unit"]),
        flight_cost_usd=route_flight,
        hotel_cost_usd=route_hotel,
        other_trip_cost_usd=80.0,
        hours_available=32.0,
        target_hourly_usd=20.0,
    )


# ---------- fixtures ----------

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Isolated DB seeded with the standard 6 whitelist SKUs + 1 route."""
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    import arb.seed as arb_seed
    conn = arb_db.connect(db_file)
    try:
        arb_seed.seed_all(conn)
    finally:
        conn.close()
    return db_file


# ---------- apply path ----------

def test_apply_proposal_overwrites_parent_price(fresh_db):
    conn = arb_db.connect(fresh_db)
    try:
        before = arb_db.get_opportunity(conn, "JP-WS-YAMAZAKI12")
        pid = _seed_proposal(conn, sku="JP-WS-YAMAZAKI12",
                             stored=float(before["sell_price_usd"]),
                             proposed=120.0)
        result = arb_db.resolve_proposed_price(conn, pid, "apply")
        assert result["applied"] is True
        assert result["proposal_status"] == "applied"
        assert result["field"] == "sell_price_usd"
        assert result["new_value"] == pytest.approx(120.0)

        after = arb_db.get_opportunity(conn, "JP-WS-YAMAZAKI12")
        assert float(after["sell_price_usd"]) == pytest.approx(120.0)
        assert after["data_freshness_ts"]  # refreshed; not asserted to a specific date.

        # proposed_prices row flipped to applied.
        row = arb_db.get_proposed_price(conn, pid)
        assert row["status"] == "applied"
        assert row["resolved_at"]  # populated
    finally:
        conn.close()


def test_apply_proposal_drives_honest_no_for_yamazaki(fresh_db):
    """Stored $320 gave a borderline ROI at 20u; after apply @ $120 the
    engine must say 不建议 at all tested unit counts and breakeven
    must exceed the new sell price."""
    conn = arb_db.connect(fresh_db)
    try:
        opp = arb_db.get_opportunity(conn, "JP-WS-YAMAZAKI12")
        pid = _seed_proposal(conn, sku="JP-WS-YAMAZAKI12",
                             stored=float(opp["sell_price_usd"]),
                             proposed=120.0)
        arb_db.resolve_proposed_price(conn, pid, "apply")
        opp = arb_db.get_opportunity(conn, "JP-WS-YAMAZAKI12")
        assert float(opp["sell_price_usd"]) == pytest.approx(120.0)

        for units in (1, 5, 20, 50):
            d = arb_dec.judge(_opp_inputs(opp, num_units=units))
            assert d.level == "不建议", (
                f"Yamazaki @ units={units} expected 不建议 after apply, got {d.level}"
            )
            assert d.breakeven_sell_price_usd > float(opp["sell_price_usd"]), (
                f"breakeven {d.breakeven_sell_price_usd:.2f} should be > stored "
                f"sell price {opp['sell_price_usd']:.2f}"
            )
            assert d.net_profit_usd < 0
    finally:
        conn.close()


def test_apply_proposal_drives_honest_no_for_anime_gojo(fresh_db):
    """Stored $290 was already 不建议 at low units; after apply @ $150
    the engine must remain 不建议 across 1..50 units."""
    conn = arb_db.connect(fresh_db)
    try:
        opp = arb_db.get_opportunity(conn, "JP-ANIME-GK2024")
        pid = _seed_proposal(conn, sku="JP-ANIME-GK2024",
                             stored=float(opp["sell_price_usd"]),
                             proposed=150.0)
        arb_db.resolve_proposed_price(conn, pid, "apply")
        opp = arb_db.get_opportunity(conn, "JP-ANIME-GK2024")
        assert float(opp["sell_price_usd"]) == pytest.approx(150.0)

        for units in (1, 5, 20, 50):
            d = arb_dec.judge(_opp_inputs(opp, num_units=units))
            assert d.level == "不建议", (
                f"Anime Gojo @ units={units} expected 不建议 after apply, got {d.level}"
            )
            assert d.breakeven_sell_price_usd > float(opp["sell_price_usd"])
            assert d.net_profit_usd < 0
    finally:
        conn.close()


# ---------- reject path ----------

def test_reject_proposal_leaves_parent_unchanged(fresh_db):
    conn = arb_db.connect(fresh_db)
    try:
        before = arb_db.get_opportunity(conn, "JP-SKII-FT230")
        original_sell = float(before["sell_price_usd"])
        original_ts = before["data_freshness_ts"]
        pid = _seed_proposal(conn, sku="JP-SKII-FT230",
                             stored=original_sell, proposed=999.99)
        result = arb_db.resolve_proposed_price(conn, pid, "reject")
        assert result["applied"] is False
        assert result["proposal_status"] == "rejected"

        after = arb_db.get_opportunity(conn, "JP-SKII-FT230")
        assert float(after["sell_price_usd"]) == pytest.approx(original_sell)
        assert after["data_freshness_ts"] == original_ts

        row = arb_db.get_proposed_price(conn, pid)
        assert row["status"] == "rejected"
        assert row["resolved_at"]
    finally:
        conn.close()


# ---------- id/state guards ----------

def test_apply_is_idempotent_for_non_pending(fresh_db):
    """Re-applying an already-applied proposal must be a no-op (no DB
    drift, no new side-effects).  Returns applied=False with the prior
    status echoed back."""
    conn = arb_db.connect(fresh_db)
    try:
        opp = arb_db.get_opportunity(conn, "JP-WS-YAMAZAKI12")
        pid = _seed_proposal(conn, sku="JP-WS-YAMAZAKI12",
                             stored=float(opp["sell_price_usd"]),
                             proposed=120.0)
        first = arb_db.resolve_proposed_price(conn, pid, "apply")
        assert first["applied"] is True

        second = arb_db.resolve_proposed_price(conn, pid, "apply")
        assert second["applied"] is False
        assert second["proposal_status"] == "applied"
        assert second["message"].startswith("proposal already")
    finally:
        conn.close()


def test_apply_unknown_proposal_returns_not_found(fresh_db):
    conn = arb_db.connect(fresh_db)
    try:
        result = arb_db.resolve_proposed_price(conn, 99_999, "apply")
        assert result["applied"] is False
        assert result["proposal_status"] is None
        assert "not found" in result["message"]
    finally:
        conn.close()
