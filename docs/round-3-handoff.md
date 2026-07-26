# Round 3 Handoff — jp-us-arb-route

**Date**: 2026-07-26
**Branch**: `pm-loop/20260726-103909-jp-us-arb-route-55490`
**Goal**: 实现 Brief §6 风险 #8 — 数据陈旧 (>30 天 → "陈旧待复核") 告警 + 半自动抓取基础设施

## TL;DR

Round 3 ships a self-contained freshness watchdog + safe HTTP scraper.
All UI surfaces (CLI / FastAPI / SPA / Markdown / HTML / PDF) now show the
verdict per opportunity.  **61 → 116 tests passing (+55 new)**.

The watchdog DOES NOT auto-overwrite prices.  It only refreshes
`data_freshness_ts` when both purchase + sell URLs are reachable, and
returns `price_hints` for human review.  This avoids the "half-correct
auto-update is worse than no update" failure mode the brief calls out.

## Changed files

| Path | Purpose |
|---|---|
| `arb/freshness.py` | NEW — pure `classify(ts, today)` → `FreshnessVerdict` (fresh/aging/stale/missing/future); `attach()` for list views; `humanize_age()` for display. |
| `arb/scraper.py` | NEW — stdlib-only `fetch_url()` with robots.txt + per-process rate limit + 1.5MB cap; `extract_price_hints()` regex; never raises (errors recorded in `ScrapedPage`). |
| `arb/refresh.py` | NEW — `refresh_opportunity(conn, sku)` ties DB + freshness + scraper together; returns `RefreshOutcome` (verdict before/after, per-URL probe, `price_hints`). |
| `arb/web_api.py` | MODIFIED — `/api/opportunities` now embeds `freshness` verdict per row; new `POST /api/opportunities/{sku}/refresh` endpoint + `RefreshResponse` Pydantic model. |
| `arb/cli.py` | MODIFIED — `freshness` subcommand (one or all SKUs) + `refresh` subcommand. |
| `arb/report.py` | MODIFIED — Markdown + HTML/PDF reports embed freshness badge + age; HTML adds `.stale-box` warning with `arb refresh` hint when stale. |
| `web/index.html` | MODIFIED — left-list footer now shows colored freshness pill + humanized age; detail pane header has "🔄 刷新" button; stale warning callout. |
| `web/app.js` | MODIFIED — Alpine state gains `refreshing` + `refreshOpportunity()` action; `freshClass()` + `freshAge()` formatters. |
| `web/style.css` | MODIFIED — `.fresh-badge.{fresh,aging,stale}` pills + `.warn-box.stale-box`. |
| `tests/test_freshness.py` | NEW — 22 cases (thresholds, boundaries, missing/unparsable/future ts, attach(), summary(), humanize_age()). |
| `tests/test_scraper.py` | NEW — 17 cases (empty URL, robots allowed/disallowed/unknown, HTTPError/URLError/exception, success path, truncation, non-text content, rate limiter sleep, price-hint dedup/cap/currency override). |
| `tests/test_refresh.py` | NEW — 7 cases (happy path bumps ts, probe failure preserves ts, no-URL edge, multi-currency hints, unknown SKU, robots block, outcome dict shape). |
| `tests/test_web_api.py` | EXTENDED — 3 new: `freshness` field on opps; refresh 404-shape; refresh endpoint with stubbed scraper. |
| `tests/test_cli.py` | EXTENDED — 3 new: `freshness` all-rows + single-row + unknown-sku. |
| `tests/test_report.py` | EXTENDED — 2 new: markdown stale warning; HTML stale-box. |
| `README.md` | UPDATED — Round 3 status row, freshness/refresh CLI examples, new endpoint, tree, risks section, next-round plan. |

## Validation run

```
$ python3 -m pytest -q
.......................................... 116 passed

$ python3 -m arb freshness
  [aging  ] JP-SKII-FT230       freshness_ts=2026-07-01 age=25    🟡 临近复核
  [aging  ] JP-WS-YAMAZAKI12    freshness_ts=2026-07-01 age=25    🟡 临近复核
  ... (6 rows)

$ python3 -m arb report --sku JP-SKII-FT230 --units 5 --md
# 决策报告 — SK-II Facial Treatment Essence 230ml (PITERA)
...
- 数据更新: 2026-07-01  (⚠️ 未验证)  🟡 临近复核 (25 天前)
...
- 数据新鲜度: 🟡 临近复核 (25 天前)
```

(Seed ts `2026-07-01` + today `2026-07-26` = 25 days → "aging" not "stale".
The stale path is covered by `tests/test_freshness.py` boundary tests + a
monkeypatched `classify()` in the report tests.)

## V0 acceptance map (unchanged, all green)

| # | Criterion | Evidence |
|---|---|---|
| 1 | 6 SKUs w/ complete fields | `arb.seed.OPPORTUNITIES` |
| 2 | 1+ complete route | `arb.seed.ROUTE` + `ROUTE_LEGS` |
| 3 | SPA: left list + right detail + top-bar params | `web/index.html` + `web/app.js` |
| 4 | Markdown + single-page PDF | `arb.report` |
| 5 | `judge()` standalone, ≥10 hand-checked cases | `tests/test_decision.py` (23 cases) |
| 6 | SQLite + CLI/Web dual entry | `arb.db` + `arb.cli` + `arb.web_api` |

## New V0 surface (Round 3)

- `arb.freshness.classify(ts, today=None, sku=None)` — pure, 100% testable.
- `POST /api/opportunities/{sku}/refresh` — fetches purchase + sell URLs
  (robots.txt-aware), updates `data_freshness_ts` only on success, returns
  `price_hints` for human review.  No price auto-overwrite.
- `python -m arb refresh --sku <SKU>` — same flow, CLI surface.
- `python -m arb freshness [--sku <SKU>]` — per-portfolio verdict (CLI).
- SPA: colored pill in left list (🟡 aging / ⚠️ stale), "🔄 刷新" button in
  detail header, full-page stale warning callout with `arb refresh` hint.

## Risks / known issues

- **Auto-update is intentionally off.**  Brief says "manual + semi-automatic".
  This round ships the *infrastructure* — the next round (or a future per-site
  parser) can layer on optimistic / pessimistic overwrite policy without
  changing the contract.
- **HTML/JSON of opportunity list now embeds `freshness` verdict.**  Existing
  API consumers must tolerate the extra field.  Tests in `test_web_api.py`
  assert the shape; SPA reads it.
- **Scraper is stdlib-only.**  No `requests`, no `BeautifulSoup`; uses
  `urllib.robotparser` and a tiny in-process rate limiter.  Per-host robots
  are not cached — each refresh re-fetches robots.txt (one extra small GET).
- **Scraper timeout default = 8s.**  Round 4 may want per-site overrides for
  slow targets (Amazon JP, etc.).
- **Pydantic v2 compatibility:**  the new `RefreshResponse` model is
  plain pydantic v2; `response_model=RefreshResponse` works without
  field aliases.

## Next action (Round 4 candidate)

Add a per-site price parser for the 3 most-stable sources (Amazon JP,
Bic Camera, eBay US) using the existing `price_hints` regex as fallback.
Wire parsed numbers into a manual-confirm flow: refresh → if `price_hints`
match the stored `purchase_price_usd` / `sell_price_usd` within 5%, mark
`verified=1` and bump freshness; otherwise stage the proposal in a new
`proposed_prices` table for human review.

This is the highest-leverage next step because it unlocks the "verified"
badge in the UI without a separate verification UI of its own.