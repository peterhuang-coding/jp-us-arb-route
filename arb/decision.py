"""Pure-function decision engine.

The judge() function returns a Decision object with explicit level, reason,
and the numbers that drove the call. No I/O, no globals — testable in isolation.

SPEC (also codified in tests/test_decision.py):

level precedence:
  1. hours_used > hours_available OR net_profit_usd <= 0  -> "不建议"
  2. roi_pct <  min_roi_pct                                -> "不建议"
  3. roi_pct <  target_roi_pct                             -> "谨慎"
  4. otherwise                                             -> "建议"

Note on currency: every monetary input is USD.  The CLI is responsible for
converting JPY prices to USD at the user's recorded rate before calling judge.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal


Level = Literal["建议", "谨慎", "不建议"]


class DecideError(ValueError):
    """Raised when DecisionInputs fail schema validation."""


@dataclass(frozen=True)
class DecisionInputs:
    num_units: int
    purchase_price_usd: float
    sell_price_usd: float
    tariff_rate: float
    shipping_per_unit_usd: float
    platform_fee_rate: float
    minutes_per_unit: float
    flight_cost_usd: float
    hotel_cost_usd: float
    other_trip_cost_usd: float = 0.0
    hours_available: float = 32.0
    target_hourly_usd: float = 20.0
    target_roi_pct: float = 15.0
    min_roi_pct: float = 10.0
    success_rate: float = 1.0


@dataclass(frozen=True)
class Decision:
    level: Level
    reason: str
    roi_pct: float
    net_profit_usd: float
    total_cost_usd: float
    total_revenue_usd: float
    breakeven_sell_price_usd: float
    hours_used: float
    per_unit_cost_usd: float
    per_unit_revenue_usd: float

    def as_dict(self) -> dict:
        return asdict(self)


# ---------- public API ----------

def judge(inp: DecisionInputs) -> Decision:
    _validate(inp)

    per_unit_cost_no_trip = (
        inp.purchase_price_usd
        + inp.purchase_price_usd * inp.tariff_rate
        + inp.shipping_per_unit_usd
    )
    per_unit_time_cost = (inp.minutes_per_unit / 60.0) * inp.target_hourly_usd
    per_unit_revenue = (
        inp.sell_price_usd * (1.0 - inp.platform_fee_rate) * inp.success_rate
    )

    trip_cost = (
        inp.flight_cost_usd
        + inp.hotel_cost_usd
        + inp.other_trip_cost_usd
    )

    total_revenue = per_unit_revenue * inp.num_units
    total_cost = (
        per_unit_cost_no_trip * inp.num_units
        + trip_cost
        + per_unit_time_cost * inp.num_units
    )
    net_profit = total_revenue - total_cost
    roi_pct = (net_profit / total_cost * 100.0) if total_cost > 0 else 0.0

    hours_used = (inp.num_units * inp.minutes_per_unit) / 60.0

    denom = (1.0 - inp.platform_fee_rate) * inp.success_rate
    if denom <= 0:
        breakeven_sell = float("inf")
    else:
        breakeven_sell = (
            per_unit_cost_no_trip + per_unit_time_cost + (trip_cost / inp.num_units)
        ) / denom

    # ---------- level cascade (highest priority first) ----------
    if hours_used > inp.hours_available:
        level: Level = "不建议"
        reason = (
            f"预计耗时 {hours_used:.1f}h 超出可用 {inp.hours_available:.1f}h,行程不可行。"
        )
    elif net_profit <= 0:
        level = "不建议"
        reason = (
            f"扣除机票/酒店/时间成本后净利润为 {net_profit:.2f} USD,负利润,无意义出差。"
        )
    elif roi_pct < inp.min_roi_pct:
        level = "不建议"
        reason = (
            f"ROI {roi_pct:.1f}% 低于最低阈值 {inp.min_roi_pct:.1f}%,不值得冒险。"
        )
    elif roi_pct < inp.target_roi_pct:
        level = "谨慎"
        reason = (
            f"ROI {roi_pct:.1f}% 介于 {inp.min_roi_pct:.1f}% 与 {inp.target_roi_pct:.1f}% 之间,勉强可行,可考虑压缩机票/酒店成本。"
        )
    else:
        level = "建议"
        reason = (
            f"ROI {roi_pct:.1f}% 高于目标 {inp.target_roi_pct:.1f}%,净利润 {net_profit:.2f} USD。"
        )

    return Decision(
        level=level,
        reason=reason,
        roi_pct=roi_pct,
        net_profit_usd=net_profit,
        total_cost_usd=total_cost,
        total_revenue_usd=total_revenue,
        breakeven_sell_price_usd=breakeven_sell,
        hours_used=hours_used,
        per_unit_cost_usd=per_unit_cost_no_trip,
        per_unit_revenue_usd=per_unit_revenue,
    )


# ---------- helpers ----------

def _validate(inp: DecisionInputs) -> None:
    if inp.num_units < 1:
        raise DecideError(f"num_units must be >= 1, got {inp.num_units}")
    if inp.platform_fee_rate < 0 or inp.platform_fee_rate >= 1:
        raise DecideError(
            f"platform_fee_rate must be in [0, 1), got {inp.platform_fee_rate}"
        )
    if inp.success_rate < 0 or inp.success_rate > 1:
        raise DecideError(
            f"success_rate must be in [0, 1], got {inp.success_rate}"
        )
    if inp.tariff_rate < 0:
        raise DecideError(f"tariff_rate must be >= 0, got {inp.tariff_rate}")
    if inp.min_roi_pct > inp.target_roi_pct:
        raise DecideError(
            f"min_roi_pct ({inp.min_roi_pct}) must be <= target_roi_pct ({inp.target_roi_pct})"
        )
    if inp.hours_available <= 0:
        raise DecideError(f"hours_available must be > 0, got {inp.hours_available}")
    if inp.target_hourly_usd < 0:
        raise DecideError(f"target_hourly_usd must be >= 0, got {inp.target_hourly_usd}")
    if inp.minutes_per_unit < 0:
        raise DecideError(f"minutes_per_unit must be >= 0, got {inp.minutes_per_unit}")
    # Costs may be 0 (edge case), but never negative.
    for field in (
        "purchase_price_usd",
        "sell_price_usd",
        "shipping_per_unit_usd",
        "flight_cost_usd",
        "hotel_cost_usd",
        "other_trip_cost_usd",
    ):
        if getattr(inp, field) < 0:
            raise DecideError(f"{field} must be >= 0, got {getattr(inp, field)}")
