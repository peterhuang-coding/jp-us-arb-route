import json

import pytest
from fastapi.testclient import TestClient

from arb import cli, db, web_api


ROUTE = {
    "name": "TEST-ROUTE",
    "cn_to_usd_fx": 1.0,
    "flight_cost_usd": 100.0,
    "hotel_cost_usd": 40.0,
    "other_cost_usd": 10.0,
}


def opp(sku, name, purchase, home, sell, cap):
    return {
        "sku": sku,
        "name": name,
        "category": "synthetic",
        "purchase_price_usd": purchase,
        "sell_price_usd": sell,
        "home_price_cny": home,
        "max_units_per_trip": cap,
        "tariff_rate": 0.0,
        "shipping_per_unit_usd": 0.0,
    }


CASES = [
    (
        [opp("A", "Alpha", 1.49, 4.49, 4.49, 2)],
        2.0,
        2.0,
        {"A": 1},
        1.49,
        3.0,
        0.51,
        [],
    ),
    (
        [
            opp("ZERO", "Zero cap", 0.50, 100.0, 100.0, 0),
            opp("B", "Bravo", 1.00, 2.00, 2.00, 1),
        ],
        2.0,
        2.0,
        {"B": 1},
        1.00,
        1.00,
        1.00,
        ["ZERO: max_units < 1"],
    ),
    (
        [opp("C", "Charlie", 1.25, 2.25, 2.25, 3)],
        3.0,
        3.0,
        {"C": 2},
        2.50,
        2.00,
        0.50,
        [],
    ),
]


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def install_fake_db(monkeypatch, opportunities):
    state = {"conns": []}

    def fake_connect():
        conn = FakeConn()
        state["conns"].append(conn)
        return conn

    monkeypatch.setattr(db, "connect", fake_connect)
    monkeypatch.setattr(db, "get_route", lambda conn, route: dict(ROUTE))
    monkeypatch.setattr(db, "list_opportunities", lambda conn: list(opportunities))
    return state


@pytest.mark.parametrize("opportunities,budget,customs,expected_qty,spend,savings,leftover,skipped", CASES)
def test_api_and_cli_basket_results_match(monkeypatch, capsys, opportunities, budget, customs, expected_qty, spend, savings, leftover, skipped):
    state = install_fake_db(monkeypatch, opportunities)
    client = TestClient(web_api.app)

    resp = client.post(
        "/api/basket",
        json={"route": "TEST-ROUTE", "budget_cny": budget, "customs_limit_cny": customs},
    )

    assert resp.status_code == 200
    api = resp.json()
    assert state["conns"][0].closed is True

    rc = cli.main([
        "basket",
        "--budget",
        str(budget),
        "--customs",
        str(customs),
        "--route",
        "TEST-ROUTE",
        "--json",
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.err == ""
    cli_data = json.loads(captured.out)
    assert state["conns"][1].closed is True

    public_fields = (
        "route", "fx_rate", "budget_cny", "customs_limit_cny", "trip_cost_usd",
        "total_spend_cny", "total_savings_cny", "payback_rate_pct",
        "leftover_cny", "customs_headroom_cny", "algorithm", "notes",
        "skipped_skus", "picks",
    )
    assert {k: api[k] for k in public_fields} == {k: cli_data[k] for k in public_fields}

    by_sku = {p["sku"]: p["num_units"] for p in api["picks"]}
    assert by_sku == expected_qty
    assert {p["sku"]: p["num_units"] for p in cli_data["picks"]} == expected_qty

    assert 0 <= api["total_spend_cny"] <= min(budget, customs)
    assert api["total_spend_cny"] == spend
    assert api["total_savings_cny"] == savings
    assert api["leftover_cny"] == leftover
    assert api["customs_headroom_cny"] == customs - spend
    assert api["budget_cny"] == budget
    assert api["customs_limit_cny"] == customs
    assert api["fx_rate"] == 1.0
    assert api["trip_cost_usd"] == 150.0
    assert api["skipped_skus"] == skipped
    assert cli_data["skipped_skus"] == skipped

    caps = {o["sku"]: o["max_units_per_trip"] for o in opportunities}
    for pick in api["picks"]:
        qty = pick["num_units"]
        assert isinstance(qty, int)
        assert qty > 0
        assert qty <= caps[pick["sku"]]
        assert pick["subtotal_cny"] == pytest.approx(qty * pick["jp_price_per_unit_cny"])
        assert pick["total_savings_cny"] == pytest.approx(qty * pick["savings_per_unit_cny"])

    assert all(conn.closed for conn in state["conns"])
