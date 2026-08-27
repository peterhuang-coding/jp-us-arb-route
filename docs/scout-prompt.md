# 扫货提示词模板（每次「扫货」按此口径执行）

> 用法: 用户说「扫货」时, 按此模板派调研 agent, 产出 JSON 导入候选池。
> 导入命令: `python3 -m arb candidates import <json文件>`（在项目根目录执行）。

## 背景（给 agent 的）

用户是北京上班族, 周末飞东京(PEK↔NRT), 做日本代购。当前阶段: **路线 a 先行** ——
日本本地买货 → 人肉带回中国 → 闲鱼/朋友圈卖给国内买家。定价 = 日元价×汇率 + 5-20% 代购费。
选品方向: 药妆(15-25%利润)、中古(20-40%)、宝可梦卡牌/限定周边、USJ 限定、动漫手办、
中古游戏机、保温杯、小家电。**卖价锚必须用闲鱼搜索 URL**（不是 eBay）。

## 红线（命中的候选直接不要）

威士忌/烟/肉/水果/种子/液体>100ml/中药>500g/假名牌/象牙/含二氢可待因等管制成分药品（要标 ⚠️ 人工复核）。

## 产出格式

写 JSON 数组到 `$CLAUDE_JOB_DIR/tmp/candidates-batch<N>.json`, 每条:

```json
{
  "name": "中文名 (采购渠道, ¥JPY价)",
  "category": "品类",
  "buy_price_usd": 数字,
  "sell_price_usd": 数字,
  "source_market": "在哪买(药妆店/Bic Camera/Pokemon Center/USJ/Book Off/日亚...)",
  "target_market": "闲鱼/国内",
  "evidence": [
    {"label": "货源", "url": "货源链接", "side": "buy"},
    {"label": "闲鱼参考", "url": "https://www.goofish.com/search?q=关键词", "side": "sell"}
  ]
}
```

## 质量门槛

- ROI ≥ 15%（(卖-进)/进），低于的不要
- 每条必须 2 个证据链接（买侧+卖侧），卖侧用闲鱼搜索
- 一次 10-15 条, 覆盖 3 个以上品类
- 回复只给: 条数 + ROI 排序摘要 + 文件路径
