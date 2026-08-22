"""来回采购行程推荐 — v3.4 🅲 出差代购 leg 核心。

输入:出发城市 + 目的地 + 日期窗口 + 用户预算
输出:TripRecommendation(机票 + 食宿 + 货值上限 + 推荐 SKU + ROI)

Phase 1 stub:固定路线表 + 固定日期窗口 + 估算。
Phase 2:接 Amadeus 实查 + F5 HS 码关税估算。
Phase 3:拼货多人 trip / ¥5,000 额度窗口管理。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TripRecommendation:
    origin_city: str          # PEK / PVG / CAN
    dest_city: str            # NRT / KIX / HND
    depart_date: str          # YYYY-MM-DD
    return_date: str          # YYYY-MM-DD
    weekend_match: bool       # 周五/周六去 + 周日/周一回
    flight_cost_cny: float    # 估算机票(Amadeus stub)
    hotel_food_cny: float     # 估算食宿
    total_fixed_cny: float    # 机票 + 食宿
    cargo_capacity_cny: float # ¥5,000 + ¥1,000 二次入境
    recommended_skus: list[str]
    net_roi: float            # cargo - fixed - customs_budget

    def summary(self) -> str:
        return (
            f"{self.origin_city}→{self.dest_city} "
            f"{self.depart_date}→{self.return_date} "
            f"({'周末' if self.weekend_match else '平日'}) "
            f"机票 ¥{self.flight_cost_cny:.0f} + 食宿 ¥{self.hotel_food_cny:.0f} "
            f"= ¥{self.total_fixed_cny:.0f} 固定 / ¥{self.cargo_capacity_cny:.0f} 货值 / "
            f"ROI {self.net_roi / max(self.total_fixed_cny, 1):.1f}×"
        )


# Phase 1 stub:固定路线表 + 估算(Amadeus Phase 2 接入)。
# ¥5,000 + ¥1,000 二次入境 = ¥6,000 货值上限。
TRIP_STUB_TABLE: list[TripRecommendation] = [
    TripRecommendation(
        origin_city="PEK",
        dest_city="NRT",
        depart_date="2026-09-04",  # 周五
        return_date="2026-09-07",  # 周一
        weekend_match=True,
        flight_cost_cny=2500.0,
        hotel_food_cny=1200.0,
        total_fixed_cny=3700.0,
        cargo_capacity_cny=6000.0,
        recommended_skus=["JP-PKMN-PSA", "JP-HUMANMADE-TEE-GRAPHIC", "JP-ANIME-USJ-NEZ"],
        net_roi=6000.0 - 3700.0,
    ),
    TripRecommendation(
        origin_city="PVG",
        dest_city="NRT",
        depart_date="2026-09-11",
        return_date="2026-09-14",
        weekend_match=True,
        flight_cost_cny=1800.0,
        hotel_food_cny=1200.0,
        total_fixed_cny=3000.0,
        cargo_capacity_cny=6000.0,
        recommended_skus=["JP-PKMN-151-BB", "JP-HUMANMADE-TEE-GRAPHIC"],
        net_roi=6000.0 - 3000.0,
    ),
    TripRecommendation(
        origin_city="CAN",
        dest_city="NRT",
        depart_date="2026-09-18",
        return_date="2026-09-21",
        weekend_match=True,
        flight_cost_cny=2200.0,
        hotel_food_cny=1200.0,
        total_fixed_cny=3400.0,
        cargo_capacity_cny=6000.0,
        recommended_skus=["JP-ANIME-USJ-NEZ", "JP-PKMN-151-BB"],
        net_roi=6000.0 - 3400.0,
    ),
]


def recommend_trips() -> list[TripRecommendation]:
    """返回所有候选行程(按 ROI 降序)。"""
    sorted_table = sorted(TRIP_STUB_TABLE, key=lambda t: t.net_roi, reverse=True)
    return sorted_table


def best_trip() -> TripRecommendation | None:
    """返回 ROI 最高的 1 个 trip。"""
    trips = recommend_trips()
    return trips[0] if trips else None


if __name__ == "__main__":
    print("=" * 80)
    print(f"{'Rank':<5} {'Trip':<28} {'Cost':<10} {'Cargo':<8} {'ROI'}")
    print("=" * 80)
    for i, t in enumerate(recommend_trips(), start=1):
        print(f"{i:<5} {t.origin_city}→{t.dest_city} {t.depart_date[5:]}→{t.return_date[5:]}"
              f"{'🌙' if t.weekend_match else '  '}"
              f"    ¥{t.total_fixed_cny:<7.0f} ¥{t.cargo_capacity_cny:<6.0f} "
              f"{t.net_roi / max(t.total_fixed_cny, 1):.1f}×")
    print("=" * 80)
    best = best_trip()
    if best:
        print(f"\nTop pick: {best.summary()}")