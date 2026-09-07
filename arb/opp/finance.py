"""统一 CNY 净利 / 资金占用口径 (PRD §4.3/§4.8).

硬规则:
- 所有金额一律 CNY. 旧 opportunities 表只有 USD 静态价差 —— 本模块
  不做任何 USD→CNY 换算 (FX 随时间变, 强行换算等于臆造).
- 缺数据一律返回 None (落库为 NULL), 不用 0 顶替, 不猜费用.
- 纯函数, 不碰数据库; backfill/sync 负责取数, 本模块只算.
"""
from __future__ import annotations

import statistics
from datetime import date, datetime
from typing import Iterable, Optional


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def net_profit_cny(*, buy_cny: Optional[float], exit_cny: Optional[float],
                   platform_fee_cny: Optional[float] = 0.0,
                   ship_cny: Optional[float] = 0.0,
                   tax_cny: Optional[float] = 0.0,
                   other_cny: Optional[float] = 0.0) -> Optional[float]:
    """单件净利 = 退出价 - 采购价 - 平台费 - 运费 - 税 - 其他.

    buy/exit 任一缺失 → None (无法计算, 不臆造). 费用项缺失按 0 处理
    (调用方知道没有该项费用时才传 None/0; 未知费用应显式传 None 之外的
    方式 —— 阶段0 backfill 不掌握费用, 直接不算净利).
    """
    buy = _num(buy_cny)
    exit_ = _num(exit_cny)
    if buy is None or exit_ is None:
        return None
    fee = (_num(platform_fee_cny) or 0.0) + (_num(ship_cny) or 0.0) \
        + (_num(tax_cny) or 0.0) + (_num(other_cny) or 0.0)
    return round(exit_ - buy - fee, 2)


def margin_pct(net_profit_cny: Optional[float], buy_cny: Optional[float]) -> Optional[float]:
    """利润率 = 净利 / 采购成本 × 100. 任一缺失或成本为 0 → None."""
    net = _num(net_profit_cny)
    buy = _num(buy_cny)
    if net is None or not buy:
        return None
    return round(net / buy * 100, 2)


def capital_occupation_cny(buy_cny: Optional[float], qty: int = 1,
                           inbound_ship_cny: Optional[float] = 0.0) -> Optional[float]:
    """资金占用 = (单件采购 + 入境物流) × 数量. 采购价缺失 → None."""
    buy = _num(buy_cny)
    if buy is None:
        return None
    qty = int(qty or 1)
    return round((buy + (_num(inbound_ship_cny) or 0.0)) * qty, 2)


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
    return round(act - est, 2)


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
        if price is None:
            continue
        if max_age_days is not None:
            d = _parse_date(get("observed_at"))
            if d is None or (as_of_date - d).days > max_age_days:
                continue
        if kind in groups:
            groups[kind].append(price)
        elif kind == "ask":
            ask_prices.append(price)

    for kind in ("buyback", "bid", "sold"):
        if groups[kind]:
            return {
                "value_cny": round(statistics.median(groups[kind]), 2),
                "kind": kind,
                "sample_count": len(groups[kind]),
                "anchor_ask_cny": round(statistics.median(ask_prices), 2) if ask_prices else None,
                "ask_count": len(ask_prices),
            }
    return {
        "value_cny": None,
        "kind": None,
        "sample_count": 0,
        "anchor_ask_cny": round(statistics.median(ask_prices), 2) if ask_prices else None,
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
