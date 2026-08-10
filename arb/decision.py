"""Pure-function decision engine.

The judge() function returns a Decision object with explicit level, reason,
and the numbers that drove the call. No I/O, no globals — testable in isolation.

SPEC (Round 13: flipped from resale ROI to self-use trip payback):

level precedence:
  1. num_units > max_units_per_trip                       -> "不建议"
  2. payback_rate_pct < 50                                -> "不建议"
  3. payback_rate_pct < 100                               -> "谨慎"
  4. otherwise                                             -> "建议"

The metric: how much of the trip cost does shopping recover? Time is no
longer an opportunity cost (leisure trip), and the comparison baseline is
what the item would cost in China (``home_price_usd``) — not what it would
fetch on eBay. ``payback_rate_pct = (savings - trip_cost) / trip_cost * 100``
when framed as net, or ``savings / trip_cost * 100`` for the gross rate we
use here. >=100% means the trip is fully covered.

Note on currency: every monetary input is USD.  The CLI/API is responsible
for converting home_price_cny to USD via cn_to_usd_fx before calling judge.
``home_price_usd`` falls back to ``sell_price_usd`` when the caller passes
``None``, preserving backward compatibility for research SKUs that don't
have a self-use baseline yet.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal, Optional


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
    target_hourly_usd: float = 0.0          # no longer used in math; kept for API stability
    target_roi_pct: float = 15.0            # legacy, unused under payback model
    min_roi_pct: float = 10.0               # legacy, unused under payback model
    success_rate: float = 1.0               # self-use = 1.0 (you use what you buy)
    home_price_usd: Optional[float] = None  # self-use baseline; None → fall back to sell_price_usd
    max_units_per_trip: int = 50            # per-SKU carry cap


@dataclass(frozen=True)
class Decision:
    level: Level
    reason: str
    roi_pct: float                          # now = trip_net_value_usd / trip_cost_usd * 100
    net_profit_usd: float                   # alias for trip_net_value_usd (backward compat)
    total_cost_usd: float                   # trip_cost (the threshold)
    total_revenue_usd: float                # = total_savings_usd (backward-compat naming)
    breakeven_sell_price_usd: float         # breakeven home price in USD
    hours_used: float                       # minutes_per_unit * num_units / 60
    per_unit_cost_usd: float                # = purchase + tariff + shipping (no time, no platform)
    per_unit_revenue_usd: float             # = home_price_usd - per_unit_cost_usd
    # ---- Round 13: payback-specific ----
    total_savings_usd: float                # per_unit_savings * num_units
    trip_net_value_usd: float               # total_savings - trip_cost
    payback_rate_pct: float                 # total_savings / trip_cost * 100

    def as_dict(self) -> dict:
        return asdict(self)


# ---------- public API ----------

def judge(inp: DecisionInputs) -> Decision:
    _validate(inp)

    # Resolve self-use home price in USD. Fallback: legacy sell_price_usd.
    home_usd = inp.home_price_usd if inp.home_price_usd is not None else inp.sell_price_usd

    per_unit_cost_no_trip = (
        inp.purchase_price_usd
        + inp.purchase_price_usd * inp.tariff_rate
        + inp.shipping_per_unit_usd
    )
    # Self-use savings: what you'd pay at home minus what you pay in Japan.
    # No platform fee, no success-rate haircut — you consume what you buy.
    per_unit_savings_usd = home_usd - per_unit_cost_no_trip
    per_unit_revenue_usd = per_unit_savings_usd  # alias for backward compat

    trip_cost = (
        inp.flight_cost_usd
        + inp.hotel_cost_usd
        + inp.other_trip_cost_usd
    )

    total_savings = per_unit_savings_usd * inp.num_units
    trip_net_value = total_savings - trip_cost
    if trip_cost > 0:
        payback_rate_pct = (total_savings / trip_cost) * 100.0
    elif total_savings > 0:
        payback_rate_pct = float("inf")
    else:
        payback_rate_pct = 0.0

    # Legacy "ROI" now reframes as: net value of the trip as a % of trip cost.
    # Keeps the SPA's ROI bar and metric tile working without code changes.
    roi_pct = (trip_net_value / trip_cost * 100.0) if trip_cost > 0 else 0.0

    hours_used = (inp.num_units * inp.minutes_per_unit) / 60.0

    # Breakeven home price: above this, the trip nets positive. No fee/success haircut.
    if inp.num_units > 0:
        breakeven_home = per_unit_cost_no_trip + (trip_cost / inp.num_units)
    else:
        breakeven_home = float("inf")

    # ---------- level cascade (highest priority first) ----------
    if inp.num_units > inp.max_units_per_trip:
        level: Level = "不建议"
        reason = (
            f"购买数量 {inp.num_units} 超过单 SKU 携带上限 {inp.max_units_per_trip}。"
        )
    elif payback_rate_pct < 50.0:
        level = "不建议"
        reason = (
            f"回本率 {payback_rate_pct:.1f}% < 50%,购物只能覆盖不到一半行程,"
            f"不值得为这点差价跑一趟。"
        )
    elif payback_rate_pct < 100.0:
        level = "谨慎"
        reason = (
            f"回本率 {payback_rate_pct:.1f}% 介于 50–100% 之间,"
            f"行程部分回本,净支出 ${abs(trip_net_value):,.2f}。"
        )
    else:
        level = "建议"
        reason = (
            f"回本率 {payback_rate_pct:.1f}% ≥ 100%,行程完全回本,"
            f"净赚 ${trip_net_value:,.2f} USD。"
        )

    return Decision(
        level=level,
        reason=reason,
        roi_pct=roi_pct,
        net_profit_usd=trip_net_value,
        total_cost_usd=trip_cost,
        total_revenue_usd=total_savings,
        breakeven_sell_price_usd=breakeven_home,
        hours_used=hours_used,
        per_unit_cost_usd=per_unit_cost_no_trip,
        per_unit_revenue_usd=per_unit_revenue_usd,
        total_savings_usd=total_savings,
        trip_net_value_usd=trip_net_value,
        payback_rate_pct=payback_rate_pct,
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
    # legacy ROI thresholds no longer used but still validated
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
    if inp.max_units_per_trip < 1:
        raise DecideError(
            f"max_units_per_trip must be >= 1, got {inp.max_units_per_trip}"
        )
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
