"""统一 CNY 净利 / 资金占用口径 (PRD §4.3/§4.8).

硬规则:
- 所有金额一律 CNY. 旧 opportunities 表只有 USD 静态价差 —— 本模块
  不做任何 USD→CNY 换算 (FX 随时间变, 强行换算等于臆造).
- 缺数据一律返回 None (落库为 NULL), 不用 0 顶替, 不猜费用.
- 纯函数, 不碰数据库; backfill/sync 负责取数, 本模块只算.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime
from typing import Iterable, Optional


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _nonnegative_num(v) -> Optional[float]:
    value = _num(v)
    return value if value is not None and value >= 0 else None


def _finite_round(value: float) -> Optional[float]:
    return round(value, 2) if math.isfinite(value) else None


def net_profit_cny(*, buy_cny: Optional[float], exit_cny: Optional[float],
                   platform_fee_cny: Optional[float] = 0.0,
                   ship_cny: Optional[float] = 0.0,
                   tax_cny: Optional[float] = 0.0,
                   other_cny: Optional[float] = 0.0) -> Optional[float]:
    """单件净利 = 退出价 - 采购价 - 平台费 - 运费 - 税 - 其他.

    金额缺失或无效 → None (无法计算, 不臆造). 费用参数省略时保留默认 0;
    费用未知须显式传 None, 确认没有该项费用才传 0.
    """
    buy = _nonnegative_num(buy_cny)
    exit_ = _nonnegative_num(exit_cny)
    if buy is None or exit_ is None:
        return None
    fees = [_nonnegative_num(value) for value in
            (platform_fee_cny, ship_cny, tax_cny, other_cny)]
    if any(value is None for value in fees):
        return None
    return _finite_round(exit_ - buy - sum(fees))


def margin_pct(net_profit_cny: Optional[float], buy_cny: Optional[float]) -> Optional[float]:
    """利润率 = 净利 / 采购成本 × 100. 任一缺失或成本非正 → None."""
    net = _num(net_profit_cny)
    buy = _num(buy_cny)
    if net is None or buy is None or buy <= 0:
        return None
    return _finite_round(net / buy * 100)


def capital_occupation_cny(buy_cny: Optional[float], qty: int = 1,
                           inbound_ship_cny: Optional[float] = 0.0) -> Optional[float]:
    """资金占用 = (单件采购 + 入境物流) × 正整数数量. 缺失或无效 → None."""
    buy = _nonnegative_num(buy_cny)
    inbound = _nonnegative_num(inbound_ship_cny)
    quantity = _num(qty)
    if (buy is None or inbound is None or quantity is None
            or quantity <= 0 or not quantity.is_integer()):
        return None
    return _finite_round((buy + inbound) * quantity)


def _parse_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def capital_days(acquired_at, settled_at) -> Optional[int]:
    """资金占用天数 = 回款日 - 入手日. 任一缺失 → None."""
    d1 = _parse_date(acquired_at)
    d2 = _parse_date(settled_at)
    if d1 is None or d2 is None:
        return None
    return (d2 - d1).days


def sell_cycle_days(listed_at, sold_at) -> Optional[int]:
    """售出周期 = 成交日 - 上架日. 任一缺失 → None."""
    d1 = _parse_date(listed_at)
    d2 = _parse_date(sold_at)
    if d1 is None or d2 is None:
        return None
    return (d2 - d1).days


def forecast_error_cny(est_net_profit_cny: Optional[float],
                       actual_net_profit_cny: Optional[float]) -> Optional[float]:
    """预测误差 = 实际净利 - 预计净利 (正=超预期). 任一缺失 → None."""
    est = _num(est_net_profit_cny)
    act = _num(actual_net_profit_cny)
    if est is None or act is None:
        return None
    return _finite_round(act - est)


def executable_exit_value(evidences: Iterable[dict], *,
                          max_age_days: Optional[int] = None,
                          as_of=None) -> dict:
    """可执行退出价口径 (总控交叉复核③): 优先级 buyback > bid > sold.

    同类型取同规格近 N 天 (max_age_days) 价格中位数, 记录样本量;
    ask 仅作锚点 (单独返回, 永不作预计收入); rumor/heat 不计.
    返回 {"value_cny", "kind", "sample_count", "anchor_ask_cny", "ask_count"}.
    全部缺失 → value_cny=None (缺数据留 NULL, 不臆造).

    evidences 元素需含 kind/side/price_cny, 可选 observed_at.
    """
    as_of_date = _parse_date(as_of) or date.today()
    groups: dict[str, list[float]] = {"buyback": [], "bid": [], "sold": []}
    ask_prices: list[float] = []
    for e in evidences:
        get = e.get if hasattr(e, "get") else (lambda k, d=None: e[k] if k in e.keys() else d)
        if get("side") != "sell":
            continue
        kind = str(get("kind", ""))
        price = _num(get("price_cny"))
        if price is None or price <= 0:
            continue
        if max_age_days is not None:
            d = _parse_date(get("observed_at"))
            if d is None or not 0 <= (as_of_date - d).days <= max_age_days:
                continue
        if kind in groups:
            groups[kind].append(price)
        elif kind == "ask":
            ask_prices.append(price)

    for kind in ("buyback", "bid", "sold"):
        if groups[kind]:
            value = _finite_round(statistics.median(groups[kind]))
            if value is None:
                continue
            return {
                "value_cny": value,
                "kind": kind,
                "sample_count": len(groups[kind]),
                "anchor_ask_cny": _finite_round(statistics.median(ask_prices)) if ask_prices else None,
                "ask_count": len(ask_prices),
            }
    return {
        "value_cny": None,
        "kind": None,
        "sample_count": 0,
        "anchor_ask_cny": _finite_round(statistics.median(ask_prices)) if ask_prices else None,
        "ask_count": len(ask_prices),
    }


def evidence_grade(supply_count: int, exit_signal_count: int,
                   has_executable_exit: bool) -> Optional[str]:
    """证据等级 A-D (纯展示用口径):

    A: ≥1 官方供给 + ≥2 独立退出信号 + 含可执行退出 (bid/buyback/sold)
    B: ≥1 官方供给 + ≥2 独立退出信号 (仅挂单)
    C: 有官方供给但退出信号不足
    D: 无官方供给
    """
    if supply_count >= 1 and exit_signal_count >= 2 and has_executable_exit:
        return "A"
    if supply_count >= 1 and exit_signal_count >= 2:
        return "B"
    if supply_count >= 1:
        return "C"
    return "D"
