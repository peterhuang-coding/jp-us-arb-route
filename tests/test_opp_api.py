"""阶段0: /api/opp/* 只读端点冒烟."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arb import db
from arb.opp import backfill


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    conn = db.connect(db_file)
    # 最小 legacy 数据: 1 个 verified opp + 买卖证据
    conn.execute(
        "INSERT INTO opportunities (sku,name,category,source_market,target_market,"
        "purchase_price_usd,sell_price_usd,data_freshness_ts,verified) "
        "VALUES ('SKU-X','测试品','test','JP','CN',10,20,'2026-09-01',1)",
    )
    conn.execute(
        "INSERT INTO evidence_log (sku,side,channel_name,price_cny,price_type,observed_at) "
        "VALUES ('SKU-X','buy','免税店',900,'tax-free','2026-08')",
    )
    conn.execute(
        "INSERT INTO evidence_log (sku,side,channel_name,price_cny,price_type,observed_at) "
        "VALUES ('SKU-X','sell','得物',1300,'成交','2026-08')",
    )
    conn.execute(
        "INSERT INTO evidence_log (sku,side,channel_name,price_cny,price_type,observed_at) "
        "VALUES ('SKU-X','sell','闲鱼',1200,'挂单','2026-08')",
    )
    conn.commit()
    backfill.run(conn, dry_run=False)
    conn.close()
    from arb.web_api import app
    with TestClient(app) as c:
        yield c


def test_list_items(client):
    r = client.get("/api/opp/items")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["item_key"] == "SKU-X"
    assert isinstance(body[0]["spec_json"], dict)


def test_list_cases_and_filter(client):
    r = client.get("/api/opp/cases")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r2 = client.get("/api/opp/cases", params={"status": "settled"})
    assert r2.json() == []
    r3 = client.get("/api/opp/cases", params={"status": "qualified"})
    assert len(r3.json()) == 1


def test_case_detail_with_evidence_and_events(client):
    r = client.get("/api/opp/cases/SKU-X")
    assert r.status_code == 200
    body = r.json()
    assert body["case"]["status"] == "qualified"
    kinds = {e["kind"] for e in body["evidence"]}
    assert {"retail", "sold", "ask"} <= kinds
    assert body["events"][0]["to_status"] in ("discovered", "qualified")
    # 404
    assert client.get("/api/opp/cases/NOPE").status_code == 404


def test_evidence_filter(client):
    r = client.get("/api/opp/evidence", params={"kind": "sold"})
    assert r.status_code == 200
    assert all(e["kind"] == "sold" for e in r.json())
    r2 = client.get("/api/opp/evidence", params={"side": "buy"})
    assert all(e["side"] == "buy" for e in r2.json())


def test_funnel_counts(client):
    r = client.get("/api/opp/funnel")
    assert r.status_code == 200
    body = r.json()
    assert body["by_status"].get("qualified") == 1
    assert body["total_cases"] == 1
    assert "conversion_pct" in body and "north_star" in body
