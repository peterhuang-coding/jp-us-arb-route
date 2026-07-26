"""Seed data for the 6 whitelist opportunities + 1 canonical route.

All prices are calibrated to 2025-2026 public retail observations and exchange
rates around USD/JPY ≈ 150.  ``verified=0`` marks every price as "未验证" so
the UI shows the warning label the brief requires.
"""
from __future__ import annotations

from typing import Iterable

from . import db


# ---------- 6 whitelist opportunities ----------

OPPORTUNITIES: list[dict] = [
    {
        "sku": "JP-SKII-FT230",
        "name": "SK-II Facial Treatment Essence 230ml (PITERA)",
        "category": "skincare",
        "source_market": "JP (NaritaAirport免税)",
        "target_market": "US (Amazon / eBay)",
        "purchase_price_usd": 85.0,   # ~¥12,800 tax-free at NRT
        "tariff_rate": 0.0,           # stays under $800 personal exemption
        "sell_price_usd": 145.0,      # US Amazon Prime listing
        "shipping_per_unit_usd": 4.0,
        "platform_fee_rate": 0.13,    # eBay FVF + PayPal
        "minutes_per_unit": 20.0,
        "success_rate": 0.85,
        "purchase_source_url": "https://www.japan-taxfree.jp/",
        "sell_source_url": "https://www.amazon.com/SK-II-Facial-Treatment-Essence/dp/B000VOHH8I",
        "notes": "每人每日限购 6 瓶;常温运输;海关申报免税额内。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
    },
    {
        "sku": "JP-WS-YAMAZAKI12",
        "name": "Yamazaki 12 Year Single Malt (免税限定)",
        "category": "spirits",
        "source_market": "JP (Fa-So-La / 関空免税)",
        "target_market": "US (eBay Reserve / WhiskyAuction)",
        "purchase_price_usd": 165.0,  # ¥24,750 tax-free
        "tariff_rate": 0.0,
        "sell_price_usd": 320.0,      # US resale avg, 750ml sealed
        "shipping_per_unit_usd": 22.0,
        "platform_fee_rate": 0.13,
        "minutes_per_unit": 35.0,
        "success_rate": 0.65,
        "purchase_source_url": "https://www.fasola.jp/",
        "sell_source_url": "https://www.ebay.com/sch/i.html?_nkw=yamazaki+12",
        "notes": "酒类随身行李 100ml 限制;必须托运;抵达后当地零售价稳定。需年满 21 岁。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
    },
    {
        "sku": "JP-NINTENDO-SWOLED",
        "name": "Nintendo Switch OLED ホワイト (日本限定)",
        "category": "electronics",
        "source_market": "JP (ヨドバシAkiba / Bic Camera)",
        "target_market": "US (eBay / Mercari)",
        "purchase_price_usd": 270.0,  # ¥39,800 税抜
        "tariff_rate": 0.0,
        "sell_price_usd": 360.0,      # US resale avg
        "shipping_per_unit_usd": 18.0,
        "platform_fee_rate": 0.13,
        "minutes_per_unit": 40.0,
        "success_rate": 0.75,
        "purchase_source_url": "https://www.yodobashi.com/category/12431/711/21455/",
        "sell_source_url": "https://www.ebay.com/sch/i.html?_nkw=switch+oled+japan",
        "notes": "日本版只能在日亚账号激活 eShop;美区游戏机玩家会买日本限定色。需注意 100V 插座差异。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
    },
    {
        "sku": "JP-DYSON-V12S",
        "name": "Dyson V12s Detect Slim Submarine (日本版)",
        "category": "appliances",
        "source_market": "JP (Dyson公式 / ビック)",
        "target_market": "US (Amazon US / Dyson US)",
        "purchase_price_usd": 510.0,  # ¥76,500 税込
        "tariff_rate": 0.0,
        "sell_price_usd": 620.0,
        "shipping_per_unit_usd": 25.0,
        "platform_fee_rate": 0.13,
        "minutes_per_unit": 30.0,
        "success_rate": 0.70,
        "purchase_source_url": "https://www.dyson.co.jp/",
        "sell_source_url": "https://www.amazon.com/Dyson-V12s-Detect-Slim/dp/B0CQHLQLD4",
        "notes": "100V 仕様注意;美国版 110V 几乎无差;海外保証カード可在日美通用。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
    },
    {
        "sku": "JP-LUX-PATEK",
        "name": "Patek Philippe Calatrava 中古 (日本中古店)",
        "category": "luxury_used",
        "source_market": "JP (BrandOff / 銀蔵 / ジャックロード)",
        "target_market": "US (eBay Authenticity Guarantee / Chrono24)",
        "purchase_price_usd": 8200.0,  # ¥1,230,000 brandOff retail
        "tariff_rate": 0.0,            # 二手个人自用;走非贸易申报
        "sell_price_usd": 11500.0,
        "shipping_per_unit_usd": 60.0,
        "platform_fee_rate": 0.13,
        "minutes_per_unit": 180.0,     # 鉴定 + 谈判耗时
        "success_rate": 0.50,
        "purchase_source_url": "https://www.brandoff.co.jp/",
        "sell_source_url": "https://www.chrono24.com/patekphilippe/index.htm",
        "notes": "中高价值二手表;必须 eBay Authenticity Guarantee 渠道;需真品证书 + 盒子。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
    },
    {
        "sku": "JP-ANIME-GK2024",
        "name": "Anime Goods 限定 (例:呪術廻戦 五条 1/7 スケール)",
        "category": "anime_collectibles",
        "source_market": "JP (秋葉原 / Amazon JP / アニメイト)",
        "target_market": "US (eBay / Mercari US)",
        "purchase_price_usd": 175.0,  # ¥26,250 限定版
        "tariff_rate": 0.0,
        "sell_price_usd": 290.0,
        "shipping_per_unit_usd": 28.0,
        "platform_fee_rate": 0.13,
        "minutes_per_unit": 25.0,
        "success_rate": 0.60,
        "purchase_source_url": "https://www.animate.co.jp/",
        "sell_source_url": "https://www.ebay.com/sch/i.html?_nkw=jujutsu+kaisen+gojo+scale",
        "notes": "限定编号会影响价差;未拆封状态加分;日本限定货更有溢价。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
    },
]


# ---------- 1 canonical route ----------

ROUTE: dict = {
    "name": "PVG-NRT-LAX-2N",
    "origin_city": "上海 PVG",
    "dest_city": "洛杉矶 LAX",
    "flight_cost_usd": 720.0,
    "hotel_cost_usd": 240.0,
    "other_cost_usd": 80.0,
    "hours_available": 32.0,
    "target_hourly_usd": 20.0,
    "target_roi_pct": 15.0,
    "min_roi_pct": 10.0,
    "departure_date": "2026-09-15",
    "source_url": "https://www.google.com/travel/flights",
    "notes": "示例路线:上海→成田→洛杉矶,2 晚酒店,4 段飞行+1 个采购点。",
}

ROUTE_LEGS: list[dict] = [
    {"seq": 1, "kind": "flight", "label": "PVG → NRT",          "cost_usd": 150.0, "duration_min": 200.0, "location": "Shanghai",     "notes": "NH 920 / JL 870 区间"},
    {"seq": 2, "kind": "flight", "label": "NRT → LAX",          "cost_usd": 540.0, "duration_min": 660.0, "location": "Tokyo",        "notes": "NH 105 直飞"},
    {"seq": 3, "kind": "hotel",  "label": "Rodeway Inn LAX 2N", "cost_usd": 240.0, "duration_min": 0.0,   "location": "Los Angeles",  "notes": "机场附近, 接送方便"},
    {"seq": 4, "kind": "shop",   "label": "Bic Camera LA / Target /  CVS", "cost_usd": 0.0, "duration_min": 240.0, "location": "Los Angeles", "notes": "按商机清单采购"},
    {"seq": 5, "kind": "flight", "label": "LAX → NRT",          "cost_usd": 540.0, "duration_min": 660.0, "location": "Los Angeles",  "notes": "NH 106 直飞"},
    {"seq": 6, "kind": "flight", "label": "NRT → PVG",          "cost_usd": 150.0, "duration_min": 200.0, "location": "Tokyo",        "notes": "回程"},
]

# ---------- 2nd route (round 8): US-domestic regional connector ----------
# LAX → SFO 1-night ferry for users who already bought in JP but need to
# move inventory to the Bay Area resale market.  Trip-level costs are
# ~$150 flight + $120 hotel vs $720 + $240 for the international route,
# so per-trip break-even is far lower and even small-margin SKUs profit.

ROUTE_REGIONAL: dict = {
    "name": "LAX-SFO-1N",
    "origin_city": "洛杉矶 LAX",
    "dest_city": "旧金山 SFO",
    "flight_cost_usd": 150.0,
    "hotel_cost_usd": 120.0,
    "other_cost_usd": 30.0,
    "hours_available": 16.0,
    "target_hourly_usd": 20.0,
    "target_roi_pct": 15.0,
    "min_roi_pct": 10.0,
    "departure_date": "2026-09-16",
    "source_url": "https://www.google.com/travel/flights",
    "notes": "区域连接段:LAX→SFO 单程 1 晚,适合已完成国际采购、需在美西境内转运的 SKU。",
}

ROUTE_REGIONAL_LEGS: list[dict] = [
    {"seq": 1, "kind": "flight", "label": "LAX → SFO",          "cost_usd": 150.0, "duration_min": 90.0,  "location": "Los Angeles", "notes": "AS 1949 / UA 522 区间"},
    {"seq": 2, "kind": "hotel",  "label": "Bay Bridge Inn SFO 1N", "cost_usd": 120.0, "duration_min": 0.0,   "location": "San Francisco", "notes": "机场附近, 接送方便"},
    {"seq": 3, "kind": "shop",   "label": "Japantown / eBay drop-off SFO", "cost_usd": 0.0, "duration_min": 120.0, "location": "San Francisco", "notes": "小批量二次采购或 eBay 寄售点"},
    {"seq": 4, "kind": "flight", "label": "SFO → LAX",          "cost_usd": 150.0, "duration_min": 90.0,  "location": "San Francisco", "notes": "返程"},
]

ROUTES: list[dict] = [ROUTE, ROUTE_REGIONAL]
ROUTES_BY_LEGS: dict[str, list[dict]] = {
    ROUTE["name"]: ROUTE_LEGS,
    ROUTE_REGIONAL["name"]: ROUTE_REGIONAL_LEGS,
}


def seed_all(conn) -> dict:
    """Insert seed data. Returns counts: {opportunities, routes, legs}."""
    opp_ids = []
    for opp in OPPORTUNITIES:
        opp_ids.append(db.upsert_opportunity(conn, opp))
    route_ids = []
    total_legs = 0
    for r in ROUTES:
        rid = db.upsert_route(conn, r)
        route_ids.append(rid)
        legs = ROUTES_BY_LEGS[r["name"]]
        db.add_route_legs(conn, rid, legs)
        total_legs += len(legs)
    return {
        "opportunities": len(opp_ids),
        "routes": len(route_ids),
        "legs": total_legs,
        "route_ids": route_ids,
    }


def main() -> dict:
    conn = db.connect()
    try:
        return seed_all(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    print(json.dumps(main(), indent=2))
