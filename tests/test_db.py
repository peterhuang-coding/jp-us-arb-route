"""Tests for the SQLite persistence layer."""
from __future__ import annotations

import pytest

from arb import db


@pytest.fixture
def conn():
    c = db.connect_memory()
    yield c
    c.close()


def test_schema_creates_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "opportunities" in names
    assert "routes" in names
    assert "route_legs" in names
    assert "decisions" in names


def test_upsert_opportunity_insert(conn):
    opp = dict(
        sku="TEST-001", name="Test Widget", category="misc",
        source_market="JP", target_market="US",
        purchase_price_usd=10.0, tariff_rate=0.0,
        sell_price_usd=20.0, shipping_per_unit_usd=1.0,
        platform_fee_rate=0.13, minutes_per_unit=10.0,
        success_rate=0.7, purchase_source_url="https://example.com/jp",
        sell_source_url="https://example.com/us", notes="",
        data_freshness_ts="2026-07-01", verified=0,
    )
    db.upsert_opportunity(conn, opp)
    got = db.get_opportunity(conn, "TEST-001")
    assert got is not None
    assert got["name"] == "Test Widget"
    assert got["purchase_price_usd"] == 10.0


def test_upsert_opportunity_updates_on_conflict(conn):
    opp = dict(sku="TEST-002", name="v1", category="misc", source_market="JP",
               target_market="US", purchase_price_usd=10.0, tariff_rate=0.0,
               sell_price_usd=20.0, shipping_per_unit_usd=1.0,
               platform_fee_rate=0.13, minutes_per_unit=10.0, success_rate=0.7,
               purchase_source_url=None, sell_source_url=None, notes=None,
               data_freshness_ts="2026-07-01", verified=0)
    db.upsert_opportunity(conn, opp)
    opp2 = dict(opp, name="v2", sell_price_usd=22.0)
    db.upsert_opportunity(conn, opp2)
    got = db.get_opportunity(conn, "TEST-002")
    assert got["name"] == "v2"
    assert got["sell_price_usd"] == 22.0


def test_upsert_route_and_legs(conn):
    route = dict(name="R-TEST", origin_city="PVG", dest_city="LAX",
                 flight_cost_usd=700.0, hotel_cost_usd=240.0,
                 other_cost_usd=0.0, hours_available=32.0,
                 target_hourly_usd=20.0, target_roi_pct=15.0,
                 min_roi_pct=10.0, departure_date="2026-09-01",
                 source_url="https://example.com", notes="test")
    rid = db.upsert_route(conn, route)
    legs = [
        dict(seq=1, kind="flight", label="PVG -> NRT", cost_usd=120.0,
             duration_min=180.0, location="PVG", notes=""),
        dict(seq=2, kind="flight", label="NRT -> LAX", cost_usd=580.0,
             duration_min=660.0, location="NRT", notes=""),
        dict(seq=3, kind="hotel", label="Rodeway Inn LAX", cost_usd=240.0,
             duration_min=0.0, location="LAX", notes="2 nights"),
        dict(seq=4, kind="shop", label="Bic Camera LA", cost_usd=0.0,
             duration_min=240.0, location="LAX", notes=""),
        dict(seq=5, kind="flight", label="LAX -> NRT", cost_usd=580.0,
             duration_min=660.0, location="LAX", notes=""),
        dict(seq=6, kind="flight", label="NRT -> PVG", cost_usd=120.0,
             duration_min=180.0, location="NRT", notes=""),
    ]
    db.add_route_legs(conn, rid, legs)
    got = db.list_route_legs(conn, rid)
    assert len(got) == 6
    assert got[0]["label"] == "PVG -> NRT"
    assert got[5]["label"] == "NRT -> PVG"


def test_record_decision_round_trip(conn):
    opp = dict(sku="R-D-001", name="r", category="misc", source_market="JP",
               target_market="US", purchase_price_usd=10.0, tariff_rate=0.0,
               sell_price_usd=20.0, shipping_per_unit_usd=1.0,
               platform_fee_rate=0.13, minutes_per_unit=10.0, success_rate=0.7,
               purchase_source_url=None, sell_source_url=None, notes=None,
               data_freshness_ts="2026-07-01", verified=0)
    oid = db.upsert_opportunity(conn, opp)
    route = dict(name="R-DEC", origin_city="PVG", dest_city="LAX",
                 flight_cost_usd=100.0, hotel_cost_usd=100.0, other_cost_usd=0.0,
                 hours_available=32.0, target_hourly_usd=20.0,
                 target_roi_pct=15.0, min_roi_pct=10.0, departure_date=None,
                 source_url=None, notes=None)
    rid = db.upsert_route(conn, route)
    from arb.decision import Decision, judge, DecisionInputs
    di = DecisionInputs(num_units=10, purchase_price_usd=10.0, sell_price_usd=20.0,
                        tariff_rate=0.0, shipping_per_unit_usd=1.0,
                        platform_fee_rate=0.13, minutes_per_unit=10.0,
                        flight_cost_usd=100.0, hotel_cost_usd=100.0,
                        other_trip_cost_usd=0.0, hours_available=32.0,
                        target_hourly_usd=20.0, target_roi_pct=15.0, min_roi_pct=10.0)
    d = judge(di)
    did = db.record_decision(conn, oid, rid, 10, d)
    row = conn.execute("SELECT * FROM decisions WHERE id=?", (did,)).fetchone()
    assert row is not None
    import json
    payload = json.loads(row["decision_json"])
    assert payload["level"] == d.level
    assert payload["roi_pct"] == d.roi_pct


def test_list_opportunities_orders_by_id(conn):
    for sku in ("C-001", "A-001", "B-001"):
        opp = dict(sku=sku, name=sku, category="misc", source_market="JP",
                   target_market="US", purchase_price_usd=10.0, tariff_rate=0.0,
                   sell_price_usd=20.0, shipping_per_unit_usd=1.0,
                   platform_fee_rate=0.13, minutes_per_unit=10.0, success_rate=0.7,
                   purchase_source_url=None, sell_source_url=None, notes=None,
                   data_freshness_ts="2026-07-01", verified=0)
        db.upsert_opportunity(conn, opp)
    rows = db.list_opportunities(conn)
    assert [r["sku"] for r in rows] == ["C-001", "A-001", "B-001"]
