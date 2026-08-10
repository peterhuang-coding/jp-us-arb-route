# Round 13 Handoff — Self-Use Payback Model + 5000元 Basket Solver

## TL;DR

The decision model was reframed from "resale ROI" to "self-use trip payback", and a new 5000元 bounded-knapsack basket solver answers the question the user actually wants answered: **"given the trip is hypothetical, will shopping cover the airfare?"** Three coupled changes (cost flip, self-use baseline, knapsack solver) shipped together with schema migration, fresh tests, and a new SPA section.

- **Tests**: 245 passed (+36 from baseline 209), 15s
- **CLI**: `arb basket --budget 5000 --customs 5000 [--json]`
- **API**: `POST /api/basket` with `{budget_cny, customs_limit_cny, route}`
- **UI**: new "🛒 5000元 最优购物清单" section above 今日PICK, 3 new metric tiles, payback-based card tiers

## What changed

### 1. Cost model flip (`arb/decision.py`)

Old: `ROI = (resale_revenue - trip_cost - time_cost) / total_cost`
New: `payback_rate = self_use_savings / trip_cost`

- Removed `per_unit_time_cost` from the formula (leisure trip, no opportunity cost).
- New `Decision` fields: `total_savings_usd`, `trip_net_value_usd`, `payback_rate_pct`.
- New level cascade:
  - `num_units > max_units_per_trip` → 不建议
  - `payback < 50%` → 不建议
  - `payback < 100%` → 谨慎
  - else → 建议
- Old field names (`roi_pct`, `net_profit_usd`, `total_revenue_usd`) kept for backward compat but redefined: ROI is now `trip_net_value / trip_cost * 100`, and `net_profit` aliases `trip_net_value`.

### 2. Self-use baseline (`home_price_cny`)

New schema columns:
- `opportunities.home_price_cny REAL` — what you'd pay in China (天猫/中免/日上/代购)
- `opportunities.unit_volume_ml REAL` — physical size hint
- `opportunities.max_units_per_trip INTEGER NOT NULL DEFAULT 50` — per-SKU carry cap
- `routes.cn_to_usd_fx REAL NOT NULL DEFAULT 0.14` — CNY→USD rate

Caller passes `home_price_usd = home_price_cny * cn_to_usd_fx`. If `home_price_cny IS NULL`, the model falls back to `sell_price_usd * cn_to_usd_fx` for backward compat — flagged via a banner on each pick card so the user knows which rows are using the eBay-resale proxy vs a real China retail price.

### 3. 5000元 bounded knapsack (`arb/basket.py`, new)

`POST /api/basket` (or `arb basket --json`) returns the optimal multi-SKU purchase plan within `min(budget_cny, customs_limit_cny)`. Bounded 0/1 knapsack via DP — 42 SKUs × 50 unit cap × 5000 capacity = 10.5M operations, <1s. SKUs with NULL `home_price_cny` (after fallback) or non-positive `savings_per_unit_cny` are skipped with a `skipped_skus` list for transparency.

### 4. Migration mechanism (new infra)

The DB had no migration path before. `arb/db.py` now has:
- `_table_columns(conn, table)` via `PRAGMA table_info`
- `_ensure_columns(conn, table, expected: dict)` runs `ALTER TABLE ADD COLUMN` for any missing column

Called from both `connect()` and `connect_memory()`. The 4 new columns above are added idempotently. **All future column additions just append to `_EXPECTED_COLUMNS` in `db.py` plus the SCHEMA string for fresh installs.**

### 5. UI changes (`web/index.html` + `web/app.js`)

- 3 new metric tiles in the detail block: 回本率 / 行程净值 / 累计节省 (with `paybackClass` for green/yellow/red coloring).
- New "🛒 5000元 最优购物清单" section: 5 summary metrics + a table of picks sorted by savings density. Re-fetches on route change.
- 今日PICK card tier thresholds changed from `roi >= 15` to `payback >= 100 → GO`, `>= 50 → WATCH`, else `SKIP`. Sort changed from ROI to payback.
- "ROI" label on pick cards renamed to "回本率".

## Verification

```
$ python3 -m pytest -q
245 passed in 15.34s
```

Hand-calc spot checks against live API (raw socket):
- **SK-II 5u, intl route**: hand says 5 × ($185 sell - $150 purchase - $4 ship) = $155, trip $1040 → payback 14.9%, trip_net -$885. API: 14.9%, -$885. ✓
- **Albion 5u**: hand says 5 × ($555 - $153 - $8) = $1968, trip $1040 → payback 189%, trip_net $928. API: 189.26%, $928.35. ✓

CLI: `arb basket --budget 5000 --customs 5000` produces a human-readable pick table; `--json` emits the same data as a single document.

SPA: server runs on 127.0.0.1:8791. Basket section visible at top of dashboard, 5 metric tiles, 1 pick (PKMN-PSA: 7u ¥5000 spend ¥54750 save), 2 SKUs skipped (Yamazaki, Anime due to negative savings at current FX).

## Known data issues (not bugs, follow-up)

- The 42 research SKUs in `data/db.sqlite` have NULL `home_price_cny`. They fall back to `sell_price_usd * 0.14` which uses eBay resale as the China retail proxy. Some picks (notably Pokemon cards) show absurd savings — that's a data issue, not a model bug. UI shows the cards as usual but the user should fill in real `home_price_cny` for the research SKUs to get accurate numbers.
- The seed now has 6 SKUs with realistic `home_price_cny` (天猫/中免/京东 estimates). `python -m arb seed` overwrites the seeded SKU rows but **does not** touch the 36 research SKUs (they were inserted by an earlier round's `scripts/insert_research_skus.py`).
- `web/data-snapshot.js` (2523 lines) was not regenerated. The offline PICK fallback still uses the stale resale-ROI data. Live API is the source of truth when the server is up.

## Files changed (summary)

| File | Change |
|---|---|
| `arb/db.py` | migration infra + 4 new columns |
| `arb/decision.py` | payback math, 3 new fields, new level cascade |
| `arb/scenarios.py` | 3 new fields in `as_dict`; `apply_shifts` also shifts `home_price_usd` |
| `arb/basket.py` | **new** — DP solver |
| `arb/report.py` | pull 3 new opp/route fields; markdown/HTML add 3 rows in 综合决策 |
| `arb/cli.py` | `cmd_basket` + parser + dispatch + docstring; `_print_decision` shows payback line |
| `arb/web_api.py` | `POST /api/basket` + Pydantic models |
| `arb/seed.py` | `home_price_cny` + `cn_to_usd_fx` for 6 seeded SKUs/routes |
| `web/index.html` | 3 new metric tiles + 购物清单 section + pick card label change |
| `web/app.js` | `baskets` state, `loadBasket()`, `paybackClass()`, route-change handler, payback-based sort/tier |
| `tests/test_decision.py` | rewritten for payback model (23 tests) |
| `tests/test_scenarios.py` | base_inputs updated; hand-calc tests updated; cross-check test retuned |
| `tests/test_report.py` | `test_report_uses_home_price_for_decision` |
| `tests/test_routes_cli.py` | SK-II test reworked for new model + max_units=6 |
| `tests/test_web_api.py` | `test_decide_propagates_payback_fields` |
| `tests/test_basket.py` | **new** — 18 tests |
| `tests/test_migration.py` | **new** — 6 tests |
| `docs/round-13-handoff.md` | **this file** |

`web/data-snapshot.js` — **not modified** (stale offline fallback; see known data issues).
