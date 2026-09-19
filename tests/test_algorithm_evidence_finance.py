"""Regressions for invalid finance inputs and evidence dates."""
import pytest
from arb.opp import finance


@pytest.mark.parametrize(("buy", "exit_", "fee", "ship", "tax", "other", "expected"), [
    (1000, 1500, 100, 50, 30, 20, 300.0),
    ("1000", "1500", "100", "50", "30", "20", 300.0),
    (100.25, 200.50, None, None, None, None, None),
    (50, 25, 10, 0, 0, 0, -35.0),
    (None, 1500, 0, 0, 0, 0, None),
    (1000, None, 0, 0, 0, 0, None),
    (True, 1500, 0, 0, 0, 0, None),
    (1000, False, 0, 0, 0, 0, None),
    (1000, 1500, "bad", 0, 0, 0, None),
    (1000, 1500, float("nan"), 0, 0, 0, None),
    (-100, 0, 0, 0, 0, 0, None),
    (0, 100, -1, 0, 0, 0, None),
    (1e308, 1e308, -1e308, 0, 0, 0, None),
    (0, 0, 1e308, 1e308, 0, 0, None),
    (10**400, 100, 0, 0, 0, 0, None),
    (1000, 1500, 0, "unknown", 0, 0, None),
])
def test_net_profit_validation_and_compatibility(buy, exit_, fee, ship, tax, other, expected):
    result = finance.net_profit_cny(
        buy_cny=buy, exit_cny=exit_, platform_fee_cny=fee,
        ship_cny=ship, tax_cny=tax, other_cny=other)
    assert result == expected


@pytest.mark.parametrize(("net", "buy", "expected"), [
    (300, 1000, 30.0),
    ("25.5", "100", 25.5),
    (-25, 100, -25.0),
    (None, 1000, None),
    (300, None, None),
    (300, 0, None),
    (300, -100, None),
    (True, 100, None),
    (300, "bad", None),
    (float("inf"), 100, None),
])
def test_margin_pct_validation(net, buy, expected):
    result = finance.margin_pct(net, buy)
    assert result == expected


@pytest.mark.parametrize(("buy", "qty", "inbound", "expected"), [
    (1000, 3, 0, 3000.0),
    (1000, 2, 100, 2200.0),
    (1000, "2.0", 0, 2000.0),
    (1000, 1, None, None),
    (100.25, 2, "0.25", 201.0),
    (None, 1, 0, None),
    (-1, 1, 0, None),
    (1000, 0, 0, None),
    (1000, -1, 0, None),
    (1000, 2.5, 0, None),
    (1000, "2x", 0, None),
    (1000, True, 0, None),
    (1000, 2, "bad", None),
    (1000, 2, -1, None),
])
def test_capital_occupation_validation(buy, qty, inbound, expected):
    result = finance.capital_occupation_cny(buy, qty=qty, inbound_ship_cny=inbound)
    assert result == expected


def test_capital_occupation_overflow_returns_none():
    assert finance.capital_occupation_cny(1e308, qty=10) is None


@pytest.mark.parametrize(("est", "actual", "expected"), [
    (300, 280, -20.0),
    ("300.25", "280.00", -20.25),
    (-50, -20, 30.0),
    (None, 280, None),
    (300, None, None),
    (True, 280, None),
    (300, float("inf"), None),
    (1e308, -1e308, None),
])
def test_forecast_error_validation(est, actual, expected):
    result = finance.forecast_error_cny(est, actual)
    assert result == expected


def test_executable_exit_ignores_invalid_rows_and_uses_ask_only_as_anchor():
    rows = [
        {"kind": "ask", "side": "sell", "price_cny": 2000, "observed_at": "2026-09-01"},
        {"kind": "ask", "side": "sell", "price_cny": 0, "observed_at": "2026-09-01"},
        {"kind": "ask", "side": "sell", "price_cny": -1, "observed_at": "2026-09-01"},
        {"kind": "bid", "side": "buy", "price_cny": 900, "observed_at": "2026-09-01"},
        {"kind": "bid", "side": "sell", "price_cny": None, "observed_at": "2026-09-01"},
        {"kind": "bid", "side": "sell", "price_cny": True, "observed_at": "2026-09-01"},
        {"kind": "rumor", "side": "sell", "price_cny": 5000, "observed_at": "2026-09-01"},
        {"kind": "heat", "side": "sell", "price_cny": 5000, "observed_at": "2026-09-01"},
    ]
    r = finance.executable_exit_value(rows)
    assert r == {"value_cny": None, "kind": None, "sample_count": 0,
                 "anchor_ask_cny": 2000.0, "ask_count": 1}


@pytest.mark.parametrize(("observed", "expected_count"), [
    ("2026-09-05", 1),
    ("2026-09-08", 1),
    ("2026-09-09", 0),
    ("2026-08-08", 0),
    (None, 0),
    ("bad", 0),
])
def test_executable_exit_max_age_rejects_future_old_and_missing_dates(observed, expected_count):
    rows = [{"kind": "sold", "side": "sell", "price_cny": 1500, "observed_at": observed}]
    r = finance.executable_exit_value(rows, max_age_days=30, as_of="2026-09-08")
    assert r["sample_count"] == expected_count
    assert r["value_cny"] == (1500.0 if expected_count else None)


def test_no_age_filter_keeps_valid_and_invalid_evidence_rules():
    rows = [
        {"kind": "sold", "side": "sell", "price_cny": "1300.5"},
        {"kind": "sold", "side": "sell", "price_cny": 0},
        {"kind": "sold", "side": "sell", "price_cny": float("nan")},
        {"kind": "ask", "side": "sell", "price_cny": 2000},
    ]
    r = finance.executable_exit_value(rows)
    assert r["value_cny"] == 1300.5
    assert r["anchor_ask_cny"] == 2000.0
    assert finance.evidence_grade(1, 2, True) == "A"
    assert finance.evidence_grade(1, 2, False) == "B"
    assert finance.evidence_grade(1, 1, False) == "C"
    assert finance.evidence_grade(0, 0, False) == "D"


@pytest.mark.parametrize("fee_name", ["platform_fee_cny", "ship_cny", "tax_cny", "other_cny"])
def test_explicit_unknown_fee_is_not_the_omitted_zero_default(fee_name):
    assert finance.net_profit_cny(buy_cny=100, exit_cny=150) == 50.0
    assert finance.net_profit_cny(buy_cny=100, exit_cny=150, **{fee_name: None}) is None


@pytest.mark.parametrize("kind", ["sold", "ask"])
def test_overflowing_evidence_median_never_becomes_a_price(kind):
    rows = [{"kind": kind, "side": "sell", "price_cny": 1e308}] * 2
    result = finance.executable_exit_value(rows)
    assert result["value_cny"] is None
    assert result["anchor_ask_cny"] is None
