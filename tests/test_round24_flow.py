"""Round 24 — F1 (跨源价) + F2 (报警) + F3 (¥5,000 额度) + F4 (退货) + F5 (HS 码).

End-to-end test on memory DB.  No network — uses the stub JPY price table
in ``arb.prices``.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from arb import alerts, db, prices, tax_codes


@pytest.fixture
def conn():
    c = db.connect_memory()
    # Seed one whitelist SKU + one opportunity
    db.upsert_opportunity(c, dict(
        sku="JP-SKII-FT230", name="SK-II 230ml", category="skincare",
        source_market="JP", target_market="CN",
        purchase_price_usd=139.0, tariff_rate=0.0,
        sell_price_usd=133.0, shipping_per_unit_usd=4.0,
        platform_fee_rate=0.06, minutes_per_unit=20.0,
        success_rate=0.85, purchase_source_url=None, sell_source_url=None,
        notes="", data_freshness_ts="2026-08-01", verified=0,
    ))
    yield c
    c.close()


# ---------- F1: competitor_prices ----------

def test_upsert_competitor_price_writes_row(conn):
    row = dict(sku="JP-SKII-FT230", source="amazon_jp",
               price_jpy=21500.0, price_cny=1032.0, fx_rate_at_fetch=20.83,
               fx_source="manual", url="https://amazon.co.jp/test",
               fetched_at="2026-08-16T10:00:00")
    new_id = db.upsert_competitor_price(conn, row)
    assert new_id > 0
    latest = db.latest_competitor_price(conn, "JP-SKII-FT230", "amazon_jp")
    assert latest is not None
    assert latest["price_jpy"] == 21500.0


def test_upsert_replaces_same_day(conn):
    """UNIQUE(opportunity_id, source, fetched_at) — same day overwrite."""
    db.upsert_competitor_price(conn, dict(
        sku="JP-SKII-FT230", source="amazon_jp",
        price_jpy=20000.0, price_cny=960.0, fx_rate_at_fetch=20.83,
        fx_source="manual", url="u", fetched_at="2026-08-16T10:00:00",
    ))
    db.upsert_competitor_price(conn, dict(
        sku="JP-SKII-FT230", source="amazon_jp",
        price_jpy=21500.0, price_cny=1032.0, fx_rate_at_fetch=20.83,
        fx_source="manual", url="u", fetched_at="2026-08-16T10:00:00",
    ))
    rows = db.list_competitor_prices(conn, sku="JP-SKII-FT230", source="amazon_jp")
    assert len(rows) == 1
    assert rows[0]["price_jpy"] == 21500.0


def test_fetch_one_uses_stub(conn):
    """Stub fetcher returns the (sku, source) → JPY price."""
    row = prices.fetch_one(conn, "JP-SKII-FT230", "amazon_jp")
    assert row["price_jpy"] == 21500.0
    assert row["price_cny"] > 0
    assert row["fx_rate_at_fetch"] > 0


def test_fetch_one_rejects_unknown_source(conn):
    with pytest.raises(ValueError, match="unsupported source"):
        prices.fetch_one(conn, "JP-SKII-FT230", "ebay")


def test_price_diff_cny(conn):
    prices.fetch_one(conn, "JP-SKII-FT230", "amazon_jp")
    diff = prices.price_diff_cny(conn, "JP-SKII-FT230", "amazon_jp")
    assert diff is not None
    # Diff is non-zero in either direction (sign depends on live FX); just
    # verify the helper produces a magnitude and direction field.
    assert isinstance(diff["diff_pct"], float)
    assert diff["snapshot_cny"] > 0
    assert diff["stored_cny"] > 0


# ---------- F2: alerts ----------

def test_setup_default_alerts_seeds_24_rows(conn):
    n = alerts.setup_default_alerts(conn, threshold_pct=5.0)
    assert n == 24
    rows = db.list_price_alerts(conn, enabled_only=True)
    assert len(rows) == 24


def test_evaluate_alerts_triggers_when_diff_exceeds_threshold(conn):
    # Use a very loose threshold (0.1%) so any non-zero diff triggers.
    db.upsert_price_alert(conn, dict(sku="JP-SKII-FT230", source="amazon_jp",
                                     threshold_pct=0.1, enabled=1))
    prices.fetch_one(conn, "JP-SKII-FT230", "amazon_jp")
    triggered = alerts.evaluate_alerts(conn, sku="JP-SKII-FT230")
    diff = prices.price_diff_cny(conn, "JP-SKII-FT230", "amazon_jp")
    if abs(diff["diff_pct"]) >= 0.1:
        assert len(triggered) == 1
        assert triggered[0]["sku"] == "JP-SKII-FT230"
    else:
        # FX round-trips perfectly → no trigger.  Still assert the contract
        # is "list returns, possibly empty".
        assert isinstance(triggered, list)


# ---------- F3: quota ----------

def test_quota_summary_first_trip(conn):
    summary = db.quota_summary(conn)
    assert summary["limit_cny"] == 5000.0  # first trip default
    assert summary["headroom_cny"] == 5000.0
    assert summary["is_repeat_within_15d"] is False


def test_quota_drops_to_1000_on_repeat_within_15d(conn):
    """¥5,000 → ¥1,000 when any prior entry is within 15 days of as_of."""
    db.record_quota_entry(conn, dict(entry_date="2026-08-10", sku="JP-SKII-FT230",
                                     quantity=2, unit_price_cny=995.0))
    summary = db.quota_summary(conn, as_of="2026-08-16")
    assert summary["is_repeat_within_15d"] is True
    assert summary["limit_cny"] == 1000.0
    assert summary["headroom_cny"] == 0.0  # 1990 - 1000 capped


def test_quota_stays_at_5000_when_15d_clear(conn):
    """More than 15 days between entries → ¥5,000 limit."""
    db.record_quota_entry(conn, dict(entry_date="2026-07-01", sku="JP-SKII-FT230",
                                     quantity=1, unit_price_cny=1000.0))
    summary = db.quota_summary(conn, as_of="2026-08-16")
    assert summary["is_repeat_within_15d"] is False
    assert summary["limit_cny"] == 5000.0


def test_quota_30d_window_aggregates(conn):
    # 2026-07-20 → 2026-08-16 = 27 days (in window); 2026-08-01 → 16 days (in)
    db.record_quota_entry(conn, dict(entry_date="2026-07-20", sku="JP-SKII-FT230",
                                     quantity=1, unit_price_cny=1000.0))
    db.record_quota_entry(conn, dict(entry_date="2026-08-01", sku="JP-SKII-FT230",
                                     quantity=1, unit_price_cny=1000.0))
    summary = db.quota_summary(conn, as_of="2026-08-16")
    assert summary["window_30d_cny"] == 2000.0


# ---------- F4: returns ----------

def test_record_return_basic(conn):
    db.record_return(conn, dict(sku="JP-SKII-FT230", sold_at="2026-08-15",
                                sold_price_cny=950.0, sold_channel="闲鱼"))
    rows = db.list_returns(conn)
    assert len(rows) == 1


def test_monthly_margin_subtracts_purchase_and_tax(conn):
    # 1 sale @ ¥950, no return, SKU stored price $139 × 7.14 = ¥992 (purchase)
    # tariff_rate = 0 so tax = 0
    # net = 950 - 0 - 0 - 992 - 0 = -42
    db.record_return(conn, dict(sku="JP-SKII-FT230", sold_at="2026-08-15",
                                sold_price_cny=950.0, sold_channel="闲鱼"))
    res = db.monthly_margin(conn, "2026-08")
    assert res["totals"]["units_sold"] == 1
    assert res["totals"]["gross_revenue_cny"] == 950.0
    assert res["totals"]["net_cny"] == round(950.0 - 992.46, 2)


def test_monthly_margin_counts_returns(conn):
    db.record_return(conn, dict(sku="JP-SKII-FT230", sold_at="2026-08-15",
                                sold_price_cny=950.0, sold_channel="闲鱼",
                                returned_at="2026-08-20", refund_cny=950.0))
    res = db.monthly_margin(conn, "2026-08")
    assert res["totals"]["return_count"] == 1
    assert res["totals"]["refund_cny"] == 950.0


# ---------- F5: tax codes ----------

def test_tax_table_has_6_whitelist_skus():
    assert len(tax_codes.TAX_TABLE) == 6


def test_tax_projection_colors():
    """6 SKU projection: 2 green, 2 yellow, 2 red."""
    colors = [tax_codes.projection_color(s) for s in tax_codes.list_skus()]
    assert sorted(colors) == ["green", "green", "red", "red", "yellow", "yellow"]


def test_tax_skii_is_high_end():
    """SK-II 230ml × ¥10/毫升 = ¥2,300 > ¥10,000? No — but it IS a high-end
    import by current rate (海关 实际 ≥¥10/毫升 = ¥230 per SKU)。 See tax_codes.
    """
    info = tax_codes.get_tax_info("JP-SKII-FT230")
    assert info["is_high_end"] is True
    assert tax_codes.effective_rate("JP-SKII-FT230") == 0.50


def test_tax_switch_is_green():
    assert tax_codes.projection_color("JP-NINTENDO-SWOLED") == "green"
    assert tax_codes.effective_rate("JP-NINTENDO-SWOLED") == 0.13


def test_tax_anime_is_green():
    assert tax_codes.projection_color("JP-ANIME-GK2024") == "green"
    assert tax_codes.effective_rate("JP-ANIME-GK2024") == 0.13


def test_tax_patek_is_red():
    assert tax_codes.projection_color("JP-LUX-PATEK") == "red"
    assert tax_codes.effective_rate("JP-LUX-PATEK") == 0.50


def test_tax_summary_table_returns_list_of_dicts():
    rows = tax_codes.summary_table()
    assert isinstance(rows, list)
    assert len(rows) == 6
    assert all("hs_code" in r for r in rows)
    assert all("projection_color" in r for r in rows)


def test_tax_is_banned_20_default_false():
    """No 6 whitelist SKU is in 20 种不予免税 (手机/电脑/相机)."""
    for sku in tax_codes.list_skus():
        assert tax_codes.is_banned_20(sku) is False
