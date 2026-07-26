# jp-us-arb-route

> 让有美签 + 日签、时间稀缺的用户在 5 分钟内做完"这次出差值不值得去赚这个钱"的决策。
> 左侧商机清单,右侧路线详情,一键导出 Markdown / HTML / PDF 决策报告。

🌏 范围:仅 日本 ↔ 美国 (东西海岸均可),V0 不接支付、不做多用户、不做移动端。

---

## V0 状态 (Round 2 已交付)

| # | 验收项 | 状态 |
|---|---|---|
| 1 | 至少 6 个可执行商机 | ✅ SK-II / 山崎 12 / Switch OLED / Dyson V12 / Patek 中古 / Anime 限定 |
| 2 | 至少 1 条完整路线 | ✅ PVG → NRT → LAX 2-night, 6 段 leg |
| 3 | 一体化平台原型 (左侧列表 + 右侧详情 + 顶栏参数) | ✅ Web SPA (`web/`, Alpine.js + FastAPI) |
| 4 | Markdown / PDF 导出 | ✅ Markdown + HTML + PDF (`arb/report.py`) |
| 5 | 决策等级判定函数 + ≥ 10 条样例 | ✅ `arb.decision.judge`, 23 单元测试 |
| 6 | SQLite 持久化 + CLI / Web 双入口 | ✅ SQLite (`data/db.sqlite`) + CLI (`python -m arb`) + API (`/api/*`) |

**61 tests pass** (`pytest -v`) — 23 decision + 6 db + 11 cli + 9 report + 12 api.

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
| GET | `/api/opportunities` | 商机清单 JSON |
| GET | `/api/routes` | 路线清单(含 legs) JSON |
| POST | `/api/decide` | 计算决策;body=`{sku, num_units, route?}` |
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
│   ├── report.py          # Markdown / HTML / PDF 共享渲染器
│   ├── web_api.py         # FastAPI app (REST + 静态 SPA)
│   └── cli.py             # list / decide / report / seed / health / serve
├── tests/
│   ├── test_decision.py   # 23 个手算对照用例
│   ├── test_db.py         # 6 个 schema + 仓储用例
│   ├── test_cli.py        # 11 个 CLI 子进程用例 (含 md/html/pdf)
│   ├── test_report.py     # 9 个 report 渲染器用例 (含真 PDF)
│   └── test_web_api.py    # 12 个 FastAPI endpoint 用例
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

---

## 下一轮计划

- Round 3: 半自动抓取 (requests + BeautifulSoup, 限速,尊重 robots.txt);30 天陈旧度告警。
- Round 4: eBay Buy API / Amazon PA-API 自动发现 (V1)。
- Round 5: PWA / 移动端优化;Notion / Apple Notes 导出。