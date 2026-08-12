# Round 17 Handoff — 路线时间表

## 目标

用户提的问题:"路线上在这个界面里,我好像没看到他应该是从几点到几点飞飞机,
几点到,几点回呢?"

修法:数据 + UI 全做。

## 数据层

| 路径 | 改动 |
|---|---|
| `arb/db.py` SCHEMA | `route_legs` 加 `depart_at TEXT` + `arrive_at TEXT` 两列(ISO8601 local time) |
| `arb/db.py` _EXPECTED_COLUMNS | 幂等迁移,已部署 DB 自动加列 |
| `arb/db.py` 新函数 | `backfill_route_leg_times(conn, route_id)` |
| `arb/db.py` 内部 helper | `_parse_iso_min` / `_fmt_iso_min` — naive local time,不走 epoch/UTC |

## 回填算法

从 `routes.departure_date + 09:00` 起算(假定出发当地上午 9 点),
按 seq 累加每段 `duration_min`,产出:
- `flight` / `transit` 段:`depart_at` = cursor,`arrive_at` = cursor + duration
- `hotel` / `shop` 段(`duration_min == 0`):`depart_at` = NULL(没具体开始时刻),`arrive_at` = cursor(标记墙钟推进)
- 跨日自动处理(用 naive timedelta,不绕 epoch)

## 自动触发

`arb/web_api.py` 加 `@app.on_event("startup")` 钩子,每次 server 启动时
对所有 routes 跑 `backfill_route_leg_times`。无 `departure_date` 的
legacy routes 静默跳过。

## 实跑结果(真 DB)

```
Route: PVG-NRT-LAX-2N (depart_date=2026-09-15)
  seq=1 flight  09-15 09:00 → 12:20 | PVG → NRT       (200min)
  seq=2 flight  09-15 12:20 → 23:20 | NRT → LAX       (660min)
  seq=3 hotel   → 09-15 23:20       | Rodeway Inn LAX 2N
  seq=4 shop    09-15 23:20 → 09-16 03:20 | Bic Camera (240min)
  seq=5 flight  09-16 03:20 → 14:20 | LAX → NRT       (660min)
  seq=6 flight  09-16 14:20 → 17:40 | NRT → PVG       (200min)

Route: LAX-SFO-1N (depart_date=2026-09-16)
  seq=1 flight  09-16 09:00 → 10:30 | LAX → SFO
  seq=2 hotel   → 09-16 10:30       | Bay Bridge Inn SFO 1N
  seq=3 shop    09-16 10:30 → 12:30 | Japantown
  seq=4 flight  09-16 12:30 → 14:00 | SFO → LAX
```

## UI

`web/index.html` 路线时间线 `<li>` 加 `<span class="leg-time" x-text="legTimeLabel(leg)">`,
`web/app.js` 加 `legTimeLabel(leg)`:
- 形如 `[09-15 09:00 → 12:20]` (同日) 或 `[09-15 23:20 → 09-16 03:20]` (跨日)
- 仅有 `arrive_at`(hotel 段):`[→ 10:30]`
- 都缺:空字符串

## 测试

`tests/test_route_timing.py` — 15 case:
- ISO parse/format round-trip
- schema 迁移幂等
- legacy DB 自动迁移
- basic walk + 跨日
- hotel leg depart NULL
- idempotent
- 缺 depart_date / 未知 route / 空 legs 报错

全量:`303 passed` (新增 15,无回归)

## 已知边界

1. **时区未编码** — `depart_at` / `arrive_at` 是 "naive" string,假设是路线
   当地的"墙上时间"。跨时区段(如 PVG→NRT)实际要算时差,但当前 schema 不
   区分。这个问题要解决需加 `tz_hint` 列或 `depart_tz`/`arrive_tz`。
2. **shop 段时间不准** — seq=4 shop 段写"23:20 → 03:20",实际购物不可能
   通宵 4 小时,这是 heuristic 推算。下一步可让 `duration_min` 不再代表
   "耗时"而代表 "起算偏移"。
3. **第二轮路线** (LAX-SFO-1N) depart_date 是 9/16 — 实际用户在多路线间
   应该 reset cursor,不能跨路线累加。当前实现是每条路线独立 walk,正确。

## commit / 分支

- **分支**: `pm-loop/20260726-103909-jp-us-arb-route-55490`
- 待 commit: arb/db.py, arb/web_api.py, web/app.js, web/index.html,
  tests/test_route_timing.py, docs/round-17-handoff.md,
  web/data-snapshot.js (regenerated)
- **真 DB 已写入** route_legs 时间戳(6+4=10 行),commit 不含 DB 文件