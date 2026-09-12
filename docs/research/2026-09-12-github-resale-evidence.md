# GitHub 转售工具的能力与盈利证据核查

适用情境：2026 年 10 月 2—7 日东京采购，经营资金 10,000 CNY，回国以得物／闲鱼销售。访问日统一为 **2026-09-12**；提交时间以 GitHub 返回的 UTC 为准。以下为六个公开仓库的代表性核查，不是全网穷尽清单，也不把公开源码一律称为可商用开源软件。

## 判断

**本次最值得借用的是网页变化监控、证据保留和草稿生成；最值得自己积累的是准确规格、国内真实退出价格、完整成本和售后结算。** 六个仓库均未提供足以证明本次“东京买入→得物／闲鱼净回款”能够盈利的可复查成交闭环。此结论只针对已检查的实现和本次市场，不能推导为“自动化没有价值”或“市场没有机会”。

真正的采购判断至少需要四个彼此分开的事实：日本当时能买到的准确标的与全成本、国内同规格的近期成交／有效买家、此账户的卖出费用与履约条件、资金实际回收时间。页面出现新链接、AI 打出高分、生成一条上架文案，只覆盖其中很小一部分。

| 仓库 | 读到的实质能力 | 对本次最有用的部分 | 尚未解决的盈利瓶颈 | 建议 |
|---|---|---|---|---|
| changedetection.io | 页面／JSON 差异、价格／补货条件、历史快照、API、通知 | 少量官方发售页、门店公告、已确认商品页的变化提醒 | 不提供得物／闲鱼成交，不保证尺码库存、购买资格或净利 | 可作为通用监控层候选，先验证具体页面 |
| MediaCrawler | 七类中文社媒的帖子、评论、互动数据采集 | 热点和内容线索的方法参考 | 不是国内成交接口；当前许可限制商业用途 | 不直接接入经营系统 |
| ai-marketplace-monitor | Facebook 新挂牌搜索、条件筛选、LLM 评分、通知 | 去重、变更复评、可解释筛选模式 | 评分主要依据卖家挂牌内容；非得物／闲鱼，也非 sold comps | 参考流程，不搬运整套平台适配 |
| resell-agent | 图片属性提取、eBay 对照价格、草稿、eBay 发布接口 | 属性不确定性和人工审核草稿 | sold API 不默认可用；回退值是挂牌价折扣；未发现许可证 | 参考设计，不作为采购定价引擎 |
| Autoselll | 图片识别／文案／估价界面与发布队列 | 展示“草稿→审核”的交互样例 | FINN 定价实际走 AI 估计；FINN／Facebook 发布为随机模拟 | 视作原型，不作为可交易产品引入 |
| psa-auction-agent | eBay 卡牌竞拍筛选、LLM 市场研究、确定性出价门槛 | 证据异常拦截、上限和重复出价记录 | 默认样例数据；真实数据／竞价有权限；利润口径不含本次跨境履约成本 | 参考门槛，不接入自动竞价 |

本表的“建议”是分析判断；具体事实与限制见下文。没有用 Stars 排序，也没有把仓库提交活跃度视为投资回报证明。

## 1. changedetection.io：通用监控层最接近可复用

**事实。** 支持 HTTP 和浏览器获取、CSS／XPath／JSONPath／jq 过滤、条件提醒，以及单商品页的补货／价格变化监控。REST API 管理 watch、历史和通知；返回字段包含 URL、检查时间、变化时间、抓取错误、历史数量等，适合保留“什么时候看到了什么”。通知使用现成的 Apprise 生态。浏览器步骤需要浏览器后端，AI 功能另需相应模型服务；这些能力不会替用户取得目标站点的访问权限。[README](https://github.com/dgtlmoon/changedetection.io/blob/900a77e8285ac8c4241d5ad2acabaf01657404eb/README.md)、[官方 API 文档](https://changedetection.io/docs/api_v1/index.html)

**托管与自托管边界。** README 的 AI 规则／摘要段附有“自 2026 年 6 月在订阅／托管服务提供”的注记，同时描述可连接本地模型。固定提交虽已出现 LLM 源码与 API 字段，这些文字仍不足以证明任一稳定版自托管安装已经具备相同功能；本轮没有安装验证。此处推荐复用的是普通页面／价格／补货监控，不把托管 AI 宣传列为已验证的开源自托管能力；也不将该注记扩写成原文未明说的“仅托管可用”。[对应 README 段落](https://github.com/dgtlmoon/changedetection.io/blob/900a77e8285ac8c4241d5ad2acabaf01657404eb/README.md#ai-powered-website-change-detection--smart-alerts-and-plain-language-summaries)

**维护与许可。** GitHub 元数据为未归档；所检主分支最新提交 `900a77e`，2026-09-12 14:04:39 UTC。`LICENSE` 为 Apache-2.0，但同一仓库另有 `COMMERCIAL_LICENCE.md`，针对向第三方提供托管／转售软件服务列出商业许可要求。不能在采购报告中仅写“Apache，所有商业形态都无条件可用”；本次自己监控商品页与向客户出售监控 SaaS 是不同使用情境。本文只记录文件内容，不裁定两文件的法律关系。[主许可证](https://github.com/dgtlmoon/changedetection.io/blob/900a77e8285ac8c4241d5ad2acabaf01657404eb/LICENSE)、[商业许可文件](https://github.com/dgtlmoon/changedetection.io/blob/900a77e8285ac8c4241d5ad2acabaf01657404eb/COMMERCIAL_LICENCE.md)

**推论。** 这是最适合避免重复开发的部分：定时检查、过滤、diff、失败提醒、webhook。可以给官方发售页、门店补货公告、已确认准确货号的商品页建少量监控，再把“新增候选＋原文证据”传给现有工作台。

**限制。** 页面的总价或“有库存”可能对应别的尺码；新品公告不等于游客有资格购买；拍卖当前价不等于成交价或含税含佣总成本。监控输出必须先成为待核证据，不能直接把采购状态改成“值得买”。本轮没有部署或实测任何日本页面，无法给出漏报率、延迟或稳定性保证。

## 2. MediaCrawler：社媒线索，不是得物／闲鱼成交底座

**事实。** 主仓库明确支持小红书、抖音、快手、B 站、微博、贴吧、知乎，使用浏览器登录态进行采集；支持 CSV、JSON、JSONL、Excel、SQLite、MySQL 等保存方式。检查到的数据库模型是帖子／视频／评论：例如小红书包括笔记 ID、标题、正文、点赞、收藏、评论数量、时间及 URL。支持矩阵没有得物、闲鱼、日本 Mercari 或 Yahoo! 拍卖；这些互动字段也不是订单成交价。[README](https://github.com/NanmiCoder/MediaCrawler/blob/d6f7c5bb906b6dac40ddf343ef9e26438a3de092/README.md)、[数据库模型](https://github.com/NanmiCoder/MediaCrawler/blob/d6f7c5bb906b6dac40ddf343ef9e26438a3de092/database/models.py)

**维护与许可。** 未归档；最新主分支提交 `d6f7c5b`，2026-08-14 08:18:52 UTC，提交内容为 README 更新，不能把这个日期当作所有采集器当日可用的证据。当前 `LICENSE` 是 **Non-Commercial Learning License 1.1**，限定非商业学习研究；商业用途需版权所有者书面同意。GitHub 的许可标识为 `Other/NOASSERTION`，不是 MIT／Apache。故本次营利选品系统不能默认直接复用。[LICENSE](https://github.com/NanmiCoder/MediaCrawler/blob/d6f7c5bb906b6dac40ddf343ef9e26438a3de092/LICENSE)

**推论与限制。** 社媒内容可帮助发现某个联名、品牌或配色，但热度不能估算指定尺码的净回款或售出概率。项目当前的缺口是国内可验证退出需求，接入大量点赞评论会增加信号数量，不会自动填上这个缺口。未运行采集、未登录目标平台、未评估各平台实时成功率。

## 3. BoPeng/ai-marketplace-monitor：能筛挂牌，不能证明转售收益

**事实。** 面向 Facebook Marketplace，支持关键词、价格和地点筛选，使用浏览器搜索，配合 OpenAI／Anthropic／DeepSeek／Ollama 等模型，向通知渠道输出评分与原因。`Listing` 数据结构包含 `id/title/image/price/post_url/location/seller/condition/description`；AI 的输入是用户条件和该挂牌的标题、价格、地点、描述，默认输出 1—5 的匹配／好价评分。检查到的这条评分调用未取得独立的成交对照数据库。[README](https://github.com/BoPeng/ai-marketplace-monitor/blob/4d18385dc6337937dae4abcb2069033b16c4a95b/README.md)、[Listing 字段](https://github.com/BoPeng/ai-marketplace-monitor/blob/4d18385dc6337937dae4abcb2069033b16c4a95b/src/ai_marketplace_monitor/listing.py)、[AI 提示与调用](https://github.com/BoPeng/ai-marketplace-monitor/blob/4d18385dc6337937dae4abcb2069033b16c4a95b/src/ai_marketplace_monitor/ai.py)

**接入、维护与许可。** 浏览器／Facebook 会话、页面语言和布局都会影响读取，AI 与通知服务按所选方式提供凭据；README 也说明自动采集需要符合 Facebook 的授权要求。仓库未归档，AGPL-3.0；最新主分支提交 `4d18385`，2026-08-31 17:17:51 UTC，为 Docker 登录 Action 依赖升级；最近 push 为 2026-09-01。存在持续维护迹象，但未在本机验证目标平台实际读取。[许可证](https://github.com/BoPeng/ai-marketplace-monitor/blob/4d18385dc6337937dae4abcb2069033b16c4a95b/LICENSE)

**推论。** 值得参考的是候选去重、对变化内容复评、筛选原因随通知输出。`Great deal` 可能只是“价格低于用户预算且描述符合要求”，不能升级为国内有买家、利润为正或低假货风险。将 Facebook 解析器移植到闲鱼不是改一个域名；这仍需要新的、实际可用的数据接入。

## 4. wuisabel-gif/resell-agent：结构化草稿有用，定价回退不宜采购

**事实。** 从照片提取品牌、产品名、尺码、颜色、材质、成色、瑕疵，并标记品牌是否推测；提示要求尺码无标签时返回空值。对照记录保留 `title/price/currency/condition/url/source`，生成价格建议、各来源统计和上架草稿。eBay 发布路径使用卖家 API，仍需开发者凭据、卖家授权及账户配置；其他平台浏览器流程需要另外配置。[属性提取](https://github.com/wuisabel-gif/resell-agent/blob/8593a9b2a19746f8c61dd2f8dca9708067d6d3f3/src/brain/extract.ts)、[类型定义](https://github.com/wuisabel-gif/resell-agent/blob/8593a9b2a19746f8c61dd2f8dca9708067d6d3f3/src/types.ts)、[README](https://github.com/wuisabel-gif/resell-agent/blob/8593a9b2a19746f8c61dd2f8dca9708067d6d3f3/README.md)

**关键代码事实。** `getSoldComps` 默认返回空数组，需 `EBAY_INSIGHTS` 及 Marketplace Insights 权限才请求成交数据；活动挂牌搜索固定 `EBAY_US`。`priceFromComps` 至少有 3 条 sold 样本才使用其统计，否则取 active 样本截尾中位数乘 **0.85**。这是程序写死的折扣假设，不是实证估算的成交折扣，更不是得物／闲鱼的可售净收入。匹配查询主要拼接品牌、标题关键词和尺码；这不构成严格的货号＋配色＋尺码身份校验。[eBay 接口代码](https://github.com/wuisabel-gif/resell-agent/blob/8593a9b2a19746f8c61dd2f8dca9708067d6d3f3/src/ebay/browse.ts)、[定价代码](https://github.com/wuisabel-gif/resell-agent/blob/8593a9b2a19746f8c61dd2f8dca9708067d6d3f3/src/brain/price.ts)

**维护与许可。** 未归档；最新主分支提交 `8593a9b`，2026-09-09 06:35:10 UTC。GitHub API 的 `license` 为 null，完整文件树未发现 LICENSE／COPYING 等授权文件；此处只确认“未发现”，不能据此给予复用授权。GitHub 官方说明，没有许可时默认版权适用，公开仓库不自动授予复制／分发／派生的开放许可。[GitHub 许可说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)

**推论。** 拍实物与标签、提取属性、显示不确定字段、人工审稿，很适合少量库存上架。由于本次只有少量货物，直接用现有模型生成可审核草稿可能比接一整套新站点更合算；具体节省时间须测量，不能宣称已经证实 ROI。未取得该仓库代码商用许可，也未测试其发布或识别准确率。

## 5. Codehagen/Autoselll：README 的完整流程，代码里仍有模拟段

**事实。** README 宣称照片识别、挪威市场价格核验、挪威语描述和平台发布准备。但 `lib/finn-api.ts` 的 `analyzePrices` 实际直接调用 GPT 估价，先抓 FINN 再统计的分支整段注释为未来工作。`lib/publishing-queue.ts` 的 FINN／Facebook 发布方法用随机数生成成功／失败及模拟 ID，随后队列可以被标成完成。[README](https://github.com/Codehagen/Autoselll/blob/437f24781496edd204259b642df1cfe79e23a299/README.md)、[定价实现](https://github.com/Codehagen/Autoselll/blob/437f24781496edd204259b642df1cfe79e23a299/lib/finn-api.ts#L497)、[发布实现](https://github.com/Codehagen/Autoselll/blob/437f24781496edd204259b642df1cfe79e23a299/lib/publishing-queue.ts#L110)

**维护与许可。** 仓库未归档、AGPL-3.0。创建日与所检主分支最后提交都为 2025-08-05，最后提交 `437f247` 的时间为 17:35:14 UTC；截至访问日，主分支没有更晚提交。未归档不等于目前仍持续维护。[许可证](https://github.com/Codehagen/Autoselll/blob/437f24781496edd204259b642df1cfe79e23a299/LICENSE.md)

**推论与限制。** 可以研究界面和草稿流程，但不能把“发布成功”截图视为真实订单或真实平台刊登证据，也不能将 GPT 估价当作 FINN 成交样本。其市场、货币、语言也与东京→国内销售不匹配。没有运行或安装该仓库，判断仅针对以上已读代码路径。

## 6. YaroslawBagriy/psa-auction-agent：有出价门槛，仍不是跨境利润系统

**事实。** 这是专门扫描 PSA 官方 eBay 卖家卡牌拍卖的 Python MVP。默认使用样例 eBay 数据；启用 live 模式才通过 Browse API 获取拍卖。市场研究默认由 OpenAI web search 产生结构化市场摘要，另有可选 Marketplace Insights 适配器。输出包含拍卖 ID／当前价／截止时间、对照数量、成交价数组、估值、推荐最高价、理由和来源 URL。自动竞价使用官方 Offer API 且受账号授权与显式配置控制；默认给人工行动建议。[README](https://github.com/YaroslawBagriy/psa-auction-agent/blob/bdacb3810a6122f546c4669cad7e5754e7c9163a/README.md)、[市场模型](https://github.com/YaroslawBagriy/psa-auction-agent/blob/bdacb3810a6122f546c4669cad7e5754e7c9163a/app/models/market.py)

**有价值的代码。** 确定性层拒绝已结束拍卖、卖家不符、估值／上限缺失、低置信度、重复出价和异常成交价格；会将估值压到较低成交样本所支持的范围。将“LLM 提议”放在硬性门槛之前，这个分工值得借鉴。[出价门槛](https://github.com/YaroslawBagriy/psa-auction-agent/blob/bdacb3810a6122f546c4669cad7e5754e7c9163a/app/services/bid_guardrails.py)、[成交样本检查](https://github.com/YaroslawBagriy/psa-auction-agent/blob/bdacb3810a6122f546c4669cad7e5754e7c9163a/app/services/market_sanity.py)

**不可照搬的口径。** `expected_margin` 是估值减出价上限，并未扣本次所需的跨境运输、国内渠道费、税费、退货和资金占用；README 明说运输费因“卡留在 PSA Vault”而不计。官方适配器的 `sell_through_rate` 是 sold 数量除以当前 active 数量；它是两个数量的比值，可能大于 1，不能称作“这件货在若干天内售出的概率”。LLM 市场输出只是汇总价格数组、数量与 URL，其模式本身不保证逐条成交记录真实、同版本或处在一致时间窗。[接口及比值计算](https://github.com/YaroslawBagriy/psa-auction-agent/blob/bdacb3810a6122f546c4669cad7e5754e7c9163a/app/clients/ebay_market.py)、[LLM 输出模型](https://github.com/YaroslawBagriy/psa-auction-agent/blob/bdacb3810a6122f546c4669cad7e5754e7c9163a/app/models/market.py)

**维护与许可。** 未归档；最新主分支提交 `bdacb38`，2026-05-04 19:54:19 UTC。GitHub API `license` 为 null，文件树没有授权文件。其测试文件与样例输出存在，但本轮未执行测试、未核对样例中的真实成交、未验证生产竞价权限，因此不报告“已跑通真实盈利”。

## API 权限是独立门槛

1. **eBay sold 数据不是注册普通开发者账户就能拿。** 官方市场支持文档当前明确写 Marketplace Insights 受限，且暂不向新用户开放。以上仓库 README 所说的“获批后打开开关”，只能当条件分支，不能当本次随时可得数据。官方接口文档的访问还重定向到开发者登录页。[官方市场支持](https://developer.ebay.com/api-docs/buy/static/ref-marketplace-supported.html)、[Marketplace Insights 文档入口](https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html)
2. **旧的 Finding API 方案不能照抄。** eBay 官方退役表列出 Finding API 全部接口于 2025-02-04 停用，2025 年一季度公告亦确认已经停用；旧资料中计划日期曾为 2 月 5 日，应以当前状态表为准。Browse 搜索可以查询挂牌，不因此获得原有成交查询能力。[官方退役表](https://developer.ebay.com/develop/get-started/api-deprecation-status)、[2025 Q1 公告](https://developer.ebay.com/updates/newsletter/q1_2025)
3. **生产访问与市场适用性分别核验。** eBay 官方要求根据 API 与业务情境申请生产权限，并说明批准不保证。eBay 美国挂牌／成交、Amazon ASIN／卖家数据，即使代码已经能读，也不能外推成当前账户拥有得物／闲鱼的数据权限或国内销售价格。本轮六个样本没有展示后两者的有效接入。[官方 Buy API 要求](https://developer.ebay.com/api-docs/buy/static/buy-requirements.html)

## 哪些通用层不要重复开发

**建议。** 网页轮询、浏览器渲染、差异比对、通知通道、失败重试和历史快照使用成熟组件；图片 OCR／翻译／初稿使用已有模型能力。第一步先选少量能正常访问的官方／商品页验证输入质量，避免在尚无销售证据时同时养多个平台爬虫和常驻 AI 服务。

尽量用独立 API／文件输入接到现有 `sourcing` 判断层，保留原始链接、观察时间、截图或文本、来源类型和错误状态。外部采集器只能新增“待核候选”或“旧证据已变化”；不能直接确认规格、确认需求、填零费用，或者把 AI 估值写成实际结算。

对于只有几十条候选的首趟采购，准确 SKU 匹配优先采用货号／JAN／型号、配色、尺码体系、成色、包装／配件组成的明确字段。照片相似度和关键词分数用于发现可能的同款，最终身份必须能回到标签或商品页核对。没有证据表明当前体量需要自建向量搜索或训练定价模型。

## 必须自己保有的交易回填层

这是经营反馈与可审计记录的要求，不要求重新造数据库或平台；沿用当前 SQLite／工作台即可。外部工具的“estimated profit”不能替代它。

| 记录 | 最小字段 | 防止的误判 |
|---|---|---|
| 商品身份 | 货号／JAN、品牌型号、配色、尺码与体系、成色、件数、包装配件、核对来源 | 看起来相似却不是同款同码 |
| 观察证据 | 来源平台、URL、观测时间、证据类型、原始价格／币种、卖家／商品 ID、有效时间窗 | 挂牌当成交，旧价当现价，AI 总结当原文 |
| 日本买入 | 实购时间数量、含税价、拍卖另收费、汇率、支付／配送／额外交通成本、收据、批次 ID | 当前竞价当最终全成本、额外费用漏计 |
| 国内销售 | 同规格依据、卖出渠道、可复查实际订单、议价成交额、平台／鉴定／运费、退货及其他扣款 | 把可售展示价当卖家净到账 |
| 资金与库存 | 实付、未售数量、冻结与预留、预计回款、实际到账日期与金额、退款／损失 | 未售预期利润提前变成可花现金 |
| 决策回填 | 买／不买理由、最高采购价、后来是否售出、持有天数、净利润、识别／费用／需求误差原因 | 永远只统计“发现机会”，不统计错误与资金占用 |

建议分别计算已售毛利、扣齐费用后的实际净利、每批持有天数和实际回款；未售库存列出成本与不同退出报价，避免把模型估值计为收入。样本很少时先逐笔复盘误差，不对几次成功计算稳定的“成功率”。

**唯一优先下一步：** 选择一个准确同款同码标的，取得当前能复查的日本全成本和国内净退出依据，填入现有工作台并人工核算。只有这条链成立后，再用监控组件把同类页面变更更快地送进来。本轮未新建监控、未安装仓库、未运行陌生代码、未下单／竞价／上架，也未写入生产数据库。

## 核查方法与来源索引

本轮读取原仓库 README、选定实现文件、许可文件和 GitHub 公共 API 的仓库／提交／完整文件树；只执行自写的只读下载与文本检查。没有执行仓库脚本，没有以演示截图或测试文件存在推断实际运行成功。源代码行为属于静态核查；市场可用性、数据访问许可、抓取稳定性、模型准确率和真实 ROI 均未经过生产测试。

| 项目 | 固定提交 | 主分支最后提交（UTC） | 查询到的归档状态／许可 | 元数据原始入口 |
|---|---|---|---|---|
| dgtlmoon/changedetection.io | `900a77e8285ac8c4241d5ad2acabaf01657404eb` | 2026-09-12 14:04:39 | 未归档；Apache-2.0，另有商业托管许可文件 | [仓库](https://api.github.com/repos/dgtlmoon/changedetection.io)、[提交](https://api.github.com/repos/dgtlmoon/changedetection.io/commits/900a77e8285ac8c4241d5ad2acabaf01657404eb) |
| NanmiCoder/MediaCrawler | `d6f7c5bb906b6dac40ddf343ef9e26438a3de092` | 2026-08-14 08:18:52 | 未归档；Non-Commercial Learning License 1.1 | [仓库](https://api.github.com/repos/NanmiCoder/MediaCrawler)、[提交](https://api.github.com/repos/NanmiCoder/MediaCrawler/commits/d6f7c5bb906b6dac40ddf343ef9e26438a3de092) |
| BoPeng/ai-marketplace-monitor | `4d18385dc6337937dae4abcb2069033b16c4a95b` | 2026-08-31 17:17:51 | 未归档；AGPL-3.0 | [仓库](https://api.github.com/repos/BoPeng/ai-marketplace-monitor)、[提交](https://api.github.com/repos/BoPeng/ai-marketplace-monitor/commits/4d18385dc6337937dae4abcb2069033b16c4a95b) |
| wuisabel-gif/resell-agent | `8593a9b2a19746f8c61dd2f8dca9708067d6d3f3` | 2026-09-09 06:35:10 | 未归档；API 无许可标识且文件树未发现许可文件 | [仓库](https://api.github.com/repos/wuisabel-gif/resell-agent)、[提交](https://api.github.com/repos/wuisabel-gif/resell-agent/commits/8593a9b2a19746f8c61dd2f8dca9708067d6d3f3) |
| Codehagen/Autoselll | `437f24781496edd204259b642df1cfe79e23a299` | 2025-08-05 17:35:14 | 未归档；AGPL-3.0 | [仓库](https://api.github.com/repos/Codehagen/Autoselll)、[提交](https://api.github.com/repos/Codehagen/Autoselll/commits/437f24781496edd204259b642df1cfe79e23a299) |
| YaroslawBagriy/psa-auction-agent | `bdacb3810a6122f546c4669cad7e5754e7c9163a` | 2026-05-04 19:54:19 | 未归档；API 无许可标识且文件树未发现许可文件 | [仓库](https://api.github.com/repos/YaroslawBagriy/psa-auction-agent)、[提交](https://api.github.com/repos/YaroslawBagriy/psa-auction-agent/commits/bdacb3810a6122f546c4669cad7e5754e7c9163a) |

所有原文链接在各条事实附近；原文发布者为相应项目维护者、GitHub 或 eBay。平台和仓库内容今后可变，固定提交只用于复查本轮判断，不表示建议安装该提交。上述元数据和文件均于 2026-09-12 读取。
