# jp-us-arb-route

> 让有美签 + 日签、时间稀缺的用户在 5 分钟内做完"这次出差值不值得去赚这个钱"的决策。
> 左侧商机清单,右侧路线详情,一键导出 Markdown / HTML / PDF 决策报告。

🌏 范围:仅 日本 ↔ 美国 (东西海岸均可),V0 不接支付、不做多用户、不做移动端。

---

## V0 状态 (Round 4 已交付)

| # | 验收项 | 状态 |
|---|---|---|
| 1 | 至少 6 个可执行商机 | ✅ SK-II / 山崎 12 / Switch OLED / Dyson V12 / Patek 中古 / Anime 限定 |
| 2 | 至少 1 条完整路线 | ✅ PVG → NRT → LAX 2-night, 6 段 leg |
| 3 | 一体化平台原型 (左侧列表 + 右侧详情 + 顶栏参数) | ✅ Web SPA (`web/`, Alpine.js + FastAPI) |
| 4 | Markdown / PDF 导出 | ✅ Markdown + HTML + PDF (`arb/report.py`) |
| 5 | 决策等级判定函数 + ≥ 10 条样例 | ✅ `arb.decision.judge`, 23 单元测试 |
| 6 | SQLite 持久化 + CLI / Web 双入口 | ✅ SQLite (`data/db.sqlite`) + CLI (`python -m arb`) + API (`/api/*`) |
| 7 | 数据新鲜度告警 + 半自动抓取 (Round 3) | ✅ `arb.freshness` + `arb.scraper` + `arb.refresh`;30 天阈值 + `arb refresh --sku X` CLI + `POST /api/opportunities/{sku}/refresh` |
| 8 | **验证徽章 + 提案审批 (Round 4)** | ✅ `arb.verify` + `proposed_prices` 表;`arb verify --sku X` + `arb proposals [apply|reject <id>]` + `POST /api/opportunities/{sku}/verify`;±5% 容差内自动 verified,超容差或币种不匹配 stage 提案待人工 apply/reject |
| 9 | **三档情景 保守/中性/乐观 (Round 5)** | ✅ `arb.scenarios`;`arb scenarios --sku X --units N` + `--json`;`/api/decide` 增 `scenarios` 字段;Markdown / HTML / PDF / SPA 全链路渲染;保守降级提示 (cross-check) |

**189 tests pass** (`pytest -q`) — 23 decision + 6 db + 22 cli + 13 report + 26 api + 22 freshness + 17 scraper + 7 refresh + 24 verify + 18 scenarios + 11 new (Round 5 CLI/API).

**155 tests pass** (`pytest -q`) — 23 decision + 6 db + 19 cli + 13 report + 25 api + 22 freshness + 17 scraper + 7 refresh + 24 verify.

---

## 快速开始

```bash
# 1. 装依赖
pip install pytest fastapi uvicorn playwright
python3 -m playwright install chromium   # 单次,供 PDF 导出使用

# 2. 种子数据: 6 个白名单商机 + 1 条路线
python3 -m arb seed

# 3. CLI 用法
python3 -m arb list                                      # 列出商机 + 路线
python3 -m arb decide --sku JP-SKII-FT230 --units 5      # 文字决策
python3 -m arb report --sku JP-SKII-FT230 --units 5 --md --out exports/
python3 -m arb report --sku JP-SKII-FT230 --units 5 --pdf --out exports/
python3 -m arb report --sku JP-SKII-FT230 --units 5 --html --out exports/
python3 -m arb freshness                                # 所有商机新鲜度告警
python3 -m arb freshness --sku JP-SKII-FT230            # 单条
python3 -m arb refresh --sku JP-SKII-FT230               # 重抓 URL 并更新 freshness_ts
python3 -m arb verify --sku JP-SKII-FT230                # 抓取并与存储价格比对 (±5% 容差)
python3 -m arb verify --sku JP-SKII-FT230 --dry-run      # 只报告,不入 proposed_prices
python3 -m arb scenarios --sku JP-SKII-FT230 --units 5   # 保守/中性/乐观 三档判定 (Round 5)
python3 -m arb scenarios --sku JP-SKII-FT230 --units 5 --json  # 同上,JSON 输出
python3 -m arb proposals                                 # 列出所有提案
python3 -m arb proposals --sku JP-SKII-FT230 --status pending
python3 -m arb proposals apply 7                         # 接受提案 #7 (覆盖存储价格)
python3 -m arb proposals reject 7                        # 拒绝提案 #7 (保持存储价格)
python3 -m arb health                                   # DB 健康
python3 -m arb serve --port 8765                        # 启动 Web SPA

# 4. 测试
python3 -m pytest -v
```

---

## Web SPA (Round 2)

启动本地 Web 服务后浏览器打开 `http://127.0.0.1:8765`:

```
┌─────────────────────────────────────────────────────────────┐
│ 🌏 jp-us-arb-route           [出发▾] [目的▾] [日期] [ROI] [数量] │
├──────────────┬──────────────────────────────────────────────┤
│ 商机清单 (6) │  SK-II Facial Treatment Essence 230ml        │
│ ┌──────────┐ │  [❌ 不建议]  ROI -58.5%  净利润 $-887.58      │
│ │SK-II FT230│ │  ────────────                                │
│ │Yamazaki12 │ │  [⬇ Markdown] [⬇ HTML] [⬇ PDF]              │
│ │Switch OLED│ │                                              │
│ │Dyson V12  │ │  单件成本明细  (USD)                          │
│ │Patek 中古 │ │  采购价(JP免税)   $85.00                     │
│ │Anime 限定 │ │  关税              $0.00                      │
│ └──────────┘ │  ...                                          │
│              │  行程时间线 (6 段)                              │
│              │  1 ▸ flight PVG → NRT                         │
│              │  2 ▸ flight NRT → LAX                         │
│              │  ...                                          │
│              │  数据来源 + 风险提示                            │
└──────────────┴──────────────────────────────────────────────┘
```

技术栈:**Alpine.js + 手写 CSS**(零构建步骤,单 HTML),后端 **FastAPI + uvicorn**。
无需 npm / node_modules;Alpine.js 通过 unpkg CDN 加载。

### API endpoints

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/health` | DB 健康 + counts |
| GET | `/api/opportunities` | 商机清单 JSON (每条嵌入 `freshness` 判定) |
| GET | `/api/routes` | 路线清单(含 legs) JSON |
| POST | `/api/decide` | 计算决策;body=`{sku, num_units, route?}`;返回 `decision` + `scenarios` [保守,中性,乐观] (Round 5) |
| POST | `/api/opportunities/{sku}/refresh` | 重抓 URL,成功时刷新 `data_freshness_ts`;返回 `price_hints` (不自动覆盖价格) |
| POST | `/api/opportunities/{sku}/verify` | 抓取并比对 `purchase_price_usd` / `sell_price_usd` (±5% 容差);容差内标记 `verified=1`,超容差或币种不匹配 stage 提案 |
| GET | `/api/proposals` | 提案清单(可 `?sku=...&status=pending`) |
| POST | `/api/proposals/{id}/apply` | 接受提案(覆盖存储价格并刷新 freshness_ts) |
| POST | `/api/proposals/{id}/reject` | 拒绝提案(保持存储价格) |
| GET | `/api/report/{sku}.md` | Markdown 报告(attachment, RFC 5987 文件名) |
| GET | `/api/report/{sku}.html` | HTML 报告 |
| GET | `/api/report/{sku}.pdf` | 单页 PDF(Playwright Chromium) |
| GET | `/docs` | FastAPI 自动 OpenAPI 文档 |
| GET | `/` | SPA 入口 (`web/index.html`) |

报告文件名格式:`jp-us-arb_<YYYY-MM-DD>_<SKU>_<目的城市>.<ext>`(CJK 走 RFC 5987 `filename*=UTF-8''`)。

---

## 项目结构

```
.
├── arb/
│   ├── __init__.py
│   ├── __main__.py        # 让 `python -m arb` 走 CLI
│   ├── decision.py        # 纯函数决策引擎 (无 I/O)
│   ├── db.py              # SQLite schema + repository
│   ├── seed.py            # 6 商机 + 1 路线种子数据
│   ├── freshness.py       # 数据新鲜度判定 (Round 3)
│   ├── scraper.py         # 安全 HTTP 抓取 + robots.txt (Round 3)
│   ├── refresh.py         # 刷新协调 (Round 3)
│   ├── verify.py          # 验证徽章 + 提案 stage (Round 4)
│   ├── scenarios.py       # 三档情景 (保守/中性/乐观) (Round 5)
│   ├── report.py          # Markdown / HTML / PDF 共享渲染器
│   ├── web_api.py         # FastAPI app (REST + 静态 SPA)
│   └── cli.py             # list / decide / report / seed / health / serve / refresh / freshness / verify / proposals
├── tests/
│   ├── test_decision.py   # 23 个手算对照用例
│   ├── test_db.py         # 6 个 schema + 仓储用例
│   ├── test_cli.py        # 19 个 CLI 子进程用例 (含 md/html/pdf/freshness/verify/proposals)
│   ├── test_report.py     # 13 个 report 渲染器用例 (含真 PDF + 新鲜度标记 + 提案 banner)
│   ├── test_web_api.py    # 25 个 FastAPI endpoint 用例
│   ├── test_freshness.py  # 22 个 freshness 判定用例
│   ├── test_scraper.py    # 17 个 scraper 安全网测试
│   ├── test_refresh.py    # 7 个 refresh 协调用例
│   ├── test_verify.py     # 24 个 verify + 提案审批用例 (Round 4)
│   └── test_scenarios.py  # 18 个 scenarios + 报告集成用例 (Round 5)
├── web/                   # 静态 SPA (Alpine.js)
│   ├── index.html
│   ├── app.js
│   └── style.css
├── data/
│   └── db.sqlite          # SQLite 数据库 (gitignored)
├── exports/               # 决策报告落盘
├── docs/
└── scripts/
```

---

## 决策引擎公式

每趟出差净利 = (目的售价 × (1 − 平台抽成)) × 件数 − (采购价 × (1 + 税率) + 物流) × 件数 − 旅费 − (时间 × 时薪)

```
ROI = 净利润 / 总成本 × 100%
```

| 输出 | 含义 |
|---|---|
| `level` | `建议` / `谨慎` / `不建议` |
| `reason` | 一句话理由,中文 |
| `roi_pct` | 利润率 |
| `net_profit_usd` | 净利润 |
| `total_cost_usd` | 总成本(=采购+关税+物流+旅费+时间) |
| `breakeven_sell_price_usd` | 盈亏平衡售价 |
| `hours_used` | 预计耗时 |

等级判定优先级:
1. `hours_used > hours_available` **或** `net_profit <= 0` → `不建议`
2. `roi_pct < min_roi_pct` → `不建议`
3. `roi_pct < target_roi_pct` → `谨慎`
4. 否则 → `建议`

---

## 风险与边界

- **未验证价格**:所有 SKU 标注 `verified=0`,UI/PDF 报告强制显示「⚠️ 未验证」字样。
- **海关免税额**:US CBP $800 / 日方 ¥20,000,数据以出发日两国海关公告为准。
- **品牌方限购**:每个商机 notes 字段记录限购数量,默认按单人额度算。
- **法规风险**:仅服务个人非贸易自用;所有报告显式标注「非投资建议 / 个人使用,非商业再销售」。
- **数据新鲜度 (Round 3)**:所有商机带 `data_freshness_ts`;>15 天标「🟡 临近复核」,>30 天标「⚠️ 陈旧待复核」。UI/CLI/PDF 都看得见;`arb refresh --sku X` 或 SPA 「🔄 刷新」按钮会重抓 URL,成功则更新 ts,**不自动覆盖价格**(返回 `price_hints` 给人工核对)。
- **验证徽章 + 提案审批 (Round 4)**:`arb verify --sku X` 或 SPA 「✓ 验证」按钮抓取 URL,与存储价格 ±5% 容差比对;容差内自动 `verified=1`,超容差或币种不匹配则 stage 到 `proposed_prices` 表(不自动覆盖)。人工通过 `arb proposals apply|reject <id>` 或 `POST /api/proposals/{id}/{apply|reject}` 接受或拒绝提案(接受时同时覆盖价格并刷新 freshness_ts)。
- **三档情景 (Round 5)**:单一净利数字易高估收益。`arb scenarios --sku X` 或 SPA 「三档情景」面板给出售价 -10% / 采购 +5~10% / 时薪 +20% 的保守档与售价 +5% / 采购 -3% / 时薪 -10% 的乐观档;`/api/decide` 增 `scenarios` 字段;Markdown / HTML / PDF 报告嵌入情景表;若保守档决策严于中性,自动产生 cross_check 降级提示。

---

## 下一轮计划

- Round 3: ✅ 已交付 — `arb.freshness` (30 天阈值) + `arb.scraper` (stdlib-only, robots.txt + 限速) + `arb.refresh` 协调;POST `/api/opportunities/{sku}/refresh` + CLI `arb refresh`;UI/CLI/PDF 全链路显示新鲜度。
- Round 4: ✅ 已交付 — `arb.verify` + `proposed_prices` 表;`arb verify --sku X` + `arb proposals apply|reject <id>` + `POST /api/opportunities/{sku}/verify`;±5% 容差内 `verified=1`,超容差或币种不匹配 stage 提案待人工审批;UI/CLI/PDF 全链路显示。
- Round 5: ✅ 已交付 — `arb.scenarios` (保守/中性/乐观) + `arb scenarios --sku X --units N [--json]` + `/api/decide` 增 `scenarios` 字段;Markdown / HTML / PDF / SPA 全链路渲染;保守降级自动产生 cross_check 提示。直击 Brief §10 风险表「用户真实利润与估算偏差大 → 决策报告里给保守/中性/乐观三档」。
- Round 6: eBay Buy API / Amazon PA-API 自动发现 (V1)。
- Round 7: PWA / 移动端优化;Notion / Apple Notes 导出。