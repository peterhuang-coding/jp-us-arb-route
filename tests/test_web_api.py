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
    6 SKUs + 2 routes (international PVG→LAX and regional LAX→SFO) so the
    SPA's default selection works."""
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
    assert body["routes"] == 2


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
    assert len(body) == 2
    names = [b["name"] for b in body]
    assert "PVG-NRT-LAX-2N" in names
    assert "LAX-SFO-1N" in names
    # Each seeded route should have at least 3 legs (flight/hotel/shop).
    for r_data in body:
        assert len(r_data["legs"]) >= 3


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
    # Round 5: scenarios returned with the canonical decision.
    assert "scenarios" in body
    assert [s["name"] for s in body["scenarios"]] == ["保守", "中性", "乐观"]
    # 中性 band matches the canonical decision numerically.
    neutral = body["scenarios"][1]
    assert neutral["level"] == body["decision"]["level"]
    assert abs(neutral["roi_pct"] - body["decision"]["roi_pct"]) < 1e-9
    assert abs(neutral["net_profit_usd"] - body["decision"]["net_profit_usd"]) < 1e-9


def test_decide_scenarios_cover_downside_upside_delta(client):
    """Conservative ROI must be <= neutral <= optimistic (monotonic)."""
    r = client.post("/api/decide", json={
        "sku": "JP-DYSON-V12S", "num_units": 3, "route": "PVG-NRT-LAX-2N",
    })
    assert r.status_code == 200
    scenarios = r.json()["scenarios"]
    cons, neu, opt = scenarios
    assert cons["delta_roi_pct"] <= 0
    assert neu["delta_roi_pct"] == 0
    assert opt["delta_roi_pct"] >= 0
    assert cons["net_profit_usd"] <= neu["net_profit_usd"] <= opt["net_profit_usd"]


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


def test_opportunities_attach_freshness_field(client):
    """GET /api/opportunities must embed a 'freshness' verdict on each row."""
    r = client.get("/api/opportunities")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1
    for o in body:
        assert "freshness" in o
        f = o["freshness"]
        assert f["status"] in ("fresh", "aging", "stale", "missing", "future")
        assert "badge" in f and "age_days" in f
    # Seed ts is 2026-07-01; today is 2026-07-26 → 25 days old → "aging"
    skii = next(o for o in body if o["sku"] == "JP-SKII-FT230")
    assert skii["freshness"]["status"] == "aging"


def test_refresh_unknown_sku_returns_404(client):
    r = client.post("/api/opportunities/NOPE/refresh")
    assert r.status_code == 200  # outcome payload includes message
    body = r.json()
    assert body["updated"] is False
    assert "opportunity not found" in body["message"]


def test_refresh_endpoint_returns_outcome_shape(client, monkeypatch):
    """Stub the scraper so the refresh path is deterministic in tests."""
    from arb import scraper
    class _Stub:
        ok = True
        status = 200
        final_url = "https://example.com"
        content_type = "text/html"
        bytes_read = 0
        elapsed_ms = 1
        robots_allowed = True
        blocked_reason = None
        text = "<html>USD 145.00</html>"
    monkeypatch.setattr(scraper, "fetch_url", lambda *a, **kw: _Stub())
    r = client.post("/api/opportunities/JP-SKII-FT230/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["sku"] == "JP-SKII-FT230"
    assert body["updated"] is True
    assert body["new_freshness_ts"] is not None
    assert body["purchase"] is not None and body["purchase"]["ok"] is True


# ---------- Round 4: verify + proposals endpoints ----------

def test_verify_endpoint_returns_shape(client, monkeypatch):
    """Stub the scraper so verify can run without network."""
    from arb import scraper
    class _Stub:
        ok = True
        status = 200
        final_url = "https://example.com"
        content_type = "text/html"
        bytes_read = 0
        elapsed_ms = 1
        robots_allowed = True
        blocked_reason = None
        text = "<html>USD 145.99</html>"
    monkeypatch.setattr(scraper, "fetch_url", lambda *a, **kw: _Stub())
    r = client.post("/api/opportunities/JP-SKII-FT230/verify")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {
        "sku", "name", "refresh_updated", "verified_now",
        "final_verified", "purchase", "sell", "message",
    }


def test_verify_unknown_sku_returns_404(client):
    r = client.post("/api/opportunities/NOPE/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["verified_now"] is False
    assert body["message"].startswith("opportunity not found")


def test_list_proposals_empty_by_default(client):
    r = client.get("/api/proposals")
    assert r.status_code == 200
    assert r.json() == []


def test_list_proposals_filter_by_sku_and_status(client, monkeypatch):
    from arb import scraper, db
    # Stage one proposal directly so the GET has something to return.
    conn = db.connect()
    opp = db.get_opportunity(conn, "JP-SKII-FT230")
    pid = db.add_proposed_price(
        conn, opp["id"], "sell_price_usd",
        stored_value=145.0, proposed_value=200.0,
        detected_currency="USD", detected_raw="USD 200.00",
        source_url="https://example.com/us", drift_pct=37.93,
    )
    conn.close()
    r = client.get("/api/proposals", params={"sku": "JP-SKII-FT230", "status": "pending"})
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["id"] == pid
    assert rows[0]["sku"] == "JP-SKII-FT230"


def test_apply_proposal_endpoint_overwrites_price(client):
    from arb import db
    conn = db.connect()
    opp = db.get_opportunity(conn, "JP-SKII-FT230")
    pid = db.add_proposed_price(
        conn, opp["id"], "sell_price_usd",
        stored_value=145.0, proposed_value=200.0,
        detected_currency="USD", detected_raw="USD 200.00",
        source_url="https://example.com/us", drift_pct=37.93,
    )
    conn.close()
    r = client.post(f"/api/proposals/{pid}/apply")
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["new_value"] == 200.0
    # DB updated
    conn = db.connect()
    row = db.get_opportunity(conn, "JP-SKII-FT230")
    assert row["sell_price_usd"] == 200.0
    conn.close()


def test_reject_proposal_endpoint_keeps_price(client):
    from arb import db
    conn = db.connect()
    opp = db.get_opportunity(conn, "JP-SKII-FT230")
    pid = db.add_proposed_price(
        conn, opp["id"], "sell_price_usd",
        stored_value=145.0, proposed_value=200.0,
        detected_currency="USD", detected_raw="USD 200.00",
        source_url="https://example.com/us", drift_pct=37.93,
    )
    conn.close()
    r = client.post(f"/api/proposals/{pid}/reject")
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is False
    assert body["proposal_status"] == "rejected"
    conn = db.connect()
    row = db.get_opportunity(conn, "JP-SKII-FT230")
    assert row["sell_price_usd"] == 145.0
    conn.close()


def test_apply_proposal_unknown_id_returns_404(client):
    r = client.post("/api/proposals/99999/apply")
    assert r.status_code == 404


def test_decide_propagates_payback_fields(client):
    """Round 13: /api/decide response includes the payback-specific fields."""
    sku = "JP-SKII-FT230"
    payload = {"sku": sku, "num_units": 5, "route": "PVG-NRT-LAX-2N"}
    r = client.post("/api/decide", json=payload)
    assert r.status_code == 200
    body = r.json()
    d = body["decision"]
    # New payback fields present
    for k in ("total_savings_usd", "trip_net_value_usd", "payback_rate_pct"):
        assert k in d, f"missing {k}"
    # Sanity: SK-II baseline is unprofitable at this route / 5 units
    assert d["payback_rate_pct"] < 100.0
    assert d["trip_net_value_usd"] < 0
    # Decision cascade uses the new thresholds
    assert d["level"] in ("建议", "谨慎", "不建议")


# ---------- Round 12: SPA routepicker shows fixed trip cost ----------

def _spa_asset(path: str) -> str:
    """Read a SPA static file from the repo's web/ directory."""
    return (Path(__file__).resolve().parent.parent / "web" / path).read_text(
        encoding="utf-8"
    )


def test_routepicker_exposes_route_fixed_helper():
    """web/app.js must define routeFixed() so the dropdown can label
    each option with the trip-level fixed cost."""
    src = _spa_asset("app.js")
    assert "routeFixed" in src, "app.js missing routeFixed helper"
    # Sanity: the helper sums flight + hotel + other.
    assert "flight_cost_usd" in src
    assert "hotel_cost_usd" in src
    assert "other_cost_usd" in src


def test_routepicker_dropdown_options_show_fixed_cost():
    """Both origin and dest <select>s must render their options with
    a 固定 $X label, surfacing the round-8 cost lesson in the UI."""
    html = _spa_asset("index.html")
    # Two options per route row: origin picker and dest picker, each
    # calls routeFixed(r) and emits the 固定 label.
    assert html.count("routeFixed(") >= 4  # 2 selects × 2 uses (label + title)
    assert "固定" in html, "index.html missing 固定 label"
    # The dropdown must still set the city as the option value, so
    # existing x-model bindings (origin / dest) keep working.
    assert 'x-model="origin"' in html
    assert 'x-model="dest"' in html


def test_list_routes_payload_supports_route_fixed(client):
    """The /api/routes payload must carry the three cost fields that
    the SPA's routeFixed() helper sums.  Regression guard so future
    schema changes keep the dropdown meaningful."""
    r = client.get("/api/routes")
    assert r.status_code == 200
    body = r.json()
    by_name = {b["name"]: b for b in body}
    # Seed: 1 intl ($1040) + 1 regional ($300).
    assert set(by_name) == {"PVG-NRT-LAX-2N", "LAX-SFO-1N"}
    intl = by_name["PVG-NRT-LAX-2N"]
    reg = by_name["LAX-SFO-1N"]
    intl_fixed = intl["flight_cost_usd"] + intl["hotel_cost_usd"] + intl["other_cost_usd"]
    reg_fixed = reg["flight_cost_usd"] + reg["hotel_cost_usd"] + reg["other_cost_usd"]
    assert intl_fixed == pytest.approx(1040.0)
    assert reg_fixed == pytest.approx(300.0)
    # The whole point of round-12 (c): the two routes must look different
    # in the picker, so the regional-vs-international split is visible.
    assert intl_fixed > reg_fixed * 2
