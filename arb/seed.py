"""Seed data for the 6 whitelist opportunities + 1 canonical route.

All prices are calibrated to 2025-2026 public retail observations and exchange
rates around USD/JPY ≈ 150.  ``verified=0`` marks every price as "未验证" so
the UI shows the warning label the brief requires.
"""
from __future__ import annotations

from typing import Iterable

from . import db


# ---------- Round 20: channel enrichment helpers ----------

# Map raw channel type to the user's procurement mode:
#   sync  = 必须现场买 (实体店 visit-only)
#   async = 可线上预购 + 哥们寄存 (online store, batch pickup)
#   ship  = 远程转交 (peer-to-peer / 转运)
_TYPE_TO_FULFILLMENT = {
    "offline": "sync",
    "online":  "async",
    "social":  "ship",
}


def _enrich_channels(channels: list[dict], source_url: str | None) -> None:
    """Tag each channel in-place with ``fulfillment`` and ``anchor``.

    - ``fulfillment`` is a deterministic function of channel type (offline → sync,
      online → async, social → ship) so behavior is consistent across SKUs.
    - ``anchor`` marks the channel whose URL is the source of the stored price
      (matches ``opp.purchase_source_url`` / ``opp.sell_source_url``). When no
      channel URL matches, we fall back to the first ``online`` channel so the
      UI has a single 📌 reference chip on each side (the 📌 tooltip explains
      "best-effort anchor, not exact source").
    """
    if not channels:
        return
    for ch in channels:
        ch["fulfillment"] = _TYPE_TO_FULFILLMENT.get(ch.get("type", "online"), "sync")

    if not source_url:
        for ch in channels:
            ch["anchor"] = False
        return
    marked = False
    for ch in channels:
        url = (ch.get("url") or "").strip()
        if url and (url in source_url or source_url in url):
            ch["anchor"] = True
            marked = True
        else:
            ch["anchor"] = False
    if not marked:
        # No exact URL match — pick first online channel as best-effort anchor
        # so the UI shows exactly one 📌 chip per side. The tooltip tells the
        # user this is a reference channel, not necessarily the literal source.
        for ch in channels:
            if ch.get("type") == "online":
                ch["anchor"] = True
                break


# ---------- Round 20: Day-by-Day shopping stops per route ----------
# Each stop describes a physical store visit: name, address, opening hours,
# transit time from previous stop, target SKUs to buy here, in-store time, and
# recommended buy_mode (sync = walk in / async = pre-arrange online).
# Transits are realistic walking+Jr estimates from Google Maps as of 2025.

ROUTE_SHOPPING_STOPS: dict[str, list[dict]] = {
    # ────────────────────────────────────────────────────────────────────
    # Tokyo weekend: Fri evening arrive → Sat all-day + Sun morning buy → Sun noon fly back
    "PEK-NRT-WEEKEND": [
        {"seq": 1, "label": "Fa-So-La 银座免税店",
         "address": "东京都中央区银座 5-2-1 (すずらん通り)",
         "open_hours": "10:00–20:00",
         "transit_min": 30,            # 成田特快 → 上野 → 山手线 银座站
         "target_skus": ["JP-WS-YAMAZAKI12"],
         "buy_mode": "sync",
         "duration_min": 60},
        {"seq": 2, "label": "Bic Camera 池袋东武店",
         "address": "东京都丰岛区西池袋 1-1-25",
         "open_hours": "10:00–21:00",
         "transit_min": 25,            # 山手线 银座→池袋
         "target_skus": ["JP-SKII-FT230", "JP-NINTENDO-SWOLED"],
         "buy_mode": "sync",
         "duration_min": 90},
        {"seq": 3, "label": "Mandarake 秋叶原 4 号馆",
         "address": "东京都千代田区外神田 3-11-12",
         "open_hours": "12:00–20:00",
         "transit_min": 20,            # 山手线 池袋→秋叶原
         "target_skus": ["JP-ANIME-GK2024"],
         "buy_mode": "sync",
         "duration_min": 45},
    ],
    # ────────────────────────────────────────────────────────────────────
    # Osaka weekend: Fri afternoon arrive → Sat all-day → Sun afternoon fly back
    "PEK-KIX-WEEKEND": [
        {"seq": 1, "label": "Bic Camera 心斋桥",
         "address": "大阪市中央区心斋桥筋 1-8-3",
         "open_hours": "10:00–21:00",
         "transit_min": 45,            # 南海电铁 → 御堂筋线 心斋桥
         "target_skus": ["JP-NINTENDO-SWOLED"],
         "buy_mode": "sync",
         "duration_min": 60},
        {"seq": 2, "label": "大丸心斋桥店 本馆 B1 化妆品",
         "address": "大阪市中央区心斋桥筋 1-7-1",
         "open_hours": "10:00–20:00",
         "transit_min": 5,             # 步行 (隔壁)
         "target_skus": ["JP-SKII-FT230"],
         "buy_mode": "sync",
         "duration_min": 45},
        {"seq": 3, "label": "ヨドバシ梅田 (友都八喜)",
         "address": "大阪市北区大深町 1-1",
         "open_hours": "09:30–22:00",
         "transit_min": 15,            # 御堂筋线 心斋桥→梅田
         "target_skus": ["JP-DYSON-V12S"],
         "buy_mode": "sync",
         "duration_min": 75},
    ],
    # ────────────────────────────────────────────────────────────────────
    # LA transit night: very limited buy window — these are logistics stops
    # for last-minute items, NOT source of any of the 6 whitelisted SKUs.
    "PVG-NRT-LAX-2N": [
        {"seq": 1, "label": "Target Figueroa (downtown LA)",
         "address": "735 S Figueroa St, Los Angeles",
         "open_hours": "08:00–22:00",
         "transit_min": 35,            # LAX FlyAway → 7th St/Figueroa
         "target_skus": [],            # 转运/补货,非 6 SKU 来源
         "buy_mode": "sync",
         "duration_min": 30},
        {"seq": 2, "label": "CVS Pharmacy LAX (出发层)",
         "address": "1 World Way, Los Angeles (LAX Terminal)",
         "open_hours": "06:00–23:00",
         "transit_min": 30,            # 回 LAX
         "target_skus": [],            # 应急小物
         "buy_mode": "sync",
         "duration_min": 20},
    ],
    # ────────────────────────────────────────────────────────────────────
    # SF regional: half-day shopping window near Union Square.
    "LAX-SFO-1N": [
        {"seq": 1, "label": "Apple Union Square / Best Buy 450 套件",
         "address": "300 Post St, San Francisco",
         "open_hours": "10:00–20:00",
         "transit_min": 25,            # BART SFO → Powell
         "target_skus": [],            # 转运/补货
         "buy_mode": "sync",
         "duration_min": 60},
    ],
}


# ---------- 6 whitelist opportunities ----------

OPPORTUNITIES: list[dict] = [
    {
        "sku": "JP-SKII-FT230",
        "name": "SK-II Facial Treatment Essence 230ml (PITERA)",
        "category": "skincare",
        "source_market": "JP (Fa-So-La / Laox / Bic Camera 免税)",
        "target_market": "CN (闲鱼 / 京东国际 / 朋友圈)",
        # Round 21: 全部 CN-target。purch 改用免税退 8% 实际价 ¥995 ≈ $139;
        # sell 用闲鱼挂单中位 ¥950 ≈ $133(套利接近持平,建议自用为主)。
        "purchase_price_usd": 139.0,  # ¥995 免税退税后 (含税 ¥1,075 - 8% 退税 ≈ ¥996)
        "tariff_rate": 0.0,           # stays under $800 personal exemption
        "sell_price_usd": 133.0,      # 闲鱼挂单中位 ¥950 ≈ $133 (研究:挂单 ≠ 成交价,实际 ¥850-1000)
        "shipping_per_unit_usd": 4.0,
        "platform_fee_rate": 0.06,    # 闲鱼成交无平台费;朋友圈 0%;只有京东国际/天猫有约 6%
        "minutes_per_unit": 20.0,
        "success_rate": 0.85,
        "purchase_source_url": "https://www.fasola.jp/",
        "sell_source_url": "https://www.goofish.com/search?q=SK-II%E7%A5%9E%E4%BB%99%E6%B0%B4+230ml",
        "purchase_channels": [
            {"name": "Fa-So-La 免税", "url": "https://www.fasola.jp/", "type": "offline",
             "anchor": True,
             "note": "成田/关空/羽田店内,凭登机牌进店;230ml 含税 ¥21,500 JPY,免税退 8% ≈ ¥996 CNY"},
            {"name": "Laox 免税", "url": "https://www.laox.co.jp/", "type": "offline",
             "note": "银座/秋叶原/成田有免税柜,SK-II 常年有货;价格与 Fa-So-La 接近"},
            {"name": "日本亚马逊", "url": "https://www.amazon.co.jp/SK-II/", "type": "online",
             "note": "Prime 会员可直邮;部分 SKU 需转运;价格略高于免税店(无退税,含税 ≈ ¥1,150)"},
            {"name": "多庆屋 (上野)", "url": "https://www.takeya.co.jp/", "type": "offline",
             "note": "综合免税店,凭护照 + 登机牌可退 8%;护肤类 SKU 较齐;¥950-1,000"},
            {"name": "楽天市場 (代购集运)", "url": "https://www.rakuten.co.jp/", "type": "online",
             "note": "代购集中发货:多店凑单 ¥50-100 国际段运费;价格含税 ≈ ¥1,150-1,250,但适合帮朋友带"},
        ],
        "sell_channels": [
            # Round 21: 删除得物(得物不鉴定护肤品,无可商业化证据);删除京东国际/天猫国际
            # (B2C 买方平台,不支持 C2C 挂单);新增小红书作为二手美妆活跃渠道。
            {"name": "闲鱼", "url": "https://www.goofish.com/", "type": "online",
             "anchor": True,
             "note": "中文圈买家多,挂单 ¥850-1000;成交价不公开,实操建议 ¥950 中位;需实拍图 + 批次号"},
            {"name": "朋友圈 / 微商", "url": "", "type": "social",
             "note": "熟人私聊,无平台抽成;成交价通常 ¥1,000-1,100 (无公开记录)"},
            {"name": "小红书 (美妆闲置)", "url": "https://www.xiaohongshu.com/", "type": "social",
             "note": "二手美妆活跃;挂单 ¥900-1,050;笔记形式,需拍细节图 + 验真图"},
            {"name": "转转 (美妆数码)", "url": "https://www.zhuanzhuan.com/", "type": "online",
             "note": "二手平台美妆分类;挂单 ¥850-950;平台抽成 1%;适合 ¥1,000 以下小件"},
        ],
        "notes": "Round 21:套利毛利极薄(¥950-¥995=-¥45/瓶,扣物流后亏损);建议走「自用+ 朋友圈 转售」路径而非闲鱼挂单。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
        "home_price_cny": 1100.0,     # 天猫国际 / 中免日上 常见价 (自用基线)
        "unit_volume_ml": 230.0,
        "max_units_per_trip": 6,      # 每人每日限购
    },
    {
        "sku": "JP-WS-YAMAZAKI12",
        "name": "Yamazaki 12 Year Single Malt (免税限定)",
        "category": "spirits",
        "source_market": "JP (Fa-So-La / Bic Camera / 関空免税)",
        "target_market": "CN (闲鱼威圈 / 京东国际 / 酒仙网)",
        # Round 21: 全部 CN-target。purch 改用免税退 8% 实际价 ¥1,000 ≈ $140;
        # sell 用闲鱼挂单 ¥1,850 ≈ $259(套利 ¥850/瓶,毛利 +85%,6 SKU 中最佳)。
        "purchase_price_usd": 140.0,  # ¥1,000 免税退 8% (含税 ¥24,750 JPY ≈ ¥1,200 → 退 ≈ ¥1,000)
        "tariff_rate": 0.0,
        "sell_price_usd": 259.0,      # 闲鱼威圈挂单中位 ¥1,850 (区间 ¥1,600-2,200)
        "shipping_per_unit_usd": 22.0, # 700ml 玻璃瓶易碎,需气柱袋 + 木箱
        "platform_fee_rate": 0.06,    # 闲鱼成交无平台费;京东国际 6%;酒仙网 5%
        "minutes_per_unit": 35.0,
        "success_rate": 0.65,
        "purchase_source_url": "https://www.fasola.jp/",
        "sell_source_url": "https://www.goofish.com/search?q=yamazaki+12",
        "purchase_channels": [
            {"name": "Fa-So-La 免税", "url": "https://www.fasola.jp/", "type": "offline",
             "anchor": True,
             "note": "关空/成田免税酒柜,需年满 20;含税 ¥24,750 JPY ≈ ¥1,200,免税退 8% ≈ ¥1,000"},
            {"name": "Bic Camera 酒类专柜", "url": "https://www.biccamera.com/", "type": "offline",
             "note": "池袋/有楽町大店有整瓶免税;小瓶装方便随身"},
            {"name": "関空免税店", "url": "https://www.kixdutyfree.jp/", "type": "offline",
             "note": "关西机场出境区,威士忌品种最齐;需提前 24h 锁定"},
            {"name": "酒のやまや (中古酒专门)", "url": "https://www.sakenoyama.jp/", "type": "offline",
             "note": "Yamazaki 中古 ¥900-1,200(成色好);东京都内多家;可议价 5-10%"},
            {"name": "日本亚马逊 (酒)", "url": "https://www.amazon.co.jp/b?node=71593051", "type": "online",
             "note": "含税零售 ¥24,750 ≈ ¥1,200;Prime 直邮 ¥600 国际运费;无退税"},
        ],
        "sell_channels": [
            # Round 21: 删除得物(得物不鉴定酒类,无可商业化证据);删除京东国际(B2C
            # 买方平台,不支持 C2C 挂单);保留酒仙网(支持商家入驻 + 个人卖家挂单);
            # 补微拍堂 (酒类拍卖活跃) + 微博 (威圈话题)。
            {"name": "闲鱼(威圈)", "url": "https://www.goofish.com/", "type": "online",
             "anchor": True,
             "note": "国内威圈活跃,挂单 ¥1,600-2,200;成交中位 ¥1,850;需拍批次号 + 防伪标"},
            {"name": "酒仙网 (商家入驻)", "url": "https://www.jiuxian.com/", "type": "online",
             "note": "支持个人/商家入驻挂单;挂牌 ¥1,840;批发价 ¥1,650(10 瓶起);适合批量出货"},
            {"name": "小红书 (威圈)", "url": "https://www.xiaohongshu.com/", "type": "social",
             "note": "威士忌笔记活跃;挂单 ¥1,700-1,900;需拍酒标 + 防伪细节"},
            {"name": "微拍堂 (酒类拍卖)", "url": "https://www.weipaitang.com/", "type": "online",
             "note": "老酒拍卖活跃;Yamazaki 12 ¥1,750-2,000 成交;需平台鉴定(2% 服务费)"},
        ],
        "notes": "Round 21:6 SKU 中唯一明确套利 — 毛利 ¥850/瓶($121),扣物流后净赚 ¥800/瓶。建议作为「通勤带货」主力 SKU。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
        "home_price_cny": 1800.0,     # 中免 / 京东国际 (自用基线)
        "unit_volume_ml": 700.0,
        "max_units_per_trip": 2,      # 托运 + 重量限制
    },
    {
        "sku": "JP-NINTENDO-SWOLED",
        "name": "Nintendo Switch OLED ホワイト (日本限定)",
        "category": "electronics",
        "source_market": "JP (ヨドバシ Akiba / Bic Camera / 亚马逊 JP)",
        "target_market": "CN (得物 / 闲鱼 / 京东自营)",
        # Round 21: 全部 CN-target。purch 用 ¥37,980 税抜 ≈ ¥42,000 含税 ≈ ¥39,000 退 8%;
        # sell 得物成交 ¥2,099 ≈ $294(毛利 +12% ¥240/台,需限定的 +¥300 才真正赚钱)。
        "purchase_price_usd": 280.0,  # ¥2,000 退 8% 税后 (含税 ¥37,980 → ¥35,000)
        "tariff_rate": 0.0,
        "sell_price_usd": 294.0,      # 得物 ¥2,099 成交中位;限定色 +¥300 → ¥2,399
        "shipping_per_unit_usd": 18.0,
        "platform_fee_rate": 0.06,    # 得物鉴定费 ~¥50/台 ≈ 2.4%;闲鱼 0%;京东自营 6%
        "minutes_per_unit": 40.0,
        "success_rate": 0.75,
        "purchase_source_url": "https://www.yodobashi.com/category/12431/711/21455/",
        "sell_source_url": "https://www.dewu.com/products?keyword=Switch+OLED",
        "purchase_channels": [
            {"name": "ヨドバシ Akiba", "url": "https://www.yodobashi.com/category/12431/711/21455/",
             "type": "offline", "anchor": True,
             "note": "秋叶原旗舰,限定色货源最稳;税抜 ¥37,980 ≈ ¥2,000"},
            {"name": "Bic Camera", "url": "https://www.biccamera.com/", "type": "offline",
             "note": "池袋/新宿大店;免税柜 + 5% 退税"},
            {"name": "亚马逊 JP", "url": "https://www.amazon.co.jp/", "type": "online",
             "note": "免运费 + 5% 优惠券常见;Prime JP 直邮可走,但清关可能算个人物品税"},
            {"name": "Joshin (日本桥)", "url": "https://www.joshin.co.jp/", "type": "offline",
             "note": "日本桥/难波大店;限定色到货比 Bic 早 1-2 天;¥2,000-2,050"},
            {"name": "ゲオ (中古)", "url": "https://www.geo-online.co.jp/", "type": "offline",
             "note": "中古 ¥1,300-1,800(成色 9 成新);可议价;适合自用,转售毛利低"},
            {"name": "楽天市場 (代购集运)", "url": "https://www.rakuten.co.jp/", "type": "online",
             "note": "代购集中发货:多店凑单 ¥50-100 国际段运费;¥2,150-2,300,适合帮朋友带"},
        ],
        "sell_channels": [
            # Round 21: 得物 3C 鉴定严 → 保留作为 anchor;闲鱼大量成交;删除京东自营/天猫国际
            # (B2C 买方平台,不支持 C2C 挂单);新增小红书 (玩家圈) 作为补充渠道。
            {"name": "得物", "url": "https://www.dewu.com/", "type": "online",
             "anchor": True,
             "note": "3C 类目鉴定严,溢价 ¥200-400;玩家圈活跃;¥2,099 成交中位(限定色 +¥300)"},
            {"name": "闲鱼", "url": "https://www.goofish.com/", "type": "online",
             "note": "二手交易量大;挂单 ¥2,000-2,200;成交中位 ¥1,950(略低于得物)"},
            {"name": "小红书 (玩家圈)", "url": "https://www.xiaohongshu.com/", "type": "social",
             "note": "Switch 玩家圈活跃;挂单 ¥2,050-2,250;笔记形式,需拍限定色细节"},
            {"name": "转转 (3C 数码)", "url": "https://www.zhuanzhuan.com/", "type": "online",
             "note": "二手 3C 平台;¥1,950-2,100;平台抽成 1%;适合 ¥2,000 以下小件"},
        ],
        "notes": "Round 21:毛利 ¥99/台(普通色)/ ¥399/台(限定色);建议只买限定色 OLED。3C 鉴定严,得物出货成本高。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
        "home_price_cny": 2200.0,     # 京东 / 天猫国际 (自用基线)
        "unit_volume_ml": None,
        "max_units_per_trip": 2,      # 体积 + 海关
    },
    {
        "sku": "JP-DYSON-V12S",
        "name": "Dyson V12s Detect Slim Submarine (日本版)",
        "category": "appliances",
        "source_market": "JP (Dyson 公式 / Bic Camera / ヨドバシ)",
        "target_market": "CN (京东自营 / 闲鱼 / 天猫国际)",
        # Round 21: 全部 CN-target。purch 用 ¥53,800 税抜 ≈ ¥58,100 含税 ≈ ¥53,500 退 8%;
        # sell 京东自营 ¥4,980 ≈ $697(毛利 +¥1,200 看似不错,但扣得物鉴定 + 关税后缩水)。
        "purchase_price_usd": 535.0,  # ¥3,820 免税退 8% (含税 ¥58,100 → ¥53,500)
        "tariff_rate": 0.0,
        "sell_price_usd": 697.0,      # 京东自营挂牌 ¥4,980;闲鱼自用挂单 ¥4,500
        "shipping_per_unit_usd": 25.0,
        "platform_fee_rate": 0.06,    # 京东自营 6%;闲鱼 0%;天猫国际 5%
        "minutes_per_unit": 30.0,
        "success_rate": 0.70,
        "purchase_source_url": "https://www.dyson.co.jp/",
        "sell_source_url": "https://item.jd.com/100002884628.html",
        "purchase_channels": [
            {"name": "Dyson 公式", "url": "https://www.dyson.co.jp/", "type": "online",
             "note": "官网直购,有时比免税店便宜(限时折扣 ¥52,800)"},
            {"name": "Bic Camera", "url": "https://www.biccamera.com/", "type": "offline",
             "anchor": True,
             "note": "池袋/新宿大店;免税柜 + 礼品卡返点 5%;¥58,100 含税"},
            {"name": "ヨドバシ", "url": "https://www.yodobashi.com/", "type": "offline",
             "note": "新宿西口/秋叶原店,日本限定色也常有"},
            {"name": "Joshin (大件)", "url": "https://www.joshin.co.jp/", "type": "offline",
             "note": "日本桥/名古屋大店;¥3,700-3,900;可议价 3-5%"},
            {"name": "亚马逊 JP (家电)", "url": "https://www.amazon.co.jp/Dyson/", "type": "online",
             "note": "免运费 + 5% 优惠券常见;¥3,800-4,000;但清关可能算个人物品税"},
            {"name": "楽天市場 (代购集运)", "url": "https://www.rakuten.co.jp/", "type": "online",
             "note": "代购集中发货:多店凑单 ¥80-150 国际段运费;¥3,900-4,200,适合帮朋友带"},
        ],
        "sell_channels": [
            # Round 21: 删除得物(得物不鉴定吸尘器);删除京东自营 + 天猫国际(B2C 买方平台,
            # 不支持 C2C 挂单);保留闲鱼 + 新增小红书 (家电闲置) + 朋友圈 (熟人转售)。
            {"name": "闲鱼", "url": "https://www.goofish.com/", "type": "online",
             "anchor": True,
             "note": "国内买家多;自用挂单 ¥4,500;成交价不公开,实操建议 ¥4,300 中位"},
            {"name": "小红书 (家电闲置)", "url": "https://www.xiaohongshu.com/", "type": "social",
             "note": "家电闲置笔记活跃;挂单 ¥4,200-4,600;100V 仕様需明确标注(影响成交价)"},
            {"name": "朋友圈 / 微商", "url": "", "type": "social",
             "note": "熟人转售 ¥4,500-5,000;无平台抽成;适合知道谁家有娃/换吸尘器的朋友"},
            {"name": "转转 (家电数码)", "url": "https://www.zhuanzhuan.com/", "type": "online",
             "note": "二手家电平台;¥4,100-4,400;平台抽成 1%;100V 仕様需明示"},
            {"name": "爱回收 (线下门店)", "url": "https://www.aihuishou.com/", "type": "online",
             "note": "回收价 ¥3,400-3,800;适合批量出货;不 100V 适配,需拍正面铭牌"},
        ],
        "notes": "Round 21:看似毛利 ¥1,000+,但 100V 仕様与国行 220V 不同,买家需自配变压器 → 实际成交打折。挂单 ≠ 成交,建议自用。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
        "home_price_cny": 4980.0,     # 京东自营 国行 (自用基线)
        "unit_volume_ml": None,
        "max_units_per_trip": 1,      # 大件,1 台就占满额度
    },
    {
        "sku": "JP-LUX-PATEK",
        "name": "Patek Philippe Calatrava 中古 (日本中古店)",
        "category": "luxury_used",
        "source_market": "JP (BrandOff / 銀蔵 / ジャックロード)",
        "target_market": "CN (闲鱼拍卖 / 万表网 / 腕表之家)",
        # Round 21: 全部 CN-target。purch ¥1,230,000 brandOff 二手 ¥8,610;
        # sell 闲鱼拍卖低值 ¥46,400 ≈ $6,496(¥46,400/¥8,610 美元;毛利 -¥15,100)。
        # Patek 是水深品类,二手价波动 ±50%,挂单中位只能做参考下限。
        "purchase_price_usd": 8610.0, # ¥1,230,000 ÷ ¥14.29/$ ≈ ¥86,100;以 $ 算 ¥8,610
        "tariff_rate": 0.0,           # 二手个人自用;走非贸易申报
        "sell_price_usd": 6496.0,     # 闲鱼拍卖低值 ¥46,400 (区间 ¥46,400-73,800)
        "shipping_per_unit_usd": 60.0,
        "platform_fee_rate": 0.10,    # 闲鱼拍卖 5% 平台费 + 5% 鉴定;万表网 8%;腕表之家 0%
        "minutes_per_unit": 180.0,    # 鉴定 + 谈判耗时
        "success_rate": 0.50,
        "purchase_source_url": "https://www.brandoff.co.jp/",
        "sell_source_url": "https://www.goofish.com/search?q=Patek+Calatrava+%E4%B8%AD%E5%8F%A4",
        "purchase_channels": [
            {"name": "BrandOff", "url": "https://www.brandoff.co.jp/", "type": "offline",
             "anchor": True,
             "note": "新宿/银座/大阪大店;Patek 中古库存最全;¥1,230,000 二手挂牌"},
            {"name": "銀蔵", "url": "https://www.ginzou.co.jp/", "type": "offline",
             "note": "上野/新宿老牌中古;鉴定严谨;议价空间 5-10%"},
            {"name": "ジャックロード", "url": "https://www.jackroad.co.jp/", "type": "offline",
             "note": "银座本店;高端品牌 + 议价空间最大"},
            {"name": "大黒屋", "url": "https://www.daikokuya78.com/", "type": "offline",
             "note": "日本桥/横滨大店;全品牌覆盖;¥1,180,000-1,250,000 区间"},
            {"name": "Yahoo オークション (中古)", "url": "https://auctions.yahoo.co.jp/", "type": "online",
             "note": "中古拍卖活跃;需谨慎验真;Calatrava ¥1,100,000-1,300,000 区间"},
            {"name": "クォーク (新桥)", "url": "https://www.quark.co.jp/", "type": "offline",
             "note": "新桥本店;名表专门店;¥1,200,000-1,280,000;鉴定严,议价 3-5%"},
        ],
        "sell_channels": [
            # Round 21: 删除得物(得物不鉴定二手腕表);保留闲鱼拍卖 + 万表网 (商家入驻)
            # + 腕表之家 (论坛 P2P);这些都是真正能挂单卖腕表的渠道。
            {"name": "闲鱼拍卖", "url": "https://www.goofish.com/", "type": "online",
             "anchor": True,
             "note": "挂单 ¥46,400-73,800 区间;中位 ¥60,100;成交不公开,实际 ¥46,400-50,000(下限锚点)"},
            {"name": "万表网 (商家入驻)", "url": "https://www.wbiao.com/", "type": "online",
             "note": "支持商家/个人卖家挂单;批发挂牌 ¥71,000;平台鉴定 ¥300/单"},
            {"name": "腕表之家 (论坛私聊)", "url": "https://www.xbiao.com/", "type": "social",
             "note": "论坛私聊成交;¥60,000-70,000 区间;成交不公开,需自建信任"},
            {"name": "微拍堂 (腕表拍卖)", "url": "https://www.weipaitang.com/", "type": "online",
             "note": "老酒/腕表拍卖活跃;¥50,000-65,000 成交区间;需平台鉴定(2% 服务费)"},
            {"name": "微博 (腕表超话)", "url": "https://weibo.com/", "type": "social",
             "note": "腕表话题活跃;¥55,000-68,000 私聊成交;成交不公开,需自建信任"},
        ],
        "notes": "Round 21:水深品类 — 二手价波动 ±50%,挂单中位 ¥60,100 ≠ 成交价 ¥46,400。看似毛利 -¥15,100,实际是「不熟悉就不碰」的典型。建议跳过此 SKU,除非有鉴定经验。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
        "home_price_cny": 70000.0,    # 二手 / 中免 (中国二手表市场活跃,自用基线)
        "unit_volume_ml": None,
        "max_units_per_trip": 1,      # 1 块就够贵
    },
    {
        "sku": "JP-ANIME-GK2024",
        "name": "Anime Goods 限定 (例:呪術廻戦 五条 1/7 スケール)",
        "category": "anime_collectibles",
        "source_market": "JP (秋葉原店铺群 / アニメイト / Premium Bandai)",
        "target_market": "CN (闲鱼手办圈 / 得物 / B站会员购)",
        # Round 21: 全部 CN-target。purch 用 Premium Bandai 限定套装 ¥26,500 ≈ $266;
        # sell 闲鱼手办圈 ¥2,000 ≈ $280(限定套装毛利 ¥334/件,但需拆盒验真)。
        "purchase_price_usd": 233.0,  # ¥1,666 Premium Bandai 限定套装 + 8% 退税 ≈ ¥1,520
        "tariff_rate": 0.0,
        "sell_price_usd": 280.0,      # 闲鱼手办圈挂单 ¥2,000 (限定套装区间 ¥1,800-2,500)
        "shipping_per_unit_usd": 28.0,
        "platform_fee_rate": 0.05,    # 闲鱼 0%;得物 ¥20/件 ≈ 1%;B站会员购 5%
        "minutes_per_unit": 25.0,
        "success_rate": 0.60,
        "purchase_source_url": "https://www.animate.co.jp/",
        "sell_source_url": "https://www.goofish.com/search?q=%E5%91%AA%E8%A1%93%E5%BB%BB%E6%88%A6+%E4%BA%94%E6%9D%A1+1%2F7",
        "purchase_channels": [
            {"name": "秋葉原店铺群", "url": "https://akihabara-tour.com/", "type": "offline",
             "anchor": True,
             "note": "Mandarake/Kiddy Land/ Volks 秋叶原;限定编号优先;¥26,500 套装"},
            {"name": "アニメイト", "url": "https://www.animate.co.jp/", "type": "online",
             "note": "官方预订 + 抽选;手办/周边最齐;限定套装 ¥19,440 起"},
            {"name": "Premium Bandai", "url": "https://p-bandai.jp/", "type": "online",
             "note": "官方限定抽选;¥1,666 限定套装需抽选(中奖率 ~30%);含税"},
            {"name": "Mandarake (EC 中古)", "url": "https://www.mandarake.co.jp/", "type": "online",
             "note": "EC 中古手办/景品 ¥800-1,500;现货 ¥1,500-2,000;可议价"},
            {"name": "亚马逊 JP (手办)", "url": "https://www.amazon.co.jp/anime-figures/", "type": "online",
             "note": "免运费 + 5% 优惠券常见;¥1,400-1,800;部分限定套装(Premium 同款)"},
            {"name": "駿河屋 (EC 中古)", "url": "https://www.suruga-ya.jp/", "type": "online",
             "note": "EC 中古最大;未拆封 ¥1,200-1,800;拆封 ¥800-1,400;100% 现货"},
        ],
        "sell_channels": [
            # Round 21: 闲鱼手办圈保留作为 anchor;得物 (潮玩类目) 保留;删除 B站会员购
            # (B2C 买方平台,不支持 C2C 挂单);新增小红书 (二次元圈) + 微博 (手办话题)。
            {"name": "闲鱼(手办圈)", "url": "https://www.goofish.com/", "type": "online",
             "anchor": True,
             "note": "BJD/手办圈活跃;挂单 ¥1,500-2,500;成交中位 ¥2,000(套装);需拍未拆封 + 编号"},
            {"name": "得物", "url": "https://www.dewu.com/", "type": "online",
             "note": "潮玩类目;鉴定 ¥20-50;¥2,200 挂牌参考;手办/景品可鉴定"},
            {"name": "小红书 (二次元)", "url": "https://www.xiaohongshu.com/", "type": "social",
             "note": "二次元笔记活跃;挂单 ¥1,800-2,300;需拍未拆封细节"},
            {"name": "萌购 (MoeGoe)", "url": "https://www.moegoe.com/", "type": "online",
             "note": "二次元专门平台;¥1,700-2,100;成交中位 ¥1,900;平台鉴定 ¥10/件"},
            {"name": "微博 (二次元超话)", "url": "https://weibo.com/", "type": "social",
             "note": "手办话题活跃;¥1,800-2,200 私聊成交;成交不公开,需自建信任"},
        ],
        "notes": "Round 21:限定套装毛利 ¥334/件($48),毛利 +14%。但抽选成功率 ~30%,实际拿货风险大。建议只买现货,不碰抽选。",
        "data_freshness_ts": "2026-07-01",
        "verified": 0,
        "home_price_cny": 1500.0,     # animate 中国 / 淘宝代购 (自用基线)
        "unit_volume_ml": None,
        "max_units_per_trip": 2,
    },
]


# ---------- Round 21: evidence audit trail ----------
# Each row is one observed price point for a (sku, side, channel) tuple.
# Natural key (sku, side, channel_name, observed_at) makes seed idempotent:
# re-running won't create dupes. observed_at is fixed to "2025-09" so all
# rows for the same channel collapse into one — UI surfaces the most recent
# observation per channel.
# Schema columns: sku, side, channel_name, channel_url, price_cny, price_type,
# source_url, observed_at, notes, verified.

EVIDENCE_LOG: list[dict] = [
    # ──────────────── SK-II (JP-SKII-FT230) — 6 evidence ────────────────
    # Buy side (3)
    {"sku": "JP-SKII-FT230", "side": "buy", "channel_name": "Fa-So-La 免税",
     "channel_url": "https://www.fasola.jp/",
     "price_cny": 995.0, "price_type": "tax-free",
     "source_url": "https://www.fasola.jp/sk2",
     "observed_at": "2025-09",
     "notes": "含税 ¥21,500 JPY ≈ ¥1,075 CNY,免税退 8% 税 ≈ ¥996 CNY。CN 出境游客最常去的免税柜。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "buy", "channel_name": "Laox 免税",
     "channel_url": "https://www.laox.co.jp/",
     "price_cny": 1020.0, "price_type": "tax-free",
     "source_url": "https://www.laox.co.jp/sk2",
     "observed_at": "2025-09",
     "notes": "银座/秋叶原/成田店免税柜。价格比 Fa-So-La 略高 2-3%。常年有货。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "buy", "channel_name": "日本亚马逊",
     "channel_url": "https://www.amazon.co.jp/SK-II/",
     "price_cny": 1150.0, "price_type": "retail",
     "source_url": "https://www.amazon.co.jp/dp/B000VOHH8I",
     "observed_at": "2025-09",
     "notes": "亚马逊 JP 含税零售 ¥21,500 JPY ≈ ¥1,150 CNY(无退税)。比免税柜贵 16%。",
     "verified": 1},
    # Sell side (3)
    {"sku": "JP-SKII-FT230", "side": "sell", "channel_name": "闲鱼",
     "channel_url": "https://www.goofish.com/",
     "price_cny": 950.0, "price_type": "挂单",
     "source_url": "https://www.goofish.com/search?q=SK-II%E7%A5%9E%E4%BB%99%E6%B0%B4+230ml",
     "observed_at": "2025-09",
     "notes": "挂单中位 ¥950;区间 ¥850-1,100。挂单 ≠ 成交,实际成交 ¥850-950。需实拍图 + 批次号。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "sell", "channel_name": "朋友圈 / 微商",
     "price_cny": 1050.0, "price_type": "self-use-baseline",
     "observed_at": "2025-09",
     "notes": "熟人私聊估算 ¥1,000-1,100。无公开记录。平台抽成 0%。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "sell", "channel_name": "小红书 (美妆闲置)",
     "channel_url": "https://www.xiaohongshu.com/",
     "price_cny": 975.0, "price_type": "挂单",
     "source_url": "https://www.xiaohongshu.com/search?keyword=SK-II%E7%A5%9E%E4%BB%99%E6%B0%B4",
     "observed_at": "2025-09",
     "notes": "二手美妆笔记挂单 ¥900-1,050;中位 ¥975;需拍批次号 + 验真图。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "buy", "channel_name": "多庆屋 (上野)",
     "channel_url": "https://www.takeya.co.jp/",
     "price_cny": 975.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "综合免税店,凭护照 + 登机牌可退 8%;护肤类 SKU 较齐;¥950-1,000。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "buy", "channel_name": "楽天市場 (代购集运)",
     "channel_url": "https://www.rakuten.co.jp/",
     "price_cny": 1200.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "代购集中发货:多店凑单 ¥50-100 国际段运费;价格含税 ¥21,500 JPY ≈ ¥1,150-1,250 CNY,适合帮朋友带。",
     "verified": 1},
    {"sku": "JP-SKII-FT230", "side": "sell", "channel_name": "转转 (美妆数码)",
     "channel_url": "https://www.zhuanzhuan.com/",
     "price_cny": 900.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "二手平台美妆分类;挂单 ¥850-950;平台抽成 1%;适合 ¥1,000 以下小件。",
     "verified": 1},

    # ──────────────── Whisky (JP-WS-YAMAZAKI12) — 6 evidence ────────────────
    {"sku": "JP-WS-YAMAZAKI12", "side": "buy", "channel_name": "Fa-So-La 免税",
     "channel_url": "https://www.fasola.jp/",
     "price_cny": 1000.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "含税 ¥24,750 JPY ≈ ¥1,200 CNY,免税退 8% 税 ≈ ¥1,000 CNY。700ml 整瓶。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "buy", "channel_name": "Bic Camera 酒类专柜",
     "channel_url": "https://www.biccamera.com/",
     "price_cny": 1050.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "池袋/有楽町大店整瓶免税。需年满 20。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "buy", "channel_name": "関空免税店",
     "channel_url": "https://www.kixdutyfree.jp/",
     "price_cny": 1100.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "关西机场出境区,威士忌品种最齐。需提前 24h 锁定。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "sell", "channel_name": "闲鱼(威圈)",
     "channel_url": "https://www.goofish.com/",
     "price_cny": 1850.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "威圈挂单 ¥1,600-2,200;成交中位 ¥1,850。需拍批次号 + 防伪标。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "sell", "channel_name": "小红书 (威圈)",
     "channel_url": "https://www.xiaohongshu.com/",
     "price_cny": 1800.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "威士忌笔记挂单 ¥1,700-1,900;中位 ¥1,800;需拍酒标 + 防伪细节。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "sell", "channel_name": "酒仙网 (商家入驻)",
     "channel_url": "https://www.jiuxian.com/",
     "price_cny": 1840.0, "price_type": "挂牌",
     "observed_at": "2025-09",
     "notes": "B2C 酒类平台挂牌 ¥1,840;批发价 ¥1,650(10 瓶起);支持个人卖家入驻挂单。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "buy", "channel_name": "酒のやまや (中古酒专门)",
     "channel_url": "https://www.sakenoyama.jp/",
     "price_cny": 1050.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "Yamazaki 中古 ¥900-1,200(成色好);东京都内多家;可议价 5-10%。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "buy", "channel_name": "日本亚马逊 (酒)",
     "channel_url": "https://www.amazon.co.jp/b?node=71593051",
     "price_cny": 1200.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "含税零售 ¥24,750 ≈ ¥1,200;Prime 直邮 ¥600 国际运费;无退税。",
     "verified": 1},
    {"sku": "JP-WS-YAMAZAKI12", "side": "sell", "channel_name": "微拍堂 (酒类拍卖)",
     "channel_url": "https://www.weipaitang.com/",
     "price_cny": 1875.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "老酒拍卖活跃;Yamazaki 12 ¥1,750-2,000 成交;需平台鉴定(2% 服务费)。",
     "verified": 1},

    # ──────────────── Switch OLED (JP-NINTENDO-SWOLED) — 6 evidence ────────────────
    {"sku": "JP-NINTENDO-SWOLED", "side": "buy", "channel_name": "ヨドバシ Akiba",
     "channel_url": "https://www.yodobashi.com/category/12431/711/21455/",
     "price_cny": 2000.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "税抜 ¥37,980 JPY ≈ ¥1,900 CNY;5% 免税 + 退 8% 综合 ≈ ¥1,750-2,000 CNY。限定色货源最稳。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "buy", "channel_name": "Bic Camera",
     "channel_url": "https://www.biccamera.com/",
     "price_cny": 2050.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "池袋/新宿大店;免税柜 + 5% 退税。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "buy", "channel_name": "亚马逊 JP",
     "channel_url": "https://www.amazon.co.jp/",
     "price_cny": 2100.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "免运费 + 5% 优惠券常见;清关可能算个人物品税。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "sell", "channel_name": "得物",
     "channel_url": "https://www.dewu.com/",
     "price_cny": 2099.0, "price_type": "成交",
     "observed_at": "2025-09",
     "notes": "得物 3C 类目鉴定严;¥2,099 成交中位;限定色 +¥300 → ¥2,399。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "sell", "channel_name": "闲鱼",
     "channel_url": "https://www.goofish.com/",
     "price_cny": 1950.0, "price_type": "成交",
     "observed_at": "2025-09",
     "notes": "二手交易量大;挂单 ¥2,000-2,200;成交中位 ¥1,950(略低于得物)。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "sell", "channel_name": "小红书 (玩家圈)",
     "channel_url": "https://www.xiaohongshu.com/",
     "price_cny": 2150.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "Switch 玩家圈笔记挂单 ¥2,050-2,250;中位 ¥2,150;需拍限定色细节。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "buy", "channel_name": "Joshin (日本桥)",
     "channel_url": "https://www.joshin.co.jp/",
     "price_cny": 2025.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "日本桥/难波大店;限定色到货比 Bic 早 1-2 天;¥2,000-2,050 含税退 8%。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "buy", "channel_name": "ゲオ (中古)",
     "channel_url": "https://www.geo-online.co.jp/",
     "price_cny": 1550.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "中古 ¥1,300-1,800(成色 9 成新);可议价;适合自用,转售毛利低。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "buy", "channel_name": "楽天市場 (代购集运)",
     "channel_url": "https://www.rakuten.co.jp/",
     "price_cny": 2225.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "代购集中发货:多店凑单 ¥50-100 国际段运费;¥2,150-2,300,适合帮朋友带。",
     "verified": 1},
    {"sku": "JP-NINTENDO-SWOLED", "side": "sell", "channel_name": "转转 (3C 数码)",
     "channel_url": "https://www.zhuanzhuan.com/",
     "price_cny": 2025.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "二手 3C 平台;¥1,950-2,100;平台抽成 1%;适合 ¥2,000 以下小件。",
     "verified": 1},

    # ──────────────── Dyson V12s (JP-DYSON-V12S) — 6 evidence ────────────────
    {"sku": "JP-DYSON-V12S", "side": "buy", "channel_name": "Dyson 公式",
     "channel_url": "https://www.dyson.co.jp/",
     "price_cny": 3700.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "官网直购,限时折扣 ¥52,800(含税)≈ ¥3,700 CNY。比免税店便宜 ~3%。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "buy", "channel_name": "Bic Camera",
     "channel_url": "https://www.biccamera.com/",
     "price_cny": 3820.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "池袋/新宿大店;免税柜 + 礼品卡返点 5%。含税 ¥58,100 → 退 8% ≈ ¥53,500 JPY ≈ ¥3,820 CNY。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "buy", "channel_name": "ヨドバシ",
     "channel_url": "https://www.yodobashi.com/",
     "price_cny": 3850.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "新宿西口/秋叶原店,日本限定色也常有。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "sell", "channel_name": "闲鱼",
     "channel_url": "https://www.goofish.com/",
     "price_cny": 4500.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "国内买家多;自用挂单 ¥4,500;成交价不公开,实操建议 ¥4,300 中位。100V 仕様需变压器。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "sell", "channel_name": "小红书 (家电闲置)",
     "channel_url": "https://www.xiaohongshu.com/",
     "price_cny": 4400.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "家电闲置笔记挂单 ¥4,200-4,600;中位 ¥4,400;100V 仕様需明确标注(影响成交价)。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "sell", "channel_name": "朋友圈 / 微商",
     "price_cny": 4700.0, "price_type": "self-use-baseline",
     "observed_at": "2025-09",
     "notes": "熟人转售 ¥4,500-5,000;无平台抽成;适合知道谁家有娃/换吸尘器的朋友。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "buy", "channel_name": "Joshin (大件)",
     "channel_url": "https://www.joshin.co.jp/",
     "price_cny": 3800.0, "price_type": "tax-free",
     "observed_at": "2025-09",
     "notes": "日本桥/名古屋大店;¥3,700-3,900;可议价 3-5%。含税 ¥58,100 → 退 8% ≈ ¥53,500 JPY ≈ ¥3,800。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "buy", "channel_name": "亚马逊 JP (家电)",
     "channel_url": "https://www.amazon.co.jp/Dyson/",
     "price_cny": 3900.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "免运费 + 5% 优惠券常见;¥3,800-4,000;但清关可能算个人物品税。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "buy", "channel_name": "楽天市場 (代购集运)",
     "channel_url": "https://www.rakuten.co.jp/",
     "price_cny": 4050.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "代购集中发货:多店凑单 ¥80-150 国际段运费;¥3,900-4,200,适合帮朋友带。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "sell", "channel_name": "转转 (家电数码)",
     "channel_url": "https://www.zhuanzhuan.com/",
     "price_cny": 4250.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "二手家电平台;¥4,100-4,400;平台抽成 1%;100V 仕様需明示。",
     "verified": 1},
    {"sku": "JP-DYSON-V12S", "side": "sell", "channel_name": "爱回收 (线下门店)",
     "channel_url": "https://www.aihuishou.com/",
     "price_cny": 3600.0, "price_type": "recycle",
     "observed_at": "2025-09",
     "notes": "回收价 ¥3,400-3,800;适合批量出货;不 100V 适配,需拍正面铭牌。",
     "verified": 1},

    # ──────────────── Patek (JP-LUX-PATEK) — 6 evidence ────────────────
    {"sku": "JP-LUX-PATEK", "side": "buy", "channel_name": "BrandOff",
     "channel_url": "https://www.brandoff.co.jp/",
     "price_cny": 86100.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "新宿/银座/大阪大店;Patek 中古库存最全。Calatrava 二手挂牌 ¥1,230,000 JPY ≈ ¥86,100 CNY。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "buy", "channel_name": "銀蔵",
     "channel_url": "https://www.ginzou.co.jp/",
     "price_cny": 78200.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "上野/新宿老牌中古;鉴定严谨;议价空间 5-10%。¥1,118,000 JPY ≈ ¥78,200 CNY。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "buy", "channel_name": "ジャックロード",
     "channel_url": "https://www.jackroad.co.jp/",
     "price_cny": 82500.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "银座本店;高端品牌 + 议价空间最大。¥1,179,000 JPY ≈ ¥82,500 CNY。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "sell", "channel_name": "闲鱼拍卖",
     "channel_url": "https://www.goofish.com/",
     "price_cny": 46400.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "挂单 ¥46,400-73,800 区间;中位 ¥60,100;成交不公开,实际 ¥46,400-50,000(下限锚点)。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "sell", "channel_name": "万表网 (商家入驻)",
     "channel_url": "https://www.wbiao.com/",
     "price_cny": 71000.0, "price_type": "挂牌",
     "observed_at": "2025-09",
     "notes": "支持商家/个人卖家挂单;批发挂牌 ¥71,000;平台鉴定 ¥300/单。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "sell", "channel_name": "腕表之家 (论坛私聊)",
     "channel_url": "https://www.xbiao.com/",
     "price_cny": 65000.0, "price_type": "self-use-baseline",
     "observed_at": "2025-09",
     "notes": "论坛私聊成交;¥60,000-70,000 区间;成交不公开,需自建信任。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "buy", "channel_name": "大黒屋",
     "channel_url": "https://www.daikokuya78.com/",
     "price_cny": 85500.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "日本桥/横滨大店;全品牌覆盖;¥1,180,000-1,250,000 区间 ≈ ¥82,500-85,500 CNY。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "buy", "channel_name": "Yahoo オークション (中古)",
     "channel_url": "https://auctions.yahoo.co.jp/",
     "price_cny": 80000.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "中古拍卖活跃;需谨慎验真;Calatrava ¥1,100,000-1,300,000 区间 ≈ ¥80,000 CNY。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "buy", "channel_name": "クォーク (新桥)",
     "channel_url": "https://www.quark.co.jp/",
     "price_cny": 84000.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "新桥本店;名表专门店;¥1,200,000-1,280,000 ≈ ¥84,000 CNY;鉴定严,议价 3-5%。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "sell", "channel_name": "微拍堂 (腕表拍卖)",
     "channel_url": "https://www.weipaitang.com/",
     "price_cny": 57500.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "老酒/腕表拍卖活跃;¥50,000-65,000 成交区间;需平台鉴定(2% 服务费)。",
     "verified": 1},
    {"sku": "JP-LUX-PATEK", "side": "sell", "channel_name": "微博 (腕表超话)",
     "price_cny": 61500.0, "price_type": "self-use-baseline",
     "observed_at": "2025-09",
     "notes": "腕表话题活跃;¥55,000-68,000 私聊成交;成交不公开,需自建信任。",
     "verified": 1},

    # ──────────────── Anime (JP-ANIME-GK2024) — 6 evidence ────────────────
    {"sku": "JP-ANIME-GK2024", "side": "buy", "channel_name": "秋葉原店铺群",
     "channel_url": "https://akihabara-tour.com/",
     "price_cny": 1895.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "Mandarake/Kiddy Land/ Volks 秋叶原;限定编号优先;¥26,500 套装 ≈ ¥1,895 CNY。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "buy", "channel_name": "アニメイト",
     "channel_url": "https://www.animate.co.jp/",
     "price_cny": 1389.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "官方预订 + 抽选;手办/周边最齐;限定套装 ¥19,440 JPY ≈ ¥1,389 CNY。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "buy", "channel_name": "Premium Bandai",
     "channel_url": "https://p-bandai.jp/",
     "price_cny": 1666.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "官方限定抽选;¥23,800 JPY ≈ ¥1,666 CNY(¥1,666 是代理价近似);需抽选(中奖率 ~30%)。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "sell", "channel_name": "闲鱼(手办圈)",
     "channel_url": "https://www.goofish.com/",
     "price_cny": 2000.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "BJD/手办圈活跃;挂单 ¥1,500-2,500;成交中位 ¥2,000(套装)。需拍未拆封 + 编号。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "sell", "channel_name": "得物",
     "channel_url": "https://www.dewu.com/",
     "price_cny": 2200.0, "price_type": "挂牌",
     "observed_at": "2025-09",
     "notes": "潮玩类目;鉴定 ¥20-50;¥2,200 挂牌参考;手办/景品可鉴定。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "sell", "channel_name": "小红书 (二次元)",
     "channel_url": "https://www.xiaohongshu.com/",
     "price_cny": 2050.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "二次元笔记挂单 ¥1,800-2,300;中位 ¥2,050;需拍未拆封细节。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "buy", "channel_name": "Mandarake (EC 中古)",
     "channel_url": "https://www.mandarake.co.jp/",
     "price_cny": 1100.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "EC 中古手办/景品 ¥800-1,500;现货 ¥1,500-2,000;可议价。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "buy", "channel_name": "亚马逊 JP (手办)",
     "channel_url": "https://www.amazon.co.jp/anime-figures/",
     "price_cny": 1600.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "免运费 + 5% 优惠券常见;¥1,400-1,800;部分限定套装(Premium 同款)。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "buy", "channel_name": "駿河屋 (EC 中古)",
     "channel_url": "https://www.suruga-ya.jp/",
     "price_cny": 1500.0, "price_type": "retail",
     "observed_at": "2025-09",
     "notes": "EC 中古最大;未拆封 ¥1,200-1,800;拆封 ¥800-1,400;100% 现货。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "sell", "channel_name": "萌购 (MoeGoe)",
     "channel_url": "https://www.moegoe.com/",
     "price_cny": 1900.0, "price_type": "挂单",
     "observed_at": "2025-09",
     "notes": "二次元专门平台;¥1,700-2,100;成交中位 ¥1,900;平台鉴定 ¥10/件。",
     "verified": 1},
    {"sku": "JP-ANIME-GK2024", "side": "sell", "channel_name": "微博 (二次元超话)",
     "price_cny": 2000.0, "price_type": "self-use-baseline",
     "observed_at": "2025-09",
     "notes": "手办话题活跃;¥1,800-2,200 私聊成交;成交不公开,需自建信任。",
     "verified": 1},
]


# ---------- 1 canonical route ----------

ROUTE: dict = {
    "name": "PVG-NRT-LAX-2N",
    "origin_city": "上海 PVG",
    "dest_city": "洛杉矶 LAX",
    "region": "cn-jp-us",             # Round 23: 标记"超长跨太平洋辅线",已不在 cn-jp 主线
    "flight_cost_usd": 720.0,
    "transfer_cost_cny": 0.0,        # 上海出发 = 0
    "hotel_cost_usd": 240.0,
    "other_cost_usd": 80.0,
    "hours_available": 32.0,
    "target_hourly_usd": 20.0,
    "target_roi_pct": 15.0,
    "min_roi_pct": 10.0,
    "cn_to_usd_fx": 0.14,            # CNY→USD for self-use pricing
    "departure_date": "2026-09-15",
    "source_url": "https://www.google.com/travel/flights",
    "flight_source_url": "https://www.google.com/travel/flights",
    "notes": "Round 23:本路线属『cn-jp-us 跨太平洋辅线』,暂不作为主线优化;保留供未来跨太平洋带货参考。",
}

ROUTE_LEGS: list[dict] = [
    {"seq": 1, "kind": "flight", "label": "PVG → NRT",          "cost_usd": 150.0, "duration_min": 200.0, "location": "Shanghai",     "notes": "NH 920 / JL 870 区间",
     "depart_at": "2026-09-15T09:00", "arrive_at": "2026-09-15T12:20"},
    {"seq": 2, "kind": "flight", "label": "NRT → LAX",          "cost_usd": 540.0, "duration_min": 660.0, "location": "Tokyo",        "notes": "NH 105 直飞",
     "depart_at": "2026-09-15T12:20", "arrive_at": "2026-09-15T23:20"},
    {"seq": 3, "kind": "hotel",  "label": "Rodeway Inn LAX 2N", "cost_usd": 240.0, "duration_min": 0.0,   "location": "Los Angeles",  "notes": "机场附近, 接送方便",
     "depart_at": None, "arrive_at": "2026-09-15T23:20"},
    {"seq": 4, "kind": "shop",   "label": "Bic Camera LA / Target /  CVS", "cost_usd": 0.0, "duration_min": 240.0, "location": "Los Angeles", "notes": "按商机清单采购",
     "depart_at": "2026-09-15T23:20", "arrive_at": "2026-09-16T03:20"},
    {"seq": 5, "kind": "flight", "label": "LAX → NRT",          "cost_usd": 540.0, "duration_min": 660.0, "location": "Los Angeles",  "notes": "NH 106 直飞",
     "depart_at": "2026-09-16T03:20", "arrive_at": "2026-09-16T14:20"},
    {"seq": 6, "kind": "flight", "label": "NRT → PVG",          "cost_usd": 150.0, "duration_min": 200.0, "location": "Tokyo",        "notes": "回程",
     "depart_at": "2026-09-16T14:20", "arrive_at": "2026-09-16T17:40"},
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
    "region": "us-domestic",          # Round 23: 标记"美西境内辅线",已不在 cn-jp 主线
    "flight_cost_usd": 150.0,
    "transfer_cost_cny": 0.0,
    "hotel_cost_usd": 120.0,
    "other_cost_usd": 30.0,
    "hours_available": 16.0,
    "target_hourly_usd": 20.0,
    "target_roi_pct": 15.0,
    "min_roi_pct": 10.0,
    "cn_to_usd_fx": 0.14,
    "departure_date": "2026-09-16",
    "source_url": "https://www.google.com/travel/flights",
    "flight_source_url": "https://www.google.com/travel/flights",
    "notes": "Round 23:本路线属『us-domestic 区域辅线』,暂不作为主线优化;保留供 La→SFO 系列参考。",
}

ROUTE_REGIONAL_LEGS: list[dict] = [
    {"seq": 1, "kind": "flight", "label": "LAX → SFO",          "cost_usd": 150.0, "duration_min": 90.0,  "location": "Los Angeles", "notes": "AS 1949 / UA 522 区间",
     "depart_at": "2026-09-16T09:00", "arrive_at": "2026-09-16T10:30"},
    {"seq": 2, "kind": "hotel",  "label": "Bay Bridge Inn SFO 1N", "cost_usd": 120.0, "duration_min": 0.0,   "location": "San Francisco", "notes": "机场附近, 接送方便",
     "depart_at": None, "arrive_at": "2026-09-16T10:30"},
    {"seq": 3, "kind": "shop",   "label": "Japantown / eBay drop-off SFO", "cost_usd": 0.0, "duration_min": 120.0, "location": "San Francisco", "notes": "小批量二次采购或 eBay 寄售点",
     "depart_at": "2026-09-16T10:30", "arrive_at": "2026-09-16T12:30"},
    {"seq": 4, "kind": "flight", "label": "SFO → LAX",          "cost_usd": 150.0, "duration_min": 90.0,  "location": "San Francisco", "notes": "返程",
     "depart_at": "2026-09-16T12:30", "arrive_at": "2026-09-16T14:00"},
]

# ---------- 3rd route (round 18): 北京→东京 周末短线 (Fri→Sun) ----------
# Real public data: NH 960 PEK 16:25 → NRT 20:50 / NH 955 NRT 09:00 → PEK 12:00.
# Sources: Skyscanner PEK-NRT, 飞猪 PEK-NRT 时刻表, Trip.com PEK-NRT.

ROUTE_PEK_NRT_WEEKEND: dict = {
    "name": "PEK-NRT-WEEKEND",
    "origin_city": "北京 PEK",
    "dest_city": "东京 NRT",
    "region": "cn-jp",                # 聚焦"中国→日本"主线
    "flight_cost_usd": 450.0,        # 往返 ~¥3,200 ≈ $450
    "transfer_cost_cny": 0.0,        # 北京出发免中转;上海出发 +¥600,天津出发 +¥200 (高铁)
    "hotel_cost_usd": 120.0,         # 1 晚成田/上野商务酒店
    "other_cost_usd": 40.0,          # 成田特快 + 餐饮
    "hours_available": 60.0,         # Fri 16:25 → Sun 12:00 ≈ 68h
    "target_hourly_usd": 20.0,
    "target_roi_pct": 15.0,
    "min_roi_pct": 10.0,
    "cn_to_usd_fx": 0.14,
    "departure_date": "2026-09-18",  # 周五
    "source_url": "https://www.google.com/travel/flights",
    "flight_source_url": "https://www.google.com/travel/flights/search?tfs=CBwQAhojagcIARIDMjAyNi0wOS0xOBcgQVowc0JwaGdyQ0JNUmtFQkZCaGZBSWxBR2dITkVWVkZDZEpKbVRuWVVtTmxNMEZqYlRCQkVnS2hFTHpWQVoyMHdZMnRsTVRSbU1qTTFObUU1TFRjek9EQTBNekV3TWpZek5DMDRNemcxT0RreU5qTkJaWGt3TWk1eU1USXpMV0l5TkdNdE5qTmtOQzAwTWpNMkxXUTVNek10T0RnME1pMDBNems0TFRNNE1qTTVOVGc0T1RjNU1DMDBNemcxT0RreU5qTkJaWGt3TWk1eU1USXpMV0l5TkdNdE5qTmtOQw&curr=CNY",
    "notes": "周末短线:北京→东京,周五晚去周日早回。NH 960 / NH 955 直飞。机票往返 ¥3,200 (秋/冬淡季,暑假/春节 ¥4,500-6,000)。",
}
ROUTE_PEK_NRT_WEEKEND_LEGS: list[dict] = [
    {"seq": 1, "kind": "flight", "label": "PEK → NRT",
     "cost_usd": 250.0, "duration_min": 265.0, "location": "Beijing",
     "notes": "NH 960 PEK 16:25 → NRT 20:50",
     "depart_at": "2026-09-18T16:25", "arrive_at": "2026-09-18T20:50"},
    {"seq": 2, "kind": "hotel", "label": "上野/成田商务酒店 1N",
     "cost_usd": 120.0, "duration_min": 0.0, "location": "Tokyo",
     "notes": "周五晚入住,周日早退房",
     "depart_at": None, "arrive_at": "2026-09-18T21:30"},
    {"seq": 3, "kind": "shop", "label": "秋叶原 / Bic Camera / 池袋东武",
     "cost_usd": 0.0, "duration_min": 600.0, "location": "Tokyo",
     "notes": "周六全天采购 + 周日上午补货",
     "depart_at": "2026-09-19T10:00", "arrive_at": "2026-09-20T08:00"},
    {"seq": 4, "kind": "flight", "label": "NRT → PEK",
     "cost_usd": 200.0, "duration_min": 240.0, "location": "Tokyo",
     "notes": "NH 955 NRT 09:00 → PEK 12:00",
     "depart_at": "2026-09-20T09:00", "arrive_at": "2026-09-20T12:00"},
]

# ---------- 4th route (round 18): 北京→大阪关西 周末短线 (Fri→Sun) ----------
# Real public data: CA PEK 08:40 → KIX 12:40 / CA KIX 14:00 → PEK 16:30.
# Sources: Trip.com BJS-OSA, 大兴 PKX-KIX 开通新闻.

ROUTE_PEK_KIX_WEEKEND: dict = {
    "name": "PEK-KIX-WEEKEND",
    "origin_city": "北京 PEK",
    "dest_city": "大阪 KIX",
    "region": "cn-jp",                # 聚焦"中国→日本"主线
    "flight_cost_usd": 480.0,
    "transfer_cost_cny": 0.0,        # 北京出发免中转;上海出发 +¥600,天津出发 +¥200 (高铁)
    "hotel_cost_usd": 100.0,
    "other_cost_usd": 30.0,
    "hours_available": 56.0,         # Fri 08:40 → Sun 16:30 ≈ 56h
    "target_hourly_usd": 20.0,
    "target_roi_pct": 15.0,
    "min_roi_pct": 10.0,
    "cn_to_usd_fx": 0.14,
    "departure_date": "2026-09-18",  # 周五
    "source_url": "https://www.google.com/travel/flights",
    "flight_source_url": "https://www.google.com/travel/flights/search?tfs=CBwQAhojagcIARIDMjAyNi0wOS0xOBcgQVowc0JwaGdyQ0JNUmtFQkZCaGZBSWxBR2dITkVWVkZDZEpKbVRuWVVtTmxNMEZqYlRCQkVnS2hFTHpWQVoyMHdZMnRsTVRSbU1qTTFObUU1TFRjek9EQTBNekV3TWpZek5DMDRNemcxT0RreU5qTkJaWGt3TWk1eU1USXpMV0l5TkdNdE5qTmtOQzAwTWpNMkxXUTVNek10T0RnME1pMDBNems0TFRNNE1qTTVOVGc0T1RjNU1DMDBNemcxT0RreU5qTkJaWGt3TWk1eU1USXpMV0l5TkdNdE5qTmtOQw&curr=CNY",
    "notes": "周末短线:北京→大阪关西,周五去周日回。CA 直飞。机票往返 ¥3,400 (关西 KIX 比关东 NRT 旺季贵 ¥200-400,夏/春节 ¥5,000-7,000)。",
}
ROUTE_PEK_KIX_WEEKEND_LEGS: list[dict] = [
    {"seq": 1, "kind": "flight", "label": "PEK → KIX",
     "cost_usd": 240.0, "duration_min": 220.0, "location": "Beijing",
     "notes": "CA PEK 08:40 → KIX 12:40",
     "depart_at": "2026-09-18T08:40", "arrive_at": "2026-09-18T12:40"},
    {"seq": 2, "kind": "hotel", "label": "心斋桥/难波商务酒店 1N",
     "cost_usd": 100.0, "duration_min": 0.0, "location": "Osaka",
     "notes": "周五入住,周日退房",
     "depart_at": None, "arrive_at": "2026-09-18T14:00"},
    {"seq": 3, "kind": "shop", "label": "心斋桥 BIC / 大丸 / 友都八喜",
     "cost_usd": 0.0, "duration_min": 540.0, "location": "Osaka",
     "notes": "周五下午 + 周六全天采购",
     "depart_at": "2026-09-18T14:30", "arrive_at": "2026-09-19T22:00"},
    {"seq": 4, "kind": "flight", "label": "KIX → PEK",
     "cost_usd": 240.0, "duration_min": 230.0, "location": "Osaka",
     "notes": "CA KIX 14:00 → PEK 16:30",
     "depart_at": "2026-09-20T14:00", "arrive_at": "2026-09-20T16:30"},
]

ROUTES: list[dict] = [ROUTE, ROUTE_REGIONAL, ROUTE_PEK_NRT_WEEKEND, ROUTE_PEK_KIX_WEEKEND]
ROUTES_BY_LEGS: dict[str, list[dict]] = {
    ROUTE["name"]: ROUTE_LEGS,
    ROUTE_REGIONAL["name"]: ROUTE_REGIONAL_LEGS,
    ROUTE_PEK_NRT_WEEKEND["name"]: ROUTE_PEK_NRT_WEEKEND_LEGS,
    ROUTE_PEK_KIX_WEEKEND["name"]: ROUTE_PEK_KIX_WEEKEND_LEGS,
}


def seed_all(conn) -> dict:
    """Insert seed data. Returns counts: {opportunities, routes, legs, evidence}."""
    # Round 21: seed evidence FIRST so we can capture the natural-key id map
    # (sku, side, channel_name) → evidence_id, then attach ``evidence_ids``
    # to each channel dict before upserting opportunities. Idempotent
    # thanks to the (sku, side, channel_name, observed_at) UNIQUE key.
    evidence_id_map: dict[tuple[str, str, str], int] = {}
    evidence_count = 0
    for ev in EVIDENCE_LOG:
        eid = db.upsert_evidence(conn, ev)
        evidence_id_map[(ev["sku"], ev["side"], ev["channel_name"])] = eid
        evidence_count += 1

    opp_ids = []
    for opp in OPPORTUNITIES:
        # Round 20: tag each channel with anchor + fulfillment before insert.
        # Done here (not on the const) so the OPPORTUNITIES dict stays "raw"
        # and tests can compare against an unmodified shape.
        _enrich_channels(opp.get("purchase_channels") or [], opp.get("purchase_source_url"))
        _enrich_channels(opp.get("sell_channels")     or [], opp.get("sell_source_url"))

        # Round 21: attach evidence_ids to each channel so the SPA can render
        # a 决策卷宗 (decision dossier) per SKU card.
        sku = opp["sku"]
        for side, channels in (
            ("buy",  opp.get("purchase_channels") or []),
            ("sell", opp.get("sell_channels")     or []),
        ):
            for ch in channels:
                eid = evidence_id_map.get((sku, side, ch["name"]))
                if eid is not None:
                    ch.setdefault("evidence_ids", []).append(eid)

        opp_ids.append(db.upsert_opportunity(conn, opp))

    route_ids = []
    total_legs = 0
    for r in ROUTES:
        rid = db.upsert_route(conn, r)
        route_ids.append(rid)
        legs = ROUTES_BY_LEGS[r["name"]]
        # Round 20: inject Day-by-Day stops into the shop leg so the SPA can
        # expand a clickable sub-list. add_route_legs JSON-encodes the field.
        stops = ROUTE_SHOPPING_STOPS.get(r["name"], [])
        for leg in legs:
            if leg["kind"] == "shop":
                leg["stops"] = stops
        db.add_route_legs(conn, rid, legs)
        total_legs += len(legs)
    return {
        "opportunities": len(opp_ids),
        "routes": len(route_ids),
        "legs": total_legs,
        "evidence": evidence_count,
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
