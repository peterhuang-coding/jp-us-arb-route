"""SKU 实测闭环: 候选池 API 测试."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arb import db
from arb.web_api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    conn = db.connect(db_file)
    from arb.seed import seed_all
    seed_all(conn)
    conn.close()
    with TestClient(app) as c:
        yield c


CAND = {
    "name": "测试候选 SKU",
    "category": "玩具",
    "buy_price_usd": 30.0,
    "sell_price_usd": 80.0,
    "source_market": "JP 电器城",
    "target_market": "eBay US",
    "evidence": [
        {"label": "货源链接", "url": "https://example.com/buy", "side": "buy"},
        {"label": "eBay sold", "url": "https://example.com/sell", "side": "sell"},
    ],
}


def _create(client, **overrides):
    r = client.post("/api/candidates", json={**CAND, **overrides})
    assert r.status_code == 200, r.text
    return r.json()


def test_candidates_starts_empty(client):
    assert client.get("/api/candidates").json() == []


def test_candidate_create_and_list(client):
    body = _create(client)
    assert body["status"] == "candidate"
    assert body["evidence"][0]["side"] == "buy"
    lst = client.get("/api/candidates").json()
    assert len(lst) == 1
    assert lst[0]["name"] == CAND["name"]


def test_candidate_status_filter(client):
    _create(client)
    c2 = _create(client, name="第二条")
    client.post(f"/api/candidates/{c2['id']}/status", json={"status": "testing"})
    assert len(client.get("/api/candidates", params={"status": "testing"}).json()) == 1


def test_promote_creates_opportunity(client):
    c = _create(client, sku="CAND-TEST-1")
    r = client.post(f"/api/candidates/{c['id']}/status",
                    json={"status": "ok", "reason": "实测能卖"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["sku"] == "CAND-TEST-1"
    opps = client.get("/api/opportunities").json()
    promoted = [o for o in opps if o["sku"] == "CAND-TEST-1"]
    assert len(promoted) == 1
    o = promoted[0]
    assert o["purchase_price_usd"] == 30.0
    assert o["sell_price_usd"] == 80.0
    # 渠道从 evidence 构建, 保证进 ROI 推荐
    assert len(o["purchase_channels"]) == 1
    assert len(o["sell_channels"]) == 1


def test_promote_idempotent(client):
    """重复转正不重复插入 opportunities."""
    c = _create(client, sku="CAND-TEST-2")
    client.post(f"/api/candidates/{c['id']}/status", json={"status": "ok"})
    client.post(f"/api/candidates/{c['id']}/status", json={"status": "ok"})
    opps = [o for o in client.get("/api/opportunities").json()
            if o["sku"] == "CAND-TEST-2"]
    assert len(opps) == 1


def test_bad_reason_roundtrip(client):
    c = _create(client)
    r = client.post(f"/api/candidates/{c['id']}/status",
                    json={"status": "bad", "reason": "实测卖不动"})
    assert r.json()["status"] == "bad"
    assert r.json()["reason"] == "实测卖不动"
    # bad 候选不进 opportunities
    assert not any(o["sku"] == c["id"] for o in client.get("/api/opportunities").json())


def test_invalid_status_rejected(client):
    c = _create(client)
    r = client.post(f"/api/candidates/{c['id']}/status", json={"status": "maybe"})
    assert r.status_code == 422


def test_missing_candidate_404(client):
    r = client.post("/api/candidates/9999/status", json={"status": "ok"})
    assert r.status_code == 404


def test_create_requires_name(client):
    r = client.post("/api/candidates", json={"buy_price_usd": 1.0})
    assert r.status_code == 422
