"""Regression tests for exact bounded-knapsack basket optimization."""
from __future__ import annotations

from decimal import Decimal
from itertools import product
from random import Random

import pytest

from arb.basket import BasketItem, solve_basket


def _item(sku: str, cost: Decimal, saving: Decimal, max_units: int) -> BasketItem:
    cost_f = float(cost)
    saving_f = float(saving)
    return BasketItem(
        sku=sku,
        name=sku,
        category="misc",
        jp_price_per_unit_cny=cost_f,
        home_price_per_unit_cny=cost_f + saving_f,
        savings_per_unit_cny=saving_f,
        max_units=max_units,
        purchase_price_usd=0.0,
        home_price_cny=cost_f + saving_f,
        sell_price_usd=0.0,
        fx_rate=0.14,
    )


def _quantities(solution, skus):
    chosen = {pick.sku: pick.num_units for pick in solution.picks}
    return [chosen.get(sku, 0) for sku in skus]


def _oracle(items, cap):
    bounds = [item.max_units for item in items]
    best_value = Decimal("0")
    best_quantities = [0] * len(items)

    for quantities in product(*(range(bound + 1) for bound in bounds)):
        spend = sum(
            Decimal(str(item.jp_price_per_unit_cny)) * qty
            for item, qty in zip(items, quantities)
        )
        if spend > cap:
            continue
        value = sum(
            Decimal(str(item.savings_per_unit_cny)) * qty
            for item, qty in zip(items, quantities)
        )
        if value > best_value:
            best_value = value
            best_quantities = list(quantities)

    return best_quantities, best_value


def _assert_optimal(solution, items, cap_text):
    cap = Decimal(cap_text)
    skus = [item.sku for item in items]
    quantities = _quantities(solution, skus)

    assert len(quantities) == len(items)
    assert all(isinstance(qty, int) for qty in quantities)
    assert all(0 <= qty <= item.max_units for qty, item in zip(quantities, items))

    spend = sum(
        Decimal(str(item.jp_price_per_unit_cny)) * qty
        for item, qty in zip(items, quantities)
    )
    savings = sum(
        Decimal(str(item.savings_per_unit_cny)) * qty
        for item, qty in zip(items, quantities)
    )

    assert spend <= cap
    assert solution.total_spend_cny == pytest.approx(float(spend))
    assert solution.total_savings_cny == pytest.approx(float(savings))

    _, expected_savings = _oracle(items, cap)
    assert savings == expected_savings



@pytest.mark.parametrize(
    ("cost_text", "max_units", "cap_text", "expected_units", "saving_text"),
    [
        ("1.49", 3, "2.00", 1, "1"),
        ("1.51", 2, "3.02", 2, "1"),
        ("0.34", 2, "0.68", 2, "1"),
        ("0.0049", 3, "0.01", 2, "1"),
        ("1.00", 1, "1.00", 1, "0.1"),
    ],
)
def test_sub_yuan_rounding_counterexamples(cost_text, max_units, cap_text, expected_units, saving_text):
    items = [_item("ONLY", Decimal(cost_text), Decimal(saving_text), max_units)]
    solution = solve_basket(
        items,
        budget_cny=float(cap_text),
        customs_limit_cny=float(cap_text),
    )
    quantities = _quantities(solution, ["ONLY"])
    assert quantities == [expected_units]
    _assert_optimal(solution, items, cap_text)


def test_16_seeded_small_decimal_cases_match_independent_oracle():
    rng = Random(20260308)
    case_id = 0

    for n in range(1, 5):
        for max_units in range(4):
            case_id += 1
            skus = [f"S{index}" for index in range(n)]
            items = []

            for sku in skus:
                # Mix whole-cent and tenth-cent prices so ordinary rounding is exercised.
                if rng.random() < 0.55:
                    cost = Decimal(rng.randint(1, 399)) / Decimal(100)
                else:
                    cost = Decimal(rng.randint(1, 3999)) / Decimal(1000)

                # Positive savings of either 0.1 or 1 CNY; all items remain eligible.
                saving = Decimal("0.1") if rng.random() < 0.3 else Decimal("1")
                items.append(_item(sku, cost, saving, max_units))

            max_total_cost = sum(
                cost * item.max_units
                for item, cost in zip(
                    items,
                    [Decimal(str(item.jp_price_per_unit_cny)) for item in items],
                )
            )
            # Include zero, tight sub-yuan caps, and caps near/above full cost.
            cap = (max_total_cost * Decimal(rng.randint(0, 130))) / Decimal(100)
            cap_text = format(cap.quantize(Decimal("0.0001")), "f")

            solution = solve_basket(
                items,
                budget_cny=float(cap_text),
                customs_limit_cny=float(cap_text),
            )
            _assert_optimal(solution, items, cap_text)

            repeated = solve_basket(
                items,
                budget_cny=float(cap_text),
                customs_limit_cny=float(cap_text),
            )
            assert _quantities(repeated, skus) == _quantities(solution, skus)
            assert repeated.total_spend_cny == solution.total_spend_cny
            assert repeated.total_savings_cny == solution.total_savings_cny

    assert case_id == 16


def test_zero_and_negative_max_units_are_skipped_but_other_items_stay_optimal():
    good = _item("GOOD", Decimal("1.25"), Decimal("1"), 2)
    zero_cap = _item("ZERO", Decimal("1.00"), Decimal("1"), 0)
    negative_cap = _item("NEG", Decimal("1.00"), Decimal("1"), -1)
    solution = solve_basket(
        [zero_cap, good, negative_cap],
        budget_cny=3.0,
        customs_limit_cny=3.0,
    )

    assert _quantities(solution, ["ZERO", "GOOD", "NEG"]) == [0, 2, 0]
    assert Decimal(str(solution.total_spend_cny)) == Decimal("2.50")
    assert Decimal(str(solution.total_savings_cny)) == Decimal("2")


def test_default_payback_is_infinite_only_when_positive_savings_exist():
    profitable = solve_basket(
        [_item("A", Decimal("1.50"), Decimal("1"), 1)],
        budget_cny=2.0,
        customs_limit_cny=2.0,
    )
    assert profitable.payback_rate_pct == float("inf")

    empty = solve_basket([], budget_cny=2.0, customs_limit_cny=2.0)
    assert empty.payback_rate_pct == 0.0
