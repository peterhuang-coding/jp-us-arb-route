"""M0 execution_orders 表 CRUD 测试."""
from datetime import date

import pytest

from arb import db


@pytest.fixture
def conn():
    c = db.connect_memory()
    yield c
    c.close()


def test_create_and_get_roundtrip(conn):
    oid = db.create_execution_order(conn, dict(
        sku="JP-SKII-FT230", leg="D", sell_price_cny=950.0))
    assert oid > 0
    row = db.get_execution_order(conn, oid)
    assert row["sku"] == "JP-SKII-FT230"
    assert row["state"] == "created"
    assert row["leg"] == "D"


def test_update_patches_fields_and_bumps_updated_at(conn):
    oid = db.create_execution_order(conn, dict(sku="JP-SKII-FT230", leg="D"))
    before = db.get_execution_order(conn, oid)["updated_at"]
    db.update_execution_order(conn, oid, state="listed",
                              sell_ext_id="dry-sell-JP-SKII-FT230")
    row = db.get_execution_order(conn, oid)
    assert row["state"] == "listed"
    assert row["sell_ext_id"] == "dry-sell-JP-SKII-FT230"
    assert row["updated_at"] >= before


def test_list_filters_by_state(conn):
    db.create_execution_order(conn, dict(sku="A", leg="D"))
    oid = db.create_execution_order(conn, dict(sku="B", leg="E"))
    db.update_execution_order(conn, oid, state="completed")
    rows = db.list_execution_orders(conn, state="completed")
    assert [r["sku"] for r in rows] == ["B"]


def test_sum_paid_cny_on_counts_only_paid_orders(conn):
    a = db.create_execution_order(conn, dict(sku="A", leg="D"))
    b = db.create_execution_order(conn, dict(sku="B", leg="E"))
    db.update_execution_order(conn, a, state="paid", buy_price_cny=100.0)
    db.update_execution_order(conn, b, state="purchased", buy_price_cny=999.0)
    assert db.sum_paid_cny_on(conn, date.today().isoformat()) == 100.0
