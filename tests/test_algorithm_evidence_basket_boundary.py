import json

import pytest
from fastapi.testclient import TestClient

from arb import cli, db, web_api


MSG = "basket state budget exceeded; narrow candidate set"
ROUTE = {
    "name": "TEST-ROUTE",
    "cn_to_usd_fx": 0.14,
    "flight_cost_usd": 100.0,
    "hotel_cost_usd": 40.0,
    "other_cost_usd": 10.0,
}


class FakeConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def install_fake_db(monkeypatch):
    state = {"conn": None}

    def fake_connect(*args, **kwargs):
        state["conn"] = FakeConn()
        return state["conn"]

    monkeypatch.setattr(db, "connect", fake_connect)
    monkeypatch.setattr(db, "get_route", lambda conn, route: dict(ROUTE))
    monkeypatch.setattr(db, "list_opportunities", lambda conn: [])
    return state


def test_api_basket_success_preserves_response(monkeypatch):
    state = install_fake_db(monkeypatch)
    # Deliberately do not patch web_api.solve_basket: this exercises the real solver.
    client = TestClient(web_api.app, raise_server_exceptions=True)

    resp = client.post("/api/basket", json={"route": "TEST-ROUTE"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["route"] == "TEST-ROUTE"
    assert data["trip_cost_usd"] == 150.0
    assert data["picks"] == []
    assert {"fx_rate", "budget_cny", "customs_limit_cny", "total_spend_cny",
            "total_savings_cny", "payback_rate_pct", "leftover_cny",
            "customs_headroom_cny", "algorithm", "notes", "skipped_skus"} <= data.keys()
    assert state["conn"].closed is True


def test_api_basket_value_error_becomes_422_and_closes(monkeypatch):
    state = install_fake_db(monkeypatch)

    def boom(*args, **kwargs):
        raise ValueError(MSG)

    monkeypatch.setattr(web_api, "solve_basket", boom)
    client = TestClient(web_api.app, raise_server_exceptions=True)

    resp = client.post("/api/basket", json={"route": "TEST-ROUTE"})

    assert resp.status_code == 422
    assert resp.json() == {"detail": MSG}
    assert state["conn"].closed is True


def test_api_basket_unexpected_error_propagates_and_closes(monkeypatch):
    state = install_fake_db(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected solver failure")

    monkeypatch.setattr(web_api, "solve_basket", boom)
    client = TestClient(web_api.app, raise_server_exceptions=True)

    with pytest.raises(RuntimeError, match="unexpected solver failure"):
        client.post("/api/basket", json={"route": "TEST-ROUTE"})
    assert state["conn"].closed is True


def test_cli_basket_failure_and_success_boundary(monkeypatch, capsys):
    state = install_fake_db(monkeypatch)
    monkeypatch.setattr(cli, "solve_basket", lambda *a, **k: (_ for _ in ()).throw(ValueError(MSG)))

    assert cli.main(["basket", "--json"]) == 1
    err = capsys.readouterr()
    assert MSG in err.err
    assert err.out == ""
    assert state["conn"].closed is True

    monkeypatch.setattr(cli, "solve_basket", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unexpected solver failure")))
    with pytest.raises(RuntimeError, match="unexpected solver failure"):
        cli.main(["basket", "--json"])
    assert state["conn"].closed is True

    # Success control: restore the real imported solver and verify public JSON shape.
    monkeypatch.setattr(cli, "solve_basket", web_api.solve_basket)
    assert cli.main(["basket", "--json"]) == 0
    out = capsys.readouterr()
    data = json.loads(out.out)
    assert data["route"] == "TEST-ROUTE"
    assert data["trip_cost_usd"] == 150.0
    assert data["picks"] == []
    assert state["conn"].closed is True
