"""M0 限额守卫测试 (spec §7)."""
from arb.execution.payguard import PayConfig, check_funds, check_pay

CFG = PayConfig(per_order_limit_cny=300.0, daily_limit_cny=2000.0)


def order(buy=200.0, ship=30.0, paid=950.0):
    return {"buy_price_cny": buy, "ship_cost_cny": ship, "buyer_paid_cny": paid}


def test_check_funds_blocks_unpaid():
    assert not check_funds(order(paid=0.0)).allowed
    assert check_funds(order()).allowed


def test_check_pay_allows_under_limits():
    assert check_pay(order(), CFG, paid_today_cny=0.0).allowed


def test_check_pay_per_order_boundary_is_inclusive():
    assert check_pay(order(buy=300.0), CFG, paid_today_cny=0.0).allowed


def test_check_pay_blocks_over_per_order_limit():
    d = check_pay(order(buy=300.01), CFG, paid_today_cny=0.0)
    assert not d.allowed and any("单笔" in r for r in d.reasons)


def test_check_pay_daily_boundary_is_inclusive():
    assert check_pay(order(buy=200.0), CFG, paid_today_cny=1800.0).allowed


def test_check_pay_blocks_over_daily_limit():
    d = check_pay(order(buy=200.0), CFG, paid_today_cny=1800.01)
    assert not d.allowed and any("日累计" in r for r in d.reasons)


def test_check_pay_blocks_non_positive_margin():
    d = check_pay(order(buy=300.0, ship=650.0, paid=950.0), CFG, paid_today_cny=0.0)
    assert not d.allowed and any("毛利" in r for r in d.reasons)


def test_check_pay_blocks_missing_buy_price():
    d = check_pay(order(buy=None), CFG, paid_today_cny=0.0)
    assert not d.allowed and any("采购价" in r for r in d.reasons)
