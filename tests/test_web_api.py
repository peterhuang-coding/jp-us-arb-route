"""FastAPI endpoint smoke tests using TestClient (in-process)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arb import db
from arb.web_api import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Per-test client backed by a tmp SQLite file.  Seeded with the canonical
    6 SKUs + 1 route so the SPA's default selection works."""
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    conn = db.connect(db_file)
    from arb.seed import seed_all
    seed_all(conn)
    conn.close()
    with TestClient(app) as c:
        yield c


def test_health_returns_counts(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["opportunities"] == 6
    assert body["routes"] == 1


def test_list_opportunities(client):
    r = client.get("/api/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 6
    skus = {o["sku"] for o in body}
    assert "JP-SKII-FT230" in skus
    assert "JP-LUX-PATEK" in skus
    # verified is bool, not int
    for o in body:
        assert isinstance(o["verified"], bool)


def test_list_routes_includes_legs(client):
    r = client.get("/api/routes")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["name"] == "PVG-NRT-LAX-2N"
    assert len(body[0]["legs"]) == 6


def test_decide_post_returns_decision(client):
    r = client.post("/api/decide", json={
        "sku": "JP-NINTENDO-SWOLED",
        "num_units": 10,
        "route": "PVG-NRT-LAX-2N",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["opp"]["sku"] == "JP-NINTENDO-SWOLED"
    assert body["num_units"] == 10
    assert body["decision"]["level"] in ("建议", "谨慎", "不建议")
    assert isinstance(body["decision"]["roi_pct"], float)


def test_decide_404_for_unknown_sku(client):
    r = client.post("/api/decide", json={"sku": "NOPE", "num_units": 1})
    assert r.status_code == 404


def test_decide_validates_units(client):
    r = client.post("/api/decide", json={"sku": "JP-SKII-FT230", "num_units": 0})
    assert r.status_code == 422


def test_report_markdown(client):
    r = client.get("/api/report/JP-SKII-FT230.md?num_units=5")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "# 决策报告" in r.text
    assert "JP-SKII-FT230" in r.text


def test_report_markdown_content_disposition(client):
    r = client.get("/api/report/JP-SKII-FT230.md?num_units=5")
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert ".md" in cd


def test_report_html(client):
    r = client.get("/api/report/JP-SKII-FT230.html?num_units=5")
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text
    assert "决策报告" in r.text


def test_report_pdf(client, tmp_path):
    """PDF render via real playwright; saves a copy for inspection."""
    r = client.get("/api/report/JP-SKII-FT230.pdf?num_units=5")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    out = tmp_path / "from-api.pdf"
    out.write_bytes(r.content)
    assert out.read_bytes()[:4] == b"%PDF"


def test_report_404_for_unknown_sku(client):
    r = client.get("/api/report/NOPE.md")
    assert r.status_code == 404


def test_spa_index_served(client):
    """Static SPA must mount at / and serve web/index.html."""
    r = client.get("/")
    assert r.status_code == 200
    assert "<!DOCTYPE html>" in r.text
    assert "jp-us-arb-route" in r.text


def test_spa_static_assets(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_decide_records_to_db(client):
    """POST /api/decide must persist a row in the decisions table."""
    r = client.post("/api/decide", json={
        "sku": "JP-SKII-FT230", "num_units": 5, "route": "PVG-NRT-LAX-2N",
    })
    assert r.status_code == 200
    conn = db.connect(db.DB_PATH)
    rows = conn.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()
    conn.close()
    assert rows["c"] >= 1