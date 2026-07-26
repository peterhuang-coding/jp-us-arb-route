"""Unit tests for the pure decision engine.

SPEC (locked before implementation):

Per-trip inputs:
  num_units                : int   >= 1
  purchase_price_usd       : float per unit (tax-exclusive price tag in Japan)
  sell_price_usd           : float per unit (US-side target listing price)
  tariff_rate              : 0..1, applied to purchase_price_usd when crossing US CBP
                             under personal-use exemption this is 0 when total
                             purchase_value <= $800 per traveler per day.
  shipping_per_unit_usd    : float
  platform_fee_rate        : 0..1, applied to sell_price_usd (eBay/Amazon referral)
  minutes_per_unit         : float, including queue, transit, listings
  flight_cost_usd          : float, round-trip PEK/PVG/SHA -> NRT/HND -> LAX/SFO
  hotel_cost_usd           : float, full stay
  other_trip_cost_usd      : float (transit, food, misc., default 0)
  hours_available          : float, user total time budget for the whole trip
  target_hourly_usd        : float, user's opportunity cost of time
  target_roi_pct           : float, default 15.0
  min_roi_pct              : float, default 10.0

Outputs:
  level                    : "建议" | "谨慎" | "不建议"
  reason                   : str, one short sentence
  roi_pct                  : float, net_profit / total_cost * 100
  net_profit_usd           : float
  total_cost_usd           : float (purchase + tariff + shipping + trip + time)
  breakeven_sell_price_usd : float, sell_price making net_profit = 0
  hours_used               : float, (num_units * minutes_per_unit) / 60

Rules:
  trip_cost_usd = flight_cost_usd + hotel_cost_usd + other_trip_cost_usd
  per_unit_cost_no_trip = purchase_price_usd + purchase_price_usd*tariff_rate + shipping
  per_unit_time_cost_usd = (minutes_per_unit / 60) * target_hourly_usd
  per_unit_revenue_usd = sell_price_usd * (1 - platform_fee_rate)
  total_revenue_usd = per_unit_revenue_usd * num_units
  total_cost_usd = per_unit_cost_no_trip * num_units + trip_cost + per_unit_time_cost_usd * num_units
  net_profit_usd = total_revenue_usd - total_cost_usd
  roi_pct = (net_profit_usd / total_cost_usd) * 100 if total_cost_usd > 0 else 0
  breakeven_sell_price_usd = (per_unit_cost_no_trip + per_unit_time_cost_usd + trip_cost/num_units) / (1 - platform_fee_rate)

Level precedence (highest first):
  1. hours_used > hours_available OR net_profit_usd <= 0  -> "不建议"
  2. roi_pct <  min_roi_pct                                -> "不建议"
  3. roi_pct <  target_roi_pct                             -> "谨慎"
  4. otherwise                                             -> "建议"
"""
from __future__ import annotations

import math
import pytest

from arb.decision import DecisionInputs, judge, DecideError


# ---------- helpers ----------

def base_inputs(**overrides):
    """Healthy baseline: 2x SK-II PITERA 230ml, classic happy path."""
    d = dict(
        num_units=2,
        purchase_price_usd=85.0,
        sell_price_usd=140.0,
        tariff_rate=0.0,
        shipping_per_unit_usd=4.0,
        platform_fee_rate=0.13,
        minutes_per_unit=20.0,
        flight_cost_usd=720.0,
        hotel_cost_usd=240.0,
        other_trip_cost_usd=80.0,
        hours_available=32.0,
        target_hourly_usd=20.0,
        target_roi_pct=15.0,
        min_roi_pct=10.0,
    )
    d.update(overrides)
    return DecisionInputs(**d)


def per_unit_time_cost(minutes: float, hourly: float) -> float:
    return (minutes / 60.0) * hourly


# ---------- core happy path ----------

def test_healthy_baseline_returns_recommend_etc():
    """Two units of SK-II cannot clear $1040 trip cost — must be '不建议'."""
    out = judge(base_inputs())
    assert out.level == "不建议"
    assert out.net_profit_usd < 0


def test_high_volume_units_pushes_to_cautious():
    """At num_units=80, ROI lands between 10% and 15% -> '谨慎'."""
    out = judge(base_inputs(num_units=80))
    assert out.level == "谨慎"
    assert 10.0 <= out.roi_pct < 15.0


def test_recommend_above_target_roi():
    """At num_units=110 with hours_available=40, ROI > 15% and time fits -> '建议'."""
    out = judge(base_inputs(num_units=110, hours_available=40.0))
    assert out.level == "建议"
    assert out.roi_pct >= 15.0


# ---------- level semantics ----------

def test_cautious_between_min_and_target_roi():
    out = judge(base_inputs(num_units=85))
    assert min(10.0, 15.0) <= out.roi_pct <= 15.0
    assert out.level == "谨慎"


def test_not_recommend_when_roi_below_min_threshold():
    out = judge(base_inputs(num_units=20, flight_cost_usd=2500, hotel_cost_usd=900))
    assert out.level == "不建议"
    assert out.roi_pct < 10.0


def test_not_recommend_when_net_profit_negative():
    out = judge(base_inputs(num_units=1))
    assert out.net_profit_usd < 0
    assert out.level == "不建议"


def test_not_recommend_when_hours_exceed_budget():
    out = judge(base_inputs(num_units=60, minutes_per_unit=60.0))
    assert out.hours_used > 32.0
    assert out.level == "不建议"


# ---------- breakeven + math ----------

def test_breakeven_makes_profit_zero():
    out = judge(base_inputs(num_units=2))
    per_unit_cost_no_trip = 85.0 + 0.0 + 4.0
    per_unit_time = per_unit_time_cost(20.0, 20.0)
    trip_per_unit = (720.0 + 240.0 + 80.0) / 2.0
    expected_be = (per_unit_cost_no_trip + per_unit_time + trip_per_unit) / (1 - 0.13)
    assert math.isclose(out.breakeven_sell_price_usd, expected_be, rel_tol=1e-9)


def test_breakeven_inverse_property():
    """At sell_price = breakeven, net_profit is exactly 0 (definition)."""
    base = judge(base_inputs())
    edge = judge(base_inputs(num_units=base_inputs().num_units,
                             sell_price_usd=base.breakeven_sell_price_usd))
    assert math.isclose(edge.net_profit_usd, 0.0, abs_tol=1e-6)


def test_monotonic_profit_in_sell_price():
    """Profit must increase monotonically as sell_price rises above breakeven."""
    base = judge(base_inputs())
    be = base.breakeven_sell_price_usd
    a = judge(base_inputs(sell_price_usd=be + 1.0)).net_profit_usd
    b = judge(base_inputs(sell_price_usd=be + 50.0)).net_profit_usd
    c = judge(base_inputs(sell_price_usd=be + 200.0)).net_profit_usd
    assert a < b < c


def test_total_cost_includes_trip_and_time():
    n = 2
    out = judge(base_inputs(num_units=n))
    per_unit_cost_no_trip = 85.0 + 0.0 + 4.0
    per_unit_time = per_unit_time_cost(20.0, 20.0)
    expected = (
        n * per_unit_cost_no_trip
        + 720.0 + 240.0 + 80.0
        + n * per_unit_time
    )
    assert math.isclose(out.total_cost_usd, expected, rel_tol=1e-9)


def test_zero_platform_fee_simplifies_revenue():
    out = judge(base_inputs(platform_fee_rate=0.0, num_units=20))
    assert math.isclose(out.total_revenue_usd, 20 * 140.0, rel_tol=1e-9)
    assert out.net_profit_usd < 0


def test_tariff_rate_applied_to_purchase_price():
    out = judge(base_inputs(num_units=50, tariff_rate=0.10, sell_price_usd=200.0))
    assert out.level == "建议"
    per_unit_cost_no_trip = 85.0 + 85.0 * 0.10 + 4.0
    per_unit_time = per_unit_time_cost(20.0, 20.0)
    expected_total_cost = 50 * per_unit_cost_no_trip + 1040.0 + 50 * per_unit_time
    assert math.isclose(out.total_cost_usd, expected_total_cost, rel_tol=1e-9)


# ---------- edge cases + validation ----------

def test_roi_extreme_high_still_recommend():
    """Need hours_used < hours_available AND ROI > target."""
    out = judge(base_inputs(num_units=200, sell_price_usd=500.0, hours_available=200.0))
    assert out.level == "建议"
    assert out.roi_pct > 100.0


def test_zero_trip_cost_is_valid():
    out = judge(base_inputs(num_units=2, flight_cost_usd=0, hotel_cost_usd=0, other_trip_cost_usd=0))
    per_unit_cost_no_trip = 85.0 + 0.0 + 4.0
    per_unit_time = per_unit_time_cost(20.0, 20.0)
    expected = 2 * per_unit_cost_no_trip + 2 * per_unit_time
    assert math.isclose(out.total_cost_usd, expected, rel_tol=1e-9)


def test_invalid_inputs_rejected():
    with pytest.raises(DecideError):
        judge(base_inputs(num_units=0))
    with pytest.raises(DecideError):
        judge(base_inputs(num_units=-1))
    with pytest.raises(DecideError):
        judge(base_inputs(platform_fee_rate=1.0))
    with pytest.raises(DecideError):
        judge(base_inputs(platform_fee_rate=1.5))
    with pytest.raises(DecideError):
        judge(base_inputs(target_roi_pct=5.0, min_roi_pct=10.0))
    with pytest.raises(DecideError):
        judge(base_inputs(purchase_price_usd=-1.0))


def test_min_roi_zero_is_allowed():
    out = judge(base_inputs(num_units=2, min_roi_pct=0.0))
    assert out.level in ("建议", "谨慎", "不建议")


def test_reason_is_short_string():
    out = judge(base_inputs())
    assert isinstance(out.reason, str)
    assert 5 <= len(out.reason) <= 200


def test_hand_calc_invariance_for_assets():
    out = judge(base_inputs(num_units=10, sell_price_usd=200.0))
    assert out.net_profit_usd < 0
    assert out.level == "不建议"


def test_total_revenue_equals_units_times_post_fee_price():
    out = judge(base_inputs(num_units=5, sell_price_usd=100.0, platform_fee_rate=0.20))
    assert math.isclose(out.total_revenue_usd, 5 * 100.0 * 0.80, rel_tol=1e-9)


def test_decision_reason_mentions_key_driver_when_negative():
    out = judge(base_inputs(num_units=1))
    assert out.reason
    # Reason mentions one of the cost/time drivers
    assert any(k in out.reason for k in ("成本", "时间", "ROI", "利润", "机票", "酒店"))


def test_decision_reason_mentions_roi_when_recommend():
    out = judge(base_inputs(num_units=200, sell_price_usd=500.0, hours_available=200.0))
    assert out.level == "建议"
    assert "ROI" in out.reason or "利润" in out.reason


def test_decision_serializes_to_dict():
    out = judge(base_inputs())
    d = out.as_dict()
    assert d["level"] in ("建议", "谨慎", "不建议")
    assert isinstance(d["roi_pct"], float)
    assert set(d.keys()) == {
        "level", "reason", "roi_pct", "net_profit_usd", "total_cost_usd",
        "total_revenue_usd", "breakeven_sell_price_usd", "hours_used",
        "per_unit_cost_usd", "per_unit_revenue_usd",
    }
