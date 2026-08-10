"""5000元 额度内最优购物清单求解器 (Round 13).

Given a budget (typically how much you want to spend) and a customs
duty-free cap (typically 5000元 for Chinese入境), find the multi-SKU
purchase plan that maximizes total self-use savings.

This is a bounded 0/1 knapsack: each SKU can be taken 0..max_units times,
weight is JP purchase price in CNY per unit, value is per-unit savings
(home CNY − JP CNY − tariff − shipping, all converted to CNY). Capacity
is min(budget, customs_limit) — both are hard caps.

Algorithm: classic DP.  For 42 SKUs × 50 unit cap × 5000 capacity, the
state table is (43 × 5001) ≈ 215K cells; each cell transition considers
up to max_units options.  Total ops ≈ 10.5M; runs in <1s in CPython.
Reconstruction walks the table backward picking optimal unit counts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class BasketItem:
    """One opportunity prepared for the solver.

    All CNY-denominated fields are floats.  Items with savings_per_unit_cny
    <= 0 are skipped before reaching the DP — they can never contribute to
    the optimum and would waste capacity.
    """
    sku: str
    name: str
    category: str
    jp_price_per_unit_cny: float     # what you pay in Japan (per unit, CNY)
    home_price_per_unit_cny: float    # what you'd pay in China (per unit, CNY)
    savings_per_unit_cny: float       # home - jp - tariff*jp - shipping*fx (CNY)
    max_units: int                    # carry cap for this SKU
    # Diagnostics for the report
    purchase_price_usd: float
    home_price_cny: Optional[float]   # None means we fell back to sell_price_usd * fx
    sell_price_usd: float
    fx_rate: float


@dataclass(frozen=True)
class BasketPick:
    sku: str
    name: str
    category: str
    num_units: int
    jp_price_per_unit_cny: float
    home_price_per_unit_cny: float
    savings_per_unit_cny: float
    subtotal_cny: float               # num_units * jp_price_per_unit_cny
    total_savings_cny: float          # num_units * savings_per_unit_cny


@dataclass(frozen=True)
class BasketSolution:
    picks: list[BasketPick]
    total_spend_cny: float
    total_savings_cny: float
    budget_cny: float
    customs_limit_cny: float
    fx_rate: float
    trip_cost_usd: float
    payback_rate_pct: float           # total_savings / trip_cost * 100
    leftover_cny: float               # budget - total_spend
    customs_headroom_cny: float       # customs_limit - total_spend
    capacity_used_cny: float          # min(budget, customs_limit) effectively used
    algorithm: str
    notes: list[str]
    skipped_skus: list[str]           # items excluded and why (no baseline, neg savings, ...)


def _item_to_pick(item: BasketItem, num_units: int) -> BasketPick:
    return BasketPick(
        sku=item.sku,
        name=item.name,
        category=item.category,
        num_units=num_units,
        jp_price_per_unit_cny=item.jp_price_per_unit_cny,
        home_price_per_unit_cny=item.home_price_per_unit_cny,
        savings_per_unit_cny=item.savings_per_unit_cny,
        subtotal_cny=num_units * item.jp_price_per_unit_cny,
        total_savings_cny=num_units * item.savings_per_unit_cny,
    )


def solve_basket(
    items: Iterable[BasketItem],
    *,
    budget_cny: float = 5000.0,
    customs_limit_cny: float = 5000.0,
    trip_cost_usd: float = 0.0,
    fx_rate: float = 0.14,
) -> BasketSolution:
    """Solve the bounded 0/1 knapsack for the optimal shopping basket.

    Parameters
    ----------
    items : iterable of BasketItem
        Already-converted items. The caller (typically ``basket_for_route``
        below) handles DB → BasketItem conversion.
    budget_cny : float
        How much you are willing to spend in JP, in CNY.
    customs_limit_cny : float
        Regulatory cap (Chinese入境 5000元 by default).  Hard cap.
    trip_cost_usd : float
        Trip cost in USD, used to compute payback rate.
    fx_rate : float
        USD↔CNY rate (default 0.14 USD per CNY, i.e. 1 CNY ≈ 0.14 USD).
    """
    notes: list[str] = []
    skipped: list[str] = []
    eligible: list[BasketItem] = []
    for it in items:
        if it.home_price_per_unit_cny <= 0 or it.jp_price_per_unit_cny <= 0:
            skipped.append(f"{it.sku}: missing price")
            continue
        if it.savings_per_unit_cny <= 0:
            skipped.append(f"{it.sku}: savings_per_unit_cny={it.savings_per_unit_cny:.2f} ≤ 0")
            continue
        if it.max_units < 1:
            skipped.append(f"{it.sku}: max_units < 1")
            continue
        eligible.append(it)

    if not eligible:
        return BasketSolution(
            picks=[],
            total_spend_cny=0.0,
            total_savings_cny=0.0,
            budget_cny=budget_cny,
            customs_limit_cny=customs_limit_cny,
            fx_rate=fx_rate,
            trip_cost_usd=trip_cost_usd,
            payback_rate_pct=0.0,
            leftover_cny=budget_cny,
            customs_headroom_cny=customs_limit_cny,
            capacity_used_cny=0.0,
            algorithm="dp-bounded-knapsack",
            notes=["无符合条件 SKU"],
            skipped_skus=skipped,
        )

    # The capacity is the harder of the two caps. We track both for reporting.
    capacity = int(min(budget_cny, customs_limit_cny))
    if capacity <= 0:
        return BasketSolution(
            picks=[],
            total_spend_cny=0.0,
            total_savings_cny=0.0,
            budget_cny=budget_cny,
            customs_limit_cny=customs_limit_cny,
            fx_rate=fx_rate,
            trip_cost_usd=trip_cost_usd,
            payback_rate_pct=0.0,
            leftover_cny=budget_cny,
            customs_headroom_cny=customs_limit_cny,
            capacity_used_cny=0.0,
            algorithm="dp-bounded-knapsack",
            notes=["budget 和 customs_limit 都为 0"],
            skipped_skus=skipped,
        )

    n = len(eligible)
    # dp[i][w] = max savings using first i items (0..i) with total spend ≤ w.
    # Stored as a flat list of size (n+1) * (capacity+1).
    W = capacity
    INF_NEG = float("-inf")
    dp: list[list[float]] = [[INF_NEG] * (W + 1) for _ in range(n + 1)]
    for w in range(W + 1):
        dp[0][w] = 0.0

    # We also need to know how many units of each item were chosen.
    # choice[i][w] = best k (0..max_units) for item i (1-indexed) at weight w.
    choice: list[list[int]] = [[0] * (W + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        item = eligible[i - 1]
        cost = int(round(item.jp_price_per_unit_cny))   # weights in integer CNY
        value = item.savings_per_unit_cny
        max_k = min(item.max_units, W // max(cost, 1))
        for w in range(W + 1):
            best_val = dp[i - 1][w]            # take 0
            best_k = 0
            # Try taking k=1..max_k of this item, if it fits
            for k in range(1, max_k + 1):
                if k * cost > w:
                    break
                cand = dp[i - 1][w - k * cost] + k * value
                if cand > best_val:
                    best_val = cand
                    best_k = k
            dp[i][w] = best_val
            choice[i][w] = best_k

    # Reconstruct at the full capacity.
    units_per_item = [0] * n
    w = W
    for i in range(n, 0, -1):
        k = choice[i][w]
        units_per_item[i - 1] = k
        w -= k * int(round(eligible[i - 1].jp_price_per_unit_cny))

    # Build pick list (drop zero-unit picks)
    picks = [
        _item_to_pick(it, units_per_item[idx])
        for idx, it in enumerate(eligible)
        if units_per_item[idx] > 0
    ]
    # Sort by savings density desc so the report reads well.
    picks.sort(key=lambda p: p.savings_per_unit_cny / p.jp_price_per_unit_cny, reverse=True)

    total_spend = sum(p.subtotal_cny for p in picks)
    total_savings = sum(p.total_savings_cny for p in picks)

    # Payback rate: total_savings in CNY, trip_cost in USD → convert.
    if trip_cost_usd > 0:
        trip_cost_cny = trip_cost_usd / fx_rate if fx_rate > 0 else 0.0
        payback = (total_savings / trip_cost_cny * 100.0) if trip_cost_cny > 0 else 0.0
    elif total_savings > 0:
        payback = float("inf")
    else:
        payback = 0.0

    return BasketSolution(
        picks=picks,
        total_spend_cny=total_spend,
        total_savings_cny=total_savings,
        budget_cny=budget_cny,
        customs_limit_cny=customs_limit_cny,
        fx_rate=fx_rate,
        trip_cost_usd=trip_cost_usd,
        payback_rate_pct=payback,
        leftover_cny=budget_cny - total_spend,
        customs_headroom_cny=customs_limit_cny - total_spend,
        capacity_used_cny=total_spend,
        algorithm="dp-bounded-knapsack",
        notes=notes,
        skipped_skus=skipped,
    )


# ---------- conversion helpers ----------

def item_from_opportunity(
    opp: dict,
    *,
    fx_rate: float = 0.14,
    fx_inverse: Optional[float] = None,
) -> BasketItem:
    """Build a BasketItem from an opportunities table row.

    CNY conversion: purchase_price_usd / fx_rate → JP price in CNY.
    home_price_cny comes from the new column (may be None) or falls back
    to sell_price_usd / fx_rate (the legacy behavior).
    """
    if fx_inverse is None:
        fx_inverse = 1.0 / fx_rate if fx_rate > 0 else 0.0
    jp_cny = opp["purchase_price_usd"] * fx_inverse
    # Tariff + shipping also convert to CNY so savings is apples-to-apples.
    tariff_cny = opp["purchase_price_usd"] * opp["tariff_rate"] * fx_inverse
    ship_cny = opp["shipping_per_unit_usd"] * fx_inverse
    home_cny = opp["home_price_cny"]  # may be None

    if home_cny is not None:
        home_used = home_cny
        savings_cny = home_used - jp_cny - tariff_cny - ship_cny
    else:
        # Fallback: use sell_price_usd converted as a proxy. Mark via home_price_cny=None
        # in the returned BasketItem so the UI knows.
        home_used = opp["sell_price_usd"] * fx_inverse
        savings_cny = home_used - jp_cny - tariff_cny - ship_cny
        home_cny = None  # keep the None marker for reporting

    return BasketItem(
        sku=opp["sku"],
        name=opp["name"],
        category=opp["category"],
        jp_price_per_unit_cny=jp_cny,
        home_price_per_unit_cny=home_used,
        savings_per_unit_cny=savings_cny,
        max_units=int(opp.get("max_units_per_trip") or 50),
        purchase_price_usd=opp["purchase_price_usd"],
        home_price_cny=home_cny,
        sell_price_usd=opp["sell_price_usd"],
        fx_rate=fx_rate,
    )
