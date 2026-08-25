"""SKU 反馈标注 API 测试 (面板简化: 用户 re 商机机制)."""
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


def test_feedback_starts_empty(client):
    r = client.get("/api/feedback")
    assert r.status_code == 200
    assert r.json() == []


def test_feedback_bad_roundtrip(client):
    r = client.post("/api/feedback", json={
        "sku": "JP-SKII-FT230", "status": "bad", "reason": "利润太低",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["sku"] == "JP-SKII-FT230"
    assert body["status"] == "bad"
    assert body["reason"] == "利润太低"
    assert "updated_at" in body

    lst = client.get("/api/feedback").json()
    assert len(lst) == 1
    assert lst[0]["sku"] == "JP-SKII-FT230"


def test_feedback_upsert_overwrites(client):
    client.post("/api/feedback", json={"sku": "JP-LUX-PATEK", "status": "bad", "reason": "渠道不符"})
    r = client.post("/api/feedback", json={"sku": "JP-LUX-PATEK", "status": "ok", "reason": ""})
    assert r.status_code == 200
    lst = client.get("/api/feedback").json()
    assert len(lst) == 1              # 同 SKU 覆盖, 不新增行
    assert lst[0]["status"] == "ok"


def test_feedback_invalid_status_rejected(client):
    r = client.post("/api/feedback", json={"sku": "X", "status": "maybe", "reason": ""})
    assert r.status_code == 422


def test_feedback_delete_restores(client):
    client.post("/api/feedback", json={"sku": "JP-SKII-FT230", "status": "bad", "reason": "卖不动"})
    r = client.delete("/api/feedback/JP-SKII-FT230")
    assert r.status_code == 200
    assert r.json() == {"deleted": "JP-SKII-FT230"}
    assert client.get("/api/feedback").json() == []


def test_feedback_reason_trimmed_to_200_chars(client):
    r = client.post("/api/feedback", json={
        "sku": "JP-SKII-FT230", "status": "bad", "reason": "长" * 300,
    })
    assert r.status_code == 200
    assert len(r.json()["reason"]) <= 200
