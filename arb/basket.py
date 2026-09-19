"""5000元 额度内最优购物清单求解器 (Round 13).

Given a budget (typically how much you want to spend) and a customs
duty-free cap (typically 5000元 for Chinese入境), find the multi-SKU
purchase plan that maximizes total self-use savings.

This is a bounded 0/1 knapsack: each SKU can be taken 0..max_units times,
weight is JP purchase price in CNY per unit, value is per-unit savings
(home CNY − JP CNY − tariff − shipping, all converted to CNY). Capacity
is min(budget, customs_limit) — both are hard caps.

The solver uses an exact sparse Pareto frontier in the decimal-string monetary
values supplied by the caller. It never rounds item costs to whole CNY. Work
and state limits raise ValueError rather than return an approximate basket.
Worst-case state growth is exponential; runtime depends on the input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
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


def _finite_number(x) -> bool:
    """Return True only for finite, non-boolean int/float-like numeric inputs."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except (OverflowError, TypeError):
        return False


def _decimal_string_fraction(x) -> Fraction:
    """Exact Fraction from the caller-visible decimal representation of a float."""
    return Fraction(Decimal(str(x)))


def _prune(states: dict[int, tuple[int, tuple[tuple[int, int], ...]]]):
    """Remove states dominated by another no-more-costly, at-least-valuable state."""
    ordered = sorted(states.items(), key=lambda kv: (kv[0], -kv[1][0]))
    kept: dict[int, tuple[int, tuple[tuple[int, int], ...]]] = {}
    best_value: int | None = None

    for cost, payload in ordered:
        value = payload[0]
        if best_value is None or value > best_value:
            kept[cost] = payload
            best_value = value

    return kept

def solve_basket(
    items: Iterable[BasketItem],
    *,
    budget_cny: float = 5000.0,
    customs_limit_cny: float = 5000.0,
    trip_cost_usd: float = 0.0,
    fx_rate: float = 0.14,
) -> BasketSolution:
    """Solve the bounded knapsack with an exact, bounded sparse DP frontier."""
    notes: list[str] = []
    skipped: list[str] = []

    for name, value in (
        ("budget_cny", budget_cny),
        ("customs_limit_cny", customs_limit_cny),
        ("trip_cost_usd", trip_cost_usd),
        ("fx_rate", fx_rate),
    ):
        if not _finite_number(value):
            raise ValueError(f"{name} must be a finite number")

    if fx_rate <= 0:
        raise ValueError("fx_rate must be positive")
    if trip_cost_usd < 0:
        raise ValueError("trip_cost_usd must be non-negative")

    def empty(notes_out: list[str]) -> BasketSolution:
        return BasketSolution(
            picks=[],
            total_spend_cny=0.0,
            total_savings_cny=0.0,
            budget_cny=budget_cny,
            customs_limit_cny=customs_limit_cny,
            fx_rate=fx_rate,
            trip_cost_usd=trip_cost_usd,
            payback_rate_pct=0.0,
            leftover_cny=float(budget_cny),
            customs_headroom_cny=float(customs_limit_cny),
            capacity_used_cny=0.0,
            algorithm="dp-bounded-knapsack",
            notes=notes_out,
            skipped_skus=skipped,
        )

    if budget_cny <= 0 or customs_limit_cny <= 0:
        return empty(["budget 和 customs_limit 都为 0"])

    parsed: list[tuple[BasketItem, Fraction, Fraction]] = []
    denominators: list[int] = []

    for it in items:
        reason = None
        if (
            not _finite_number(it.jp_price_per_unit_cny)
            or not _finite_number(it.home_price_per_unit_cny)
            or not _finite_number(it.savings_per_unit_cny)
        ):
            reason = "missing price"
        elif not isinstance(it.max_units, int) or isinstance(it.max_units, bool):
            reason = "max_units must be an integer quantity"
        elif it.home_price_per_unit_cny <= 0 or it.jp_price_per_unit_cny <= 0:
            reason = "missing price"
        elif it.savings_per_unit_cny <= 0:
            reason = f"savings_per_unit_cny={it.savings_per_unit_cny:.2f} ≤ 0"
        elif it.max_units < 1:
            reason = "max_units < 1"

        if reason:
            skipped.append(f"{it.sku}: {reason}")
            continue

        cost = _decimal_string_fraction(it.jp_price_per_unit_cny)
        value = _decimal_string_fraction(it.savings_per_unit_cny)
        if cost <= 0 or value <= 0:
            skipped.append(f"{it.sku}: missing price")
            continue
        parsed.append((it, cost, value))
        denominators.extend((cost.denominator, value.denominator))

    cap_frac = _decimal_string_fraction(min(budget_cny, customs_limit_cny))
    if cap_frac <= 0:
        return empty(["budget 和 customs_limit 都为 0"])
    denominators.append(cap_frac.denominator)

    scale = 1
    for denominator in denominators:
        scale = math.lcm(scale, denominator)

    cap_scaled = int(cap_frac * scale)
    eligible: list[tuple[BasketItem, int, int, int, Fraction, Fraction]] = []
    for it, cost, value in parsed:
        cost_scaled = int(cost * scale)
        value_scaled = int(value * scale)
        bound = min(it.max_units, cap_scaled // cost_scaled)
        eligible.append((it, cost_scaled, value_scaled, bound, cost, value))

    if not eligible:
        return empty(["无符合条件 SKU"])

    MAX_STATES = 50_000
    MAX_TRANSITIONS = 2_000_000

    State = tuple[int, tuple[tuple[int, int], ...]]
    frontier: dict[int, State] = {0: (0, ())}
    transitions = 0

    for idx, (_, cost_scaled, value_scaled, bound, _, _) in enumerate(eligible):
        if bound <= 0:
            continue

        candidates: dict[int, State] = dict(frontier)
        old_states = list(frontier.items())

        for old_cost, (old_value, old_choice) in old_states:
            for qty in range(1, bound + 1):
                new_cost = old_cost + cost_scaled * qty

                if new_cost > cap_scaled:
                    break

                transitions += 1
                if transitions > MAX_TRANSITIONS:
                    raise ValueError(
                        "exact basket solve could not complete within configured "
                        "state/transition bounds"
                    )

                existing = candidates.get(new_cost)
                if existing is None and len(candidates) >= MAX_STATES:
                    raise ValueError(
                        "exact basket solve could not complete within configured "
                        "state/transition bounds"
                    )

                new_value = old_value + value_scaled * qty

                if existing is None or new_value > existing[0]:
                    candidates[new_cost] = (
                        new_value,
                        old_choice + ((idx, qty),),
                    )

        frontier = _prune(candidates)
        if len(frontier) > MAX_STATES:
            raise ValueError(
                "exact basket solve could not complete within configured "
                "state/transition bounds"
            )

    best_cost = 0
    best_value = -1
    best_choice: tuple[tuple[int, int], ...] = ()
    for cost, (value, choice) in frontier.items():
        if value > best_value or (value == best_value and cost < best_cost):
            best_cost = cost
            best_value = value
            best_choice = choice

    if best_value < 0:
        best_cost = 0
        best_value = 0
        best_choice = ()

    selected: dict[int, int] = dict(best_choice)
    picks = [
        _item_to_pick(it, selected[idx])
        for idx, (it, _, _, bound, _, _) in enumerate(eligible)
        if bound > 0 and selected.get(idx, 0) > 0
    ]
    picks.sort(
        key=lambda p: p.savings_per_unit_cny / p.jp_price_per_unit_cny,
        reverse=True,
    )

    exact_cost = Fraction(best_cost, scale)
    exact_savings = Fraction(best_value, scale)
    try:
        total_spend = float(exact_cost)
        total_savings = float(exact_savings)
    except OverflowError as exc:
        raise ValueError("selected basket produced a non-finite monetary total") from exc
    if not math.isfinite(total_spend) or not math.isfinite(total_savings):
        raise ValueError("selected basket produced a non-finite monetary total")

    if trip_cost_usd > 0:
        trip_cost_cny = trip_cost_usd / fx_rate
        payback = (
            total_savings / trip_cost_cny * 100.0 if trip_cost_cny > 0 else 0.0
        )
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
        leftover_cny=float(budget_cny) - total_spend,
        customs_headroom_cny=float(customs_limit_cny) - total_spend,
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

    Quantity handling: a missing or None max_units_per_trip defaults to 50.
    Explicit 0 is preserved so the solver can skip the row. Booleans and
    fractional numbers are left as their raw values rather than truncated;
    solve_basket treats those non-integer capacities as invalid rows and
    skips them. Integer strings and exactly-integral floats are accepted
    for compatibility with previously accepted table input.
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

    raw_max_units = opp.get("max_units_per_trip")
    if raw_max_units is None:
        max_units = 50
    elif isinstance(raw_max_units, bool):
        # Never coerce bool through int(); preserve it so the strict solver skips the row.
        max_units = raw_max_units
    elif isinstance(raw_max_units, int):
        max_units = raw_max_units
    elif isinstance(raw_max_units, float) and raw_max_units.is_integer():
        max_units = int(raw_max_units)
    elif isinstance(raw_max_units, str):
        try:
            max_units = int(raw_max_units.strip())
        except (TypeError, ValueError):
            max_units = raw_max_units
    else:
        max_units = raw_max_units

    return BasketItem(
        sku=opp["sku"],
        name=opp["name"],
        category=opp["category"],
        jp_price_per_unit_cny=jp_cny,
        home_price_per_unit_cny=home_used,
        savings_per_unit_cny=savings_cny,
        max_units=max_units,
        purchase_price_usd=opp["purchase_price_usd"],
        home_price_cny=home_cny,
        sell_price_usd=opp["sell_price_usd"],
        fx_rate=fx_rate,
    )
