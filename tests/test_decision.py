"""Unit tests for the pure decision engine.

SPEC (Round 13: flipped from resale ROI to self-use trip payback):

Per-trip inputs:
  num_units                : int   >= 1
  purchase_price_usd       : float per unit (tax-exclusive price tag in Japan)
  home_price_usd           : float per unit (what you'd pay at home in China)
                             — the self-use baseline. None falls back to sell_price_usd.
  tariff_rate              : 0..1, applied to purchase_price_usd
  shipping_per_unit_usd    : float
  platform_fee_rate        : 0..1, unused under self-use but kept for API stability
  minutes_per_unit         : float, including queue, transit, listings
  flight_cost_usd          : float, round-trip
  hotel_cost_usd           : float, full stay
  other_trip_cost_usd      : float (transit, food, misc., default 0)
  hours_available          : float, user total time budget for the whole trip
  target_hourly_usd        : 0 (no longer used; default 0)
  max_units_per_trip       : int, per-SKU carry cap (default 50)
  target_roi_pct / min_roi_pct: legacy, unused but still validated

Outputs:
  level                    : "建议" | "谨慎" | "不建议"
  reason                   : str, one short sentence
  roi_pct                  : float, trip_net_value / trip_cost * 100 (legacy field)
  net_profit_usd           : float (alias for trip_net_value_usd)
  total_cost_usd           : float (trip_cost only — the threshold)
  total_revenue_usd        : float (alias for total_savings_usd)
  breakeven_sell_price_usd : float (breakeven home price in USD)
  hours_used               : float, (num_units * minutes_per_unit) / 60
  per_unit_cost_usd        : float, purchase + tariff + shipping
  per_unit_revenue_usd     : float, per_unit_savings_usd
  total_savings_usd        : float, per_unit_savings * num_units  (new)
  trip_net_value_usd       : float, total_savings - trip_cost    (new)
  payback_rate_pct         : float, total_savings / trip_cost * 100  (new)

Rules:
  trip_cost = flight_cost_usd + hotel_cost_usd + other_trip_cost_usd
  per_unit_cost_no_trip = purchase_price_usd + purchase_price_usd*tariff_rate + shipping
  per_unit_savings_usd = home_price_usd - per_unit_cost_no_trip
  total_savings = per_unit_savings * num_units
  trip_net_value = total_savings - trip_cost
  payback_rate_pct = (total_savings / trip_cost) * 100 if trip_cost > 0 else 0
  roi_pct (legacy) = (trip_net_value / trip_cost) * 100 if trip_cost > 0 else 0
  breakeven_sell_price_usd = per_unit_cost_no_trip + trip_cost/num_units

Level precedence (highest first):
  1. num_units > max_units_per_trip                       -> "不建议"
  2. payback_rate_pct < 50                                -> "不建议"
  3. payback_rate_pct < 100                               -> "谨慎"
  4. otherwise                                             -> "建议"
"""
from __future__ import annotations

import math
import pytest

from arb.decision import DecisionInputs, judge, DecideError


# ---------- helpers ----------

def base_inputs(**overrides):
    """Healthy baseline: 2x SK-II PITERA 230ml. Under self-use, China
    retail (≈$140) is barely above Japan ($85 + $4 shipping) so
    2 units don't clear a $1040 trip → '不建议' is the expected verdict."""
    d = dict(
        num_units=2,
        purchase_price_usd=85.0,
        sell_price_usd=140.0,        # legacy field, used as fallback when home_price_usd is None
        home_price_usd=140.0,        # self-use baseline
        tariff_rate=0.0,
        shipping_per_unit_usd=4.0,
        platform_fee_rate=0.13,      # unused for self-use, kept for compat
        minutes_per_unit=20.0,
        flight_cost_usd=720.0,
        hotel_cost_usd=240.0,
        other_trip_cost_usd=80.0,
        hours_available=32.0,
        target_hourly_usd=0.0,       # no opportunity cost
        target_roi_pct=15.0,         # legacy, unused
        min_roi_pct=10.0,            # legacy, unused
        success_rate=1.0,            # self-use = 1.0
        max_units_per_trip=50,
    )
    d.update(overrides)
    return DecisionInputs(**d)


# ---------- core happy path ----------

def test_healthy_baseline_returns_not_recommend_small_volume():
    """2 units of SK-II cannot clear $1040 trip cost → '不建议'."""
    out = judge(base_inputs())
    assert out.level == "不建议"
    assert out.trip_net_value_usd < 0
    assert out.payback_rate_pct < 100.0


def test_high_volume_units_pushes_to_recommend():
    """At num_units=40 (under the 50 cap), savings cover the trip by ~2x → 建议."""
    out = judge(base_inputs(num_units=40, max_units_per_trip=50))
    assert out.level == "建议"
    # payback_rate_pct should be high (savings >> trip cost at this volume)
    assert out.payback_rate_pct > 100.0


def test_recommend_when_payback_exceeds_100():
    """num_units=5 with a much higher home_price_usd → 建议."""
    out = judge(base_inputs(num_units=5, home_price_usd=500.0))
    assert out.level == "建议"
    assert out.payback_rate_pct >= 100.0
    assert out.trip_net_value_usd > 0


# ---------- level semantics ----------

def test_cautious_between_50_and_100_payback():
    """Choose inputs where savings land 50% < payback < 100%."""
    # per_unit_savings = home - purchase - shipping = 200 - 85 - 4 = 111
    # 8 units × 111 = 888. trip_cost = 1040. payback = 85.4%
    out = judge(base_inputs(num_units=8, home_price_usd=200.0))
    assert 50.0 <= out.payback_rate_pct < 100.0
    assert out.level == "谨慎"


def test_not_recommend_when_payback_below_50():
    """High trip cost, low home price → payback < 50%."""
    out = judge(base_inputs(
        num_units=2, home_price_usd=120.0,
        flight_cost_usd=2500.0, hotel_cost_usd=900.0,
    ))
    # per_unit_savings = 120-85-4 = 31. 2 units = 62. trip = 3480. payback ≈ 1.8%
    assert out.level == "不建议"
    assert out.payback_rate_pct < 50.0


def test_not_recommend_when_num_units_exceeds_carry_cap():
    out = judge(base_inputs(num_units=200, home_price_usd=500.0))
    # 200 > max_units_per_trip=50 → 不建议 regardless of payback
    assert out.level == "不建议"
    assert "携带上限" in out.reason


# ---------- breakeven + math ----------

def test_breakeven_makes_trip_net_value_zero():
    """At home_price = breakeven, trip_net_value_usd is exactly 0."""
    # Compute baseline, then ask for the same units at the breakeven home price.
    bi = base_inputs()
    base = judge(bi)
    edge = judge(base_inputs(num_units=bi.num_units, home_price_usd=base.breakeven_sell_price_usd))
    # home_price_usd = per_unit_cost + trip_cost/num_units → savings = trip_cost → net = 0
    assert math.isclose(edge.trip_net_value_usd, 0.0, abs_tol=1e-6)


def test_monotonic_savings_in_home_price():
    """trip_net_value_usd must increase monotonically as home_price rises."""
    base = judge(base_inputs())
    a = judge(base_inputs(home_price_usd=base.breakeven_sell_price_usd + 1.0)).trip_net_value_usd
    b = judge(base_inputs(home_price_usd=base.breakeven_sell_price_usd + 50.0)).trip_net_value_usd
    c = judge(base_inputs(home_price_usd=base.breakeven_sell_price_usd + 200.0)).trip_net_value_usd
    assert a < b < c


def test_total_cost_usd_equals_trip_cost_only():
    """Under payback model, total_cost_usd is the trip cost, not amortized."""
    n = 2
    out = judge(base_inputs(num_units=n))
    expected = 720.0 + 240.0 + 80.0
    assert math.isclose(out.total_cost_usd, expected, rel_tol=1e-9)


def test_total_savings_equals_units_times_per_unit_savings():
    out = judge(base_inputs(num_units=5, home_price_usd=200.0))
    per_unit_savings = 200.0 - 85.0 - 4.0
    assert math.isclose(out.total_savings_usd, 5 * per_unit_savings, rel_tol=1e-9)


def test_tariff_rate_reduces_savings():
    """Higher tariff → smaller per_unit_savings → lower payback."""
    no_tariff = judge(base_inputs(num_units=20, home_price_usd=200.0, tariff_rate=0.0))
    with_tariff = judge(base_inputs(num_units=20, home_price_usd=200.0, tariff_rate=0.20))
    assert with_tariff.total_savings_usd < no_tariff.total_savings_usd
    assert with_tariff.payback_rate_pct < no_tariff.payback_rate_pct


def test_shipping_per_unit_reduces_savings():
    no_ship = judge(base_inputs(num_units=10, home_price_usd=200.0, shipping_per_unit_usd=0.0))
    with_ship = judge(base_inputs(num_units=10, home_price_usd=200.0, shipping_per_unit_usd=8.0))
    assert with_ship.total_savings_usd < no_ship.total_savings_usd


# ---------- edge cases + validation ----------

def test_payback_extreme_high_still_recommend():
    """A single expensive unit that wipes the trip cost + nets profit → 建议."""
    out = judge(base_inputs(num_units=1, home_price_usd=5000.0, max_units_per_trip=10))
    assert out.level == "建议"
    assert out.payback_rate_pct > 100.0


def test_zero_trip_cost_yields_infinite_payback():
    out = judge(base_inputs(
        num_units=2, home_price_usd=200.0,
        flight_cost_usd=0, hotel_cost_usd=0, other_trip_cost_usd=0,
    ))
    # trip_cost is 0; savings > 0 → payback is inf
    assert math.isinf(out.payback_rate_pct)
    assert out.level == "建议"


def test_home_price_falls_back_to_sell_price_when_none():
    """Backward compat: home_price_usd=None uses sell_price_usd."""
    out = judge(base_inputs(home_price_usd=None, sell_price_usd=180.0))
    # Should treat home=180 same as if we'd set home_price_usd=180.0
    ref = judge(base_inputs(home_price_usd=180.0))
    assert math.isclose(out.total_savings_usd, ref.total_savings_usd, rel_tol=1e-9)
    assert math.isclose(out.payback_rate_pct, ref.payback_rate_pct, rel_tol=1e-9)


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
    with pytest.raises(DecideError):
        judge(base_inputs(success_rate=-0.1))
    with pytest.raises(DecideError):
        judge(base_inputs(success_rate=1.1))
    with pytest.raises(DecideError):
        judge(base_inputs(max_units_per_trip=0))


def test_zero_target_hourly_is_allowed():
    """target_hourly_usd=0 is the new default — must validate."""
    out = judge(base_inputs(target_hourly_usd=0.0))
    assert out.level in ("建议", "谨慎", "不建议")


def test_reason_is_short_string():
    out = judge(base_inputs())
    assert isinstance(out.reason, str)
    assert 5 <= len(out.reason) <= 200


def test_decision_reason_mentions_payback_when_recommend():
    out = judge(base_inputs(num_units=1, home_price_usd=5000.0, max_units_per_trip=10))
    assert out.level == "建议"
    assert "回本率" in out.reason or "净赚" in out.reason


def test_decision_reason_mentions_payback_when_not_recommend():
    out = judge(base_inputs())
    assert out.level == "不建议"
    assert "回本率" in out.reason or "不值得" in out.reason


def test_decision_serializes_to_dict():
    out = judge(base_inputs())
    d = out.as_dict()
    assert d["level"] in ("建议", "谨慎", "不建议")
    assert isinstance(d["roi_pct"], float)
    assert set(d.keys()) == {
        "level", "reason", "roi_pct", "net_profit_usd", "total_cost_usd",
        "total_revenue_usd", "breakeven_sell_price_usd", "hours_used",
        "per_unit_cost_usd", "per_unit_revenue_usd",
        "total_savings_usd", "trip_net_value_usd", "payback_rate_pct",
    }


def test_payback_rate_formula_holds():
    """payback_rate_pct == total_savings_usd / trip_cost_usd * 100."""
    out = judge(base_inputs(num_units=10, home_price_usd=250.0))
    expected = out.total_savings_usd / out.total_cost_usd * 100.0
    assert math.isclose(out.payback_rate_pct, expected, rel_tol=1e-9)


def test_trip_net_value_formula_holds():
    """trip_net_value_usd == total_savings - trip_cost."""
    out = judge(base_inputs(num_units=10, home_price_usd=250.0))
    expected = out.total_savings_usd - out.total_cost_usd
    assert math.isclose(out.trip_net_value_usd, expected, rel_tol=1e-9)
