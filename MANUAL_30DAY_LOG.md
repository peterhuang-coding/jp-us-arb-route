# 30 天验证手账 v3.4(5-Leg 模型:撮合 + 代购 + 出差 + 电商囤 + 哥们仓)

> **范式演进**:
> - v3.1 代购(我买 → 带回 → 我卖)→ v3.2 撮合(我接需求 → 撮合 → 抽佣)→
> - v3.3 撮合 + 代购 → **v3.4 5-Leg 模型**(撮合 + 代购集运 + 出差代购 + 电商带过去 + 哥们仓)
>
> **杠杆最高的 leg = 🅲 出差代购**(¥3-5k 机票 → ¥6,000 货值,3-4× ROI)。
> ¥5,000 入境额度 + 二次入境 ¥1,000 + 哥们仓 + 现场买,**全部重新启用**。

> **📌 协作分工(2026-08-17 锁定)**:
> - **🤖 Claude 侧 = 分析环**:5-leg 商机雷达 + 算法评分 + 来回行程推荐 + 数据更新 + 每日推荐
> - **👤 用户侧 = 操作环**:listing + 货源代购 + 集运 + 飞前囤货 + 现场买 + 哥们仓 + 带回 + 记账
> - **Claude 操作手册**:见 `ANALYSIS_LOOP.md`(战术 — 每日任务 + 5-leg 算法 + 抓取 + 推荐输出格式)

---

# 🔥 速读(Top 1-Page)

## 1. 锁定决策(2026-08-17 已锁)

| 项 | 值 |
|---|---|
| **方向** | JP → 海外(eBay / Grailed / Etsy / 微信海外华人圈) |
| **模式** | 撮合中介(P2P matching,需求池 → 供给池 → 抽佣) |
| **库存 / 入境 / 现金** | **0 / 0 / ¥0**(预收买家款再付货源款) |
| **SKU 池** | basket 4 行 + Day 1-7 用户挑 5-10 个 |
| **真去 JP?** | **看 leg** → 🅰🅱🅴 否 / 🅲🅳 要飞 |
| **数字 leg** | 副业 0-30 min/天,可跳过 |

## 2. 5-Leg 模型矩阵(v3.4 核心)

| Leg | 方向 | 触发 | 投入 | 库存 | 关税 | 角色 |
|---|---|---|---|---|---|---|
| **🅰 撮合** | JP→海外 撮合 | 每天 | ¥0 | 0 | 0 | 线上被动收入 |
| **🅱 代购集运** | JP→CN 集运 | 每周 | ¥5,000 额度 | 5-7 天 | 一般 13% | 线上小批量 |
| **🅲 出差代购** | CN 飞海外 → 现场买 → 带回 CN | 月 1-2 次 | 机票 ¥2-4k + 食宿 ¥1-2k | 用户家 | ¥5,000 / ¥1,000 二次 | **核心 leg,杠杆最高** |
| **🅳 电商带过去** | CN电商 → 飞带出境 | 飞前 X 天预囤 | 库存 | 用户家 | 海外卖 | CN 特色小商品出海 |
| **🅴 哥们仓** | 海外电商 → 哥们家 → 飞取 → 带回 CN | 飞前 X 天预囤 | 库存 | 哥们家 | ¥5,000 入境 | JP / 海外限定带回 |

**核心洞察**:🅲 出差代购是杠杆最高的 leg — ¥3-5k 机票可以撬动 ¥5,000 货 + 二次 ¥1,000 = **¥6,000 货值,3-4× ROI**。

## 2. 🤝 协作分工(分析环 vs 操作环)

| 角色 | 负责什么 | 每天工时 | 工具 / 输出位置 |
|---|---|---|---|
| **🤖 Claude = 分析环** | 商机雷达扫描 + 算法评分 + 数据更新 + 每日推荐 + 决策建议 + 沉淀维护 | 60 min | `ANALYSIS_LOOP.md` / `arb/scoring/` / `arb/scrapers/` |
| **👤 用户 = 操作环** | 撮合/代购 实际操作 + 跨平台验证 + listing + 货源代购 + 集运 + 记账 + 周复盘 | 1-2 h | 浏览器 / 闲鱼 / eBay / Grailed / 微信 / `arb returns add` |

**边界 — Claude 永远不做:**
- ❌ 实际下单付款(代发直邮也不触发)
- ❌ 写 listing 标题 / 描述(用户文笔更好)
- ❌ 微信群发 / 私聊买家(社交流用户亲自)

**边界 — 用户永远不做:**
- ❌ 跑 spread 算法 / 算关税 / 算平台费(Claude 算)
- ❌ 选 SKU 池(Claude 给 Top 5,用户挑 1-3)
- ❌ 写爬虫 / 调报警阈值(Claude 自己维护)

## 3. 撮合工作流(每天 60 秒)

```
1. 打开 🔗 两边链接对照表(下方)
2. 看 sell side 4 行均价:¥8,568 / ¥857 / ¥678 / ¥1,071
3. 看货源侧 4 行均价:¥714 / ¥262 / ¥214 / ¥321
4. 哪个 spread 缩 >20% → 暂停;扩 >20% → 优先撮合
5. `arb returns add` 记录成交
```

## 4. 今日要做的 1 件事

```
📅 Day 1-7  (2026-08-17 → 2026-08-23):建需求池
   → eBay "Sold" 看 4 行真实均价 → 填入下方"撮合池模板"

📅 Day 8-14 (2026-08-24 → 2026-08-30):建供给池
   → 货源实地询价 + Day 14 强制停盘点(必做)

📅 Day 15-21(2026-08-31 → 2026-09-06):撮合测试
   → 上 eBay / Grailed listing 3-5 SKU + 微信海外群发求购

📅 Day 22-30(2026-09-07 → 2026-09-16):扩池 + 决策
   → 加 5-10 SKU + Day 30 决策(🟢扩池 / 🟡优化 / 🔴复盘)
```

---

# 📅 每日任务清单(Day 1-30 · 操作环视角)

> **每条 = 用户要做的 1 件事**。Claude 给"今日 1 件事 + 3 候选"(格式见 `ANALYSIS_LOOP.md` §5),
> 用户挑 1 条跑。每日 60-120 min。

## Day 1-7 · 建需求池(2026-08-17 → 08-23)

| 日期 | 今日 1 件事 | 方向 | 工时 | 验收 |
|---|---|---|---|---|
| **D1** 8/17 | 开 buyee.jp / Rakuten / amazon.co.jp / humanmade.jp / pokemoncenter 账号 | 🅰 基建 | 30 min | 5 个账号都能登录 |
| **D2** 8/18 | eBay 上 listing 第 1 条(PKMN-PSA)| 🅰 撮合 | 60 min | listing 上线 + 截图 |
| **D3** 8/19 | eBay 上 listing 第 2-3 条(HM Tee + USJ)| 🅰 撮合 | 60 min | 3 个 listing 在线 |
| **D4** 8/20 | 找 3 个海外华人微信群 / Reddit / 论坛,发求购信息 | 🅰 渠道 | 30 min | 群截图 + 消息截图 |
| **D5** 8/21 | 回买家咨询(如已有)+ 跑 1 单成交验证 | 🅰 撮合 | 60 min | 首单成交或学到 1 个 lesson |
| **D6** 8/22 | 闲鱼卖家号注册 + 拍闲置照片 + 挂 1-2 件 🅳 二手 | 🅳 闲鱼 | 60 min | 闲鱼 listing 上线 |
| **D7** 8/23 | 周复盘 + Day 14 决策树预演 | 复盘 | 30 min | 填好 Day 14 撮合池模板前 4 行 |

## Day 8-14 · 建供给池(2026-08-24 → 08-30)

| 日期 | 今日 1 件事 | 方向 | 工时 | 验收 |
|---|---|---|---|---|
| **D8** 8/24 | buyee.jp 询价 PKMN-PSA + HM Tee + USJ-NEZ + PKMN-151 BB | 🅰 货源 | 60 min | 4 个 SKU 拿货价已记录 |
| **D9** 8/25 | 比 3 家代购/buyee 价格(挑最低 1 家合作) | 🅰 货源 | 30 min | 选定代发渠道 |
| **D10** 8/26 | 测试 1 单代发直邮(挑最低货值 SKU 试)| 🅰 测试 | 60 min | 货源代发成功签收 |
| **D11** 8/27 | 跑 `arb basket --budget 5000` 重算 + 对比手账 4 行 | 🅰 算法 | 30 min | 重跑结果跟手账 80% 重合 |
| **D12** 8/28 | 找 5-10 个新 SKU 候选(从 Phase A 撮合池表现好的衍生)| 🅰 扩池 | 60 min | SKU 池 14 行填满 |
| **D13** 8/29 | Day 14 强制停盘点预演(填指标 + 跑决策)| 🅰 决策 | 30 min | 决策树跑通 |
| **D14** 8/30 | **Day 14 强制停盘点(必做)**| 🅰 决策 | 30 min | 三选一决策填好(🟢/🟡/🔴)|

## Day 15-21 · 撮合测试(2026-08-31 → 09-06)

| 日期 | 今日 1 件事 | 方向 | 工时 | 验收 |
|---|---|---|---|---|
| **D15** 8/31 | 撮合测试日 1:3-5 个 listing 在线,接询价 | 🅰 撮合 | 90 min | ≥ 1 个询价 |
| **D16** 9/1 | 撮合测试日 2:回 5-10 个咨询,撮合报价 | 🅰 撮合 | 90 min | ≥ 1 个成交 |
| **D17** 9/2 | 撮合测试日 3:扩 SKU 5-10 + 上新 listing | 🅰 撮合 | 90 min | 池 14 行全活 |
| **D18** 9/3 | Day 14 决策(🟢/🟡/🔴)后,follow-up 决策 | 🅰 跟进 | 60 min | 决策 follow-up 已执行 |
| **D19** 9/4 | 启 F2 报警(货源价波动盯) | 🅰 报警 | 30 min | `arb prices alerts --setup` |
| **D20** 9/5 | 跑 🅱 副 leg 试单(挑最低货值 SKU)| 🅱 代购 | 60 min | ¥5,000 额度检查 + 闲鱼 listing |
| **D21** 9/6 | 副 leg 周复盘(对比 🅰 主 leg ROI)| 复盘 | 30 min | 主/副 leg ROI 对比 |

## Day 22-30 · 扩池 + 决策(2026-09-07 → 09-16)

| 日期 | 今日 1 件事 | 方向 | 工时 | 验收 |
|---|---|---|---|---|
| **D22** 9/7 | 撮合日:SKU 池扩到 14-20 行 | 🅰 扩池 | 90 min | 池满 |
| **D23** 9/8 | 撮合日:接 5-10 个咨询,撮合 1-2 单 | 🅰 撮合 | 90 min | ≥ 1 个成交 |
| **D24** 9/9 | 撮合日:F4 退货跟踪 + 售后 | 🅰 售后 | 60 min | 退货率 < 5% |
| **D25** 9/10 | 算法优化:跑 `arb scoring learned_weights` | 🅰 算法 | 60 min | 权重更新 |
| **D26** 9/11 | eBay 自动 listing 模板优化(挑 5 个 SKU)| 🅰 自动 | 60 min | 模板上线 |
| **D27** 9/12 | 微信海外群发自动化(RPA / 半自动)| 🅰 自动 | 60 min | 群发跑通 |
| **D28** 9/13 | Day 30 决策树预演(填指标)| 🅰 决策 | 30 min | 5 项指标已填 |
| **D29** 9/14 | 月度毛利统计(`arb returns margin`)| 复盘 | 30 min | 毛利数字 |
| **D30** 9/16 | **Day 30 决策(必做)**| 🅰 决策 | 60 min | 🟢扩池 / 🟡优化 / 🔴复盘 三选一 |

---

## 🤖 Claude 分析环每日输出(对应用户 D1-D30)

**Claude 每天 60 min,严格按 `ANALYSIS_LOOP.md` §5 格式输出**:

| 时段 | Claude 必跑 | 输出 |
|---|---|---|
| **每天 0:00-0:15** | 扫 sell side 4 行均价 | spread 监控表 |
| **每天 0:15-0:30** | 扫货源侧 4 行均价 | spread 监控表 |
| **每天 0:30-0:45** | 跑 `arb.scoring.score_sku` | Top 3 候选 |
| **每天 0:45-1:00** | 输出"今日 1 件事 + 3 候选" | 用户 D1-D30 表对应行 |

**周末 30 min / 月度 60 min**:见 `ANALYSIS_LOOP.md` §4.2 / §4.3

---

# 🔗 两边链接对照表(basket 4 行 · 撮合实操起点)

> **撮合的本质 = side-by-side 比价**:左卖家的实际成交均价、右货源的实际拿货价,中间是 spread 和抽佣空间。
> 每个 SKU 给 **货源侧实链**(JP 拿货)+ **sell side 实链**(海外成交均价)。

## 1. JP-PKMN-PSA(Charizard SAR PSA 10)— 🟢 头牌

| 侧 | 平台 | 链接 | 价格参考(CNY) | 备注 |
|---|---|---|---|---|
| 货源侧 | buyee.jp | https://buyee.jp/item/search?query=charizard+sar+151 | ¥714 | 代购搜索,看 Yahoo/Mercari/Amazon JP 实时 |
| 货源侧 | Mercari JP(经 buyee) | https://jp.mercari.com/search?keyword=charizard%20sar%20psa10 | ¥700-900 | 未评级裸卡,送 PSA +¥300-500 |
| 货源侧 | Yahoo Auctions JP(经 buyee) | https://auctions.yahoo.co.jp/search?p=charizard+sar+151&auccat=0 | ¥500-1,500 | 拍卖竞价,PSA 10 偶有 ¥1,000 内捡漏 |
| sell side | eBay SG(PSA 10) | https://www.ebay.com.sg/itm/226066811104 | ¥10,659(US$1,493)| 已售均价 |
| sell side | eBay CA(PSA 10) | https://www.ebay.ca/itm/235926077820 | ¥12,438(C$1,742) | 已售均价 |
| sell side | eBay(未评级 NM) | https://www.ebay.com/itm/204809183353 | ¥2,506(US$351)| 未评级参照(不可撮合,要 PSA 10) |
| **撮合** | **¥8,568 sell 均价** | vs ¥714 货源 | **spread ¥7,854(1100%)** | 撮合一单净 ¥5,451 |

## 2. JP-HUMANMADE-TEE-GRAPHIC— 🟢 跑量款

| 侧 | 平台 | 链接 | 价格参考(CNY) | 备注 |
|---|---|---|---|---|
| 货源侧 | humanmade.jp(官网) | http://humanmade.jp/ | ¥262-462 | ¥5,500-8,800 JPY,仅发日本,需转运 |
| 货源侧 | humanmade.jp(代购) | https://www.buyfromjapan.com/ | ¥300-500 | Buy From Japan 代拍,直邮海外 |
| 货源侧 | HBX(海外授权零售) | https://hbx.com/men/brands/human-made/1117-refrigeration-t-shirt | ¥700-1,200(US$100-170)| 已含国际运费,**spread 压缩到 ¥0-200**,不划算 |
| sell side | Grailed(搜 "Human Made tee sold")| https://www.grailed.com/feed?q=human+made+tee+graphic&sort=price_desc | ¥857 已售均价 | Grailed "sold" 过滤,均价 US$120 |
| sell side | eBay(KAWS X HM)| https://www.ebay.com/itm/126111650129 | ¥700-1,400 | 联名款;非联名款 ¥857 是更稳均价 |
| sell side | eBay(基础款)| https://www.ebay.com/itm/326264749015 | ¥350-600(US$50-85)| 二手基本款;新品 ¥857 是撮合锚点 |
| **撮合** | **¥857 sell 均价** | vs ¥262 货源(代购)| **spread ¥595(227%)** | 撮合一单净 ¥300-450 |

## 3. JP-ANIME-USJ-NEZ(USJ 鬼灭 禰豆子 Popcorn Bucket)— 🟡 限量款

| 侧 | 平台 | 链接 | 价格参考(CNY) | 备注 |
|---|---|---|---|---|
| 货源侧 | USJ 现场(不直邮) | https://www.usj.co.jp/ | ¥214(JPY 4,080)| 2024-01-20 发售,鬼灭合作期内现场 |
| 货源侧 | USJ 现场代购 | https://www.buyfromjapan.com/ | ¥400-600 | 代购跑腿,直邮海外 |
| 货源侧 | Mercari JP(二手) | https://jp.mercari.com/search?keyword=%E7%A5%9E%E9%AC%BC%E8%A3%8F%E8%B1%86%E5%AD%90%20%E3%83%90%E3%82%B1%E3%83%83%E3%83%88 | ¥300-500 | 二手现货,日拍周拍 |
| sell side | eBay(Sold 过滤)| https://www.ebay.com/sch/i.html?_nkw=usj+nezuko+popcorn+bucket&LH_Sold=1 | ¥678 已售均价 | US$95 均值 |
| sell side | eBay(2025 款)| https://www.ebay.com/sch/i.html?_nkw=usj+demon+slayer+popcorn+bucket&LH_Sold=1 | ¥500-800 | 2025 合作款稍低 |
| **撮合** | **¥678 sell 均价** | vs ¥214 货源(代购)| **spread ¥464(217%)** | 撮合一单净 ¥250-350(物流吃掉部分)|

## 4. JP-PKMN-151-BB(Pokemon Card 151 Booster Box Sealed)— 🟢 货值款

| 侧 | 平台 | 链接 | 价格参考(CNY) | 备注 |
|---|---|---|---|---|
| 货源侧 | pokemoncenter-online(官方)| https://www.pokemoncenter-online.com/product/ITEM_20251031103001_701 | ¥321(JPY 6,120)| Enhanced Expansion Box(151 包),需日本转运 |
| 货源侧 | Buy From Japan 代购 | https://www.buyfromjapan.com/ | ¥450-600 | 直邮海外,加 ¥150-200 运费 |
| 货源侧 | Mercari JP | https://jp.mercari.com/search?keyword=151%20booster%20box | ¥350-500 | 未拆封溢价 |
| sell side | eBay($899.99)| https://www.ebay.com/itm/177253770067 | ¥6,423(US$899.99)| Enhanced Box 高位 |
| sell side | eBay($830)| https://www.ebay.com/itm/177113164418 | ¥5,926(US$830)| 均价 |
| sell side | eBay($679.99)| https://www.ebay.com/itm/167245898779 | ¥4,855(US$680)| 中位 |
| sell side | eBay($555)| https://www.ebay.com/itm/405703220983 | ¥3,963(US$555)| 低端 |
| sell side | eBay($399.99, 642 sold)| https://www.ebay.com/itm/175772476409 | ¥2,855(US$400)| **基础款 20 包均价**(642 sold,最强均价锚)|
| **撮合** | **¥1,071 sell 均价**(20 包)+ ¥2,855(Enhanced)| vs ¥321 货源(20 包)| **spread ¥750(233%, 20 包)** | **撮合 20 包基础款更稳**(642 sold 高频)|

### 撮合"两边验证"清单(每单必做 5 项)

- [ ] sell side eBay listing 真实在售(没下架)
- [ ] 货源 buyee.jp / pokemoncenter / humanmade.jp 真实可买(没缺货)
- [ ] 货源价 × 汇率 + 国际运费 < sell side 均价 × 0.5
- [ ] 买家信用(eBay ≥ 10 评价,Grailed ≥ 3 成交)
- [ ] 货源真伪可验证(PSA 码 / HM 镭射标 / Pokemon Center 防伪)

---

# 📋 30 天任务表(Phase A + B)

## Phase A1 — 需求池(Day 1-7,2026-08-17 → 08-23,30 min/天)

| 任务 | 工具 |
|---|---|
| eBay / Grailed 搜 Pokemon PSA 卡 "sold" 区均价 | 浏览器 |
| eBay / Grailed 搜 HumanMade Tee "sold" 区均价 | 浏览器 |
| eBay 搜 USJ 限定 / 鬼灭 Popcorn Bucket | 浏览器 |
| eBay 搜 Pokemon Card 151 Booster Box sealed | 浏览器 |
| 记录:每个 SKU 真实成交价 + 月销量 + 评价数 | 飞书/Notion |
| 找 3 个海外华人微信群 / 论坛 / Reddit | 浏览器 |

## Phase A2 — 供给池(Day 8-14,2026-08-24 → 08-30,30 min/天)

| 任务 | 工具 |
|---|---|
| `arb basket --budget 5000` 重跑,对比 Day 1-7 需求池价格 | CLI |
| 用 `arb prices fetch` 看 stub 货源价(stub,真价 Day 15-21 抓) | CLI |
| 1688 / buyee.jp / humanmade.jp 实地询价 | 浏览器 |
| 找 3 个货源代发渠道(buyee / 1688 / 代购) | 浏览器 |

## Phase B1 — 撮合测试(Day 15-21,2026-08-31 → 09-06,1h/天)

| 任务 | 工时 |
|---|---|
| 上 eBay / Grailed listing(选 3-5 个 SKU)| 30 min/天 |
| 微信海外华人群发求购信息 | 15 min/天 |
| 回买家咨询 + 撮合报价 | 15 min/天 |

## Phase B2 — 扩 SKU 池(Day 22-30,2026-09-07 → 09-16,1h/天)

- 加 5-10 个新 SKU(从 Phase A 撮合池表现好的衍生)
- Day 22-30 启用 F2 报警(货源价波动盯)
- Day 29-30 月度撮合统计

## 撮合池模板(Day 14 必填)

| # | 需求 SKU | 买家出价(eBay 已售均价)| 货源要价(buyee/1688)| spread | 我抽佣 | 净利 | 撮合可行性 |
|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |  |
| 9 |  |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  |  |

## 撮合记录表(Day 15-30 每日填)

| 日期 | 撮合 SKU | 买家 | 货源 | 买家出价 | 货源要价 | spread | 我抽佣 | 净利 | 状态 |
|---|---|---|---|---|---|---|---|---|---|
| 8/18 |  |  |  |  |  |  |  |  |  |
| ... 9/16 |  |  |  |  |  |  |  |  |  |

---

# 🚦 决策树(Day 14 + Day 30)

## Day 14 强制停盘点(2026-08-30,不可跳过)

> 两池都要填,跳过的默认 = 🔴。

### 需求池指标

| 指标 | 🟢 继续 | 🟡 减半 | 🔴 停 |
|---|---|---|---|
| 候选 SKU 需求验证完成 | ≥ 8 个 | 4-8 个 | < 4 个 |
| eBay / Grailed "sold" 均价已记录 | ≥ 5 SKU | 2-5 SKU | < 2 |
| 海外华人买家渠道 | ≥ 3 个 | 1-3 个 | 0 |

### 供给池指标

| 指标 | 🟢 继续 | 🟡 减半 | 🔴 停 |
|---|---|---|---|
| 货源代发渠道(buyee/1688/代购)| ≥ 3 个 | 1-3 个 | 0 |
| 货源实地询价完成 | ≥ 5 SKU | 2-5 SKU | < 2 |
| `arb basket` 重跑确认 | ✅ 跟需求池 80% 重合 | 50-80% | < 50% |

### 综合决策

| 需求池 | 供给池 | 综合决策 |
|---|---|---|
| 🟢 | 🟢 | **Day 15-30 撮合测试,Day 30 后扩池** |
| 🟢 | 🔴 | 需求 OK,供给不足,Day 15-30 重找货源 |
| 🔴 | 🟢 | 供给 OK,需求不足,Day 15-30 重找买家 |
| 🔴 | 🔴 | 双停,找我对账复盘 |

## Day 30 决策树(2026-09-16 必须做)

### 撮合总指标

| 指标 | 🟢 跑通 | 🟡 部分跑通 | 🔴 失败 |
|---|---|---|---|
| 30 天总撮合单数 | ≥ 10 单 | 3-10 单 | < 3 单 |
| 总抽佣 + spread 净利 | > ¥3,000 | ¥500-3,000 | < ¥500 |
| 撮合成功率(成交 / 上 listing) | ≥ 30% | 10-30% | < 10% |
| 退货 / 纠纷率 | < 5% | 5-15% | > 15% |
| 跑通 SKU 数(≥1 单成交)| ≥ 3 | 1-2 | 0 |

### 三结果

- **🟢 跑通** → 找我对账,扩池 + 优化抽佣 + 自动化(eBay 自动 listing / Grailed 批量上架)
- **🟡 部分跑通** → 优化撮合池 / 加 SKU / 换货源渠道
- **🔴 失败** → 找我对账,复盘是需求池不对 / 货源不对 / 抽佣定价不对

---

# 📦 详细信息(参考用)

## 基本信息

| 项 | 值 |
|---|---|
| 起始 | 2026-08-17 |
| 结束 | 2026-09-16 |
| 模式 | 撮合中介(P2P matching)— 不囤货 / 不入境 / 不发货 |
| 方向 | JP → 海外(货源 JP,买家海外华人 eBay / Grailed / Etsy / 微信) |
| 现金投入 | ¥0(预收买家款再付货源)|
| 库存 | 0(代发直邮,不经我手) |
| 海关风险 | 0(货源直发海外,不入境 CN) |
| 物流 | 货源代发(buyee.jp / 1688 / USJ 现场)直邮海外买家 |
| 收入结构 | 抽佣 ¥500-1,500/单 + 价差 spread |
| 时间分配 | 撮合池运营 1.5h/天 + 数字 leg 副业 0-30 min/天 |

## 撮合业务流程图

```
[买家侧] 闲鱼/eBay/Grailed 求购
       ↓
   需求池(Day 1-7 采集)
       ↓
[撮合引擎] ← 你
       ↓
   spread 测算:买家出价 - 货源要价 - 物流 - 平台费 - 退货预留 - 抽佣
       ↓
[卖家侧] 货源代发(buyee.jp / 1688 / USJ 现场 / humanmade.jp)
       ↓
   货源直邮买家
       ↓
[买家收货 + 确认]
       ↓
[抽佣落袋 ¥500-1,500/单]
```

### Spread 测算公式

```
净利 = 买家出价 - 货源要价 - 物流 - 平台费(eBay 13.25% / Grailed 9%) - 退货预留 5% - 我抽佣
     = spread × 0.85(扣平台费+退货) - 物流 - 我抽佣
```

## 单笔撮合测算(以 PKMN-PSA 为例)

```
货源要价(CNY):        ¥714   (buyee.jp 代购 + EMS 国际到买家)
买家出价(eBay 已售均价):¥8,568  (USD 1200 × 7.14)
eBay 平台费:           -¥1,135 (13.25% × ¥8,568)
PayPal 提现费:          -¥340  (4.4% × ¥8,568 - 货币转换)
退货预留 5%:           -¥428  (5% × ¥8,568)
我抽佣:                -¥500  (从 spread 抽)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
净利:                 ¥5,451 (63% margin)
```

**单笔 ¥5,451 净利 / 0 库存 / 0 入境 / 0 物流**。

## F1-F5 工具在 v3.2 撮合模型下的角色

| 工具 | v3.1 代购 | **v3.2 撮合** |
|---|---|---|
| F1 跨源价 | 我要买的源头价 | **货源侧询价**(buyee.jp / 1688 / humanmade.jp) |
| F2 报警 | 我买的价格波动 | **货源价波动**(决定撮合可行性) |
| F3 ¥5,000 额度 | 我自己用 | **不再需要**(撮合 0 库存) |
| F4 退货 | 我卖出的记录 | **撮合成功的售后跟踪** |
| F5 HS 码 | 我要买的 SKU 税档 | **货源直邮海外的 HS 码 / 关税**(eBay DDP / DDU) |

### F1-F5 在 v3.2 用得上的具体命令

```bash
# Day 1-7 货源询价(stub 先用,真价 Day 8-14 重抓)
arb prices fetch-all

# Day 8-14 重跑最优组合
arb basket --budget 5000 --route PEK-NRT-WEEKEND

# 临行前货源价格波动盯(其实不需要去 JP,但仍可用作 early warning)
arb prices alerts --setup --threshold-pct 5

# 撮合成交后登记(复用 Track A 数字 leg 的命令)
arb returns add --sku JP-PKMN-PSA --sold-at 2026-08-25 \
                --sold-cny 8568 --channel eBay

# 月度毛利(实物 + 数字合并)
arb returns margin --month 2026-08

# 撮合 SKU 直邮 HS 码(eBay DDP 申报用)
arb tax get JP-PKMN-PSA
```

---

# 🆕 v3.4 新增 4 个 Feature

> **v3.3 漏掉的功能补齐**:来回采购行程 + 现场买 + 电商预囤 + 哥们仓。

## Feature 1 · 来回采购行程推荐(🅲 出差代购)

**算法**:`arb/routes/trip_recommend.py`
**Day 1 测试输出**(stub 阶段):

| Rank | Trip | 出发 | 固定成本 | 货值上限 | ROI |
|---|---|---|---|---|---|
| **1** | **PVG→NRT 09-11→09-14🌙** | 周末 | ¥3,000 | ¥6,000 | **1.0×** |
| 2 | CAN→NRT 09-18→09-21🌙 | 周末 | ¥3,400 | ¥6,000 | 0.8× |
| 3 | PEK→NRT 09-04→09-07🌙 | 周末 | ¥3,700 | ¥6,000 | 0.6× |

**Top pick**:PVG→NRT 周五去周一回,周末 trip,¥3,000 固定撬动 ¥6,000 货值。

**算法公式**:`net_roi = cargo_capacity - fixed_cost`,其中:
- `cargo_capacity` = ¥5,000 + ¥1,000 二次入境 = ¥6,000
- `fixed_cost` = Amadeus 实查机票 + 食宿估算(¥1,200/3 天)

**Phase 2 接 Amadeus 实查机票**:`arb flightlookup` 已有 panel,直接接入。

## Feature 2 · 现场买的东西清单(🅲 出差代购子项)

**算法**:`arb/scoring/recommend.recommend_on_site()`

| SKU | 地点 | 买入 JPY | 卖 CNY | spread |
|---|---|---|---|---|
| 药妆折扣 | 松本清 / 大国药局 | ¥3,000 | ¥600 | **75%** 🟢 |
| USJ 鬼灭 Popcorn | USJ 现场 | ¥4,080 | ¥678 | **66%** 🟢 |
| USJ 2025 限定 | USJ 现场 | ¥5,500 | ¥900 | **64%** 🟢 |
| outlet MK 包 | 御殿场 / 长岛 | ¥8,000 | ¥1,500 | **55%** 🟡 |

**Phase 2 接 eBay sold 验证**(每 SKU 验证均价 + 月销量)。

## Feature 3 · 电商下单囤货带过去(🅳 CN→海外)

**算法**:`arb/scoring/recommend.recommend_cn_ecom()`

| SKU | CN 源 | CN 价 | 海外卖 | 海外价 | spread | 携带 |
|---|---|---|---|---|---|---|
| TCM 中药 | 1688 | ¥150 | Etsy 海外华人 | ¥700 | **370%** 🟢 | 随身行李 |
| 普洱茶 | 拼多多 | ¥200 | eBay US | ¥800 | **300%** 🟢 | 随身行李 |

**Phase 2 接 1688 open API + 拼多多比价**。

## Feature 4 · 电商下单放哥们那(🅴 海外→CN)

**算法**:`arb/scoring/recommend.recommend_friend_warehouse()`

| SKU | 海外源 | 海外价 | CN 卖 | CN 价 | spread | 哥们仓 |
|---|---|---|---|---|---|---|
| HM Tee | humanmade.jp 代购 | ¥350 | 闲鱼 | ¥857 | **145%** 🟢 | 7 天 |
| PKMN-151 BB | buyee.jp | ¥470 | 闲鱼 | ¥1,071 | **128%** 🟢 | 7 天 |

**¥5,000 入境额度窗口管理**:Phase 2 加 `arb.quota_window` 自动算可带货值。

---

# 🛠️ 工具辅助用法(v3.2)

## ── 撮合成交后(每单) ──

```bash
arb returns add --sku JP-PKMN-PSA --sold-at 2026-08-25 \
                --sold-cny 8568 --channel eBay \
                --note "撮合:买家 eBay $1200 / 货源 buyee.jp ¥714 / 我抽 ¥500"
```

## ── 每周日 10min ──

```bash
arb returns margin --month 2026-08
```

## ── 货源询价(选做) ──

```bash
# stub 先用,真价 Day 8-14 抓
arb prices fetch-all
arb basket --budget 5000 --route PEK-NRT-WEEKEND
arb prices alerts --setup --threshold-pct 5
arb tax get JP-PKMN-PSA  # eBay DDP 直邮 HS 码
```

## ── 数字 leg(副业,选做) ──

```bash
arb returns add --sku "Steam-ELDENRING" --sold-at 2026-08-20 \
                --sold-cny 25 --channel 闲鱼
```

## ── 不跑 ──

- ~~`arb quota summary`~~ — 不入境,¥5,000 额度用不上
- ~~F5 HS 码查 JP→CN 关税~~ — 不入境,无 CN 海关税;但仍可查 HS 码做 eBay DDP 申报

---

# 🚫 红线(不要做的事)

## 共用(3 条)

- ❌ **不记账**(没有数据就没有 Day 14 + Day 30 决策)
- ❌ **跟单一上游独家绑定**(数字 + 撮合都要 ≥ 3 个备选)
- ❌ **退回 v3.1 代购自营**(v3.2 撮合范式确立后不再退回)

## 主轨 — 撮合 leg 红线(8 条)

- ❌ **自己囤货**(违反撮合本质,变成代购)
- ❌ **入境 CN**(撮合不入境,无 ¥5,000 额度问题)
- ❌ **单笔 spread < ¥200 不撮**(抽佣都不够)
- ❌ **买家出价 < 货源 × 2 不撮**(没利润空间)
- ❌ **不验货源真实性就撮**(买空卖空 / 假货风险)
- ❌ **不验买家信用就撮**(eBay < 10 评价 / Grailed 无成交不接)
- ❌ **没用 `arb returns add` 记录每单**(撮合追溯需要)
- ❌ **没用 F1 跨源价做 spread 校验**(肉眼估算容易漏平台费)

## 副业 — 数字 leg(3 条)

- ❌ 先垫钱给上游 key
- ❌ 接月卡 / 季卡 / 礼品卡
- ❌ 单笔 > 500 CNY 大单