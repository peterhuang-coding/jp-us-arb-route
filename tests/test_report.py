"""Tests for the shared Markdown / HTML / PDF report renderer."""
from __future__ import annotations

from arb import db, report


def _seed_minimal(conn):
    opp = dict(
        sku="RPT-001", name="Test Item", category="misc",
        source_market="JP", target_market="US",
        purchase_price_usd=10.0, tariff_rate=0.0,
        sell_price_usd=20.0, shipping_per_unit_usd=1.0,
        platform_fee_rate=0.13, minutes_per_unit=10.0,
        success_rate=0.7, purchase_source_url="https://example.com/jp",
        sell_source_url="https://example.com/us", notes="note",
        data_freshness_ts="2026-07-01", verified=0,
    )
    db.upsert_opportunity(conn, opp)
    rid = db.upsert_route(conn, dict(
        name="RPT-RT", origin_city="PVG", dest_city="LAX",
        flight_cost_usd=100.0, hotel_cost_usd=100.0, other_cost_usd=0.0,
        hours_available=32.0, target_hourly_usd=20.0,
        target_roi_pct=15.0, min_roi_pct=10.0,
        departure_date="2026-09-01", source_url="https://flights.example.com",
        notes="",
    ))
    db.add_route_legs(conn, rid, [
        dict(seq=1, kind="flight", label="PVG->NRT", cost_usd=50.0,
             duration_min=120.0, location="PVG", notes="outbound"),
        dict(seq=2, kind="flight", label="NRT->LAX", cost_usd=50.0,
             duration_min=300.0, location="NRT", notes=""),
        dict(seq=3, kind="hotel", label="LA hotel", cost_usd=100.0,
             duration_min=0.0, location="LAX", notes=""),
        dict(seq=4, kind="flight", label="LAX->NRT", cost_usd=50.0,
             duration_min=300.0, location="LAX", notes=""),
        dict(seq=5, kind="flight", label="NRT->PVG", cost_usd=50.0,
             duration_min=120.0, location="NRT", notes="home"),
    ])
    return opp["sku"], "RPT-RT"


def test_decide_for_returns_four_tuple():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 5, rname)
    assert opp["sku"] == sku
    assert route["name"] == rname
    assert decision.level in ("建议", "谨慎", "不建议")
    assert len(legs) == 5


def test_render_markdown_contains_required_sections():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 5, rname)
    md = report.render_markdown(opp, route, legs, 5, decision)
    for h in ("# 决策报告", "## 数据来源", "## 单件成本明细",
              "## 行程成本", "## 行程时间线", "## 综合决策",
              "## 风险与提示"):
        assert h in md, f"missing section: {h}"
    assert sku in md
    assert "https://example.com/jp" in md
    assert "https://flights.example.com" in md


def test_render_markdown_uses_freshness_and_verified_labels():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    md = report.render_markdown(opp, route, legs, 1, decision)
    assert "2026-07-01" in md
    assert "未验证" in md  # verified=0 in fixture


def test_render_markdown_surfaces_stale_warning(monkeypatch):
    """Seed ts in the past > STALE_DAYS → report must include stale warning."""
    import datetime as _dt
    monkeypatch.setattr("arb.freshness._dt.date", _dt.date)
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    # Override ts to 2026-01-01; force today to 2026-07-26 (age 206 d → stale)
    monkeypatch.setattr(
        "arb.freshness.classify",
        lambda ts, today=None, sku=None: type("V", (), {
            "as_dict": lambda self: {
                "sku": sku, "freshness_ts": ts, "today": "2026-07-26",
                "age_days": 206, "status": "stale",
                "badge": "⚠️ 陈旧待复核", "is_stale": True,
            }
        })(),
    )
    monkeypatch.setattr(
        "arb.freshness.humanize_age",
        lambda d: "206 天前",
    )
    md = report.render_markdown(opp, route, legs, 1, decision)
    assert "陈旧待复核" in md
    assert "206 天前" in md
    assert "arb refresh" in md


def test_render_html_contains_required_sections():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 5, rname)
    html = report.render_html(opp, route, legs, 5, decision)
    assert "<!DOCTYPE html>" in html
    assert "决策报告" in html
    for s in ("单件成本明细", "行程成本", "行程时间线",
              "综合决策", "数据来源", "warn-box"):
        assert s in html
    # All 5 legs rendered
    assert html.count('class="leg-kind ') == 5


def test_render_html_uses_leg_kind_classes():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 5, rname)
    html = report.render_html(opp, route, legs, 5, decision)
    assert 'class="leg-kind flight"' in html
    assert 'class="leg-kind hotel"' in html


def test_report_filename_includes_date_sku_dest():
    name = report.report_filename("JP-SKII-FT230", "洛杉矶 LAX", "md")
    assert name.startswith("jp-us-arb_")
    assert "JP-SKII-FT230" in name
    assert "洛杉矶_LAX" in name or "_LAX" in name
    assert name.endswith(".md")


def test_report_filename_sanitizes_path_separators():
    name = report.report_filename("JP/TEST", "Foo/Bar", "pdf")
    assert "/" not in name.replace("jp-us-arb_", "").rsplit(".", 1)[0].split("_", 2)[2]
    assert name.endswith(".pdf")


def test_render_pdf_writes_a_valid_pdf(tmp_path):
    """Real PDF render via playwright (slowest test in the suite)."""
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 3, rname)
    html_str = report.render_html(opp, route, legs, 3, decision)
    target = tmp_path / "out.pdf"
    report.render_pdf(html_str, target)
    assert target.exists()
    head = target.read_bytes()[:4]
    assert head == b"%PDF", f"expected PDF magic, got {head!r}"


def test_render_html_embeds_freshness_badge():
    """HTML report must include the freshness badge + age label."""
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    html_str = report.render_html(opp, route, legs, 1, decision)
    assert "freshness-badge" in html_str
    assert "data_freshness_ts" in html_str or "freshness-badge" in html_str
    # Seed ts is 2026-07-01; today's date will make it aging (25d) by default.
    assert "freshness-badge aging" in html_str or "freshness-badge stale" in html_str


def test_render_html_warns_when_stale(monkeypatch):
    """HTML report must show stale-box when freshness is stale."""
    monkeypatch.setattr(
        "arb.freshness.classify",
        lambda ts, today=None, sku=None: type("V", (), {
            "as_dict": lambda self: {
                "sku": sku, "freshness_ts": ts, "today": "2026-07-26",
                "age_days": 200, "status": "stale",
                "badge": "⚠️ 陈旧待复核", "is_stale": True,
            }
        })(),
    )
    monkeypatch.setattr(
        "arb.freshness.humanize_age",
        lambda d: "200 天前",
    )
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    html_str = report.render_html(opp, route, legs, 1, decision)
    assert "stale-box" in html_str
    assert "200 天前" in html_str
    assert "arb refresh" in html_str


def test_render_markdown_surfaces_pending_proposals(monkeypatch):
    """Markdown report embeds pending proposed_prices banner when staged."""
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp = db.get_opportunity(conn, sku)
    db.add_proposed_price(
        conn, opp["id"], "sell_price_usd",
        stored_value=145.0, proposed_value=200.0,
        detected_currency="USD", detected_raw="USD 200.00",
        source_url="https://example.com/us", drift_pct=37.93,
    )
    # Route the report helper's DB read through the test conn.
    pending = [dict(r) for r in db.list_proposed_prices(conn, status="pending")]
    monkeypatch.setattr(report, "_pending_proposals", lambda opp: pending)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    md = report.render_markdown(opp, route, legs, 1, decision)
    assert "待人工核对的提案" in md
    assert "arb proposals apply" in md
    assert "sell_price_usd" in md


def test_render_html_surfaces_pending_proposals(monkeypatch):
    """HTML report embeds propose-box when proposals are pending."""
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp = db.get_opportunity(conn, sku)
    db.add_proposed_price(
        conn, opp["id"], "purchase_price_usd",
        stored_value=85.0, proposed_value=95.0,
        detected_currency="USD", detected_raw="USD 95.00",
        source_url="https://example.com/jp", drift_pct=11.76,
    )
    pending = [dict(r) for r in db.list_proposed_prices(conn, status="pending")]
    monkeypatch.setattr(report, "_pending_proposals", lambda opp: pending)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    html_str = report.render_html(opp, route, legs, 1, decision)
    assert "propose-box" in html_str
    assert "purchase_price_usd" in html_str
    assert "arb proposals apply" in html_str


def test_report_uses_stored_success_rate_for_decision():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 5, rname)
    assert abs(decision.total_revenue_usd - (5 * 20.0 * 0.87 * 0.7)) < 1e-9
    assert decision.breakeven_sell_price_usd > 0
    assert decision.level == "不建议"


def test_report_surfaces_success_rate_in_markdown_and_html():
    conn = db.connect_memory()
    sku, rname = _seed_minimal(conn)
    opp, route, decision, legs = report.decide_for(conn, sku, 1, rname)
    assert "成功率: 70%" in report.render_markdown(opp, route, legs, 1, decision)
    assert "成功率" in report.render_html(opp, route, legs, 1, decision)
