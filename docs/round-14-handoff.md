# Round 14 Handoff — Amadeus Flight Price Lookup (Half-Auto)

## TL;DR

`arb flight --origin PVG --dest LAX --date 2026-09-15` calls the Amadeus Self-Service Flight Offers Search API and prints the top offers as a table or JSON. **Half-auto mode**: results are not persisted — the user inspects them and decides whether to update `routes.flight_cost_usd` in the local DB manually.

- **Tests**: 256 passed (+11 from baseline 245), 29s
- **CLI**: `arb flight --origin --dest --date [--adults --cabin --currency --no-cache --json]`
- **Auth**: env vars `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` (+ optional `AMADEUS_HOSTNAME`)
- **Dep**: zero new — stdlib only, mirrors `arb/scraper.py` urllib idiom

## What changed

### 1. New module `arb/flight_price.py`

Mirrors the existing `scraper.py` patterns: dataclass returns (never raise), injected `opener=` kwarg for tests, module-level rate limiter with reset helper. Mirrors `refresh.py` / `verify.py` for the `outcome_as_dict` shim.

Public surface:
- `FlightOffer` (frozen dataclass): `offer_id`, `price_total`, `currency`, `validating_carrier`, `num_stops`, `segments`, `raw`
- `FlightSearchOutcome` (frozen dataclass): request params + `ok` + `offers` + `cached` + `elapsed_ms` + `blocked_reason` + `message`
- `search_flights(origin, dest, date, *, adults=1, cabin="ECONOMY", currency="USD", hostname=DEFAULT_HOSTNAME, client_id=None, client_secret=None, timeout=8.0, min_gap_sec=1.0, use_cache=True, cache_ttl=600.0, cache_cap=64, opener=urllib.request.urlopen)` — main entry
- `outcome_as_dict(o)` — JSON-serialisable shim

Internals:
- `_get_access_token` — POST `/v1/security/oauth2/token` with form-encoded body. Module-level cache keyed by `(hostname, client_id)`; refresh when within 60s of expiry.
- `_post_json` — tiny urllib wrapper. Mirrors `scraper.py:152-179` error branches: `HTTPError` / `URLError` / defensive generic — returns a structured dict with `ok=False` + `blocked_reason` instead of raising.
- `_in_memory_cache: OrderedDict` with TTL (600s default) + LRU cap (64 entries). **Not persisted** to SQLite.
- `_wait_for_slot` + `_reset_rate_limiter_for_tests` — copy the pattern from `scraper.py:58-74`.
- `DEFAULT_HOSTNAME = "test.api.amadeus.com"`, `DEFAULT_TIMEOUT = 8.0`, `DEFAULT_MIN_GAP_SEC = 1.0`, `DEFAULT_CACHE_TTL = 600.0`, `DEFAULT_CACHE_CAP = 64`, `USER_AGENT = "jp-us-arb-route/0.3 (+local-only personal use)"`.

### 2. New CLI subcommand `arb flight` (`arb/cli.py`)

Mirrors `cmd_refresh` (cli.py:355-366) and `cmd_verify` (cli.py:391-416). Returns JSON to stdout via `outcome_as_dict`; exits 1 with a clear stderr message if `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` are missing — same pattern as `cmd_serve`'s missing-uvicorn check.

Parser registration (after the `p_basket` block, before `return p`):
- `--origin` (required, IATA)
- `--dest` (required, IATA)
- `--date` (required, YYYY-MM-DD)
- `--adults` (default 1)
- `--cabin` (default ECONOMY, choices: ECONOMY / PREMIUM_ECONOMY / BUSINESS / FIRST)
- `--currency` (default USD)
- `--no-cache` (bypass the in-memory cache)
- `--json` (machine-readable output)

Dispatch entry: `"flight": cmd_flight` in the handler dict.

### 3. New tests `tests/test_flight_price.py` (11 cases)

Copies the `_FakeResp` helper from `tests/test_scraper.py:16-33` with `ctype="application/json"`. Stubs the network via the `opener=` and `token_opener=` kwargs (no `monkeypatch` needed — the project's signature testing idiom is to inject the network surface directly). `_Recorder` decodes form-encoded and JSON request bodies appropriately.

`@pytest.fixture(autouse=True)` resets the rate limiter, the in-memory cache, and the token cache between tests.

Cases:
1. **Happy path** — token + search returns one offer with the right fields
2. **Token-then-search ordering** — POST to `/v1/security/oauth2/token` first, then `/v2/shopping/flight-offers` with `Authorization: Bearer <token>`
3. **Token reused across different dates** — same `(client_id, hostname)` → one token call, two search calls
4. **Token refreshed when near expiry** — `expires_in=30` (below 60s safety window) triggers a refresh on the next call
5. **Missing credentials** → `ok=False`, `blocked_reason="missing AMADEUS..."`
6. **401 on token** → `ok=False`, `blocked_reason="http 401"`, no search call
7. **429 on search** → `ok=False`, `blocked_reason="http 429"`
8. **Empty offer list** → `ok=True`, `offers=[]`, `message="no offers returned"`
9. **Cache hit within TTL** — second call with same params makes zero HTTP calls
10. **No-cache bypass** — `use_cache=False` makes a fresh search but the token cache still applies
11. **outcome_as_dict shape** — JSON-serialisable with the expected keys

## Verification

```
$ python3 -m pytest -q
256 passed in 28.71s
```

End-to-end checks:
- ✅ `python3 -m arb flight --origin PVG --dest LAX --date 2026-09-15` (no creds) → exit 1, stderr `error: AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET not set. Register at https://developers.amadeus.com/ ...`
- ✅ `python3 -m arb flight --json` would print JSON; cannot verify without a real test-env account, but `search_flights()` returns well-formed JSON for all branches (verified in `test_outcome_as_dict_shape`)
- ✅ All 11 new tests pass; the 245 pre-existing tests stay green

## Files changed (summary)

| File | Change |
|---|---|
| `arb/flight_price.py` | **new** — full module, ~330 lines |
| `arb/cli.py` | `cmd_flight` handler; `p_flight` parser; dispatch entry; docstring example |
| `tests/test_flight_price.py` | **new** — 11 cases, ~250 lines |
| `docs/round-14-handoff.md` | **new** — this file |

`README.md`, `arb/seed.py`, `arb/db.py`, `arb/web_api.py`, `arb/report.py`, `arb/basket.py`, `arb/decision.py`, `arb/scenarios.py`, `web/*` — **not modified**. Round 14 is CLI-only.

## Known issues / follow-ups

- **No live test yet.** The user does not yet have an Amadeus Self-Service test account. Code is written so the credentials are read at call time from env vars. Once `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` are exported, `arb flight --json` will return real offers.
- **Test env constraints.** The Amadeus Self-Service test environment only has a handful of pre-loaded fixtures (e.g. LAX, BLR). Real-world routes like PVG may return no offers in the test env. Production access (`api.amadeus.com`) unlocks the full data; switch by setting `AMADEUS_HOSTNAME=api.amadeus.com`.
- **No persistence.** Per the half-auto design, `routes.flight_cost_usd` is **not** updated automatically. The user inspects `arb flight` output and either runs `arb routes --add` (existing command) or runs a SQL UPDATE manually to copy the cheapest reasonable offer into the route's `flight_cost_usd`.
- **No SPA exposure.** Round 14 is CLI-only. A future round could surface the offers in the dashboard via `GET /api/flight?origin=...&dest=...&date=...`.
- **Date / route pairing.** Round 14 doesn't know about the existing `routes` table. Future: `arb flight --route PVG-NRT-LAX-2N` could parse the route name into origin/dest and look up the route's `departure_date` if set.
- **No auto-bundle.** The basket solver still uses the static `flight_cost_usd` from `routes`. To make basket judgments live, the user needs to manually copy an Amadeus offer price into the route's `flight_cost_usd` and re-run `arb basket`.

## How to use (when credentials are available)

```bash
# 1. Register at https://developers.amadeus.com/ → grab test-env credentials
export AMADEUS_CLIENT_ID="<your client id>"
export AMADEUS_CLIENT_SECRET="<your client secret>"
# Production: AMADEUS_HOSTNAME=api.amadeus.com  (default is test.api.amadeus.com)

# 2. Look up flights
python3 -m arb flight --origin PVG --dest LAX --date 2026-09-15
# Pretty table with #, price, currency, carrier, stops, segment path.

# 3. Or get machine-readable output
python3 -m arb flight --origin PVG --dest LAX --date 2026-09-15 --json
# {ok, cached, offers: [{offer_id, price_total, currency, ...}]}

# 4. Manually copy the cheapest reasonable offer into the route's flight_cost_usd
#    (e.g. via `arb routes --add` with the new price, or direct SQL)

# 5. Re-run the basket to see the live verdict
python3 -m arb basket --budget 5000 --customs 5000
```
