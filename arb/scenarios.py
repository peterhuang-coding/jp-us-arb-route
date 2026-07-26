"""Scenario layer: 保守 / 中性 / 乐观 three-tier decision analysis.

Wraps ``arb.decision.judge()`` so the per-trip report can show a band of
plausible outcomes instead of a single point estimate. Directly addresses
Goal Brief §10 risk row #4 ("用户真实利润与估算偏差大 → 决策报告里给
保守/中性/乐观三档").

Public API:
  * ScenarioShifts   : multipliers applied to a DecisionInputs
  * ScenarioResult   : per-band verdict + deltas vs 中性 + cross-check hint
  * DEFAULT_SCENARIOS: ordered list [保守, 中性, 乐观] of default multipliers
  * apply_shifts()   : returns a new DecisionInputs with shifts applied
  * summarize()      : returns 3 ScenarioResults in fixed order

All functions are pure — no I/O, no globals.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .decision import Decision, DecisionInputs, judge


# ---------- scenario band ----------

@dataclass(frozen=True)
class ScenarioShifts:
    """Multipliers applied to a DecisionInputs to model a band.

    factor < 1.0 → pessimism for revenue (sell_price_factor), optimism for costs.
    factor > 1.0 → optimism for revenue, pessimism for costs.

    Defaults are all 1.0 (neutral).
    """
    sell_price_factor: float = 1.0
    purchase_price_factor: float = 1.0
    tariff_factor: float = 1.0
    shipping_factor: float = 1.0
    flight_factor: float = 1.0
    hotel_factor: float = 1.0
    minutes_per_unit_factor: float = 1.0
    target_hourly_factor: float = 1.0


@dataclass(frozen=True)
class ScenarioResult:
    """One band's verdict + deltas vs the neutral band."""
    name: str                                  # "保守" / "中性" / "乐观"
    description: str                           # 一句话说明
    shifts: ScenarioShifts
    decision: Decision                         # output of judge() under shifts
    delta_roi_pct: float                       # roi_pct - neutral_roi_pct
    delta_net_profit: float                    # net_profit_usd - neutral_net_profit_usd
    cross_check: str = ""                      # downgrade / upgrade hint vs neutral

    def as_dict(self) -> dict:
        d = {
            "name": self.name,
            "description": self.description,
            "shifts": {
                "sell_price_factor": self.shifts.sell_price_factor,
                "purchase_price_factor": self.shifts.purchase_price_factor,
                "tariff_factor": self.shifts.tariff_factor,
                "shipping_factor": self.shifts.shipping_factor,
                "flight_factor": self.shifts.flight_factor,
                "hotel_factor": self.shifts.hotel_factor,
                "minutes_per_unit_factor": self.shifts.minutes_per_unit_factor,
                "target_hourly_factor": self.shifts.target_hourly_factor,
            },
            "level": self.decision.level,
            "reason": self.decision.reason,
            "roi_pct": self.decision.roi_pct,
            "net_profit_usd": self.decision.net_profit_usd,
            "total_revenue_usd": self.decision.total_revenue_usd,
            "total_cost_usd": self.decision.total_cost_usd,
            "breakeven_sell_price_usd": self.decision.breakeven_sell_price_usd,
            "hours_used": self.decision.hours_used,
            "delta_roi_pct": self.delta_roi_pct,
            "delta_net_profit": self.delta_net_profit,
            "cross_check": self.cross_check,
        }
        return d


# ---------- default shifts (tuned per Goal Brief §10 risk row #4) ----------

# 售价 -10%, 采购 +5%, 关税 +10%, 物流 +10%, 机票 +10%, 酒店 +10%, 时薪 +20%
CONSERVATIVE_SHIFTS = ScenarioShifts(
    sell_price_factor=0.90,
    purchase_price_factor=1.05,
    tariff_factor=1.10,
    shipping_factor=1.10,
    flight_factor=1.10,
    hotel_factor=1.10,
    minutes_per_unit_factor=1.00,
    target_hourly_factor=1.20,
)

NEUTRAL_SHIFTS = ScenarioShifts()

# 售价 +5%, 采购 -3%, 机票 -5%, 酒店 -5%, 时薪 -10%
OPTIMISTIC_SHIFTS = ScenarioShifts(
    sell_price_factor=1.05,
    purchase_price_factor=0.97,
    tariff_factor=1.00,
    shipping_factor=1.00,
    flight_factor=0.95,
    hotel_factor=0.95,
    minutes_per_unit_factor=1.00,
    target_hourly_factor=0.90,
)


DEFAULT_SCENARIOS: list[ScenarioShifts] = [
    CONSERVATIVE_SHIFTS,
    NEUTRAL_SHIFTS,
    OPTIMISTIC_SHIFTS,
]


# ---------- band labels / descriptions ----------

_BAND_NAMES = ["保守", "中性", "乐观"]
_BAND_DESCRIPTIONS = [
    "保守 (下行): 售价 -10%, 成本 +5~10%, 时薪 +20% — 模拟市场降温与采购涨价。",
    "中性 (基线): 所有倍数 = 1.0,等同当前 judge() 单点判定。",
    "乐观 (上行): 售价 +5%, 采购 -3%, 机票/酒店 -5%, 时薪 -10% — 模拟压价成功与时间节省。",
]

# Lower rank number = stricter decision
_LEVEL_RANK = {"建议": 0, "谨慎": 1, "不建议": 2}


def _level_rank(level: str) -> int:
    return _LEVEL_RANK.get(level, 99)


def _cross_check(neutral_level: str, this_level: str, band_name: str) -> str:
    """Produce downgrade / upgrade / noop hint for this band relative to neutral.

    Goal: surface worst-case level so the user sees that the verdict can shift.
    """
    nr = _level_rank(neutral_level)
    tr = _level_rank(this_level)
    if tr > nr:
        return (
            f"⚠️ 保守场景下决策从「{neutral_level}」降级到「{this_level}」"
            " — 最坏情况下本趟出差可能不值得。"
        )
    if tr < nr and band_name == "乐观":
        return (
            f"✅ 乐观场景下决策从「{neutral_level}」改善到「{this_level}」"
            " — 顺利执行时本趟出差更值得。"
        )
    return ""


# ---------- public API ----------

def apply_shifts(inp: DecisionInputs, shifts: ScenarioShifts) -> DecisionInputs:
    """Return a new DecisionInputs with multipliers applied.

    Re-runs DecisionInputs validation via judge() downstream — invalid combos
    (e.g. zeroed price) will surface as DecideError from judge().
    """
    return replace(
        inp,
        purchase_price_usd=inp.purchase_price_usd * shifts.purchase_price_factor,
        sell_price_usd=inp.sell_price_usd * shifts.sell_price_factor,
        tariff_rate=inp.tariff_rate * shifts.tariff_factor,
        shipping_per_unit_usd=inp.shipping_per_unit_usd * shifts.shipping_factor,
        flight_cost_usd=inp.flight_cost_usd * shifts.flight_factor,
        hotel_cost_usd=inp.hotel_cost_usd * shifts.hotel_factor,
        minutes_per_unit=inp.minutes_per_unit * shifts.minutes_per_unit_factor,
        target_hourly_usd=inp.target_hourly_usd * shifts.target_hourly_factor,
    )


def summarize(
    inp: DecisionInputs,
    custom_shifts: Optional[list[ScenarioShifts]] = None,
) -> list[ScenarioResult]:
    """Run judge() under each scenario band and return 3 ScenarioResults.

    Order is fixed: [保守, 中性, 乐观]. Neutral always matches plain judge(inp).
    """
    shifts_list = custom_shifts if custom_shifts is not None else DEFAULT_SCENARIOS
    if len(shifts_list) != 3:
        raise ValueError(
            f"expected 3 scenario bands, got {len(shifts_list)}"
        )

    # Compute neutral first so we can compute deltas.
    neutral_inp = apply_shifts(inp, shifts_list[1])
    neutral_decision = judge(neutral_inp)

    out: list[ScenarioResult] = []
    for idx, shifts in enumerate(shifts_list):
        band_inp = apply_shifts(inp, shifts)
        decision = judge(band_inp)
        result = ScenarioResult(
            name=_BAND_NAMES[idx],
            description=_BAND_DESCRIPTIONS[idx],
            shifts=shifts,
            decision=decision,
            delta_roi_pct=decision.roi_pct - neutral_decision.roi_pct,
            delta_net_profit=decision.net_profit_usd - neutral_decision.net_profit_usd,
            cross_check=_cross_check(
                neutral_decision.level, decision.level, _BAND_NAMES[idx]
            ),
        )
        out.append(result)
    return out