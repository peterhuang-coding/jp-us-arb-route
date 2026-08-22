"""限额守卫 (spec §7): 自动付款前的检查, 纯函数无 IO.

两个检查点:
- check_funds: FUNDS_VERIFIED 转移前 — 买家付款是否到账(预收优先)
- check_pay:   PURCHASED → PAID 前 — 单笔限额 / 日累计限额 / 毛利为正
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PayConfig:
    """阈值可在 SPA 配置页改; 默认值即 spec §7. 金额单位 CNY."""
    per_order_limit_cny: float = 300.0
    daily_limit_cny: float = 2000.0


@dataclass(frozen=True)
class PayDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def check_funds(order: dict) -> PayDecision:
    """预收优先: 买家付款必须 > 0 才允许推进采购."""
    buyer_paid = float(order.get("buyer_paid_cny") or 0)
    if buyer_paid <= 0:
        return PayDecision(False, ["买家付款未到账"])
    return PayDecision(True)


def check_pay(order: dict, cfg: PayConfig, paid_today_cny: float) -> PayDecision:
    """付款前检查: 单笔 ≤ 限额; 当日累计 ≤ 限额; 毛利为正(买家付款 − 采购 − 运费 > 0)."""
    reasons: list[str] = []
    buy_price = float(order.get("buy_price_cny") or 0)
    ship = float(order.get("ship_cost_cny") or 0)
    buyer_paid = float(order.get("buyer_paid_cny") or 0)

    if buy_price > cfg.per_order_limit_cny:
        reasons.append(f"单笔 ¥{buy_price:.2f} 超过上限 ¥{cfg.per_order_limit_cny:.2f}")
    if paid_today_cny + buy_price > cfg.daily_limit_cny:
        reasons.append(
            f"日累计 ¥{paid_today_cny:.2f} + ¥{buy_price:.2f} 超过上限 ¥{cfg.daily_limit_cny:.2f}"
        )
    if buyer_paid - buy_price - ship <= 0:
        reasons.append("毛利非正(买家付款 ≤ 采购+运费)")
    return PayDecision(not reasons, reasons)
