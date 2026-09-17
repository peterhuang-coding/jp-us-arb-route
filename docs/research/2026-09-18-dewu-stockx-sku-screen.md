# 得物 → StockX：17 个货号的选品研究

研究日：2026-09-18，北京时间 00:13 起。路线是中国得物采购、国内收货检查、通过中国 StockX 卖家账户出售，按订单标签发往指定验货中心；最终买家不一定在美国。本轮是公开资料筛选，没有得到可执行的双边报价。

**先盯 NB 2002R 雨云 M2002RDA 和 ASICS K14 奶油黑 1201A019-108；1906R 两款做低成本对照。** XT-6 要等足够低的进货价；HOKA Tor 保留自用找货，不能因为喜欢它就加仓转卖。Panda、Samba 普款暂不值得优先投入核价时间。

这是研究优先级，不是已确认盈利的买入名单。17 个货号中，当前通过采购条件的为 **0**；原因是中国得物同码到手价和中国卖家账户净结算均未取得，不是已经证明 17 款都亏钱。

## 先看这七条规格

金额均为 **StockX 官方商品页的搜索索引**，不是 9 月 18 日实时报价。`Sell Now` 是索引中的卖出入口价格，未独立读到订单簿或买家数量。Ask 是购买/挂牌侧价格，不能当卖家立即到手金额。尺码均按 US 男码记录，得物端须用对应品牌鞋盒尺码再匹配。

|核价次序|商品 / 精确货号|US 男码|Sell Now / Ask / Last Sale，USD|全码近三个月成交数线索|判断|
|---|---|---:|---|---:|---|
|1|[NB 2002R 雨云 M2002RDA](https://stockx.com/new-balance-m2002-protection-pack-rain-cloud?size=11.5)|11.5|151 / 194 / 202|3,014|有国内低价渠道线索，先核大码真实成本；大码溢价不是免费利润|
|1，同款对照|[NB 2002R 雨云 M2002RDA](https://stockx.com/new-balance-m2002-protection-pack-rain-cloud?size=9.5)|9.5|109 / 123 / 124|同一款，不重复计数|比 11.5 卖出价低 42 美元，不能用全码最低买价配大码卖价|
|2|[ASICS K14 奶油黑 1201A019-108](https://stockx.com/es-us/asics-gel-kayano-14-cream-black-metallic-plum?size=9.5)|9.5|250 / 350 / 290|227|单价较高，可容纳较多固定费用；挂牌与卖出入口差 100 美元，不能按 350 算收入|
|3|[NB 1906R 白银金 M1906RA](https://stockx.com/new-balance-1906r-white-gold?size=9.5)|9.5|116 / 141 / 136|365|低采购成本样本；能否便宜到有余量比“热门”更重要|
|4|[NB 1906R 银海盐 M1906REE](https://stockx.com/new-balance-1906r-silver-metallic-sea-salt?size=9.5)|9.5|102 / 138 / 164|488|成交量线索较多，但可承受采购成本低于白银金|
|5|[Salomon XT-6 黑 L41086600](https://stockx.com/es-us/salomon-s-lab-xt-6-adv-triple-black?size=10.5)|10.5|130 / 185 / 150|702|只值得继续寻找大幅折扣，尚无得物同码价|
|6|[Salomon XT-6 白 L41252900](https://stockx.com/salomon-xt-6-white-lunar-rock?size=10.5)|10.5|126 / 155 / 155|736|与黑色作为同类对照，不凭全码销量决定买哪一码|

以上价格快照：奶油黑为搜索标注 **5 days ago**，银海盐为 **last week**，其余为 **6 days ago**。量为各型号页 **Last 3 Months、全部尺码合计**；不是表中所选码的销量，更不能据此预测几天售出。各数量来源、地区、抓取标签及其他候选见 [18 条规格记录 CSV](2026-09-18-dewu-stockx-sku-screen.csv)。型号数为 17，雨云额外一条尺码对照，因此有 18 行。

这些码是本轮找到完整索引字段的核查起点，不是已经筛出的最佳转售尺码。不能预设“大码在海外贵，所以大码一定最赚钱”。

## 把卖价换成能承受的采购成本

统一采用新卖家 Verified Marketplace 的 9% 交易费加 3% 支付处理费；中国单件基础运费按官网估算 USD20；另用 USD2/次作为银行转账费用情景。实际费用和可用回款方式以本人订单为准，不把另一销售模式的零手续费套进来。[卖家费率](https://stockx.com/help/articles/what-are-stockxs-fees-for-sellers)、[卖家运费](https://stockx.com/help/articles/How-much-does-shipping-cost-for-sellers)、[提现费用](https://stockx.com/help/articles/what-fees-and-currencies-apply-to-seller-payouts)。

参考汇率为中国银行 **2026/09/18 00:09:26 的美元现汇买入价 669.51 元/100 美元，即 6.6951**。这是外币收入换成人民币的参考口径，实际 StockX 支付服务商汇率可能不同。[中行外汇牌价](https://www.boc.cn/sourcedb/whpj/)。

令 B 为同码、本人账户可执行的美元卖价：

```text
基础费用后余额 N = (B × 0.88 − 20 − 2) × 6.6951
卖价下跌 10% 的情景余额 S = (B × 0.90 × 0.88 − 20 − 2) × 6.6951
希望剩余利润 150 元时，采购及其余成本合计预算 T = S − 150
```

**10% 跌价和 150 元目标是本轮分析假设，不是市场预测或用户已设定的经营规则。** 表内暂将索引 Sell Now 代入，只用于研究筛选；必须在本人卖家页重取 B 才能用于决策。没有用英国站 GBP 报价机械换汇填入中国卖家收益。

|规格|基础费用后余额 N|跌价 10% 后余额 S|再留 150 元利润的总成本预算 T|
|---|---:|---:|---:|
|雨云 US11.5|¥742.35|¥653.39|**¥503.39**|
|雨云 US9.5|¥494.90|¥430.68|**¥280.68**|
|K14 奶油黑 US9.5|¥1,325.63|¥1,178.34|**¥1,028.34**|
|1906R 白银金 US9.5|¥536.14|¥467.80|**¥317.80**|
|1906R 银海盐 US9.5|¥453.66|¥393.56|**¥243.56**|
|XT-6 黑 US10.5|¥618.63|¥542.04|**¥392.04**|
|XT-6 白 US10.5|¥595.06|¥520.83|**¥370.83**|

T 要同时容纳得物最终买价、国内收货及打包费用、额外汇兑/银行费用和适用税费等尚未列入模型的支出，**不是单独鞋款的最终最高买入价**。未知费用不能填零。已采用平台净结算预览时，不重复扣表内平台费和运费。

这张表给出实际筛选结论：如果得物雨云 US11.5 远高于 500 元，或者 1906RA 远高于 318 元，本模型下就不值得继续追；K14 奶油黑容许的成本空间相对更大。它们能否买到这些价格，仍未证实。没必要先铺几十个爬虫再解决这几个数。

**雨云的 530 元不能当套利证据。** [识货渠道汇总](https://m.shihuo.cn/page/supplierList/82765854?id=687268&sku_id=82765854)能看到货号 M2002RDA 和得物 530 元，但抓取标注 3 weeks ago，没有标明对应尺码。仅作假设：若 US11.5 真能以 530 元采购，基础情景剩余 212.35 元；卖价下跌 10% 后只剩 123.39 元，且两者仍未扣其余费用。这个假设尚且达不到上面的压力情景目标，更不能宣称“现在买就赚 200 多”。

普通低价款的固定成本负担也很明显：假设实际卖价只有 USD70，按同一基础模型剩 **¥265.13** 来覆盖采购和其余支出；此例不对应任何具体鞋码。海外“有人买”不等于从得物运过去有利润。

## 另外十一个货号的去留

前表包含六个不同货号；以下十一款合计构成 17 个货号的范围。这里“排除”指本轮不进入采购，不等于已证明必亏。

|商品与精确货号|全码近三个月成交数线索|处理与原因|
|---|---:|---|
|[Salomon XT-6 GTX 黑银 L47450600](https://stockx.com/salomon-xt-6-gore-tex-black-silver)|1,443|保留核价；US男8.5 仅见英国站 GBP104 Sell Now /121 Ask /123 Last，不能代替中国净结算；不要与 L45442900 混款|
|[Jordan 4 Military Blue 2024 FV5029-141](https://stockx.com/air-jordan-4-retro-military-blue-2024)|2,081|保留核价；US男11 仅英国站 GBP129/151/154，缺中国账户退出价与得物成本|
|[Jordan 1 Low OG Mocha CZ0790-102](https://stockx.com/en-gb/air-jordan-1-retro-low-og-mocha)|556|次级备选；US男11.5 英国索引抓取“2天前”与直接打开“1.4年前”冲突，报价不参与计算|
|[Nike AF1 白 CW2288-111](https://stockx.com/nike-air-force-1-low-white-07)|9,227|只作高成交量对照；US男8 报价抓取“上周”与“8个月前”冲突；页面还合并旧货号315122-111|
|[Nike Dunk Panda DD1391-100](https://stockx.com/nike-dunk-low-retro-white-black-2021)|2,527|降级；未取得目标码，低单价受固定费影响，不能用 All 的高 Sell Now 减低 Ask|
|[adidas Samba 白 B75806](https://stockx.com/adidas-samba-og-cloud-white-core-black)|3,217|降级；只有 All，且页面合并 BZ0057；识货得物400元没有同码配对|
|[adidas Samba 黑 B75807](https://stockx.com/adidas-samba-black-white-gum)|1,296|降级；只有 All，页面合并 BZ0058；需要证明对应普通男款，不套女款/其他版本|
|[ASICS GT-2160 白绿 1203A275-103](https://stockx.com/asics-gt-2160-white-shamrock-green)|100|降级；目标码无三价，成交量线索弱于前列样本|
|[ASICS K14 Triple White 1201A019-100](https://stockx.com/asics-gel-kayano-14-triple-white)|未知，页面为 --|排除本轮；无同码价、没有有效销量统计；未知不写成零|
|[HOKA Tor Ultra Lo 黑 1130310-BBLC](https://stockx.com/hoka-one-one-tor-ultra-lo-black-all-gender)|17|保留自用；用户 US男11 无有效同码三价，不拿13码报价替代；型号销量不足以支持集中备货|
|[HOKA Tor Ultra Lo 橄榄 1130310-AQLV](https://stockx.com/hoka-one-one-tor-ultra-lo-antique-olive)|13|保留自用；US男11 仅英国索引 GBP141/401/252，买卖差大且型号流量低，不作为转售首单|

HOKA 自用标签为 JP29 / US男11 / UK10.5 / EU45⅓，使用品牌通用尺码表核对，仍需看目标鞋盒与实际合脚程度。[HOKA 官方尺码表所在商品页](https://cl.hoka.com/p/hoka-hombre-transport-2-black/)。Salomon 尺码换算另按[官方男鞋尺码表](https://www.salomon.com/en-gb/sizingchart?category=footwear-men&gender=men)，不能把裸脚长与 JP 标签长度混用。[StockX 官方说明采用 US 鞋码](https://stockx.com/help/articles/i-dont-know-how-an-item-fits-can-you-make-a-size-recommendation)。

## 这轮真正缺什么，AI 该用在哪里

已完成的是精确货号筛选、17 款市场线索分层、7 个规格的条件成本核算以及错误价差排除。没有取得的是中国得物同码当前到手价、可购数量/到货期，以及中国 StockX 卖家账户同码净结算、订单深度、该码最近成交频次。不能推断出货时间、成功率、整批 ROI 或推荐备货数量。

StockX 明确按买卖双方地区动态定价；美国/英国公开页或中文路径不等于中国卖家收入。[地区定价说明](https://stockx.com/help/articles/how-does-uk-vat-affect-me-as-a-stockx-customer)。得物官网和公共分享页未提供本轮目标规格的可验证结算价；国际 POIZON 美元价、2023 发售价、全码最低价、旧促销和二手价格均不代填。StockX 产品直接读取失败或返回403后已停止，未绕过访问控制；搜索索引保留为线索。

所以当前最有价值的 AI 工作是：**把少量同货号、同尺码、同成色的双边报价配对，扣费后只提醒达到阈值的条目。** 先围绕雨云两码、奶油黑9.5、1906RA9.5、1906REE9.5这五条规格补齐一次报价，再决定监测投入。正常新品要求对应鞋盒及标签，不能拿得物瑕疵/缺盒低价直接对比 StockX 标准新品。[StockX 鞋盒条件](https://stockx.com/help/articles/what-are-the-condition-guidelines-for-sneaker-boxes-accepted-by-stockx)。

取得配对报价后：使用本人卖家净结算反算最大采购成本；核对到货与发货期限；达到预留利润及成本条件后，再由用户决定是否做一双完整交易。经营总预算 1 万元只是上限，不是本轮推荐花光的额度。本轮研究没有采购、上架、联系交易对手或新增自动监控，也没有把索引价格写入应用的可采购数据。

下一步只有一项：**在可访问的得物及中国 StockX 卖家界面中，为上述五条规格完成一次同时段的实际买价与净结算配对。** 报价入口已在表中提供；一行配齐即可明确算出买入或放弃，不必先等全平台数据。
