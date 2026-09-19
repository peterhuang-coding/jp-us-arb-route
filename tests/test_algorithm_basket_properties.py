import pytest
from decimal import Decimal
from itertools import product
from random import Random

from arb.basket import BasketItem, solve_basket


# Fixed seed for this property suite (deliberately not the old 20260308 matrix).
RND = Random(20260920)


def D(x):
    return Decimal(str(x))


def money(value, place):
    return float(D(value).scaleb(-place))


def make_item(sku, cost, saving, bound):
    # Diagnostic fields are irrelevant to the optimizer; provide valid values.
    return BasketItem(
        sku=sku,
        name="n-" + sku,
        category="cat",
        jp_price_per_unit_cny=float(cost),
        home_price_per_unit_cny=float(cost + saving),
        savings_per_unit_cny=float(saving),
        max_units=bound,
        purchase_price_usd=1.0,
        home_price_cny=float(cost + saving),
        sell_price_usd=1.0,
        fx_rate=0.14,
    )


def random_base():
    n = RND.randint(1, 4)
    cases = []
    for i in range(n):
        cp = RND.randint(0, 4)
        sp = RND.randint(0, 4)
        cost = money(RND.randint(1, 40), cp)
        saving = money(RND.randint(1, 35), sp)
        bound = RND.randint(0, 3)
        cases.append((f"S{i}", cost, saving, bound))

    # Align the cap to a multiple of a unit cost or just below it;
    # keep these feasibility scenarios nonnegative even for tiny costs.
    unit_costs = [D(v[1]) for v in cases if v[3] > 0]
    if unit_costs:
        cheapest = min(unit_costs)
        k = RND.randint(1, 4)
        cap = float(cheapest * k if RND.random() < 0.5 else cheapest * k - cheapest / Decimal("10"))
    else:
        cap = float(RND.randint(1, 10))
    return cap, cases


FIXED_BASES = [
    # Integer costs, four-decimal savings: catches savings denominator truncation.
    (1.0, [("A", 1.0, 0.0007, 1)]),
    # Exact and just-below spend boundaries with heterogeneous bounds.
    (3.0, [("A", 1.0, 2.0, 2), ("B", 2.0, 3.0, 1)]),
    (2.99, [("A", 1.0, 2.0, 2), ("B", 2.0, 3.0, 1)]),
    # Bounded "dominated" item can improve the optimum; it must not be globally pruned.
    (2.0, [("A", 1.0, 2.0, 1), ("B", 1.0, 1.0, 1)]),
    # Enough dominant inventory makes the nonincrease property valid here.
    (3.0, [("A", 1.0, 2.0, 3), ("B", 1.0, 1.0, 3)]),
]


BASES = [random_base() for _ in range(19)] + FIXED_BASES
assert len(BASES) == 24


def oracle(cap, cases):
    cap_d = D(cap)
    best_save = Decimal(0)
    best_spend = Decimal(0)
    ranges = [range(bound + 1) for _, _, _, bound in cases]
    for qtys in product(*ranges):
        spend = sum(D(cost) * q for (_, cost, _, _), q in zip(cases, qtys))
        if spend <= cap_d:
            save = sum(D(saving) * q for (_, _, saving, _), q in zip(cases, qtys))
            if save > best_save or (save == best_save and spend < best_spend):
                best_save, best_spend = save, spend
    return best_spend, best_save


def solve(cap, cases):
    return solve_basket(
        [make_item(sku, cost, saving, bound) for sku, cost, saving, bound in cases],
        budget_cny=float(cap),
        customs_limit_cny=float(cap),
    )


@pytest.mark.parametrize("cap,cases", BASES)
def test_exact_solver_matches_enumeration(cap, cases):
    result = solve(cap, cases)
    _, exact_save = oracle(cap, cases)
    by_sku = {p.sku: p for p in result.picks}

    assert len(by_sku) == len(result.picks)
    for sku, cost, _, bound in cases:
        q = by_sku[sku].num_units if sku in by_sku else 0
        assert isinstance(q, int) and not isinstance(q, bool)
        assert 0 <= q <= bound

    calc_spend = sum(D(cost) * by_sku[sku].num_units for sku, cost, _, _ in cases if sku in by_sku)
    calc_save = sum(D(saving) * by_sku[sku].num_units for sku, _, saving, _ in cases if sku in by_sku)
    assert calc_spend <= D(cap)
    assert result.total_spend_cny == pytest.approx(float(calc_spend))
    assert result.total_savings_cny == pytest.approx(float(calc_save))
    assert calc_save == exact_save

    # Reported per-line monetary fields are floats; compare only approximately.
    for p in result.picks:
        src = next(v for v in cases if v[0] == p.sku)
        assert p.subtotal_cny == pytest.approx(src[1] * p.num_units)
        assert p.total_savings_cny == pytest.approx(src[2] * p.num_units)


def test_permutation_preserves_optimum():
    for index, (cap, cases) in enumerate(BASES):
        reordered = list(cases)
        Random(20260920 + index).shuffle(reordered)
        if reordered == cases:
            continue
        a = solve(cap, cases)
        b = solve(cap, reordered)
        a_save = sum(D(p.savings_per_unit_cny) * p.num_units for p in a.picks)
        b_save = sum(D(p.savings_per_unit_cny) * p.num_units for p in b.picks)
        assert a_save == b_save == oracle(cap, cases)[1]
        assert sum(D(p.jp_price_per_unit_cny) * p.num_units for p in a.picks) <= D(cap)
        assert sum(D(p.jp_price_per_unit_cny) * p.num_units for p in b.picks) <= D(cap)


@pytest.mark.parametrize("cap,cases", BASES)
def test_positive_monetary_scaling_by_ten(cap, cases):
    scaled_cap = Decimal("10") * D(cap)
    scaled = [
        (sku, float(Decimal("10") * D(cost)), float(Decimal("10") * D(saving)), bound)
        for sku, cost, saving, bound in cases
    ]
    a = solve(cap, cases)
    b = solve(float(scaled_cap), scaled)
    a_save = sum(D(p.savings_per_unit_cny) * p.num_units for p in a.picks)
    b_save = sum(D(p.savings_per_unit_cny) * p.num_units for p in b.picks)
    b_spend = sum(D(p.jp_price_per_unit_cny) * p.num_units for p in b.picks)
    assert b_save == Decimal("10") * a_save
    assert b_spend <= scaled_cap
    assert b_save == oracle(float(scaled_cap), scaled)[1]
    assert b.total_savings_cny == pytest.approx(float(b_save))
    assert b.total_spend_cny == pytest.approx(float(b_spend))


def test_bounded_dominated_counterexample_is_regression():
    # A dominates B per unit, but with only one A the extra bounded B is useful.
    cap = 2.0
    cases = [("A", 1.0, 2.0, 1), ("B", 1.0, 1.0, 1)]
    assert solve(cap, cases[:1]).total_savings_cny == pytest.approx(2.0)
    result = solve(cap, cases)
    assert D(result.total_savings_cny) == Decimal("3")
    assert D(result.total_savings_cny) == oracle(cap, cases)[1]


def test_dominated_nonincrease_only_with_enough_dominator_inventory():
    cap = 3.0
    base = [("A", 1.0, 2.0, 3)]
    augmented = base + [("B", 1.0, 1.0, 3)]
    before = solve(cap, base).total_savings_cny
    after = solve(cap, augmented).total_savings_cny
    assert D(after) == D(before) == Decimal("6")
    assert D(after) == oracle(cap, augmented)[1]
