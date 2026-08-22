"""数据源爬虫(Phase 2 接入,Day 8-14 起)。

各 scraper 模块定义在 arb/scrapers/<source>.py,实现统一接口:
    fetch_one(sku, source) -> dict  # 单个 SKU 单源
    fetch_all(sku) -> list         # 多源对比

Phase 1 (Day 1-7):空架子 + 接口定义 + 单元测试桩。
Phase 2 (Day 8-14):接入 buyee / eBay sold / amazon_jp / rakuten / pokemoncenter / humanmade。
Phase 3 (Day 22-30):接 1688 / Grailed / 闲鱼 / 小红书。
"""