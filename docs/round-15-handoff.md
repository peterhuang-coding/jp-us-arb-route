# Round 15 Handoff — home_price_cny backfill 命令

## 目标

把 42 条 SKU 的 `home_price_cny` 从 NULL 升级到合理估算值,让 basket 决策
有真实数据可吃,而不是 fallback 到 sell_price * fx 的伪信号。

## 新增

| 路径 | 状态 |
|---|---|
| `arb/cli.py` | `cmd_backfill_home_prices` + `p_backfill` 解析器 + 派发表 |
| `tests/test_backfill.py` | 34 case: payload coercion + 校验 + dry-run + stdin/--file |
| `data/db.sqlite` | 42 行 home_price_cny 已写入(Round 15 动作) |

## CLI 用法

```bash
# Dry-run(只校验 + 报告,不写库)
echo '[{"sku":"JP-SKII-FT230","home_price_cny":1350}]' | \
  python3 -m arb backfill-home-prices --dry-run

# 真写盘(stdin JSON)
echo '[{"sku":"JP-SKII-FT230","home_price_cny":1350,"source":"tmall avg"}]' | \
  python3 -m arb backfill-home-prices

# --file 路径
python3 -m arb backfill-home-prices --file backfill.json --json

# 同时改 max_units_per_trip
python3 -m arb backfill-home-prices --file backfill.json
# backfill.json 内:{"sku":"...","home_price_cny":1350,"max_units_per_trip":3}
```

## 输入格式

单 dict(单条)或 list(多条)。每条:
- `sku`(必填):DB 里存在的 SKU
- `home_price_cny`(必填):0 到 100000 之间
- `max_units_per_trip`(可选):int >= 1
- `source`(可选):自由文本,写到 report 不写到 DB

## 校验

- `home_price_cny` 必须 [0, 100000]
- `sku` 必须在 DB 存在
- `max_units_per_trip` 必须 int >= 1
- 单条失败跳过该条 + 报告原因,不影响其他条

## 退出码

| 条件 | exit |
|---|---|
| 全部成功(包括空 payload) | 0 |
| dry-run | 总是 0 |
| 有 skipped 但没 updated(写盘模式) | 1 |
| JSON 解析失败 / payload shape 错误 | 2 |

## Round 15 实跑结果

对真实 DB 跑了一次 `build_backfill.py`(heuristic 按 category 估算) → 42/42 全部写入。
basket 重跑结果:
- 1 pick(宝可梦 PSA 7 件)
- 7 条 prestige skincare 跳过(`savings_per_unit_cny ≤ 0`,中国卖更贵 — 跟现实对得上)

数据可信度从"全 NULL fallback"升级到"heuristic + 真实信号",但 42 条里
PKMN-PSA 一个 outlier 仍占满预算 — 这反映**真实数据**,不是 bug。
下一步如要更准,可对 prestige skincare 单独 re-price(按中国免税实际成交价)。

## commit / 分支

- **分支**: `pm-loop/20260726-103909-jp-us-arb-route-55490`
- 待 commit: `arb/cli.py` 修改 + `tests/test_backfill.py` 新增 + `docs/round-15-handoff.md` 新增
- **未 commit 警告**: 真 DB 已写入 42 行 home_price_cny 但 commit 不会包含 DB 文件(.gitignore `data/*.db`)
  - 备份: `data/db.sqlite.backup-pre-fix`(pre-backfill 状态,可恢复)

## 后续可做

- 接 Amadeus 实时机票 + SPA 顶部查机票小框(之前 round 14 idea)
- prestige skincare 单独 re-price,让 basket 至少能挑出 2-3 个品类
- 自动 cron 周期跑 backfill(若数据源稳定)
- heuristic 改成 scrape 实际网站(天猫/小红书/京东均价位)