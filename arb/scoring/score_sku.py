"""主评分公式(score_sku)— 分析环核心算法。

公式(见 ANALYSIS_LOOP.md §2):
    score = (
        spread_pct * 0.35
        + sell_volume * 0.25
        + reliability * 0.20
        - complexity_penalty * 0.20
    )

Phase 1 stub:输入已标准化 0-1,直接套公式。
Phase 2:输入来自 arb.scrapers 真价。
Phase 3:权重从 arb.scoring.learned_weights 读。
"""
from __future__ import annotations

from typing import TypedDict


class ScoreInput(TypedDict, total=False):
    """score_sku 输入字段。

    所有字段应标准化到 0-1:
    - spread_pct:spread 百分比,0-1(0.5 = 50%)
    - sell_volume:月销量 / 已售数,0-1(1.0 = ≥30 单/月)
    - reliability:货源真实 + 买家信用,0-1(1.0 = 完全可信)
    - complexity_penalty:物流 + 关税 + 退货 + 合规复杂度,0-1(1.0 = 极复杂)
    """
    sku: str
    spread_pct: float
    sell_volume: float
    reliability: float
    complexity_penalty: float


class ScoreResult(TypedDict):
    sku: str
    score: float           # 0-100
    grade: str             # 🟢 主推 / 🟡 试单 / 🔴 不推
    components: dict       # 各项明细


WEIGHTS = {
    "spread_pct": 0.35,
    "sell_volume": 0.25,
    "reliability": 0.20,
    "complexity_penalty": -0.20,  # 负权重:越复杂越扣分
}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_sku(inp: ScoreInput) -> ScoreResult:
    """计算单个 SKU 的 score(0-100)+ 等级。

    >>> r = score_sku({"sku": "X", "spread_pct": 0.5, "sell_volume": 0.6, "reliability": 0.8, "complexity_penalty": 0.2})
    >>> 0 <= r["score"] <= 100
    True
    """
    spread = _clamp(inp.get("spread_pct", 0))
    volume = _clamp(inp.get("sell_volume", 0))
    rel = _clamp(inp.get("reliability", 0))
    cplx = _clamp(inp.get("complexity_penalty", 0))

    raw = (
        spread * WEIGHTS["spread_pct"]
        + volume * WEIGHTS["sell_volume"]
        + rel * WEIGHTS["reliability"]
        + cplx * WEIGHTS["complexity_penalty"]  # 负权重
    )
    # raw ∈ [-0.20, 0.80];线性映射到 0-100
    score = round((raw + 0.20) / 1.00 * 100, 1)

    return {
        "sku": inp["sku"],
        "score": max(0.0, min(100.0, score)),
        "grade": classify(score),
        "components": {
            "spread_pct": spread,
            "sell_volume": volume,
            "reliability": rel,
            "complexity_penalty": cplx,
        },
    }


def classify(score: float) -> str:
    """0-100 score → 🟢/🟡/🔴。

    >>> classify(80)
    '🟢 主推'
    >>> classify(50)
    '🟡 试单'
    >>> classify(20)
    '🔴 不推'
    """
    if score >= 70:
        return "🟢 主推"
    if score >= 40:
        return "🟡 试单"
    return "🔴 不推"


# Phase 1 stub:basket 4 行硬编码 score 输入。
# Day 8-14 替换为 arb.scrapers 真价输出。
SCORE_TABLE: list[ScoreInput] = [
    # PKMN-PSA:1100% spread / 中等销量 / 高信(PSA 10 真伪可验)/ 低复杂(撮合不入境)
    {
        "sku": "JP-PKMN-PSA",
        "spread_pct": 1.00,        # 截断到 1.0(实际 11.0)
        "sell_volume": 0.40,
        "reliability": 0.85,
        "complexity_penalty": 0.20,
    },
    # HumanMade Tee:227% spread / 中等销量 / 高信(镭射标)/ 低复杂
    {
        "sku": "JP-HUMANMADE-TEE-GRAPHIC",
        "spread_pct": 1.00,        # 截断到 1.0
        "sell_volume": 0.55,
        "reliability": 0.80,
        "complexity_penalty": 0.20,
    },
    # USJ Nezuko:217% spread / 低销量(限定)/ 中信 / 中复杂(USJ 现场代购)
    {
        "sku": "JP-ANIME-USJ-NEZ",
        "spread_pct": 1.00,        # 截断到 1.0
        "sell_volume": 0.20,
        "reliability": 0.65,
        "complexity_penalty": 0.45,
    },
    # Pokemon 151 BB:233% spread / 高销量(642 sold)/ 高信 / 中复杂(国际运费)
    {
        "sku": "JP-PKMN-151-BB",
        "spread_pct": 1.00,        # 截断到 1.0
        "sell_volume": 0.85,
        "reliability": 0.90,
        "complexity_penalty": 0.30,
    },
    # Yamazaki 12:已 out(酒类合规风险,不放 SCORE_TABLE)
]


# v3.4 — 5-Leg 评分表:每个 SKU 按 leg 单独打分。
# 不同 leg 下 spread / volume / reliability / complexity 不同:
#   🅰 撮合:spread 高 / volume 高 / reliability 高 / complexity 低
#   🅱 代购集运:spread 中 / volume 中 / reliability 中 / complexity 中
#   🅲 出差代购:spread 中(¥6k 货值上限)/ volume 极高(限定/现场)/ reliability 高 / complexity 中(机票)
#   🅳 电商带过去:spread 高(CN→海外)/ volume 中 / reliability 中 / complexity 低(不入境)
#   🅴 哥们仓:spread 高 / volume 中 / reliability 高 / complexity 高(¥5,000 额度)
LEG_SCORE_TABLE: dict[str, list[ScoreInput]] = {
    "🅰 撮合": [
        {"sku": "JP-PKMN-151-BB", "spread_pct": 1.00, "sell_volume": 0.85, "reliability": 0.90, "complexity_penalty": 0.30},
        {"sku": "JP-HUMANMADE-TEE-GRAPHIC", "spread_pct": 1.00, "sell_volume": 0.55, "reliability": 0.80, "complexity_penalty": 0.20},
        {"sku": "JP-PKMN-PSA", "spread_pct": 1.00, "sell_volume": 0.40, "reliability": 0.85, "complexity_penalty": 0.20},
    ],
    "🅱 代购集运": [
        # CN sell side 均价(闲鱼 / 小红书)低于 eBay 海外,spread 中等
        {"sku": "JP-HUMANMADE-TEE-GRAPHIC", "spread_pct": 0.80, "sell_volume": 0.60, "reliability": 0.80, "complexity_penalty": 0.45},
        {"sku": "JP-PKMN-151-BB", "spread_pct": 0.70, "sell_volume": 0.50, "reliability": 0.90, "complexity_penalty": 0.55},
    ],
    "🅲 出差代购": [
        # 现场买 + ¥6,000 货值上限:限定品 / 高货值 SKU
        {"sku": "JP-PKMN-PSA", "spread_pct": 1.00, "sell_volume": 0.85, "reliability": 0.85, "complexity_penalty": 0.40},
        {"sku": "JP-ANIME-USJ-NEZ", "spread_pct": 1.00, "sell_volume": 0.90, "reliability": 0.75, "complexity_penalty": 0.45},
        {"sku": "JP-PKMN-151-BB", "spread_pct": 1.00, "sell_volume": 0.80, "reliability": 0.90, "complexity_penalty": 0.50},
    ],
    "🅳 电商带过去": [
        # CN→海外:拼多多 / 1688 → 海外 eBay
        # PKMN-151 BB Sealed 在海外有价,但 CN 库存便宜
        {"sku": "JP-PKMN-151-BB-CN", "spread_pct": 0.60, "sell_volume": 0.50, "reliability": 0.70, "complexity_penalty": 0.25},
        # HM Tee CN 产线版本 → 海外卖不动,跳过
    ],
    "🅴 哥们仓": [
        # 海外电商 → 哥们家 → 飞过去取 → 带回 CN
        # 适合 ¥5,000 额度内的 JP 限定
        {"sku": "JP-HUMANMADE-TEE-GRAPHIC", "spread_pct": 1.00, "sell_volume": 0.70, "reliability": 0.85, "complexity_penalty": 0.55},
        {"sku": "JP-ANIME-USJ-NEZ", "spread_pct": 1.00, "sell_volume": 0.85, "reliability": 0.70, "complexity_penalty": 0.55},
    ],
}


# v3.4 — 现场买(OnSite)+ 电商囤 / 哥们仓 SKU 推荐 stub。
ON_SITE_SKUS: list[dict] = [
    # 现场买:USJ 限定 + outlet + 药妆 + Bic Camera 折扣
    {"sku": "JP-ANIME-USJ-NEZ", "location": "USJ 现场 鬼灭 popcorn", "est_buy_jpy": 4080, "est_sell_cny": 678, "spread_pct": 0.66, "reliability": 0.75},
    {"sku": "JP-USJ-NEZ-2025", "location": "USJ 2025 合作 限定", "est_buy_jpy": 5500, "est_sell_cny": 900, "spread_pct": 0.64, "reliability": 0.70},
    {"sku": "JP-DRUG-COSMETIC", "location": "松本清 药妆折扣", "est_buy_jpy": 3000, "est_sell_cny": 600, "spread_pct": 0.75, "reliability": 0.80},
    {"sku": "JP-OUTLET-MK", "location": "御殿场 outlet Michael Kors", "est_buy_jpy": 8000, "est_sell_cny": 1500, "spread_pct": 0.55, "reliability": 0.85},
]


CN_ECOM_SKUS: list[dict] = [
    # CN 电商下单,带去海外卖
    {"sku": "CN-TEA-PUER", "cn_source": "拼多多", "cn_price_cny": 200, "overseas_sell": "eBay US", "overseas_sell_cny": 800, "spread_pct": 3.0, "carry_method": "随身行李"},
    {"sku": "CN-TCM-HERB", "cn_source": "1688", "cn_price_cny": 150, "overseas_sell": "Etsy 海外华人", "overseas_sell_cny": 700, "spread_pct": 3.7, "carry_method": "随身行李"},
]


FRIEND_WAREHOUSE_SKUS: list[dict] = [
    # 海外电商 → 哥们家 → 飞过去取 → 带回 CN
    {"sku": "JP-PKMN-151-BB", "overseas_source": "buyee.jp", "overseas_price_cny": 470, "cn_sell": "闲鱼", "cn_sell_cny": 1071, "spread_pct": 1.28, "friend_storage_days": 7, "customs_budget_cny": 5000},
    {"sku": "JP-HUMANMADE-TEE-GRAPHIC", "overseas_source": "humanmade.jp 代购", "overseas_price_cny": 350, "cn_sell": "闲鱼", "cn_sell_cny": 857, "spread_pct": 1.45, "friend_storage_days": 7, "customs_budget_cny": 5000},
]