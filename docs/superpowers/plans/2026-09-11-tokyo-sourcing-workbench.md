# 东京潮流选品工作台实施计划

> **For agentic workers:** 按 executing-plans 在当前任务内逐项执行。用户已批准上一轮的常卖款 / 热点款 / 东京采购清单方案；当前运行服务直接使用此 checkout，因此在这里实施和验证。

**Goal:** 首页直接展示准确商品、东京门店或网站、国内销售渠道、核价缺口及可执行的采购清单。

**Architecture:** 保留旧页面到 legacy.html，默认首页替换为独立工作台；FastAPI 新增 sourcing 路由，复用 SQLite 连接保存观察项。财务判断集中于可单测的前端纯函数。行程读取现有 trip 1，预算 10,000 元、建议预留 3,000 元。没有可靠库存、规格、需求及费用证据时不允许进入采购清单。

**Tech Stack:** 现有 FastAPI / SQLite，原生 HTML、CSS、JavaScript modules；pytest、Node test、Playwright CLI。

## 实施与验收

- [x] 新建 tests/test_sourcing.py：验证种子数据是核价候选、新增修改持久化、非法金额/URL 拒绝、未知 id 返回 404。
- [x] 新建 tests/sourcing-model.test.mjs：验证空值不能变成零成本、报价不等于成交、过期/未来证据不能入单、利润及采购上限、数量与总预算。
- [x] 新建 arb/sourcing.py 和 web/sourcing-seed.json；web_api.py 注册路由。准确商品只填有来源的采购信息，保留售罄和尺码待核状态；不捏造东京发售事件。
- [x] 新建 web/sourcing-model.mjs、web/sourcing.js、web/sourcing.css。首页采用雾蓝背景、深蓝字、钴蓝交互、琥珀待核状态；商品路线横向串起采购地→商品→国内销路。桌面主列表+右侧行程/待办，手机单列。
- [x] 新版 index.html 支持分组/搜索/添加商品/核价保存/采购清单/CSV 导出；错误与空态明确。所有编辑保存至本地服务数据库。盯潮入口明确是外部信息来源，未接入自动采集。
- [x] 原 index.html 保留到 legacy.html 并标明历史资料。旧版结构测试改读取 legacy.html，原 API 和数据保留。
- [x] 运行 pytest tests/test_sourcing.py tests/test_web_api.py -q 和 node --test tests/sourcing-model.test.mjs。
- [x] 重启已运行的 8765 服务加载 API；Playwright 验证桌面/手机、新增保存重载、热点空态、预算与导出，检查控制台；不污染真实清单（交互写入使用隔离测试数据库）。
- [x] 更新行动文档，核对实际页面及数据，报告已完成和数据缺口。

价格资料：2026-09-11 核查零售商商品页及门店公告。种子候选为 MEXICO 66 黑黑、GEL-1130 灰、Pokémon fit 皮卡丘；前两款网页标售罄，作为补货观察样本，不是买入推荐。热点池初始为空，等待具体发售/补货线索。

## 验证结果

- 38 项相关 pytest 与 9 项 Node 测试通过。pytest 的两条 startup on_event 弃用提示来自既有服务写法。
- 浏览器验证：常卖/热点筛选、货号搜索、新增与搁置、核价保存后重载、有效清单导出、超预算禁用、规格变更重核、读取失败与恢复、390 px 手机及 1440 px 桌面。
- 独立审查发现并修复慢请求跨编辑会话关闭/写错弹窗的问题；浏览器用延迟成功与失败响应验证新草稿不被覆盖或关闭。
- 8765 服务已切换，trip 1 保持东京 10 月 2—7 日，正式数据为 3 条待核候选、0 条采购清单项，无测试报价。原数据库备份位于 data/db.sqlite.backup-20260911-sourcing。
- 自动采集未接入，买家和利润证据仍待补全。本轮仅实现已批准的手动选品/核价/清单工作台。
