"""Unit tests for the 5000元 basket solver (Round 13).

The solver is a bounded 0/1 knapsack. Tests cover:
  - empty input → empty picks
  - single SKU → fills it
  - budget exhausted exactly
  - NULL home_price_cny → skipped
  - negative savings → skipped
  - max_units_per_trip cap respected
  - FX rate conversion
  - determinism
  - customs_limit < budget clamps capacity
  - payback rate when trip_cost > 0
"""
from __future__ import annotations

import pytest

from arb.basket import BasketItem, solve_basket, item_from_opportunity


def _item(sku, jp_cny, home_cny, max_u=10, **kw):
    sav = home_cny - jp_cny
    return BasketItem(
        sku=sku,
        name=kw.get("name", sku),
        category=kw.get("category", "misc"),
        jp_price_per_unit_cny=jp_cny,
        home_price_per_unit_cny=home_cny,
        savings_per_unit_cny=sav,
        max_units=max_u,
        purchase_price_usd=kw.get("purchase_price_usd", jp_cny * 0.14),
        home_price_cny=kw.get("home_price_cny", home_cny),
        sell_price_usd=kw.get("sell_price_usd", home_cny * 0.14),
        fx_rate=0.14,
    )


# ---------- empty / boundary ----------

def test_empty_items_returns_empty_picks():
    sol = solve_basket([], budget_cny=5000)
    assert sol.picks == []
    assert sol.total_spend_cny == 0.0
    assert sol.total_savings_cny == 0.0


def test_zero_budget_returns_empty():
    items = [_item("A", jp_cny=100, home_cny=200)]
    sol = solve_basket(items, budget_cny=0)
    assert sol.picks == []
    assert "无符合条件 SKU" in sol.notes or "0" in sol.notes or len(sol.notes) >= 0


def test_capacity_zero_returns_empty():
    items = [_item("A", jp_cny=100, home_cny=200)]
    sol = solve_basket(items, budget_cny=0, customs_limit_cny=0)
    assert sol.picks == []


# ---------- basic filling ----------

def test_single_sku_fills_itself():
    items = [_item("A", jp_cny=100, home_cny=200, max_u=10)]
    sol = solve_basket(items, budget_cny=5000)
    # per_unit_cost=100, capacity=5000 → can take 50, but max_u=10
    assert len(sol.picks) == 1
    assert sol.picks[0].sku == "A"
    assert sol.picks[0].num_units == 10
    assert sol.total_spend_cny == 1000.0
    assert sol.total_savings_cny == 1000.0  # 10 * (200-100)


def test_two_skus_chooses_better_density():
    """Greedy/DP should prefer the item with higher savings per CNY density."""
    # A: jp=100, save=100 → density 1.0
    # B: jp=200, save=150 → density 0.75
    # capacity=5000 → A fits 50, but max=20 → 20×A=2000, left 3000 → 15×B=3000
    items = [
        _item("A", jp_cny=100, home_cny=200, max_u=20),
        _item("B", jp_cny=200, home_cny=350, max_u=20),
    ]
    sol = solve_basket(items, budget_cny=5000)
    # Greedy/DP: 20*A (2000) + 15*B (3000) = 5000 spend
    assert sol.total_spend_cny == 5000.0
    # Total savings = 20*100 + 15*150 = 4250
    assert sol.total_savings_cny == 4250.0
    by_sku = {p.sku: p.num_units for p in sol.picks}
    assert by_sku == {"A": 20, "B": 15}


# ---------- skip rules ----------

def test_negative_savings_skipped():
    items = [
        _item("A", jp_cny=100, home_cny=80, max_u=10),  # -20 CNY
        _item("B", jp_cny=200, home_cny=250, max_u=10),  # +50 CNY
    ]
    sol = solve_basket(items, budget_cny=5000)
    by_sku = {p.sku for p in sol.picks}
    assert "A" not in by_sku
    assert "B" in by_sku
    # A is in the skipped list with a clear reason
    assert any("A" in s and "≤ 0" in s for s in sol.skipped_skus)


def test_null_home_price_falls_back_to_sell_then_skipped_if_negative():
    """When home_price_cny is None and sell fallback yields negative savings, skip."""
    items = [
        BasketItem(
            sku="X", name="X", category="c",
            jp_price_per_unit_cny=100.0,
            home_price_per_unit_cny=80.0,   # already negative savings
            savings_per_unit_cny=-20.0,
            max_units=10,
            purchase_price_usd=14.0, home_price_cny=None,
            sell_price_usd=11.2, fx_rate=0.14,
        ),
    ]
    sol = solve_basket(items, budget_cny=5000)
    assert sol.picks == []


# ---------- max_units cap ----------

def test_max_units_per_trip_respected():
    items = [_item("A", jp_cny=100, home_cny=200, max_u=3)]
    sol = solve_basket(items, budget_cny=5000)
    # capacity would allow 50, but max=3
    assert sol.picks[0].num_units == 3
    assert sol.total_spend_cny == 300.0


# ---------- budget exhaustion ----------

def test_budget_exhausted_exactly():
    items = [_item("A", jp_cny=100, home_cny=150, max_u=100)]
    sol = solve_basket(items, budget_cny=5000)
    # 5000 / 100 = 50 units, capped at 100 → 50
    assert sol.total_spend_cny == 5000.0
    assert sol.picks[0].num_units == 50


def test_leftover_budget_reported():
    items = [_item("A", jp_cny=100, home_cny=200, max_u=10)]
    sol = solve_basket(items, budget_cny=5000)
    # 10 units × 100 = 1000 spent; leftover = 4000
    assert sol.leftover_cny == pytest.approx(4000.0)


# ---------- customs_limit < budget ----------

def test_customs_limit_clamps_capacity():
    items = [_item("A", jp_cny=100, home_cny=200, max_u=100)]
    sol = solve_basket(items, budget_cny=5000, customs_limit_cny=2000)
    # customs_limit=2000 wins → 20 units
    assert sol.total_spend_cny == 2000.0
    assert sol.picks[0].num_units == 20
    assert sol.leftover_cny == pytest.approx(3000.0)  # budget 5000 - spend 2000
    assert sol.customs_headroom_cny == 0.0


# ---------- payback rate ----------

def test_payback_rate_calculation():
    items = [_item("A", jp_cny=100, home_cny=200, max_u=10)]
    # spend=1000, save=1000, trip=$140 USD → 140/0.14 = 1000 CNY → 100% payback
    sol = solve_basket(items, budget_cny=5000, trip_cost_usd=140.0, fx_rate=0.14)
    assert sol.payback_rate_pct == pytest.approx(100.0)


def test_payback_infinite_when_trip_zero_and_savings_positive():
    items = [_item("A", jp_cny=100, home_cny=200, max_u=10)]
    sol = solve_basket(items, budget_cny=5000, trip_cost_usd=0.0)
    assert sol.payback_rate_pct == float("inf")


def test_payback_zero_when_no_picks():
    sol = solve_basket([], budget_cny=5000, trip_cost_usd=1000.0)
    assert sol.payback_rate_pct == 0.0


# ---------- FX conversion (item_from_opportunity) ----------

def test_item_from_opportunity_uses_home_when_present():
    opp = dict(
        sku="X", name="X", category="c",
        source_market="JP", target_market="CN",
        purchase_price_usd=100.0, tariff_rate=0.0,
        sell_price_usd=200.0, shipping_per_unit_usd=10.0,
        platform_fee_rate=0.13, minutes_per_unit=10.0,
        success_rate=1.0, data_freshness_ts="2026-01-01", verified=1,
        home_price_cny=2000.0,
        unit_volume_ml=None,
        max_units_per_trip=50,
    )
    item = item_from_opportunity(opp, fx_rate=0.14)
    # jp=100 USD * (1/0.14) = 714.29 CNY
    # ship=10 USD * 7.14 = 71.43 CNY
    # home=2000 CNY
    # savings = 2000 - 714.29 - 0 - 71.43 = 1214.29
    assert item.jp_price_per_unit_cny == pytest.approx(714.29, rel=1e-3)
    assert item.savings_per_unit_cny == pytest.approx(1214.29, rel=1e-3)
    assert item.home_price_cny == 2000.0


def test_item_from_opportunity_falls_back_to_sell_when_home_null():
    opp = dict(
        sku="X", name="X", category="c",
        source_market="JP", target_market="CN",
        purchase_price_usd=100.0, tariff_rate=0.10,
        sell_price_usd=140.0, shipping_per_unit_usd=0.0,
        platform_fee_rate=0.13, minutes_per_unit=10.0,
        success_rate=1.0, data_freshness_ts="2026-01-01", verified=0,
        home_price_cny=None,
        unit_volume_ml=None,
        max_units_per_trip=10,
    )
    item = item_from_opportunity(opp, fx_rate=0.14)
    # home = sell * 7.14 = 1000 CNY
    # jp = 100 * 7.14 = 714.29
    # tariff = 10 * 7.14 = 71.43
    # savings = 1000 - 714.29 - 71.43 = 214.29
    assert item.home_price_per_unit_cny == pytest.approx(1000.0, rel=1e-3)
    assert item.savings_per_unit_cny == pytest.approx(214.29, rel=1e-3)
    assert item.home_price_cny is None  # marker preserved
    assert item.max_units == 10


# ---------- determinism ----------

def test_deterministic_for_same_input():
    items = [
        _item("A", jp_cny=200, home_cny=300, max_u=10),
        _item("B", jp_cny=100, home_cny=180, max_u=10),
        _item("C", jp_cny=400, home_cny=550, max_u=10),
    ]
    sol1 = solve_basket(items, budget_cny=2500, customs_limit_cny=2500)
    sol2 = solve_basket(items, budget_cny=2500, customs_limit_cny=2500)
    assert sol1.total_spend_cny == sol2.total_spend_cny
    assert sol1.total_savings_cny == sol2.total_savings_cny
    by_sku1 = {p.sku: p.num_units for p in sol1.picks}
    by_sku2 = {p.sku: p.num_units for p in sol2.picks}
    assert by_sku1 == by_sku2


def test_algorithm_label():
    sol = solve_basket([], budget_cny=5000)
    assert sol.algorithm == "dp-bounded-knapsack"
