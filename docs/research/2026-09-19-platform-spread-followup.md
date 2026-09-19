# 平台价差续查：先核 Kayano 14 与 2002R 同款不同码

研究日期：2026-09-19，北京时间；公开商品库存于 23:07 直接读取。方向：国内得物买入 → StockX 中国卖家出售；公开海外零售商作为补充货源。用户本次明确要求使用 Coding Plan 继续找平台差价。本轮是即时研究，不代表选择了新的夜班卡或启动监控。

**结论：尚无可执行的盈利组合。** 保留 2 个款号、3 个规格作为下一次核价重点；新增排除了二手、已售出、实时缺货和近似款误配等货源。旧的 17 款报告没有取得新的得物同码采购价，不能把本轮重算包装成新行情。

## 最值得补齐的三条规格

| 核价顺序 | 货号、配色、尺码 | 历史 StockX Sell Now（美元） | 情景保本总成本（元） | 卖价跌 10% 后仍留 150 元的总成本上限（元） |
|---|---|---:|---:|---:|
| 1 | ASICS GEL-KAYANO 14，1201A019-108，Cream/Black，US 男 9.5 | 250 | 1,326.60 | 1,029.20 |
| 2 | NB 2002R，M2002RDA，Rain Cloud/Grey，US 男 11.5 | 151 | 742.90 | 503.87 |
| 对照 | 同款 M2002RDA，US 男 9.5 | 109 | 495.26 | 281.00 |

这些金额是**历史报价下的总成本预算，不是已找到的采购价格或利润**。历史价格在 9/18 观察时已滞后约 5—7 天；9/19 检索仍见 11.5 的 151 美元旧索引，未取得新结算页。其余数值明确沿用[上轮来源](2026-09-18-dewu-stockx-sku-screen.md)，不改写为今天现价。所有尺码均保留来源的 US 男码，不推定国内码。

原始页面：[Kayano 14 US 9.5](https://stockx.com/es-us/asics-gel-kayano-14-cream-black-metallic-plum?size=9.5)、[2002R US 11.5](https://stockx.com/new-balance-m2002-protection-pack-rain-cloud?size=11.5)、[2002R US 9.5](https://stockx.com/new-balance-m2002-protection-pack-rain-cloud?size=9.5)。Sell Now 保留平台标签，未读取独立买单簿，不能称为已验证的最高买单。

选择理由：Kayano 14 的历史卖价允许较高采购成本，值得先核；2002R 两码的历史卖价相差 42 美元，同费率情景净额相差 247.63 元，适合检查国内同款尺码差价能否留下空间。这不证明大码更好卖。国内 530 元的旧识货线索未注明尺码，不与任一码直接配对。

## 本轮新增核验的货源

| 货源 | 页面信息与观察口径 | 判定 |
|---|---|---|
| [Poshmark Kayano 14，US 9.5](https://poshmark.com/listing/ASICS-GelKayano-14-Cream-Black-Silver-Sneakers-1201A019108-Mens-95-6a9c9512f086edc09c5cb796) | 索引上周抓取；125 美元，Condition 为 Good | 二手，不匹配本研究的全新鞋渠道；125→250 不是有效价差 |
| [Grailed 同款，US 9.5](https://www.grailed.com/listings/85040486-asics-asics-gel-kayano-14-plum-cream-black-1201a019-108-men-s) | 索引三个月前抓取；Sold Price 109 美元，明确已售出 | 历史成交，不是当前可买货源 |
| [SoleSavy M2002RDA](https://store.solesavy.com/products/new-balance-2002rd-raincloud-grey-m2002rda) | 页面索引标 144.99 USD、Sold out；9/19 23:07 公开商品 JSON 返回 HTTP 200，12 个规格全部 available=false | 实时缺货；也不能把标价与 StockX 历史卖价之差当净利润 |
| [FEATURE GEL-1130，1201A256-118](https://feature.com/products/gel-1130-white-cloud-grey-asics?variant=40180774305863) | 9/19 23:07 公开商品 JSON 返回 HTTP 200，18 个规格全部 available=false | 搜索里出现尺码菜单或 INSTOCK 文字不足以证明有货；本次按实时规格状态排除 |
| [SNS M2002RDA](https://www.sneakersnstuff.com/en-gb/products/new-balance-2002r-m2002rda) | 上周索引显示英国站 £120；不能确认 11.5 有货。美区公开 JSON URL 返回 404 | 尺码库存、地区结算和落地费用未知，不进入采购组合 |
| [DSMNY Kayano 14 Black/Cream](https://shop-us.doverstreetmarket.com/products/asics-gel-kayano-14-blkcrm-1203a537-002-aw26) | 上周索引显示 165 USD，货号实际是 1203A537-002 | 与目标 1201A019-108 不同；近似配色不能匹配 |

公开结构化来源：[SoleSavy 商品 JSON](https://store.solesavy.com/products/new-balance-2002rd-raincloud-grey-m2002rda.js)、[FEATURE 商品 JSON](https://feature.com/products/gel-1130-white-cloud-grey-asics.js)。保存了观察时刻、货号、规格和库存状态；没有读取账户或购物车。JSON 未给出币种的字段不单独转换成金额。本次缺货只说明观察时点的网店状态。

## 两个新增款号：有市场线索，未形成价差

| 款号 | 9/19 检索获得的公开索引 | 尚缺什么 |
|---|---|---|
| [ASICS GEL-1130 White/Cloud Grey，1201A256-118](https://stockx.com/asics-gel-1130-white-cloud-grey) | 上周抓取，Size=All：Sell Now 94 美元、Buy Now 79 美元；全尺码近三个月 2,176 笔 | All 两端可能对应不同尺码，不能用 79→94 算套利。FEATURE 已缺货；仍缺同码采购价和中国卖家净回款 |
| [NB 9060 Rain Cloud/Castlerock，U9060GRY](https://stockx.com/new-balance-9060-rain-cloud-grey) | 上周抓取，Size=All：Sell Now 113 美元、Buy Now 140 美元；全尺码近三个月 1,190 笔 | 没有同码报价及国内到手成本。页面末次成交与溢价字段不一致，不据此估值 |

这两款只是款号层面的待核线索，不挤占前三条规格的核价顺序。以上销量不能证明任何目标尺码的出货速度，也不是新增买家订单。

## 可复算口径

9/19 重新核验的官方规则：Verified Marketplace 新卖家基础交易费 9% 加支付处理费 3%；中国单件发货列示基础估计 20 美元；银行转账可能另扣约 2 美元。实际订单运费会变，2 美元也不是所有回款方式固定收取。来源：[卖家费用](https://stockx.com/help/articles/what-are-stockxs-fees-for-sellers)、[发货费用](https://stockx.com/help/articles/How-much-does-shipping-cost-for-sellers)、[回款费用及汇率](https://stockx.com/help/articles/what-fees-and-currencies-apply-to-seller-payouts)。没有将部分卖家开放的 Listings/Live 零费率套到本研究。

为方便比较，本轮汇率**仅用假设 6.70 元/美元**，不是当日银行牌价或用户回款汇率。B 为上述历史 Sell Now，C 为采购到完成履约的其余全部成本，包括购买款、未在结算扣过的运费/税费/包材等。

```text
情景净回款 N = (B × (1 − 0.09 − 0.03) − 20 − 2) × 6.70
情景净利润 = N − C
压力情景总成本上限 T = (B × 0.90 × 0.88 − 22) × 6.70 − 150
实际可买鞋价上限 = T − 其余未计入采购价的成本
```

10% 回撤、150 元利润是研究情景，不是用户已批准的经营政策。真实净回款取得后直接与完整成本相减，不能再重复扣上述费用。所有未知成本需补齐后才有实际利润与 ROI。

完整 7 规格重算及待填字段见[CSV](2026-09-19-platform-spread-followup.csv)：所有真实采购价、真实回款和已确认利润均为空，purchase_eligible 均为 NO。本轮与上轮金额的微小差异来自演示汇率改为 6.70，**不是行情上涨**。

## Coding Plan 实际使用与审查

实际调用火山 Coding Plan 的 `doubao-seed-evolving` 两次，返回原生用量合计 5,072 tokens。只发送公开候选和任务约束，没有发送记忆、账户资料或凭据。

第一轮把 StockX 站内 ask−sell-now 差额当作跨平台利润空间，且费用有误，未采用。允许一次质量纠正后，定性筛选与同款尺码对照可用，但 7 行金额仍均未通过本地 Decimal 复算，因此金额全部弃用并本地重算；没有继续重试。此次证明调用通路可用，不证明研究更快、成本节省或套利盈利。模型负责整理与检查，金额必须由确定性公式完成。

## 当前限制与唯一下一步

浏览器连接本轮超时，StockX 商品详情直接读取出现内容过大/超时；未获取中国卖家登录结算页。普通公开来源继续查验，没有绕过访问验证。搜索结果中的过期、二手、其他款号和 All 报价均未拼成可交易价差。

**下一步只补前三条规格的两列：得物同款同码实际到手总价、StockX 中国账号同码实际净回款。** 两端要带观察时刻、库存/可售资格与履约条件；已保存的索引不能替代。补齐前不采购，也不报预期 ROI。
