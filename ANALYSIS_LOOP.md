# 🤖 分析环操作手册 v1.1(Claude 侧,v3.4 5-Leg)

> **本文件 = Claude 的永久 playbook**。每天的"商机雷达"、算法评分、爬虫沉淀、推荐输出,
> 全部按这里执行。每次重读这个文件就能 resume,不靠记忆。
>
> **v1.1 升级**:从 v3.3 双 leg → **v3.4 5-Leg 模型**(撮合 + 代购集运 + 出差代购 + 电商带过去 + 哥们仓)。

---

## 1. 职责划分(分析环 vs 操作环)— v3.4 5-Leg 版

### 🤖 Claude 职责(分析环)— 每天 60 min

| 任务 | 输出 | 工具 |
|---|---|---|
| **🅰 撮合商机扫描** | 🅰 Top 3 候选 | `recommend_by_leg("🅰 撮合")` |
| **🅱 代购集运扫描** | 🅱 Top 3 候选 | `recommend_by_leg("🅱 代购集运")` |
| **🅲 出差代购扫描** | 🅲 Top 3 候选 + 行程推荐 | `recommend_by_leg("🅲 出差代购")` + `trip_recommend.recommend_trips()` |
| **🅲 现场买清单** | 现场买 SKU + 地点 | `recommend_on_site()` |
| **🅳 电商带过去清单** | CN 电商 → 海外 SKU | `recommend_cn_ecom()` |
| **🅴 哥们仓清单** | 海外电商 → 哥们家 → CN SKU | `recommend_friend_warehouse()` |
| **算法评分 + 沉淀维护** | score 0-100 + 文档 | `arb.scoring` + `docs/analysis/` |

### 👤 用户职责(操作环)— 每天 1-2 h

| 任务 | 输出 | 工具 |
|---|---|---|
| **🅰 撮合 操作** | eBay/Grailed listing + 货源代购 + 微信群发 | 浏览器 |
| **🅱 代购集运 操作** | buyee.jp 询价 + 闲鱼挂 listing + 集运下单 | 浏览器 / 闲鱼 |
| **🅲 出差代购 操作** | 订机票 + 订酒店 + 现场买 + 哥们家取货 + 带回 CN | 飞猪 / 携程 / 现场 / 哥们家 |
| **🅳 电商带过去 操作** | 拼多多 / 1688 下单 + 囤国内仓 + 飞带出境 | 拼多多 / 1688 |
| **🅴 哥们仓 操作** | buyee.jp 下单 → 哥们家 → 飞过去取 → 带回 CN 卖 | buyee / 哥们家 / 闲鱼 |
| **每单记账** | `arb returns add` | CLI |
| **周复盘 / 月复盘** | 决策树输入 | `arb returns margin` |

**关键边界 — Claude 永远不做:**
- ❌ 实际下单付款(代发直邮也不需要 Claude 触发)
- ❌ 写 listing 标题 / 描述(用户文笔更好)
- ❌ 微信群发 / 私聊买家(社交流用户亲自)
- ❌ 订机票 / 订酒店 / 跟哥们商量暂存(用户亲自)

**关键边界 — 用户永远不做:**
- ❌ 跑 spread 算法 / 算关税 / 算平台费(Claude 算)
- ❌ 选 SKU 池(Claude 给 Top 5,用户挑 1-3)
- ❌ 写爬虫 / 调报警阈值(Claude 自己维护)

---

## 2. 商机雷达算法(score_sku)

### 评分公式

```python
score = (
    spread_pct * 0.35          # spread % (越大越好)
    + sell_volume * 0.25       # 月销量 / 已售数(流动性)
    + reliability * 0.20       # 货源真实性 + 买家信用
    - complexity_penalty * 0.20  # 物流 / 关税 / 退货复杂度
)
```

| 维度 | 输入 | 来源 | 权重 |
|---|---|---|---|
| `spread_pct` | (sell - buy) / buy | 两边价 | 35% |
| `sell_volume` | eBay 已售数 / Grailed 成交数 | eBay sold API / scraper | 25% |
| `reliability` | 货源验证 + 买家信用 | buyee 评论 / eBay 评价数 | 20% |
| `complexity_penalty` | 物流 + 关税 + 退货 + 合规 | HS 码 + 平台规则 | -20% |

### 评分阈值

| 等级 | 阈值 | 动作 |
|---|---|---|
| 🔴 **不推** | score < 40 或 spread_pct < 50% | 不撮合 |
| 🟡 **试单** | score 40-70 且 spread_pct 50-200% | 跑 1 单验证 |
| 🟢 **主推** | score ≥ 70 且 spread_pct ≥ 200% | 优先撮合 |

### 算法位置

- **stub**:`arb/scoring/score_sku.py` — 当前 stub,固定权重,返回 score 0-100
- **真值(Day 8-14)**:接 `arb.scrapers.ebay_sold` / `arb.scrapers.buyee_prices` 数据流
- **优化(Day 22-30)**:从 `arb/scoring/learned_weights.py` 读历史成交数据训权重

### v3.4 — 5-Leg 评分表

**`LEG_SCORE_TABLE`**(`arb/scoring/score_sku.py`):每个 SKU 按 leg 单独打分。

| Leg | 评分特征 | 推荐 API |
|---|---|---|
| 🅰 撮合 | spread 高 / volume 高 / reliability 高 / complexity 低 | `recommend_by_leg("🅰 撮合")` |
| 🅱 代购集运 | spread 中 / volume 中 / reliability 中 / complexity 中 | `recommend_by_leg("🅱 代购集运")` |
| 🅲 出差代购 | spread 中(¥6k 货值上限)/ volume 极高(限定)/ complexity 中(机票) | `recommend_by_leg("🅲 出差代购")` + `trip_recommend.recommend_trips()` |
| 🅳 电商带过去 | spread 高(CN→海外)/ volume 中 / reliability 中 / complexity 低 | `recommend_cn_ecom()` |
| 🅴 哥们仓 | spread 高 / volume 中 / reliability 高 / complexity 高(¥5,000 额度) | `recommend_friend_warehouse()` |

**关键洞察**(Day 1 测试输出):
- 🅲 出差代购是最高杠杆 leg:¥3,000 机票 → ¥6,000 货值 = **1.0× ROI**
- 🅲 出差代购 SKU 评分 = 🅰 撮合同 SKU 但 complexity 略高,score 仍 83-85 🟢
- 🅳 CN 电商 spread 极高(中药 370% / 茶 300%),但 sell_volume 0.5 拉低综合分
- 🅴 哥们仓 spread 128-145% + ¥5,000 额度约束,适合 HM Tee / PKMN-151 BB

---

## 3. 数据源与抓取计划

### 3.1 数据源矩阵(v3.4 — 5-Leg 扩展)

| 数据源 | 抓什么 | 频率 | 抓取方式 | 模块 | Leg |
|---|---|---|---|---|---|
| **eBay sold** | 已售 SKU + 均价 + 评价数 | 每日 | eBay Finding API / scraper | `arb.scrapers.ebay_sold` | 🅰🅲 |
| **Grailed sold** | 已售 SKU + 均价 | 每周 | scraper(JS 重)| `arb.scrapers.grailed_sold` | 🅰🅲 |
| **闲鱼已售** | 已售 SKU + 均价 | 每周 | scraper / 浏览器 | `arb.scrapers.xianyu_sold` | 🅱🅴 |
| **小红书** | 求购 / 在售 SKU | 每周 | 浏览器 / scraper | `arb.scrapers.xiaohongshu` | 🅱🅴 |
| **buyee.jp** | 商品价 + 国际运费 | 每日 | buyee API 不可 → scraper | `arb.scrapers.buyee` | 🅰🅱🅴 |
| **amazon.co.jp** | 商品价 | 每日 | Product Advertising API | `arb.scrapers.amazon_jp` | 🅰🅱🅲🅴 |
| **Rakuten** | 商品价 | 每日 | 楽天 API | `arb.scrapers.rakuten` | 🅰🅱🅴 |
| **Mercari JP** | 商品价(经 buyee)| 每日 | scraper | `arb.scrapers.mercari_jp` | 🅰🅱🅴 |
| **pokemoncenter-online** | 商品价 + 库存 | 每周 | scraper | `arb.scrapers.pokemoncenter` | 🅰🅲🅴 |
| **humanmade.jp** | 商品价 + 库存 | 每周 | scraper | `arb.scrapers.humanmade` | 🅰🅲🅴 |
| **USJ 现场 / 雅虎** | USJ 限定 + 鬼灭 popcorn | 每周 | scraper / 雅虎拍卖 | `arb.scrapers.usj_official` | 🅲 |
| **松本清 / 大国药局** | 药妆折扣价 | 每周 | scraper | `arb.scrapers.discount_drugstore` | 🅲 |
| **御殿场 / 长岛 outlet** | outlet 折扣价 | 每周 | scraper | `arb.scrapers.outlet_jp` | 🅲 |
| **1688 国际** | 商品价 + 集运报价 | 每周 | 1688 open API | `arb.scrapers.alibaba_1688` | 🅳🅱 |
| **拼多多 / 拼多多国际** | CN 价 + 国际物流 | 每周 | 拼多多开放平台 | `arb.scrapers.pdd` | 🅳 |
| **Amadeus 实查** | 机票价格 | 每周 | Amadeus API | `arb.scrapers.amadeus_flight` | 🅲🅳🅴 |

### 3.2 抓取阶段

| Phase | 时间 | 范围 |
|---|---|---|
| **Phase 1**(stub)| Day 1-7 | 用现有 `arb.prices` stub 表,验证 score 算法 |
| **Phase 2**(真价)| Day 8-14 | 接入 buyee / eBay sold scraper,替换 stub |
| **Phase 3**(自动化)| Day 22-30 | eBay 自动 listing + 微信半自动 + Telegram 通知 |

### 3.3 缓存与去重

- 抓取结果写 `data/cache/<source>/<sku>/<YYYY-MM-DD>.json`
- 同 SKU 同日多源抓取 → `arb.pipelines.dedupe` 取最小价 + 多源交叉验证
- 价差异常(>30% 单日波动)→ `arb.alerts.flag_anomaly`

---

## 4. 每日 Claude 必跑(60 min / 天)

### 4.1 时间分配(分析环默认 60 min,用户 1-2 h 操作)

| 时段 | 任务 | 工具 |
|---|---|---|
| 0:00-0:15 | **扫 sell side 4 行均价**(spread 监控)| WebSearch + eBay/Grailed API |
| 0:15-0:30 | **扫货源侧 4 行均价**(spread 监控)| buyee / 1688 / pokemoncenter |
| 0:30-0:45 | **重算 score_sku**(Top N 候选)| `arb.scoring.score_sku` |
| 0:45-1:00 | **输出"今日 1 件事 + 3 候选"** | 见 §5 推荐输出格式 |

### 4.2 周日必跑(30 min)

| 任务 | 命令 |
|---|---|
| basket 重跑 | `arb basket --budget 5000` |
| F1/F2 报警回顾 | `arb prices alerts --review` |
| F4 退货统计 | `arb returns margin --week` |
| 更新 SKU 池候选 | Top 10 写入手账 |

### 4.3 月度必跑(60 min)

| 任务 | 命令 |
|---|---|
| 月度毛利 | `arb returns margin --month 2026-08` |
| 撮合成功率 | `arb decision success_rate --month 2026-08` |
| 算法权重调 | `arb.scoring.learned_weights --fit` |
| 沉淀库更新 | `docs/analysis/scoring_history.md` |

---

## 5. 推荐输出格式(给用户的"今日 1 件事")— v3.4 5-Leg

每次 Claude 输出每日推荐时,严格用这个格式:

```markdown
# 📅 2026-08-17 每日推荐(Day 1)

## 🎯 今日 1 件事(主推 — 挑 1 条 leg)
- **方向**:🅰 撮合 / 🅱 代购 / 🅲 出差 / 🅳 CN 电商 / 🅴 哥们仓
- **SKU**:...
- **买**:... 价 CNY
- **卖**:... 价 CNY
- **spread**:... %
- **净利**:... CNY
- **操作**:60 min
  1. ...
  2. ...
- **风险**:...

## 🛬 5-Leg 全景(可选展示 — 用户挑 leg 时用)

### 🅰 撮合
| # | SKU | score | grade |

### 🅱 代购集运
| # | SKU | score | grade |

### 🅲 出差代购(行程 + 现场买)
- Top trip:PVG→NRT 09-11→09-14 ¥3,000 / ¥6,000 货值 / 1.0× ROI
- Top 现场买:药妆 75% / USJ 鬼灭 66%

### 🅳 电商带过去(CN→海外)
- TCM 中药 1688 ¥150 → Etsy 海外华人 ¥700(370%)

### 🅴 哥们仓(海外→CN)
- HM Tee ¥350 → 闲鱼 ¥857(145%)

## ⚠️ 风险提示
- 5-leg 各自关税 / 额度 / 物流约束
- Day 14 强制停盘点未到,先 spread 验证,不急扩池

## 🔄 决策点
- 各 leg 触发条件应对
```

**v3.4 输出差异**:每日推荐 = **1 个今日 1 件事(挑 leg)+ 5-Leg 全景**(用户可挑别的 leg 跑)。

---

## 6. 沉淀库文件结构(代码层面)

```
/Volumes/SanDisk2TB/jp-us-arb-route/
├── arb/
│   ├── scrapers/                    # 爬虫沉淀(Day 8-14 加)
│   │   ├── __init__.py
│   │   ├── base.py                  # scraper 接口
│   │   ├── ebay_sold.py             # 🅰🅲 eBay 已售抓取
│   │   ├── grailed_sold.py          # 🅰🅲 Grailed 已售抓取
│   │   ├── xianyu_sold.py           # 🅱🅴 闲鱼已售抓取
│   │   ├── buyee.py                 # 🅰🅱🅴 buyee.jp 商品价
│   │   ├── amazon_jp.py             # 🅰🅱🅲🅴 amazon.co.jp
│   │   ├── rakuten.py               # 🅰🅱🅴 楽天
│   │   ├── mercari_jp.py            # 🅰🅱🅴 Mercari JP
│   │   ├── pokemoncenter.py         # 🅰🅲🅴 宝可梦中心
│   │   ├── humanmade.py             # 🅰🅲🅴 humanmade.jp
│   │   ├── usj_official.py          # 🅲 USJ 限定
│   │   ├── discount_drugstore.py    # 🅲 松本清 / 大国药局
│   │   ├── outlet_jp.py             # 🅲 outlet 折扣
│   │   ├── alibaba_1688.py          # 🅳🅱 1688 国际
│   │   ├── pdd.py                   # 🅳 拼多多
│   │   └── amadeus_flight.py        # 🅲🅳🅴 Amadeus 实查机票
│   │
│   ├── scoring/                     # 算法沉淀(Day 1-7 起)
│   │   ├── __init__.py
│   │   ├── score_sku.py             # 主评分 + LEG_SCORE_TABLE + ON_SITE/CN_ECOM/FRIEND_WAREHOUSE
│   │   ├── recommend.py             # Top N + recommend_by_leg + recommend_on_site/cn_ecom/friend_warehouse
│   │   ├── learned_weights.py       # 历史成交训权重(Phase 3)
│   │   └── basket.py                # 已有 — 0/1 knapsack
│   │
│   ├── routes/                      # 🆕 v3.4 来回行程推荐
│   │   ├── __init__.py
│   │   └── trip_recommend.py        # PEK/PVG/CAN→NRT 3 行程 + TripRecommendation dataclass
│   │
│   ├── pipelines/                   # 数据管道(Day 8-14 加)
│   │   ├── __init__.py
│   │   ├── normalize.py             # 标准化(币种 / 名称 / SKU)
│   │   ├── fx.py                    # 汇率换算
│   │   ├── dedupe.py                # 多源去重
│   │   └── quota_window.py          # 🆕 ¥5,000 额度窗口管理(Phase 2)
│   │
│   ├── alerts.py                    # 已有 — F2 价格报警
│   ├── prices.py                    # 已有 — F1 跨源价(stub)
│   ├── returns.py                   # 已有 — F4 退货 + 月度毛利
│   ├── tax_codes.py                 # 已有 — F5 HS 码
│   ├── decision.py                  # 已有 — 决策树
│   └── cli.py                       # 已有 — CLI 入口
│
├── data/
│   ├── db.sqlite                    # 主 DB
│   └── cache/                       # 抓取缓存
│       └── <source>/<sku>/<YYYY-MM-DD>.json
│
├── docs/                            # 沉淀库(算法 + 决策 + 历史)
│   ├── analysis/
│   │   ├── scoring_history.md       # 评分历史
│   │   ├── decision_history.md      # 决策历史
│   │   ├── algorithm_versions.md    # 算法版本演进
│   │   └── scraper_status.md        # 爬虫健康状态
│   └── daily/                       # 🆕 每日推荐存档
│       └── YYYY-MM-DD.md            # 每日输出 + 用户反馈
│
├── MANUAL_30DAY_LOG.md              # 30 天验证手账(战略)
└── ANALYSIS_LOOP.md                 # 本文件(战术 — Claude 操作手册)
```

---

## 7. Phase 1 / 2 / 3 升级路径(v3.4 5-Leg 版)

### Phase 1:stub 验证(Day 1-7,2026-08-17 → 08-23)

**目标**:验证 5-Leg score 算法逻辑,不依赖真数据
- ✅ `arb.scoring.score_sku` + LEG_SCORE_TABLE(5-leg 各自 score)
- ✅ `arb.scoring.recommend_by_leg` + `recommend_all_legs`(5-leg 并行)
- ✅ `arb.scoring.recommend_on_site` + `recommend_cn_ecom` + `recommend_friend_warehouse`
- ✅ `arb.routes.trip_recommend`(PEK/PVG/CAN→NRT 3 行程 stub)
- ✅ `arb.basket` 已有 — 跑 ¥5,000 预算最优组合
- ⏳ 不抓真数据(等 Phase 2)

### Phase 2:真价抓取(Day 8-14,2026-08-24 → 08-30)

**目标**:替换 stub,接入 16 个数据源(详见 §3.1)
- ✅ `arb.scrapers.buyee` / `ebay_sold` / `amazon_jp` / `rakuten`(每日核心)
- ✅ `arb.scrapers.pokemoncenter` / `humanmade` / `mercari_jp` / `xianyu_sold`(每周)
- ✅ `arb.scrapers.usj_official` / `discount_drugstore` / `outlet_jp`(🅲 出差现场买)
- ✅ `arb.scrapers.alibaba_1688` / `pdd`(🅳 CN 电商)
- ✅ `arb.scrapers.amadeus_flight`(🅲🅳🅴 机票实查)
- ✅ `arb.pipelines.normalize` + `fx` + `dedupe` + `quota_window`(¥5,000 额度窗口)
- ✅ score_sku 接真价 → 重跑 basket → 跟手账 4 行对比

### Phase 3:自动化(Day 22-30,2026-09-07 → 09-16)

**目标**:Claude 分析环半自动 / 全自动
- ✅ eBay 自动 listing(eBay API + 模板)
- ✅ Grailed 半自动(无 API,辅助脚本)
- ✅ 微信海外群自动推送(RPA / 半自动)
- ✅ Telegram bot 撮合成交通知
- ✅ `arb.scoring.learned_weights` 训历史成交
- ✅ 🆕 🅲 拼货多人 trip / 自动 ¥5,000 额度窗口
- ✅ 🆕 🅴 哥们家库存管理 + 取货提醒

---

## 8. 不在沉淀库范围(避免记忆中断的边界)

**Claude 不应该把这些塞进沉淀库(因为它们是上下文而非代码):**

| 类别 | 内容 | 为什么不在沉淀库 |
|---|---|---|
| 个人偏好 | 决策手感、用户作息、社交流习惯 | 每次会面都重新确认 |
| 当前预算 | ¥5,000 入境额度 / 现金流 | 实时变化,放 `data/` 配置文件 |
| 当前 sell side | 锁定 eBay / Grailed / 微信海外 | 用户决策,跟 Claude 算法无关 |
| 当前 SKU 池 | basket 4 行 + 用户挑的 5-10 | 放 `MANUAL_30DAY_LOG.md` 而非 `arb/scoring/` |
| 当前运营节奏 | 60 min/天 / 周复盘 / 月决策 | 用户习惯,跟算法无关 |
| 短期目标 | Day 14 / Day 30 决策 | 30 天手账记录,30 天后过期 |
| 长期方向 | 撮合 vs 代购 vs 二手 | 战略层,放 `MANUAL_30DAY_LOG.md` |

**沉淀库的边界 = "代码 + 算法 + 抓取脚本 + 数据流"。任何主观 / 战略 / 用户偏好的都不放。**

---

## 9. Claude resume 流程(每次新会话必跑)

**Claude 启动后第一件事:读这两个文件**

1. `/Volumes/SanDisk2TB/jp-us-arb-route/MANUAL_30DAY_LOG.md` — 战略(当前方向 + 决策树 + 红线)
2. `/Volumes/SanDisk2TB/jp-us-arb-route/ANALYSIS_LOOP.md` — 本文件(战术:每日任务 + 算法 + 抓取 + 推荐输出)

读完两份文件 = Claude 完整 resume,不靠记忆。

**之后输出顺序:**
1. 汇报当前状态(战略层 + 战术层各 1 行)
2. 输出"今日 1 件事 + 3 候选"(格式见 §5)
3. 等用户操作反馈 → 调算法 / 换 SKU / 加 SKU

---

## 10. 沉淀库维护 checklist(每周日)

- [ ] 跑 `arb.basket` 重算 → 跟手账 4 行对比 → 写 `docs/analysis/scoring_history.md`
- [ ] 跑 `arb.scoring.score_sku` 看 Top 10 → 跟用户对账 → 调权重
- [ ] 检查 `data/cache/` 抓取缓存 → 异常数据 → 修 scraper
- [ ] 看 `docs/analysis/scraper_status.md` → 哪个挂了 / 哪个新加
- [ ] 更新 `docs/analysis/algorithm_versions.md` → 算法版本号 + 改动

---

## 11. 紧急 fallback(算法失败时)

| 失败 | Fallback |
|---|---|
| eBay sold 抓不到 | 用 WebSearch 手动搜 + 浏览器 |
| buyee scraper 挂 | 手动看 buyee.jp 搜索页 |
| score_sku 输出全 🔴 | 调权重 + 加新 SKU |
| 算法崩了 | 退回 stub 评分,跑 `arb basket` 看 4 行 |
| 撮合成交率 < 10% | 换 sell side 平台 / 调抽佣 / 扩 SKU |

---

**本文件 = Claude 永久 playbook。改它 = 改操作规则,需要用户确认。**