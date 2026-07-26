# Round 8 Handoff — Regional route + `arb routes` CLI + upsert_id bug fix

**Date**: 2026-07-26
**Branch**: pm-loop/20260726-103909-jp-us-arb-route-55490
**Author**: PM Agent (round 8)

## What changed

### Behavior — second route `LAX-SFO-1N` shipped in seed
Round 6/7 handoffs flagged that the single canonical route
(PVG-NRT-LAX-2N, $1040 fixed trip cost) was so expensive that most
SKUs only break even at ≥10–20 units. Round 8 ships a second seeded
route — a US-domestic regional connector LAX→SFO 1-night, $300 fixed —
and proves that **route choice can flip a verdict** the same way SKU
choice can.

| SKU                 | units | PVG-NRT-LAX-2N (intl, $1040 fixed) | LAX-SFO-1N (regional, $300 fixed) |
|---------------------|------:|------------------------------------|------------------------------------|
| `JP-SKII-FT230`     | 20    | ❌ 不建议                          | ⚠️ 谨慎                            |
| `JP-ANIME-GK2024`   | 20    | ❌ 不建议                          | ⚠️ 谨慎                            |
| `JP-NINTENDO-SWOLED`| 20    | ❌ 不建议                          | ❌ 不建议                          |

This is the round-7-handoff prediction ("regional route so the user can see
that route choice matters as much as SKU choice") verified at engine level.
The SPA picks the route via the existing top-bar dropdown (`/api/routes`
already served both routes after seed), so users now see both options without
any additional web work.

### New CLI: `arb routes`
Two subcommands:
- `arb routes` (default) — list every route with fixed cost, leg count,
  total minutes, and target/min ROI. Output is plain text, ready for piping.
- `arb routes --add --name X --origin Y --dest Z --flight F --hotel H
  [--other O] [--hours HRS] [--depart YYYY-MM-DD] [--source-url URL]
  [--notes TEXT]` — insert a new route. Idempotent on `--name` collision.

This is a parity addition for the existing `arb proposals` pattern and
makes "add a third route" a one-liner instead of editing `arb/seed.py`.

### Latent bug fixed: `upsert_route` / `upsert_opportunity` returned stale autoincrement id
The two upsert helpers previously did `return cur.lastrowid or _fetch_id(...)`.
After `ON CONFLICT DO UPDATE`, `cur.lastrowid` is **unreliable** in
Python's sqlite3 — it returns the prior autoincrement counter (e.g.
`10` after several route_legs inserts), not the actual PK of the
updated row. Round 8 added a 2nd seed route, and the test
`test_seed_all_idempotent_for_second_route` exposed the bug: a
second `seed_all()` call passed the stale `10` to `add_route_legs`,
tripping a FOREIGN KEY violation.

Fix: drop the `cur.lastrowid or ...` branch and always look up the
existing row's id by natural key (sku / name). Both upserts now
correctly return the existing row's id on conflict.

### Code touched
- `arb/seed.py` — added `ROUTE_REGIONAL` (LAX→SFO 1N), 4 legs, and the
  `ROUTES` / `ROUTES_BY_LEGS` map so `seed_all()` inserts both routes.
- `arb/cli.py` — added `cmd_routes`, registered parser subparser, and
  wired dispatcher to call `cmd_routes` for the new `routes` cmd.
- `arb/db.py` — fixed `upsert_route` and `upsert_opportunity` to always
  return the existing row's id (regression test in `test_routes_cli.py`).
- `tests/test_cli.py` — updated `test_health` from `routes: 1` to `routes: 2`.
- `tests/test_web_api.py` — updated `test_health_returns_counts` and
  `test_list_routes_includes_legs` to expect 2 routes.
- `tests/test_routes_cli.py` — **new**, 8 tests:
  1. `test_seed_all_inserts_two_routes`
  2. `test_seed_all_idempotent_for_second_route` (covers the upsert bug)
  3. `test_upsert_returns_correct_id_on_conflict` (regression test)
  4. `test_regional_route_has_cheaper_fixed_cost_than_international`
  5. `test_skii_flips_to_warn_at_20u_with_regional_route`
  6. `test_cli_routes_lists_both_routes`
  7. `test_cli_routes_add_inserts_new_route`
  8. `test_cli_routes_add_is_idempotent`

### DB state (production)
```
opportunities:    10 rows (unchanged from round 7)
routes:            2 rows  (was 1)
  [1] PVG-NRT-LAX-2N  上海 PVG → 洛杉矶 LAX  flight $720  hotel $240  (固定 $1040)
  [2] LAX-SFO-1N      洛杉矶 LAX → 旧金山 SFO  flight $150  hotel $120  (固定 $300)
route_legs:       10 rows  (was 6)
proposed_prices:  20 applied, 0 pending, 0 rejected  (unchanged)
```

### Tests
- 203/203 pass (was 195 in round 7, +8 new).
- Real DB state after pytest: still 10 opportunities, 2 routes, 10 legs.

## Risks / open items for round 9+
- **`test_apply_proposal_overwrites_parent_price` (round 7)** asserts
  the parent opportunity's `data_freshness_ts` is bumped, but the test
  uses today's date implicitly. If a freeze is needed, monkeypatch
  `_dt.date.today` in that test.
- **The Dyson loss-making case** (`JP-DYSON-V12S` per-unit net
  `$-52.84`) is still unaddressed at the engine level. The cheap regional
  route doesn't help because the per-unit margin is negative. Round 9
  should stage a **buy-side proposal** (`purchase_price_usd` drift) via
  the existing `proposed_prices` flow — see round-7 handoff option (b).
- **`arb routes --add` does not yet support adding `route_legs`**.
  Routes inserted via the CLI start with 0 legs (no time/cost schedule).
  For round 9, consider adding `--leg <kind:label:cost:duration>` repeat
  flag, or a JSON import path.
- **SPA routepicker UX**: the SPA shows the route's origin/dest city in
  the top bar, but does not display the fixed trip cost next to each
  route option. Adding that would make the cheap-regional vs
  expensive-intl choice obvious without leaving the page.

## Next action (exactly one)
Round 9 should pick **one**:
(a) add `route_legs` support to `arb routes --add` so CLI-inserted
    routes can carry their full flight/hotel/shop schedule, or
(b) stage the Dyson buy-side proposal (`field=purchase_price_usd`)
    using the existing `proposed_prices` flow to flip it to ✅/⚠️, or
(c) extend the SPA routepicker to show "$300 fixed" / "$1040 fixed"
    next to each route, making the round-8 lesson visible to the user
    without needing the CLI.