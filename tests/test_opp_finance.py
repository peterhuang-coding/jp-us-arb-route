"""阶段0: 统一 CNY 财务口径 — 缺数据留 NULL, 绝不臆造/USD 换算."""
from __future__ import annotations

import inspect

from arb.opp import finance


def test_net_profit_full_inputs():
    net = finance.net_profit_cny(
        buy_cny=1000, exit_cny=1500,
        platform_fee_cny=100, ship_cny=50, tax_cny=30, other_cny=20)
    assert net == 300.0  # 1500 - 1000 - 100 - 50 - 30 - 20


def test_net_profit_missing_inputs_returns_none():
    assert finance.net_profit_cny(buy_cny=None, exit_cny=1500) is None
    assert finance.net_profit_cny(buy_cny=1000, exit_cny=None) is None
    # 费用缺失按 0 (调用方明确无该费用), 但 buy/exit 缺就一定是 None
    assert finance.net_profit_cny(buy_cny=1000, exit_cny=1500) == 500.0


def test_margin_pct():
    assert finance.margin_pct(300, 1000) == 30.0
    assert finance.margin_pct(None, 1000) is None
    assert finance.margin_pct(300, None) is None
    assert finance.margin_pct(300, 0) is None


def test_capital_occupation():
    assert finance.capital_occupation_cny(1000, qty=3) == 3000.0
    assert finance.capital_occupation_cny(1000, qty=2, inbound_ship_cny=100) == 2200.0
    assert finance.capital_occupation_cny(None) is None


def test_capital_days_and_sell_cycle():
    assert finance.capital_days("2026-08-01", "2026-08-20") == 19
    assert finance.capital_days("2026-08-01T09:00:00", "2026-08-20 10:00:00") == 19
    assert finance.capital_days(None, "2026-08-20") is None
    assert finance.capital_days("2026-08-01", None) is None
    assert finance.sell_cycle_days("2026-08-10", "2026-08-15") == 5
    assert finance.sell_cycle_days("2026-08-10", None) is None


def test_forecast_error():
    assert finance.forecast_error_cny(300, 280) == -20.0
    assert finance.forecast_error_cny(None, 280) is None
    assert finance.forecast_error_cny(300, None) is None


def test_evidence_grade():
    assert finance.evidence_grade(1, 2, True) == "A"
    assert finance.evidence_grade(1, 2, False) == "B"
    assert finance.evidence_grade(1, 1, False) == "C"
    assert finance.evidence_grade(0, 0, False) == "D"


def test_no_usd_conversion_exists():
    """finance 代码体不得出现 USD/FX 换算 (tech 硬门禁; 文档字符串除外)."""
    import ast
    tree = ast.parse(inspect.getsource(finance))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arg_names = {a.arg for a in node.args.args} | {
                a.arg for a in node.args.kwonlyargs}
            for name in arg_names:
                assert "usd" not in name.lower() and "fx" not in name.lower(), (
                    f"finance.{node.name} 参数 {name!r} 暗示 USD/FX 换算")
        if isinstance(node, ast.Name):
            assert "usd" not in node.id.lower() and node.id.lower() != "fx", (
                f"finance 代码出现 {node.id!r} (禁止强行 USD 换算)")
