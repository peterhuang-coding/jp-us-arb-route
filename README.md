# jp-us-arb-route — CN/JP 跨境代购决策引擎

## 东京潮流选品工作台（2026-09-11）

默认首页为今日买卖建议、东京地图日计划和常卖款 / 热点款观察池，当前对应 2026 年 10 月 2—7 日东京行程（trip 1）、10,000 元垫资预算。旧页面保留在 `/legacy.html`，其历史价格和规则不作为本次采购依据。

首页“经营工作流”进入 `/workflow.html`：用六个可点击步骤展示 **确认销路 → 算收购上限 → 定向找货 → 核验采购 → 上架卖出 → 回款复盘**。每步说明输入、产出、AI 可辅助的工作、现有工具、人工确认与通过条件，并链接到观察池、信息源、东京地图或持货建议。支持 `#demand` / `#ceiling` / `#source` / `#purchase` / `#sell` / `#review` 直接打开步骤。

工作流页只读已保存的 `/api/sourcing`、`/api/day-plans`，显示候选、当前销售依据、实购与整批结算数量，给出下一步提示。读取失败时显示未知并可重试；已归档候选、过期/未来销售依据、TEST/DEMO 实购分别按口径排除，零回款仍算已记录结算。它不增加自动采集、AI 调用或交易接口，也不读取其他页面尚未保存的修改。浏览器检查记录：`output/playwright/workflow-browser-check.log`。

- 商品卡直接展示准确商品、门店地址 / 商品页、国内销售渠道及缺失证据。
- 点击“核价与判断”录入实际含税买价、汇率、卖出净收入、其余成本、需求依据与取货条件；未知成本不能当作零。
- 近 72 小时的核价和销售依据、准确规格及履约条件齐全，且达到目标利润时，可加入采购单。总成本加建议额外售后预留 3,000 元不超过 10,000 元，才允许导出 CSV。
- 改规格、货源或销售渠道后需要重新确认；采购单上的过期 / 未知成本会阻止导出。计算和勾选不是自动下单，也不代表保证成交。
- 观察项与核价写入现有本地 SQLite 的 `sourcing_watchlist` 表；`web/sourcing-seed.json` 只在首次建表时导入。现有库存、行程和订单不迁移、不覆盖。
- 当前为人工核价工作台，盯潮是外部信息入口；未连接盯潮、得物、闲鱼的实时数据或自动监控。种子候选没有经过国内利润验证，鞋款网页核验时售罄。

新增接口：`GET/POST /api/sourcing`、`PUT /api/sourcing/{id}`。

验证：

```bash
python -m pytest tests/test_sourcing.py tests/test_web_api.py -q
node --test tests/sourcing-model.test.mjs
```

## 东京地图与日计划（2026-09-12）

主页“地图与日计划”将商品关联到东京采购点：地图点开商品核价，右侧显示日程与逐段导航。默认东京站往返、10:00—19:00，可改起终点坐标、日期、可用时段和当日额外费用。

- **今天该买什么**：比较最多 10 个勾选商品的整组件数组合，在共享预算与营业/发售时窗内优先净利润，再优先更早返回。同店普通商品合并一次到访；不自动拆小采购数量。
- **先排核价路线**：即使国内成交、库存或费用还未知，也可查看门店顺序；不生成未经验证的购买利润。
- **到店执行**：记录当日累计实购件数与全成本、预期销售净收入、全部售出后的实际结算净收入，或今天跳过。从当前一站继续时先改成实际离店时间，再保存重排。
- **全趟共用资金**：日计划与原采购 CSV 共享已购数量/已用资金；其他日期已填的额外费用也会占用资金。ROI 分母是投入成本，3,000 元预留不是费用，未售收入不自动补回可用现金。机酒另计。
- **持久化**：`GET /api/day-plans`、`PUT /api/day-plans/{date}` 保存到 SQLite `sourcing_day_plans`；同日更新需带读取时的 `updated_at`，过期版本返回 409，避免多标签覆盖。
- **交通边界**：当前交通耗时是“直线距离 × 1.35 / 步行 4 km/h、上调到 5 分钟”的粗估，可按 Google Maps 逐段查询结果校准。虚线仅为访问顺序，不是道路或地铁线路；尚无实时路网、列车时刻及排队数据。线上下单任务暂安排在起点完成。
- **数据边界**：店铺为地址附近参考点，入口、营业变更、库存和未来旅行日报价须复核；精确发售时间必须附来源。当前种子仍是核价候选，未连接自动抓价、抢购或下单。

地图采用本地 [Leaflet 1.9.4](https://leafletjs.com/download.html) 与正常可见视口的 [OSM 瓦片](https://operations.osmfoundation.org/policies/tiles/)，不预取、不下载离线地图，保留署名。地图断线时地址和 [Google Maps 逐段导航](https://developers.google.com/maps/documentation/urls/get-started) 仍可用。门店资料来源在地图弹窗及 `web/tokyo-places.json`。

```bash
python -m pytest tests/test_day_plans.py tests/test_sourcing.py tests/test_web_api.py -q
node --test tests/tokyo-planner.test.mjs tests/sourcing-model.test.mjs
```

## 今日买卖与竞拍上限（2026-09-12）

首页 `/#market-board` 先回答“有什么值得买 / 抢、什么建议卖”，决定参与后再看东京日计划。

- **买入判断**：普通商品、竞拍和发售一起比较，显示具体平台链接、准确规格、最高采购 / 出价上限、预期净利和理由。每条按全趟尚未买到的目标件数独立判断，购齐后停止推荐；组合采购仍受日计划总预算限制。
- **竞拍**：录入当前含税竞价、最低加价、另收买方费率与固定费、带时区的核价及截止时间。按下一次最低出价加费用估算采购成本；最高含税出价先扣除这些费用，不把当前竞价当成成交价。费用未知、超过 15 分钟未核价、已截止或出价未达到目标利润时不能推荐参与。每条拍卖按一个标的记录；平台延时和实际加价规则需自行更新。发售 / 补货须附官方时间和来源。
- **卖出判断**：只读取日计划里实际购入且未整批结算的批次，保存货号、配色、尺码、渠道与成本快照。当前同规格的销售依据在 72 小时内且费用已核实，保守净收入达到所设利润目标，才提示可考虑卖出。亏损时提示判断止损线；记录整批结算后移出待售。旧 inventory 不自动并入，历史 TEST / DEMO 条目不作为实际持货。
- **一致性**：看板、日程、观察池与 CSV 共用报价和剩余数量；拍卖上限输出明确标作含税出价，另收拍卖费另计。卖出以批次实际成本计算；保存待完成或失败时不会根据未核账记录建议卖出。
- **数据现状**：没有自动爬取、自动竞价或自动上架。Yahoo! 拍卖、mita 发售、SNKRDUNK 是外部查询入口。首页的 KEEN × DOE 排除案例来自 [mita 官方店头抽签公告](https://blog.mita-sneakers.co.jp/%E3%80%90%E5%BA%97%E9%A0%AD%E6%8A%BD%E9%81%B8%E8%B2%A9%E5%A3%B2%E5%91%8A%E7%9F%A5%E3%80%91-249-39836.html)，2026-09-12 人工核验；日本居住资格、9 月 17—21 日取货及转售限制与本次需求不匹配，未加入采购池。现有三个候选仍未核齐盈利证据。

```bash
python -m pytest tests/test_day_plans.py tests/test_sourcing.py tests/test_web_api.py -q
node --test tests/market-decisions.test.mjs tests/tokyo-planner.test.mjs tests/sourcing-model.test.mjs
```

## 经营研究与当前缺口

[AI 辅助转售的切入点](docs/research/2026-09-12-ai-resale-strategy.md) 整理了平台官方资料、卖家案例和六个 GitHub 项目的实际能力，说明当前应优先验证销售依据、准确规格、完整成本与回款，再定向监测货源。另附 [项目差距审计](docs/research/2026-09-12-project-gap-audit.md) 和 [GitHub 工具核验](docs/research/2026-09-12-github-resale-evidence.md)。

现有软件功能与测试不代表已有盈利交易。研究建议的少量经营试验尚未执行；实时行情摄入、真实订单与售后回款仍待验证。

## v3.5 启动

```bash
cd /Volumes/SanDisk2TB/jp-us-arb-route
uvicorn arb.web_api:app --host 127.0.0.1 --port 8765
open http://127.0.0.1:8765/
```

## v3.5 新 API

| Endpoint | Method | 说明 |
|---|---|---|
| `/api/inventory` | GET/POST | 库存 CRUD |
| `/api/inventory/{id}` | PATCH/DELETE | 单项编辑 |
| `/api/inventory/summary` | GET | 按 location 聚合 |
| `/api/orders` | GET | 全部/待处理 订单 |
| `/api/orders/{sku}` | POST | 设置状态 |
| `/api/trips` | GET/POST | 行程 CRUD |
| `/api/trips/{id}` | GET/PATCH/DELETE | 单行程 |
| `/api/trips/{id}/items` | POST | 加 item |
| `/api/quota` | GET | ¥5,000 额度汇总 |
| `/api/quota-window` | POST | 记录入境额度 |
| `/api/alerts` | GET | 价格报警 |

## 旧版 SPA 区域（`/legacy.html`）

1. **simple-section**:今日买什么(看 / 拆 / 不买)
2. **inventory-section**:库存管理(哥们仓 + 在途 + 已上架)
3. **trip-section**:行程规划(大阪 / 东京 / 京都)
