"""Round 18 demo — 异步双线采购 + 周末来回决策 (假数据版).

Standalone smoke test for the new model sketched in
``projects/jp-us-arb-route/ideas.md`` 2026-08-15 entry.

目的: 给一个新 dataclass 集合 + 一个 ``decide_weekend()`` 函数的最小可运行版本,
跑两遍 — 一次 jp_to_cn 有货(FLY),一次只有 cn_to_jp 占位(SKIP),验证
「值不值得飞」+「几点飞/回来」都能在一份输出里看见。

不做的事:
  - 不动 DB schema (round 17 那套 routes/skus 表先不动)
  - 不接 Amadeus (flight_price.py 现成的 search_flights() 这里只是占位)
  - 不写 pytest (demo 而非测试;真表迁移放 round 18 spec)

运行: ``python3 -m arb.demo_round18`` 在 /Volumes/SanDisk2TB/jp-us-arb-route 下。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


# ---------- dataclasses (草案;真正落库前 round 18 schema 会再细化) ----------

@dataclass(frozen=True)
class Leg:
    """One flight leg (单程)."""
    origin: str           # IATA, e.g. "PVG"
    dest: str             # IATA, e.g. "NRT"
    depart_at: str        # ISO 8601 local time, e.g. "2026-08-22T18:00"
    arrive_at: str        # ISO 8601 local time
    price_usd: float      # 经济舱 / 普通票
    cabin: str = "ECONOMY"
    carrier: str = "?"
    flight_no: str = "?"


@dataclass(frozen=True)
class TripWindow:
    """A weekend trip window (out + back)."""
    leg_out: Leg
    leg_back: Leg
    label: str = ""       # e.g. "this weekend (Aug 22-24)"

    @property
    def total_flight_usd(self) -> float:
        return self.leg_out.price_usd + self.leg_back.price_usd

    @property
    def depart_date(self) -> str:
        return self.leg_out.depart_at[:10]

    @property
    def return_date(self) -> str:
        return self.leg_back.depart_at[:10]


Direction = Literal["jp_to_cn", "cn_to_jp"]


@dataclass(frozen=True)
class SkuLine:
    """One SKU line within an inventory pool."""
    sku: str
    units: int
    unit_savings_usd: float   # savings per unit AFTER shipping/tariff/processing
    unit_weight_kg: float
    unit_volume_l: float
    note: str = ""


@dataclass
class InventoryPool:
    """Direction-scoped inventory waiting to be carried over."""
    direction: Direction
    lines: list[SkuLine] = field(default_factory=list)

    @property
    def total_value_usd(self) -> float:
        return sum(L.units * L.unit_savings_usd for L in self.lines)

    @property
    def total_weight_kg(self) -> float:
        return sum(L.units * L.unit_weight_kg for L in self.lines)

    @property
    def total_volume_l(self) -> float:
        return sum(L.units * L.unit_volume_l for L in self.lines)

    def summary_rows(self) -> list[str]:
        rows = []
        for L in self.lines:
            rows.append(
                f"  {L.sku:<20} ×{L.units:<3}  "
                f"unit_save=${L.unit_savings_usd:>7.0f}  "
                f"line_save=${L.units * L.unit_savings_usd:>7.0f}  "
                f"weight={L.units * L.unit_weight_kg:.1f}kg"
            )
        return rows


@dataclass(frozen=True)
class TripDecision:
    """Final verdict for a candidate trip window given the pool state."""
    window: TripWindow
    pools: dict[Direction, InventoryPool]
    flight_cost_usd: float
    total_savings_usd: float
    weekend_net_usd: float
    payback_pct: float
    luggage_ok: bool
    luggage_used_kg: float
    luggage_cap_kg: float
    level: Literal["建议", "谨慎", "不建议"]
    reason: str


# ---------- decision (pure function, mirrors decision.judge() style) ----------

def decide_weekend(
    window: TripWindow,
    pools: dict[Direction, InventoryPool],
    *,
    luggage_cap_kg: float = 23.0,
    fx_jpy_per_usd: float = 150.0,           # placeholder, not used this round
    fx_cny_per_usd: float = 7.20,            # placeholder, not used this round
) -> TripDecision:
    """Pure function — no I/O. Mirrors ``arb.decision.judge`` style and
    level precedence (不建议 < 谨慎 < 建议).

    Metrics:
      total_savings_usd = sum of unit_savings across both pools
      weekend_net_usd   = total_savings - flight_cost
      payback_pct       = total_savings / flight_cost * 100
      luggage_ok        = (sum of pool weights) <= luggage_cap_kg

    Level cascade:
      - any pool exceeds luggage cap            -> "不建议" (overweight)
      - payback_pct < 50                        -> "不建议"
      - payback_pct < 100                       -> "谨慎"
      - else                                    -> "建议"
    """
    flight_cost = window.total_flight_usd
    pools_total_savings = sum(p.total_value_usd for p in pools.values())
    pools_total_weight = sum(p.total_weight_kg for p in pools.values())

    luggage_ok = pools_total_weight <= luggage_cap_kg
    if flight_cost > 0:
        payback = pools_total_savings / flight_cost * 100.0
    else:
        payback = float("inf") if pools_total_savings > 0 else 0.0

    weekend_net = pools_total_savings - flight_cost

    if not luggage_ok:
        level = "不建议"
        reason = (
            f"超重: 两 pool 共 {pools_total_weight:.1f}kg > 行李额 "
            f"{luggage_cap_kg:.0f}kg (若拆行则可降,本次直接不飞)"
        )
    elif pools_total_savings <= 0:
        level = "不建议"
        reason = "两 pool 都没有有效节省,白飞"
    elif payback < 50.0:
        level = "不建议"
        reason = f"回本率 {payback:.1f}% < 50%,机票钱都赚不回来"
    elif payback < 100.0:
        level = "谨慎"
        reason = f"回本率 {payback:.1f}% < 100%,机票一半能省回"
    else:
        level = "建议"
        reason = f"回本率 {payback:.1f}% ≥ 100%,机票全回收还有结余"

    return TripDecision(
        window=window,
        pools=pools,
        flight_cost_usd=flight_cost,
        total_savings_usd=pools_total_savings,
        weekend_net_usd=weekend_net,
        payback_pct=payback,
        luggage_ok=luggage_ok,
        luggage_used_kg=pools_total_weight,
        luggage_cap_kg=luggage_cap_kg,
        level=level,
        reason=reason,
    )


# ---------- pretty print ----------

def _fmt_money(usd: float) -> str:
    return f"${usd:,.0f}"


def render_decision(d: TripDecision) -> str:
    w = d.window
    out = []
    out.append(f"\n## TripDecision — {w.label}")
    out.append("")
    out.append("### Window")
    out.append(
        f"  Out  : {w.leg_out.carrier} {w.leg_out.flight_no:<5}  "
        f"{w.leg_out.origin} → {w.leg_out.dest}  "
        f"{w.leg_out.depart_at} → {w.leg_out.arrive_at}  "
        f"{_fmt_money(w.leg_out.price_usd)}"
    )
    out.append(
        f"  Back : {w.leg_back.carrier} {w.leg_back.flight_no:<5}  "
        f"{w.leg_back.origin} → {w.leg_back.dest}  "
        f"{w.leg_back.depart_at} → {w.leg_back.arrive_at}  "
        f"{_fmt_money(w.leg_back.price_usd)}"
    )
    out.append(f"  Total flight cost: {_fmt_money(d.flight_cost_usd)}")
    out.append("")

    for direction, pool in d.pools.items():
        out.append(f"### Pool — {direction}")
        if not pool.lines:
            out.append("  (empty — this lane is future-only in round 18 demo)")
        else:
            for row in pool.summary_rows():
                out.append(row)
        out.append(
            f"  -- pool subtotal: savings={_fmt_money(pool.total_value_usd)}, "
            f"weight={pool.total_weight_kg:.1f}kg, "
            f"vol={pool.total_volume_l:.1f}L"
        )
        out.append("")

    out.append("### Verdict")
    out.append(f"  total_savings_usd : {_fmt_money(d.total_savings_usd)}")
    out.append(f"  flight_cost_usd   : {_fmt_money(d.flight_cost_usd)}")
    out.append(f"  weekend_net_usd   : {_fmt_money(d.weekend_net_usd)}")
    out.append(f"  payback_pct       : {d.payback_pct:.1f}%")
    out.append(
        f"  luggage           : {d.luggage_used_kg:.1f}kg / {d.luggage_cap_kg:.0f}kg  "
        f"({'OK' if d.luggage_ok else 'OVER'})"
    )
    out.append(f"  level             : {d.level}")
    out.append(f"  reason            : {d.reason}")
    out.append("")
    return "\n".join(out)


# ---------- sample data ----------

def _make_window_hot() -> TripWindow:
    """Hot weekend 8/22-8/24, round trip PVG↔NRT. ¥3000 each way ≈ $290."""
    leg_out = Leg(
        origin="PVG", dest="NRT",
        depart_at="2026-08-22T18:00", arrive_at="2026-08-22T22:30",
        price_usd=290.0, carrier="NH", flight_no="NH920",
    )
    leg_back = Leg(
        origin="NRT", dest="PVG",
        depart_at="2026-08-24T14:00", arrive_at="2026-08-24T16:30",
        price_usd=290.0, carrier="NH", flight_no="NH921",
    )
    return TripWindow(leg_out=leg_out, leg_back=leg_back,
                      label="this weekend (Aug 22-24)")


def _make_pools_hot_jp_to_cn() -> InventoryPool:
    return InventoryPool(
        direction="jp_to_cn",
        lines=[
            SkuLine(sku="SK-II 神仙水 230ml", units=5,
                    unit_savings_usd=31.0,   # 5×(185-150-4) = $155, /5 = $31
                    unit_weight_kg=0.5, unit_volume_l=0.4,
                    note="Spot check from latest.md R13"),
            SkuLine(sku="Albion Excia 乳液", units=3,
                    unit_savings_usd=394.0,  # (555-153-8) = $394
                    unit_weight_kg=0.8, unit_volume_l=0.6,
                    note="High-value, payback-friendly"),
        ],
    )


def _make_pools_empty() -> dict[Direction, InventoryPool]:
    """Reverse scenario: cn_to_jp lane is placeholder only."""
    return {
        "jp_to_cn": InventoryPool(direction="jp_to_cn", lines=[]),
        "cn_to_jp": InventoryPool(direction="cn_to_jp", lines=[]),
    }


# ---------- main ----------

def main() -> None:
    print("=" * 64)
    print("Round 18 demo — 异步双线采购 + 周末来回决策")
    print("=" * 64)

    # Scenario A: hot jp_to_cn pool
    window_a = _make_window_hot()
    pools_a = {
        "jp_to_cn": _make_pools_hot_jp_to_cn(),
        "cn_to_jp": InventoryPool(direction="cn_to_jp", lines=[]),
    }
    dec_a = decide_weekend(window_a, pools_a)
    print(render_decision(dec_a))

    # Scenario B: both empty — should SKIP
    pools_b = _make_pools_empty()
    dec_b = decide_weekend(window_a, pools_b)
    print(render_decision(dec_b))

    # Scenario C: overweight — should also SKIP even with high payback
    fake_heavy = InventoryPool(
        direction="jp_to_cn",
        lines=[
            SkuLine(sku="HEAVYBOX-30kg", units=1,
                    unit_savings_usd=800.0,
                    unit_weight_kg=30.0, unit_volume_l=50.0,
                    note="Stress test the luggage gate"),
        ],
    )
    dec_c = decide_weekend(window_a, {"jp_to_cn": fake_heavy,
                                       "cn_to_jp": InventoryPool(direction="cn_to_jp", lines=[])})
    print(render_decision(dec_c))

    print("Done. Round 18 demo complete — schema not yet committed.")


if __name__ == "__main__":
    main()
