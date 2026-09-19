"""Regression tests for safe numeric basket inputs and opportunity conversion."""
from __future__ import annotations

import math

import pytest

from arb.basket import BasketItem, item_from_opportunity, solve_basket


def _item(sku, cost=1.0, saving=1.0, max_units=1, *, home=None):
    if home is None:
        home = cost + saving
    return BasketItem(
        sku=sku,
        name=sku,
        category="misc",
        jp_price_per_unit_cny=cost,
        home_price_per_unit_cny=home,
        savings_per_unit_cny=saving,
        max_units=max_units,
        purchase_price_usd=0.0,
        home_price_cny=home,
        sell_price_usd=0.0,
        fx_rate=0.14,
    )


def _opp(max_units=None, **overrides):
    row = {
        "sku": "OPP",
        "name": "Opp",
        "category": "misc",
        "purchase_price_usd": 1.0,
        "sell_price_usd": 3.0,
        "home_price_cny": 10.0,
        "tariff_rate": 0.0,
        "shipping_per_unit_usd": 0.0,
    }
    row.update(overrides)
    if max_units is not None:
        row["max_units_per_trip"] = max_units
    return row


@pytest.mark.parametrize("kwargs", [
    {"budget_cny": True},
    {"budget_cny": math.nan},
    {"budget_cny": math.inf},
    {"budget_cny": -math.inf},
    {"customs_limit_cny": False},
    {"customs_limit_cny": math.nan},
    {"customs_limit_cny": math.inf},
    {"customs_limit_cny": -math.inf},
    {"trip_cost_usd": True},
    {"trip_cost_usd": math.nan},
    {"trip_cost_usd": math.inf},
    {"trip_cost_usd": -math.inf},
    {"fx_rate": False},
    {"fx_rate": math.nan},
    {"fx_rate": math.inf},
    {"fx_rate": -math.inf},
])
def test_controls_require_finite_nonboolean_numbers_even_without_items(kwargs):
    with pytest.raises(ValueError, match="finite number|positive|non-negative"):
        solve_basket([], **{"budget_cny": 10.0, "customs_limit_cny": 10.0, **kwargs})


def test_control_range_contracts_and_nonpositive_capacity_is_empty():
    with pytest.raises(ValueError, match="fx_rate must be positive"):
        solve_basket([], fx_rate=0.0)
    with pytest.raises(ValueError, match="fx_rate must be positive"):
        solve_basket([], fx_rate=-0.14)
    with pytest.raises(ValueError, match="trip_cost_usd must be non-negative"):
        solve_basket([], trip_cost_usd=-1.0)

    sol = solve_basket([_item("ignored", max_units=1)], budget_cny=0.0, customs_limit_cny=10.0)
    assert sol.picks == []
    assert sol.total_spend_cny == 0.0
    assert sol.total_savings_cny == 0.0
    assert sol.skipped_skus == []
    assert solve_basket([_item("ignored")], budget_cny=-1.0).picks == []


@pytest.mark.parametrize("field,value", [
    ("jp_price_per_unit_cny", math.nan),
    ("jp_price_per_unit_cny", math.inf),
    ("jp_price_per_unit_cny", -math.inf),
    ("home_price_per_unit_cny", math.nan),
    ("home_price_per_unit_cny", math.inf),
    ("home_price_per_unit_cny", -math.inf),
    ("savings_per_unit_cny", math.nan),
    ("savings_per_unit_cny", math.inf),
    ("savings_per_unit_cny", -math.inf),
])
def test_bad_numeric_item_is_skipped_but_valid_neighbor_selected(field, value):
    bad = _item("badSKU")
    object.__setattr__(bad, field, value)
    good = _item("goodSKU", cost=2.0, saving=3.0)
    sol = solve_basket([bad, good], budget_cny=5.0, customs_limit_cny=5.0)
    assert [p.sku for p in sol.picks] == ["goodSKU"]
    assert sol.picks[0].num_units == 1
    assert any("badSKU" in s for s in sol.skipped_skus)


@pytest.mark.parametrize("units", [True, 1.5])
def test_boolean_or_fractional_item_quantity_is_never_truncated_or_accepted(units):
    bad = _item("badSKU", max_units=1)
    object.__setattr__(bad, "max_units", units)
    good = _item("goodSKU", cost=2.0, saving=3.0)
    sol = solve_basket([bad, good], budget_cny=5.0, customs_limit_cny=5.0)
    assert [p.sku for p in sol.picks] == ["goodSKU"]
    assert any("badSKU" in s for s in sol.skipped_skus)
    assert not any(p.sku == "badSKU" for p in sol.picks)


def test_solver_keeps_zero_quantity_sku_skipped():
    zero = _item("zeroSKU", max_units=0)
    good = _item("goodSKU", cost=1.0, saving=2.0)
    sol = solve_basket([zero, good], budget_cny=2.0, customs_limit_cny=2.0)
    assert [p.sku for p in sol.picks] == ["goodSKU"]
    assert any("zeroSKU" in s for s in sol.skipped_skus)


def test_item_converter_missing_or_none_quantity_defaults_to_50():
    missing = item_from_opportunity(_opp())
    explicit_none = item_from_opportunity({**_opp(), "max_units_per_trip": None})
    assert missing.max_units == 50
    assert explicit_none.max_units == 50


def test_item_converter_preserves_positive_integer_quantity():
    assert item_from_opportunity(_opp(2)).max_units == 2


def test_item_converter_preserves_explicit_zero_quantity():
    # Regression: `0 or 50` incorrectly converts an explicit zero to 50.
    assert item_from_opportunity(_opp(0)).max_units == 0


@pytest.mark.parametrize("quantity", [1.5, True])
def test_item_converter_does_not_truncate_or_accept_fractional_quantity(quantity):
    try:
        item = item_from_opportunity(_opp(quantity))
    except (ValueError, TypeError):
        return
    sol = solve_basket([item], budget_cny=100.0, customs_limit_cny=100.0)
    assert sol.picks == []
    assert any("OPP" in reason for reason in sol.skipped_skus)


def test_explicit_resource_bound_failure_has_no_partial_or_approximate_result():
    items = [_item(f"p{i:02d}", cost=float(2 ** i), saving=float(2 ** i), max_units=1)
             for i in range(16)]
    with pytest.raises(ValueError, match="state/transition bounds"):
        solve_basket(items, budget_cny=65535.0, customs_limit_cny=65535.0)


def test_overflowing_selected_monetary_total_is_rejected():
    overflow = _item("hugeSKU", cost=1.0, saving=1e308, max_units=2)
    with pytest.raises(ValueError, match="non-finite monetary total"):
        solve_basket([overflow], budget_cny=10.0, customs_limit_cny=10.0)


def test_zero_trip_cost_positive_savings_has_infinite_payback():
    sol = solve_basket([_item("goodSKU", cost=1.0, saving=1.0)],
                       budget_cny=2.0, customs_limit_cny=2.0, trip_cost_usd=0.0)
    assert sol.total_savings_cny == 1.0
    assert math.isinf(sol.payback_rate_pct)
    assert sol.payback_rate_pct > 0.0
