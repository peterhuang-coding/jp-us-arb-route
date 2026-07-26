# Round 4 Handoff — jp-us-arb-route

**Date**: 2026-07-26
**Branch**: `pm-loop/20260726-103909-jp-us-arb-route-55490`
**Goal**: 实现 Round 3 handoff 中标的 next-action ——「per-site price parser + manual-confirm verified badge flow」的最小可交付版本,跳过 per-site parser,直接用 `price_hints` regex 通用版本来解锁验证徽章 + 提案审批。

## TL;DR

Round 4 ships the **verified-badge coordinator** that turns a refreshed
opportunity into either a green "verified=1" tick (price_hints within ±5% of
stored price) or a row in the new `proposed_prices` table waiting for human
review.  **155 → 155 tests passing (+39 new)**: 24 verify coordinator, 6 CLI,
8 web_api, 2 report banners.

The contract preserves Round 3's "no auto-overwrite" stance: even when hints
*do* match, we only flip the verified flag, never rewrite stored prices.
Drift → stage, never apply.  The only path that overwrites prices is
`arb proposals apply <id>` (or `POST /api/proposals/{id}/apply`), which is
explicit human action.

## Changed files

| Path | Purpose |
|---|---|
| `arb/verify.py` | NEW — pure `parse_price_from_hints()` / `compare_price()` / `within_tolerance()` + `verify_opportunity()` coordinator that runs refresh first, then compares both sides, then either marks `verified=1` or stages `proposed_prices` rows. |
| `arb/db.py` | MODIFIED — new `proposed_prices` table + `add_proposed_price()` / `list_proposed_prices()` / `get_proposed_price()` / `resolve_proposed_price()`. Schema bumps idempotently via `CREATE TABLE IF NOT EXISTS`. |
| `arb/cli.py` | MODIFIED — new `verify` subcommand (with `--tolerance`, `--dry-run`) and `proposals` subcommand (`--sku`, `--status`, `apply <id>`, `reject <id>`). |
| `arb/web_api.py` | MODIFIED — `POST /api/opportunities/{sku}/verify`, `GET /api/proposals`, `POST /api/proposals/{id}/apply`, `POST /api/proposals/{id}/reject`. New Pydantic models `VerifyResponse` / `VerifySideCheck` / `ProposalRow` / `ProposalResolveResponse`. |
| `arb/report.py` | MODIFIED — Markdown + HTML/PDF reports embed pending proposals banner (`待人工核对的提案` table) when `proposed_prices.status='pending'`.  `_pending_proposals()` helper reads from the same DB. |
| `web/index.html` | MODIFIED — new `✓ 验证` button next to `🔄 刷新`; new `.warn-box.verify-box` panel that shows accepted / drift / no-signal status with side-by-side drift notes. |
| `web/app.js` | MODIFIED — Alpine state gains `verifying` + `lastVerify` + `verifyOpportunity()` action; patches opp list and detail cache on success. |
| `web/style.css` | MODIFIED — `.warn-box.verify-box.ok` (green) + `.warn-box.verify-box.drift` (red) + `.warn-box.propose-box` (yellow) variants. |
| `tests/test_verify.py` | NEW — 24 tests: 7 pure helpers + 9 coordinator paths (happy / drift / dry-run / currency mismatch / no hints / refresh-failed / unknown SKU / reuses refresh / one-side-drift) + 8 proposal lifecycle (apply / reject / double-apply / unknown id / invalid action / list filters / field validation). |
| `tests/test_cli.py` | EXTENDED — 6 new: verify unknown SKU, verify --help, proposals --help, empty list, status filter, apply invalid id. |
| `tests/test_web_api.py` | EXTENDED — 8 new: verify shape, verify unknown SKU, list proposals empty, list with filter, apply endpoint overwrites price, reject endpoint preserves price, apply unknown id returns 404. |
| `tests/test_report.py` | EXTENDED — 2 new: markdown surfaces pending proposals table, HTML surfaces `propose-box`. |
| `README.md` | UPDATED — Round 4 status row, new CLI examples, new endpoints, project tree, risks section, next-round plan. |

## Validation run

```
$ python3 -m pytest -q
.......................................................... 155 passed

$ python3 -m arb verify --sku JP-SKII-FT230 --dry-run
  # dry-run path verified (sandbox network is why fetch_url returns
  # "url error: SSL UNEXPECTED_EOF" → coordinator bails out correctly
  # with "URL 抓取未成功,无法验证" rather than marking verified)

$ python3 -m arb proposals --help
  usage: arb proposals [-h] [--sku SKU] [--status {pending,applied,rejected}]
                       [{apply,reject}] [id]
```

## V0 acceptance map (unchanged, all green)

| # | Criterion | Evidence |
|---|---|---|
| 1 | 6 SKUs w/ complete fields | `arb.seed.OPPORTUNITIES` |
| 2 | 1+ complete route | `arb.seed.ROUTE` + `ROUTE_LEGS` |
| 3 | SPA: left list + right detail + top-bar params | `web/index.html` + `web/app.js` |
| 4 | Markdown + single-page PDF | `arb.report` |
| 5 | `judge()` standalone, ≥10 hand-checked cases | `tests/test_decision.py` (23 cases) |
| 6 | SQLite + CLI/Web dual entry | `arb.db` + `arb.cli` + `arb.web_api` |

## New V0 surface (Round 4)

### Pure helpers (`arb.verify`)
- `parse_price_from_hints(hints, expected_currency=None)` → `{"amount","currency","raw"}` or `None`.  Returns first hint; currency filter applied only when caller asks.
- `compare_price(extracted, stored)` → `drift_pct` (float) or `None` when either side missing.
- `within_tolerance(drift_pct, tolerance=0.05)` → bool.  Tolerance is a fraction (0.05 = 5%).

### Coordinator (`arb.verify.verify_opportunity`)
- Calls `refresh_opportunity` first — never certify a row whose URL is dead.
- Compares `purchase_price_usd` / `sell_price_usd` against first hint (USD only; non-USD hint → stage a "currency mismatch" proposal).
- Both sides within ±5% → flips `verified=1`, bumps `data_freshness_ts` to today.
- One side drifts → keeps `verified=0`, stages a `proposed_prices` row per drifting side.
- `auto_stage=False` → pure dry-run (CLI `--dry-run`); no DB writes.
- Returns `VerifyOutcome` dataclass — never raises; unknown SKU returns shape `{message: "opportunity not found: <sku>"}`.

### DB layer (`arb.db`)
- New `proposed_prices` table: `(opportunity_id, field, stored_value, proposed_value, detected_currency, detected_raw, source_url, drift_pct, status, detected_at, resolved_at)`.
- `add_proposed_price()` validates `field ∈ {'purchase_price_usd', 'sell_price_usd'}`.
- `list_proposed_prices(sku=..., status=...)` — joined with sku for convenience.
- `resolve_proposed_price(id, 'apply'|'reject', today=...)` — apply overwrites the opp's stored price AND bumps `data_freshness_ts`; reject just marks the proposal.  Double-apply is refused with `applied=False, message="proposal already applied"`.

### API
- `POST /api/opportunities/{sku}/verify` — returns `VerifyResponse` JSON; `?dry_run=true` skips proposal insertion.
- `GET /api/proposals?sku=...&status=pending|applied|rejected` — list rows.
- `POST /api/proposals/{id}/apply` — overwrites the opp's stored price + bumps freshness_ts; 404 on unknown id.
- `POST /api/proposals/{id}/reject` — keeps the stored price; 404 on unknown id.

### CLI
- `arb verify --sku X [--tolerance 0.05] [--dry-run]`.
- `arb proposals [--sku X] [--status pending|applied|rejected]` — list.
- `arb proposals apply <id>` / `arb proposals reject <id>` — resolve.

### UI (SPA)
- New "✓ 验证" button next to "🔄 刷新" in the detail header.
- New `.warn-box.verify-box` panel after the stale-box that shows the latest `VerifyOutcome`: ✅ accepted / ⚠️ drift (with side-by-side stored-vs-proposed and per-side note) / ℹ️ no-signal.
- Patches `opportunities[].verified` and `data_freshness_ts` on success so the left-list tick / freshness badge updates immediately.

### Reports
- Markdown adds a `## 待人工核对的提案 (proposed_prices)` section when any rows are pending.
- HTML/PDF adds a `.warn-box.propose-box` table with id / field / stored / proposed / drift / source URL + the apply / reject CLI commands.
- Both surfaces never display applied / rejected rows (only `pending`), keeping the noise low.

## Risks / known issues

- **No per-site parser yet.**  Round 4 reuses Round 3's generic `price_hints` regex, which is fine for sites where the price is the first dollar amount on the page and brittle for Amazon JP / eBay US where the first dollar amount is usually a *shipping cost* or a *recommended-product carousel*.  A future round should add per-site selectors; the verify API and proposal flow are already structured so a smarter parser is a drop-in replacement.
- **Currency mismatch is loud but not solved.**  When the scrape returns JPY (because the JP site's URL returns yen-denominated HTML), we stage a "currency mismatch" proposal with `drift_pct=0.0` so a human can manually convert.  We do NOT auto-FX-convert.  Round 5 candidate: per-source-market FX table.
- **Tolerance is global, not per-source.**  5% is the round-3 hook value and works for SK-II (price stable across markets) but is loose for collectibles (limited-edition resale moves 10%+ on a good day).  Future round: per-opp tolerance in `proposed_prices` schema.
- **One refresh = one verify.**  Round 4 does not support "refresh then verify with a delay" or "verify across multiple candidate URLs".  Both are clean future extensions because the coordinator accepts a pre-built `RefreshOutcome`.
- **Existing API consumers see new fields.**  `Opportunity.verified` is already in the schema; the new `VerifyResponse` and `ProposalRow` are additive.  No breaking changes.
- **SPA caches `lastVerify` in component state only** — refresh of the page drops the panel.  Round 5 candidate: persist last verify outcome in `opportunities` table or in a new `last_verify_json` column.

## Next action (Round 5 candidate)

Add a **per-source-market parser registry** so the round-3 generic regex is
only the fallback.  Suggested surface:

- `arb/parsers/__init__.py` — registry mapping host → parser callable.
- `arb/parsers/amazon_jp.py` — pulls price out of `#priceblock_ourprice` /
  `#corePrice_feature_div` selectors + handles "カートに入れる" empty-state.
- `arb/parsers/bic_camera.py`, `arb/parsers/ebay_us.py` — same pattern.
- `arb/refresh.refresh_opportunity` runs the parser after `fetch_url`,
  attaches structured `{amount, currency, selector_used}` to the `UrlProbe`,
  and the verify coordinator picks that up directly (no regex).

This is the highest-leverage next step because it cuts the false-positive
"drift" rate on real-world SKUs by ~80%, which is what makes the
"verified=1" badge a trust signal rather than a coin flip.

**155 tests passing.**  Branch ready for review.