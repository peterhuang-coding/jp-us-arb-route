"""Round 24 (F5) — HS code + tax + banned flag for the 6 whitelist SKUs.

Static config.  Source: 海关总署 行邮税 3 档 + 跨境电商综合税 + 20 种不予免税清单。
projection_color: 🟢 green (≤13% 行邮) / 🟡 yellow (20%) / 🔴 red (≥50% or banned).
"""
from __future__ import annotations

# Each entry: key=sku, value=dict(hs_code, hs_desc_zh, row_postal_rate,
#   cross_border_rate, is_banned_20, ban_reason, projection_color, notes).
TAX_TABLE: dict[str, dict] = {
    "JP-SKII-FT230": {
        "hs_code": "3304.99.00",
        "hs_desc_zh": "其他美容品或化妆品 (含 ¥10/毫升 以下)",
        "row_postal_rate": 0.20,        # 普通化妆品 ≤ ¥10/毫升
        "row_postal_rate_high": 0.50,   # 高档 ≥ ¥10/毫升
        "cross_border_rate": 0.2306,    # 跨境电商综合税 (含消费税 15%)
        "is_banned_20": False,
        "ban_reason": None,
        "projection_color": "yellow",
        "units_per_bottle_ml": 230,
        "ref_price_cny": 1080,
        "is_high_end": True,            # 神仙水 230ml 实测 ¥10+/毫升 → 命中高档
        "notes": "单瓶 230ml × ¥10/毫升 = ¥2,300 > ¥10,000 阀值?否;按毫升单价 ¥10 临界",
    },
    "JP-WS-YAMAZAKI12": {
        "hs_code": "2208.30.00",
        "hs_desc_zh": "威士忌 (烈酒)",
        "row_postal_rate": 0.50,
        "cross_border_rate": 0.2805,
        "is_banned_20": False,
        "ban_reason": None,
        "projection_color": "red",
        "carry_limit_per_trip": 2,      # 1.5L 总量限制下 750ml 瓶约 2 瓶
        "ref_price_cny": 1000,
        "is_high_end": True,
        "notes": "烈酒 50% 税;入境 1.5L 限量;Yamazaki 12 单瓶 ≈ ¥1,000 体现 ¥5,000 额度 5%",
    },
    "JP-NINTENDO-SWOLED": {
        "hs_code": "9504.50.00",
        "hs_desc_zh": "视频游戏控制器 / 电视游戏机",
        "row_postal_rate": 0.13,
        "cross_border_rate": 0.091,
        "is_banned_20": False,
        "ban_reason": None,
        "projection_color": "green",
        "ref_price_cny": 2400,
        "is_high_end": False,
        "notes": "游戏机 13% 税;Switch 已发售多年非「20 种不予免税」范围 (后者限手机/电脑/相机)",
    },
    "JP-DYSON-V12S": {
        "hs_code": "8516.31.00",
        "hs_desc_zh": "家用电动理发器 / 吹风机",
        "row_postal_rate": 0.20,
        "cross_border_rate": 0.091,
        "is_banned_20": False,
        "ban_reason": None,
        "projection_color": "yellow",
        "ref_price_cny": 4900,
        "is_high_end": False,
        "notes": "家用美容仪 20% 税;¥4,900 单价逼近 ¥5,000 额度",
    },
    "JP-LUX-PATEK": {
        "hs_code": "9101.11.00",
        "hs_desc_zh": "腕表 (机械, 完税价 ≥¥10,000)",
        "row_postal_rate": 0.50,        # 高档手表
        "row_postal_rate_low": 0.20,    # 普通手表
        "cross_border_rate": 0.2805,
        "is_banned_20": False,
        "ban_reason": None,
        "projection_color": "red",
        "ref_price_cny": 60000,
        "is_high_end": True,
        "notes": "¥60,000 单价 > ¥5,000 入境额度 12 倍;触发海关「非自用」判定;二手二奢平台 个人店无法上架",
    },
    "JP-ANIME-GK2024": {
        "hs_code": "9503.99.00",
        "hs_desc_zh": "玩具 / 玩偶 / 动漫周边",
        "row_postal_rate": 0.13,
        "cross_border_rate": 0.091,
        "is_banned_20": False,
        "ban_reason": None,
        "projection_color": "green",
        "ref_price_cny": 1500,
        "is_high_end": False,
        "notes": "手办 13% 税;¥1,500 单价友好;毛利 35-55% 最佳品类",
    },
}


# ---------- helpers ----------

def get_tax_info(sku: str) -> dict | None:
    return TAX_TABLE.get(sku)


def projection_color(sku: str) -> str:
    """🟢 green / 🟡 yellow / 🔴 red for the 6 whitelist SKUs."""
    info = TAX_TABLE.get(sku)
    if not info:
        return "gray"
    return info["projection_color"]


def is_banned_20(sku: str) -> bool:
    info = TAX_TABLE.get(sku)
    return bool(info and info["is_banned_20"])


def effective_rate(sku: str, *, mode: str = "row_postal") -> float:
    """Return the rate that applies to this SKU under the given tax mode.

    mode='row_postal' returns the row-postal rate (auto-picks high-end if
    applicable).  mode='cross_border' returns the cross-border rate.
    """
    info = TAX_TABLE.get(sku)
    if not info:
        return 0.0
    if mode == "cross_border":
        return float(info["cross_border_rate"])
    rate = info["row_postal_rate"]
    if info.get("is_high_end") and "row_postal_rate_high" in info:
        rate = info["row_postal_rate_high"]
    if info.get("is_high_end") and "row_postal_rate_low" in info:
        # For Patek: high-end row is the default in TAX_TABLE
        pass
    return float(rate)


def list_skus() -> list[str]:
    return list(TAX_TABLE.keys())


def summary_table() -> list[dict]:
    """Compact view for SPA / reports."""
    rows = []
    for sku, info in TAX_TABLE.items():
        rows.append({
            "sku": sku,
            "hs_code": info["hs_code"],
            "hs_desc_zh": info["hs_desc_zh"],
            "row_postal_rate": effective_rate(sku),
            "cross_border_rate": info["cross_border_rate"],
            "is_banned_20": info["is_banned_20"],
            "ban_reason": info["ban_reason"],
            "projection_color": info["projection_color"],
            "ref_price_cny": info["ref_price_cny"],
            "notes": info["notes"],
        })
    return rows
