# 算法版本演进(analysis algorithm versions)

> **记录每次 score_sku / recommend / scraper / pipeline 改动**。日期 + 版本号 + 改动 + 原因 + 影响。

---

## v1.1 · 2026-08-17(v3.4 5-Leg 启动 — Day 1)

### 改动

**`arb/scoring/score_sku.py`**:
- 新增 `LEG_SCORE_TABLE`:5-leg 各自 score 评分表(不同 leg 下 spread / volume / reliability / complexity 不同)
- 新增 `ON_SITE_SKUS`:🅲 现场买 stub(USJ 限定 / outlet / 药妆 / Bic Camera)
- 新增 `CN_ECOM_SKUS`:🅳 CN 电商 → 海外 stub(中药 / 茶 / 工艺品)
- 新增 `FRIEND_WAREHOUSE_SKUS`:🅴 海外电商 → 哥们仓 → 带回 CN stub

**`arb/scoring/recommend.py`**:
- 新增 `recommend_by_leg(leg, n)` — 按 leg 推荐
- 新增 `recommend_all_legs(n)` — 5-leg 并行
- 新增 `recommend_on_site()` / `recommend_cn_ecom()` / `recommend_friend_warehouse()`
- 新增 CLI:`python -m arb.scoring.recommend {legs|on_site|cn_ecom|friend|all}`

**`arb/routes/trip_recommend.py`(新)**:
- `TripRecommendation` dataclass — 来回行程推荐结构
- `TRIP_STUB_TABLE` — 3 个候选行程(PEK/PVG/CAN→NRT 周末 trip)
- `recommend_trips()` / `best_trip()` — 按 ROI 排序

### v1.1 测试输出(Day 1 — 5-leg)

```
🅰 撮合       PKMN-151-BB 88.2 🟢  / HM Tee 80.7 🟢 / PKMN-PSA 78.0 🟢
🅱 代购集运    HM Tee 70.0 🟢 / PKMN-151-BB 64.0 🟡
🅲 出差代购    PKMN-PSA 85.2 🟢 / USJ-NEZ 83.5 🟢 / PKMN-151-BB 83.0 🟢
🅳 电商带过去  PKMN-151-BB-CN 62.5 🟡
🅴 哥们仓     USJ-NEZ 79.2 🟢 / HM Tee 78.5 🟢

🅲 现场买:药妆 75% / USJ 鬼灭 66% / USJ 2025 64% / outlet MK 55%
🅳 CN 电商:TCM 370% / 普洱茶 300%
🅴 哥们仓:HM Tee 145% / PKMN-151-BB 128%

🅲 行程:PVG→NRT 09-11→09-14 (¥3000 固定 / ¥6000 货值 / 1.0× ROI) Top pick
```

### 关键洞察

- **🅲 出差代购是最高杠杆 leg**:¥3,000 机票 → ¥6,000 货值(¥5,000 + ¥1,000 二次入境)
- **🅲 出差代购 SKU 评分 = 🅰 撮合同 SKU 但 complexity 略高**(机票 / 食宿),score 仍 83-85 🟢
- **🅳 CN 电商 spread 极高**(中药 370% / 茶 300%),但 sell_volume 0.5 拉低综合分
- **🅴 哥们仓 spread 128-145%** + ¥5,000 额度约束,适合 HM Tee / PKMN-151 BB 等货值 SKU

### 已知限制(Phase 2/3 解决)

- ❌ TRIP_STUB_TABLE 固定 3 个 trip,Phase 2 接 Amadeus 实查
- ❌ ON_SITE_SKUS / CN_ECOM_SKUS / FRIEND_WAREHOUSE_SKUS 都是 stub,Phase 2 接真价流
- ❌ ¥5,000 额度窗口管理未实现,Phase 2 加 `arb.quota_window`
- ❌ 周末 trip / 拼货多人 trip 未实现,Phase 3

---

## v1.0 · 2026-08-17(stub 阶段 — Day 1)

### `arb/scoring/score_sku.py`

| 字段 | 值 |
|---|---|
| 公式 | `score = spread×0.35 + volume×0.25 + reliability×0.20 - complexity×0.20` |
| 权重 | 固定(Phase 3 训) |
| 输入 | SCORE_TABLE 硬编码(4 SKU)|
| 输出 | score 0-100 + 🟢/🟡/🔴 等级 |
| 阈值 | 🟢 ≥ 70 / 🟡 40-70 / 🔴 < 40 |

### `arb/scoring/recommend.py`

| 字段 | 值 |
|---|---|
| 接口 | `recommend_top_n(n=3)` |
| 排序 | score 降序 |
| 输出 | list[Recommendation] = rank / sku / score / grade / components |

### Day 1 测试输出(2026-08-17)

```
Rank  SKU                          Score   Grade
1     JP-PKMN-151-BB               88.2    🟢 主推
2     JP-HUMANMADE-TEE-GRAPHIC     80.7    🟢 主推
3     JP-PKMN-PSA                  78.0    🟢 主推
4     JP-ANIME-USJ-NEZ             64.0    🟡 试单
```

**洞察**:PKMN-151 BB 第一不是 spread 最高(1100% < 233% 实际),而是 sell_volume + reliability 拉高。

### 已知限制

- ❌ spread_pct 截断到 1.0(实际 PKMN-PSA 是 11.0)— Phase 2 改用对数缩放
- ❌ SCORE_TABLE 硬编码 4 SKU — Phase 2 接真价流
- ❌ sell_volume / reliability / complexity 字段是手填 — Phase 2 自动算

---

## v1.1(规划中 · Day 8-14 Phase 2)

### 计划改动

- 接 `arb.scrapers.buyee` / `arb.scrapers.ebay_sold` / `arb.scrapers.amazon_jp` / `arb.scrapers.rakuten` 真价
- spread_pct 改对数缩放(`log(spread + 1) / log(20)`)
- sell_volume 自动从 eBay sold 数拉
- reliability 自动算:货源验证(买ee 评论 + Pokemon Center 防伪)+ 买家信用(eBay 评价数)
- complexity 自动算:HS 码查 + 平台规则 + 集运报价
- 🅲 行程接 Amadeus 实查机票 + ¥5,000 额度窗口管理
- 🅳 1688 / 拼多多 API 接入

---

## v1.2(规划中 · Day 22-30 Phase 3)

### 计划改动

- `learned_weights.py` 训历史成交权重
- eBay 自动 listing API
- 微信海外群自动推送(RPA)
- Telegram bot 撮合成交通知
- 🅲 拼货多人 trip / 自动 ¥5,000 额度窗口