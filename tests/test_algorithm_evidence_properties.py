"""Independent exact-cent property tests for the public CNY finance formulas.

These tests use only the public functions in ``finance`` and an independent
Decimal ledger oracle built from integer cents.  They intentionally do not
cover invalid/None/NaN omission behavior; that behavior is covered elsewhere.
"""

from decimal import Decimal, ROUND_HALF_EVEN
import random

import pytest

from arb.opp.finance import (
    capital_occupation_cny,
    margin_pct,
    net_profit_cny,
)


# Money fields are integer CNY cents.  Quantities are positive integers.
# Each row contains: case_id, buy, exit, platform, outbound, tax, other,
# inbound, quantity.
_BASE_CENT_SCENARIOS = [
    # Hand-authored boundary and sign cases.
    ("S00_zero_buy_zero_fees", 0, 0, 0, 0, 0, 0, 0, 1),
    ("S01_zero_buy_positive_exit", 0, 100, 0, 0, 0, 0, 0, 1),
    ("S02_zero_buy_fee_loss", 0, 50, 75, 0, 0, 0, 0, 1),
    ("S03_positive_profit_no_fees", 1000, 1400, 0, 0, 0, 0, 0, 1),
    ("S04_breakeven_all_components", 1000, 1300, 100, 100, 50, 50, 0, 1),
    ("S05_negative_profit_fees", 1000, 900, 25, 25, 25, 25, 0, 1),
    ("S06_inbound_capital_only", 800, 950, 0, 0, 0, 0, 125, 1),
    ("S07_exit_equals_buy_fees_cause_loss", 1234, 1234, 11, 22, 33, 44, 0, 1),
    ("S08_qty_three", 700, 825, 10, 15, 5, 20, 60, 3),
    ("S09_qty_seven", 1500, 1490, 0, 3, 0, 4, 80, 7),
    ("S10_large_but_small_relative_to_float_limits", 100000, 125000, 500, 250, 125, 125, 1000, 12),
    ("S11_odd_cent_amounts", 333, 777, 17, 19, 23, 29, 31, 5),
    ("S12_fee_components_equal", 1999, 2101, 7, 7, 7, 7, 0, 2),
    ("S13_buy_gt_exit_no_fees", 2500, 2499, 0, 0, 0, 0, 0, 4),
    ("S14_buy_gt_exit_with_inbound", 2500, 2499, 0, 0, 0, 0, 333, 4),
    ("S15_one_cent_profit", 100, 101, 0, 0, 0, 0, 0, 1),
    ("S16_one_cent_loss", 101, 100, 0, 0, 0, 0, 0, 1),
]


def _money(cents: int) -> float:
    """Return a two-decimal CNY value while keeping the oracle in cents."""
    return (cents // 100) + ((cents % 100) / 100.0)


def _money_decimal_from_cents(cents: int) -> Decimal:
    return Decimal(cents) / Decimal(100)


def _quant2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def _decimal_from_output(value: float) -> Decimal:
    # ``str`` captures the declared two-decimal float result and avoids using
    # binary float bits as the comparison oracle.
    return Decimal(str(value))


def _generated_scenarios():
    rng = random.Random(20260919)
    scenarios = list(_BASE_CENT_SCENARIOS)

    # A bounded, fixed seed supplements readable hand-authored cases.  Bounds
    # are tiny compared with float64 limits and quantities are small.
    while len(scenarios) < 28:
        idx = len(scenarios)
        buy = rng.randrange(0, 10000, 25)
        exit_ = rng.randrange(0, 12000, 25)
        platform = rng.randrange(0, 200, 5)
        outbound = rng.randrange(0, 200, 5)
        tax = rng.randrange(0, 150, 5)
        other = rng.randrange(0, 150, 5)
        inbound = rng.randrange(0, 500, 5)
        qty = rng.randint(1, 10)
        scenarios.append(
            (
                f"S{idx:02d}_seeded_mix",
                buy,
                exit_,
                platform,
                outbound,
                tax,
                other,
                inbound,
                qty,
            )
        )

    # Explicitly guarantee negative, zero, and positive net-profit outcomes
    # among generated scenarios, without introducing invalid/negative prices.
    scenarios.extend(
        [
            ("S28_seeded_guaranteed_negative", 4200, 3000, 200, 150, 100, 100, 250, 6),
            ("S29_seeded_guaranteed_zero", 4200, 4650, 200, 150, 100, 0, 250, 6),
            ("S30_seeded_guaranteed_positive", 4200, 6000, 100, 50, 50, 50, 250, 6),
        ]
    )
    return scenarios


SCENARIOS = _generated_scenarios()

# Scale factors are small positive integers.  Scaled cents remain integral and
# the largest generated amount is safely below any practical float overflow.
SCALE_FACTORS = (2, 3, 5)

# Fee perturbation is itself a nonnegative number of cents.  The linked profit
# invariant therefore requires an exact one-cent-for-one-cent decrease.
FEE_DELTA_CENTS = 37

@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda row: row[0])
def test_net_profit_and_capital_match_decimal_cent_ledger(scenario):
    case_id, buy, exit_, platform, outbound, tax, other, inbound, qty = scenario

    actual_net = net_profit_cny(
        buy_cny=_money(buy),
        exit_cny=_money(exit_),
        platform_fee_cny=_money(platform),
        ship_cny=_money(outbound),
        tax_cny=_money(tax),
        other_cny=_money(other),
    )
    actual_capital = capital_occupation_cny(
        buy_cny=_money(buy),
        qty=qty,
        inbound_ship_cny=_money(inbound),
    )

    expected_net_cents = exit_ - buy - platform - outbound - tax - other
    expected_net_decimal = _quant2(_money_decimal_from_cents(expected_net_cents))
    expected_capital_cents = (buy + inbound) * qty
    expected_capital_decimal = _quant2(
        _money_decimal_from_cents(expected_capital_cents)
    )

    assert actual_net is not None, case_id
    assert actual_capital is not None, case_id
    assert _decimal_from_output(actual_net) == expected_net_decimal, case_id
    assert (
        _decimal_from_output(actual_capital) == expected_capital_decimal
    ), case_id


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda row: row[0])
def test_nonnegative_fee_increase_changes_profit_by_exact_delta(scenario):
    case_id, buy, exit_, platform, outbound, tax, other, _inbound, _qty = scenario

    baseline = net_profit_cny(
        buy_cny=_money(buy),
        exit_cny=_money(exit_),
        platform_fee_cny=_money(platform),
        ship_cny=_money(outbound),
        tax_cny=_money(tax),
        other_cny=_money(other),
    )
    increased_platform = net_profit_cny(
        buy_cny=_money(buy),
        exit_cny=_money(exit_),
        platform_fee_cny=_money(platform + FEE_DELTA_CENTS),
        ship_cny=_money(outbound),
        tax_cny=_money(tax),
        other_cny=_money(other),
    )
    spread_across_fees = net_profit_cny(
        buy_cny=_money(buy),
        exit_cny=_money(exit_),
        platform_fee_cny=_money(platform + 10),
        ship_cny=_money(outbound + 11),
        tax_cny=_money(tax + 7),
        other_cny=_money(other + 9),
    )

    expected_baseline = _quant2(
        _money_decimal_from_cents(
            exit_ - buy - platform - outbound - tax - other
        )
    )
    delta_money = _money_decimal_from_cents(FEE_DELTA_CENTS)

    assert _decimal_from_output(baseline) == expected_baseline, case_id
    assert increased_platform <= baseline, case_id
    assert spread_across_fees <= baseline, case_id
    assert (
        _decimal_from_output(baseline) - _decimal_from_output(increased_platform)
        == delta_money
    ), case_id
    assert (
        _decimal_from_output(baseline) - _decimal_from_output(spread_across_fees)
        == delta_money
    ), case_id


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda row: row[0])
@pytest.mark.parametrize("scale", SCALE_FACTORS)
def test_scaling_money_scales_net_capital_and_preserves_margin(scenario, scale):
    case_id, buy, exit_, platform, outbound, tax, other, inbound, qty = scenario

    base_net = net_profit_cny(
        buy_cny=_money(buy),
        exit_cny=_money(exit_),
        platform_fee_cny=_money(platform),
        ship_cny=_money(outbound),
        tax_cny=_money(tax),
        other_cny=_money(other),
    )
    scaled_net = net_profit_cny(
        buy_cny=_money(buy * scale),
        exit_cny=_money(exit_ * scale),
        platform_fee_cny=_money(platform * scale),
        ship_cny=_money(outbound * scale),
        tax_cny=_money(tax * scale),
        other_cny=_money(other * scale),
    )

    base_capital = capital_occupation_cny(
        buy_cny=_money(buy), qty=qty, inbound_ship_cny=_money(inbound)
    )
    scaled_capital = capital_occupation_cny(
        buy_cny=_money(buy * scale),
        qty=qty,
        inbound_ship_cny=_money(inbound * scale),
    )

    base_net_decimal = _decimal_from_output(base_net)
    scaled_net_decimal = _decimal_from_output(scaled_net)
    base_capital_decimal = _decimal_from_output(base_capital)
    scaled_capital_decimal = _decimal_from_output(scaled_capital)

    assert scaled_net_decimal == _quant2(base_net_decimal * scale), case_id
    assert scaled_capital_decimal == _quant2(
        base_capital_decimal * scale
    ), case_id

    # The quantity deliberately remains unchanged: every per-unit money amount,
    # including inbound logistics, is scaled, so capital is also scaled.
    net_cents = exit_ - buy - platform - outbound - tax - other
    # Rounded percentage ties have an exact half remainder after multiplying by10000.
    if buy > 0 and 2 * (abs(net_cents) * 10000 % buy) != buy:
        base_margin = margin_pct(base_net, _money(buy))
        scaled_margin = margin_pct(scaled_net, _money(buy * scale))
        assert base_margin is not None, case_id
        assert scaled_margin is not None, case_id
        expected_margin = _quant2(Decimal(net_cents) / Decimal(buy) * 100)
        assert _decimal_from_output(base_margin) == expected_margin, case_id
        assert _decimal_from_output(scaled_margin) == expected_margin, case_id
