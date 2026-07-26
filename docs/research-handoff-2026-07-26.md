# Research Handoff — 2026-07-26 PM 总控注入

**作者**: PM Agent(并行研究汇总)
**注入给**: pm-loop 下一轮(round 5+)的 Claude Agent
**目的**: 把真实市场价 + 4 个新 SKU 走 `proposed_prices` 审批流进入 `data/db.sqlite`,并在 web/ 决策报告里用真数据。

**关键背景**: 你 Round 4 已经实现了 `proposed_prices` 审批流(`arb/db.py:225` / `arb/cli.py:312` / `arb/verify.py`)。**请走这条流**,不要直接 UPDATE opportunities 表,保留审计痕迹。

---

## 1. 必须执行的:把研究数据 stage 为 proposals(P0)

请写一次性脚本 `scripts/apply_research_proposals.py`,做以下两件事,然后用 `arb.cli.proposals apply <id>` 批量应用:

### 1.1 校准 6 个旧 SKU 的价格(`data/research/sku_prices_2026-07-26.json`)

对每个 sku,从 JSON 取 `buy_price_usd` / `sell_price_usd`,对照 opportunities 表当前值算 drift_pct,然后调 `db.add_proposed_price()` 走流程。

| sku | field | 当前值 | 真实值 | drift_pct | source_url |
|---|---|---|---|---|---|
| `JP-SKII-FT230` | purchase_price_usd | 85.00 | 150.00 | 76.5% | https://www.fasola.jp |
| `JP-SKII-FT230` | sell_price_usd | 145.00 | 185.00 | 27.6% | https://www.amazon.com/SK-II-Facial-Treatment-Essence-230ml/dp/B000VOHH8I |
| `JP-WS-YAMAZAKI12` | sell_price_usd | 320.00 | 120.00 | -62.5% ⚠️ | https://www.ebay.com/sch/i.html?_nkw=Yamazaki+12+Year+Single+Malt |
| `JP-NINTENDO-SWOLED` | purchase_price_usd | 270.00 | 319.87 | 18.5% | https://www.yodobashi.com/category/14254/ |
| `JP-NINTENDO-SWOLED` | sell_price_usd | 360.00 | 399.99 | 11.1% | https://www.amazon.com/Nintendo-Switch-OLED-Model-White/dp/B0BJL7QQQQ |
| `JP-DYSON-V12S` | purchase_price_usd | 510.00 | 593.33 | 16.3% | https://www.dyson.co.jp/vacuum-cordless/v12s/detect-slim-submarine/yellow-iron |
| `JP-DYSON-V12S` | sell_price_usd | 620.00 | 649.99 | 4.8% | https://www.dyson.com/vacuum-cleaners/cordless/v12s |
| `JP-LUX-PATEK` | purchase_price_usd | 8200.00 | 6333.33 | -22.8% | https://www.brandoff.co.jp |
| `JP-LUX-PATEK` | sell_price_usd | 11500.00 | 7800.00 | -32.2% | https://www.chrono24.com/patekphilippe/calatrava--mod--79.htm |
| `JP-ANIME-GK2024` | purchase_price_usd | 175.00 | 198.67 | 13.5% | https://www.animate.co.jp |
| `JP-ANIME-GK2024` | sell_price_usd | 290.00 | 150.00 | -48.3% ⚠️ | https://www.ebay.com/sch/i.html?_nkw=jujutsu+kaisen+gojo+1/7 |

**detected_currency**: USD 全部(数据已 FX 到 USD)
**detected_raw**: 用 JSON 里的 `notes` 截前 60 字符
**status**: 默认 'pending'

**特别注意**:
- `JP-WS-YAMAZAKI12` 的 purchase_price_usd JSON 里是 null,**不要 stage purchase 的 proposal**,只 stage sell_price 那个
- `JP-ANIME-GK2024` 的 sell_price 校准会把它从赚钱变成赔钱,**stage 但不要 apply**——写一段 `notes` 说"⚠️ US 实际售价 < JP 采购,本次为倒赔,recommend: reject"在 report.py 的 banner 里展示
- `JP-WS-YAMAZAKI12` 同样:已停产,recommend reject,decision engine 会判"不建议"

### 1.2 INSERT 4 个新 SKU(`data/research/new_skus_2026-07-26.json`)

| sku | 必填字段 |
|---|---|
| `JP-PKMN-151-BB` 🔥 ROI 100.4% HIGH | purchase_price_usd=45.00 sell_price_usd=150.00 platform_fee_rate=0.13 minutes_per_unit=30 success_rate=0.85 |
| `JP-CDPB-SERUM-40` ROI 32.8% HIGH | purchase_price_usd=132.00 sell_price_usd=230.00 success_rate=0.85 |
| `JP-ANIME-USJ-NEZ` ROI 62.8% MEDIUM | purchase_price_usd=30.00 sell_price_usd=95.00 success_rate=0.7 (单次入园限买 1-2 件) |
| `JP-HADALABO-PREM-400` ROI 5.2% LOW | purchase_price_usd=21.00 sell_price_usd=32.95 success_rate=0.9 |

直接 `INSERT INTO opportunities` 用 JSON 的字段。注意 `category` / `source_market` / `target_market` / `purchase_source_url` / `sell_source_url` / `notes` (rationale 字段) 都要带上,`verified=1`,`data_freshness_ts='2026-07-26'`。

### 1.3 应用 proposal

```bash
cd /Volumes/SanDisk2TB/jp-us-arb-route
python3 -m arb.cli proposals --status pending  # 看到底有哪些
python3 -m arb.cli proposals apply <id>       # 单条应用
# 或写脚本批量 apply,跳过上面 2 个 recommend-reject 的
```

**不要 auto-apply** JP-ANIME-GK2024 的 sell_price 校准 和 JP-WS-YAMAZAKI12 的 sell_price 校准 这两条。它们 stage 后保持 pending,在 web/ 里显示给用户看。

---

## 2. UI 设计参考(P1,正在 Round 4+ 的 web/ 任务用)

`data/research/ui_references_2026-07-26.json` 含 3 个对标(TradingView Desktop / Linear / Smartsheet)+ 17 条具体交互 ideas。

**核心要落地的 5 条**(必须出现在 `web/index.html`):

1. **左侧键盘导航**:↑↓ 切换商机,Enter 选中,Esc 清空选择
2. **筛选状态可保存**到 localStorage(参考 Linear 的 "我的视图")
3. **右侧 sticky 头**:商机名 + 决策等级("建议/谨慎/不建议")+ ROI% + 单件利润,滚动时始终可见
4. **左侧选中 → 右侧所有组件联动刷新**(参考 Smartsheet Dashboard)
5. **决策报告导出按钮**:Markdown + 单页 PDF(可选 PDF,先确保 Markdown)

**重要视觉决定**:报告里"建议"用绿色,"谨慎"用黄色,"不建议"用红色;但**不要单独依赖颜色**,必须同时有图标 ✓ ⚠ ✕(参考 Linear 的 "颜色不是唯一指示")。

---

## 3. 不在范围内(请勿扩展)

- 不接真实支付 / 不碰真实清关通道
- 不引入新依赖(只用项目现有的 sqlite3 / FastAPI / Vue 或纯 HTML)
- 不动 `arb/decision.py` 现有逻辑(只可加字段,不改判定)
- 不删除 `data/research/*.json` 这 3 个 PM 注入文件
- 不动 `pm-loop/20260726-103909-jp-us-arb-route-55490` 分支名
- 不直接 UPDATE opportunities 表(必须走 proposed_prices 流)

---

## 4. 验收自检

完成后请跑:

```bash
cd /Volumes/SanDisk2TB/jp-us-arb-route

sqlite3 data/db.sqlite "SELECT COUNT(*) FROM opportunities;"   # 应 = 10
sqlite3 data/db.sqlite "SELECT sku, name, purchase_price_usd, sell_price_usd, verified FROM opportunities WHERE verified=1 ORDER BY sku;"

sqlite3 data/db.sqlite "SELECT COUNT(*), status FROM proposed_prices GROUP BY status;"  
# 应有 applied(9-10 条)+ pending(2 条:yamazaki sell + anime sell)

python3 -m arb.cli list   # 应显示 10 条商机
python3 -m arb.cli decide --sku JP-PKMN-151-BB --units 3 --route PVG-NRT-LAX-2N  
# Pokémon 151 应该判 "建议" + ROI > 50%

python3 -m pytest tests/ -q   # 应全过(原 155 + 你加的)
```

完成后 commit message 建议:`apply(research): real market prices via proposed_prices + 4 new SKUs (round N)`

---

## 5. 文件清单(本 round 可读取)

- `/Volumes/SanDisk2TB/jp-us-arb-route/data/research/sku_prices_2026-07-26.json`(校准源)
- `/Volumes/SanDisk2TB/jp-us-arb-route/data/research/new_skus_2026-07-26.json`(新增源)
- `/Volumes/SanDisk2TB/jp-us-arb-route/data/research/ui_references_2026-07-26.json`(UI 参考)
- `/Volumes/SanDisk2TB/jp-us-arb-route/arb/db.py`(proposed_prices API 在 line 225+)
- `/Volumes/SanDisk2TB/jp-us-arb-route/arb/cli.py`(proposals 子命令 line 312)
- `/Volumes/SanDisk2TB/jp-us-arb-route/arb/verify.py`(校验逻辑)

PM 总控已就位,有任何 BLOCKED / 不确定 / 偏离验收的决策,commit 后下一轮会接力修。