# Round 2 Handoff — jp-us-arb-route

**Date**: 2026-07-26
**Branch**: `pm-loop/20260726-103909-jp-us-arb-route-55490`
**Goal**: 完成 V0 验收项 #3 (Web SPA) 和 #4 (PDF 导出)

## TL;DR

Round 2 ships the Web SPA + PDF export that close the remaining two V0 verification
items.  All 6 acceptance criteria now green.  Tests: **34 → 61 passing**.

## Changed files

| Path | Purpose |
|---|---|
| `arb/report.py` | NEW — shared Markdown / HTML / PDF renderer; CLI + API + SPA all consume it |
| `arb/web_api.py` | NEW — FastAPI app: `/api/{health,opportunities,routes,decide,report/*}` + static SPA |
| `web/index.html` | NEW — SPA shell (Alpine.js, single HTML, sticky header + left/right layout) |
| `web/app.js` | NEW — Alpine state: fetch opps/routes, POST decide, download md/html/pdf |
| `web/style.css` | NEW — light theme, responsive collapse at 900px |
| `arb/cli.py` | MODIFIED — added `--html` / `--pdf` / `--format`, auto-filename, `serve` subcommand |
| `tests/test_report.py` | NEW — 9 tests covering MD/HTML/PDF renderer incl. real PDF magic-byte check |
| `tests/test_web_api.py` | NEW — 12 in-process FastAPI tests (TestClient) |
| `tests/test_cli.py` | EXTENDED — 5 new subprocess tests for html/pdf/default/404/serve-help |
| `README.md` | UPDATED — Round 2 status table, Web SPA section, API endpoints table, updated tree |

## Validation run

```
$ python3 -m pytest -q
............................................................ 61 passed

$ python3 -m arb report --sku JP-SKII-FT230 --units 5 --pdf --out /tmp/x.pdf
wrote /tmp/x.pdf                   # 334 KB, 2 pages

$ NO_PROXY=127.0.0.1,localhost uvicorn arb.web_api:app --port 8765 &
$ curl http://127.0.0.1:8765/api/health
{"ok":true,"opportunities":6,"routes":1,"db":".../data/db.sqlite"}

$ curl -X POST -H 'Content-Type: application/json' \
       -d '{"sku":"JP-NINTENDO-SWOLED","num_units":10}' \
       http://127.0.0.1:8765/api/decide
{"opp":{...},"decision":{"level":"不建议","roi_pct":-22.7,...},...}
```

## V0 acceptance map

| # | Criterion | Evidence |
|---|---|---|
| 1 | 6 SKUs w/ complete fields | `arb.seed.OPPORTUNITIES` (6 SKUs, all fields, source URLs) |
| 2 | 1+ complete route, $1040, all data has URL | `arb.seed.ROUTE` + `ROUTE_LEGS` (6 legs, all URL-sourced) |
| 3 | SPA: left list + right detail + top-bar params | `web/index.html` (Alpine `x-data="app()"`) |
| 4 | Markdown + single-page PDF, filename = date+dest | `arb.report.report_filename()` + `_content_disposition()` (RFC 5987) |
| 5 | `judge()` standalone, ≥10 hand-checked cases | `tests/test_decision.py` (23 cases) |
| 6 | SQLite + CLI/Web dual entry | `arb.db` (CLI: `python -m arb`, Web: `/api/*`) |

## Risks / known issues

- **HEAD on report endpoints returns 404.**  Browsers/curl use GET, so this only
  affects probes — not a blocker.  Fix in Round 3 by registering both methods.
- **Playwright runtime dep.**  PDF export needs `playwright` + `chromium`
  installed; tests skip PDF on systems without chromium.  No silent fallback —
  missing dep = loud error to surface the issue.
- **CJK filenames.**  Resolved via RFC 5987 `filename*=UTF-8''…`; legacy
  clients get an ASCII fallback.  Tested on Starlette 0.41.
- **SPA reaches API via same-origin** (FastAPI mounts SPA at `/`).  No CORS
  config needed.  If reverse-proxied later, set `proxy_pass` to forward `/api/*`
  to the FastAPI backend.
- **SOCKS proxy quirk.**  The local shell exports `ALL_PROXY=socks5://...`,
  which breaks curl to `127.0.0.1`.  Use `NO_PROXY=127.0.0.1,localhost` or
  test from the browser.  Documented in README quick-start.

## Next action (Round 3 candidate)

Implement the freshness watchdog + 半自动抓取 (requests + BeautifulSoup)
called out in the brief — the seed data is dated 2026-07-01; in 30 days
the UI should flag them as "陈旧待复核" and offer a `refresh` button that
hits a new `/api/opportunities/{sku}/refresh` endpoint, scraping the
purchase_source_url / sell_source_url and updating `data_freshness_ts` +
prices (with `verified=1` only on a clean diff vs. last known value).

This is the next biggest gap and lines up with the brief's V0 risk #8.