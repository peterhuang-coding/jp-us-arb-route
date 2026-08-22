"""Top N 推荐(recommend_top_n)— 跑 SCORE_TABLE 返回排序后的 Top N。

Phase 1 stub:固定输入(SCORE_TABLE)+ 固定权重。
Phase 2:接 arb.scrapers 真价流。
Phase 3:learned_weights 训权重。

v3.4 升级:加 5-Leg 评分(recommend_by_leg)+ 现场买/电商囤/哥们仓 stub。
"""
from __future__ import annotations

from typing import TypedDict

from .score_sku import (
    SCORE_TABLE,
    LEG_SCORE_TABLE,
    ON_SITE_SKUS,
    CN_ECOM_SKUS,
    FRIEND_WAREHOUSE_SKUS,
    score_sku,
)


class Recommendation(TypedDict):
    rank: int
    sku: str
    score: float
    grade: str
    components: dict


class LegRecommendation(TypedDict):
    rank: int
    leg: str
    sku: str
    score: float
    grade: str


def recommend_top_n(n: int = 3, table: list | None = None) -> list[Recommendation]:
    """返回按 score 降序的 Top N 推荐。

    >>> recs = recommend_top_n(3)
    >>> len(recs) <= 3
    True
    >>> recs[0]["score"] >= recs[-1]["score"]  # 排序
    True
    """
    rows = table if table is not None else SCORE_TABLE
    scored = [score_sku(r) for r in rows]
    scored.sort(key=lambda r: r["score"], reverse=True)

    out: list[Recommendation] = []
    for i, r in enumerate(scored[:n], start=1):
        out.append({
            "rank": i,
            "sku": r["sku"],
            "score": r["score"],
            "grade": r["grade"],
            "components": r["components"],
        })
    return out


def recommend_by_leg(leg: str, n: int = 3) -> list[LegRecommendation]:
    """v3.4 — 按 leg 推荐 Top N。

    >>> recs = recommend_by_leg("🅰 撮合", 3)
    >>> len(recs) <= 3
    True
    """
    table = LEG_SCORE_TABLE.get(leg, [])
    scored = [score_sku(r) for r in table]
    scored.sort(key=lambda r: r["score"], reverse=True)
    return [
        {
            "rank": i,
            "leg": leg,
            "sku": r["sku"],
            "score": r["score"],
            "grade": r["grade"],
        }
        for i, r in enumerate(scored[:n], start=1)
    ]


def recommend_all_legs(n: int = 3) -> dict[str, list[LegRecommendation]]:
    """v3.4 — 5-leg 并行推荐。"""
    return {leg: recommend_by_leg(leg, n) for leg in LEG_SCORE_TABLE}


def recommend_on_site() -> list[dict]:
    """v3.4 — 🅲 现场买推荐(stub,Phase 2 接 eBay sold 验证)。"""
    return sorted(ON_SITE_SKUS, key=lambda r: r["spread_pct"], reverse=True)


def recommend_cn_ecom() -> list[dict]:
    """v3.4 — 🅳 电商带过去(CN→海外)推荐。"""
    return sorted(CN_ECOM_SKUS, key=lambda r: r["spread_pct"], reverse=True)


def recommend_friend_warehouse() -> list[dict]:
    """v3.4 — 🅴 哥们仓(海外→CN)推荐。"""
    return sorted(FRIEND_WAREHOUSE_SKUS, key=lambda r: r["spread_pct"], reverse=True)


if __name__ == "__main__":
    # CLI demo:python -m arb.scoring.recommend
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode in ("all", "legs"):
        print("=" * 80)
        print("🤖 分析环 v3.4 — 5-Leg 推荐")
        print("=" * 80)
        for leg, recs in recommend_all_legs().items():
            print(f"\n{leg}")
            print(f"  {'#':<3} {'SKU':<28} {'Score':<7} {'Grade'}")
            print(f"  {'-'*60}")
            for rec in recs:
                print(f"  {rec['rank']:<3} {rec['sku']:<28} {rec['score']:<7} {rec['grade']}")

    if mode in ("all", "on_site"):
        print("\n" + "=" * 80)
        print("🅲 现场买推荐(stub)")
        print("=" * 80)
        for r in recommend_on_site():
            print(f"  {r['sku']:<24} {r['location']:<28} spread {r['spread_pct']*100:.0f}%")

    if mode in ("all", "cn_ecom"):
        print("\n" + "=" * 80)
        print("🅳 CN 电商带过去(CN→海外)")
        print("=" * 80)
        for r in recommend_cn_ecom():
            print(f"  {r['sku']:<20} {r['cn_source']:<10} ¥{r['cn_price_cny']:.0f} → ¥{r['overseas_sell_cny']:.0f} ({r['spread_pct']*100:.0f}%)")

    if mode in ("all", "friend"):
        print("\n" + "=" * 80)
        print("🅴 哥们仓(海外→CN)")
        print("=" * 80)
        for r in recommend_friend_warehouse():
            print(f"  {r['sku']:<24} {r['overseas_source']:<22} ¥{r['overseas_price_cny']:.0f} → ¥{r['cn_sell_cny']:.0f} ({r['spread_pct']*100:.0f}%)")