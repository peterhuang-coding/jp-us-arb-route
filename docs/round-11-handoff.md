# Round 11 Handoff — `route_legs` support for `arb routes --add`

**Date**: 2026-07-26
**Branch**: pm-loop/20260726-103909-jp-us-arb-route-55490
**Author**: PM Agent (round 11)

## What changed

### Behavior — CLI-inserted routes can now carry legs

Round 8 shipped `arb routes --add` but left a documented gap: routes
inserted via the CLI started with **0 legs**. The CLI listing already
printed `legs=N (Xmin)` next to each route, so users could immediately
see that CLI-inserted routes had nothing in their timeline.

Round 11 closes the gap. `--leg` is now a **repeatable** flag accepting
a JSON payload, and CLI-inserted routes can carry their full
flight / hotel / shop / transit schedule.

```bash
# One leg per --leg flag; positional order on the CLI = leg seq.
arb routes --add --name DEMO-NRT-HND \
    --origin "东京 NRT" --dest "羽田 HND" \
    --flight 80 --hotel 60 \
    --leg '{"kind":"flight","label":"NRT → HND","cost_usd":80,"duration_min":75,"location":"Tokyo"}' \
    --leg '{"kind":"shop","label":"秋叶原采购","cost_usd":0,"duration_min":180,"location":"Akihabara"}' \
    --leg '{"kind":"flight","label":"HND → NRT","cost_usd":80,"duration_min":75,"location":"Tokyo"}'
# → {"inserted": 1, "name": "DEMO-NRT-HND", "legs": 3}

arb routes
# → [1] DEMO-NRT-HND  东京 NRT → 羽田 HND
#       flight $80  hotel $60  other $0  (固定 $140)
#       hours 24h  legs=3 (330min)  target ROI 15%  min ROI 10%
```

### Re-adding an existing route = replace its legs (only with `--leg`)

The Round 8 contract was: re-adding an existing route name is a
no-op (prints `route 'X' already exists; no changes made`). Round 11
preserves that contract when `--leg` is **not** passed, so existing
scripts and tests stay green.

When `--leg` IS passed alongside an existing route name, the CLI now
**replaces** the leg set (DELETE then INSERT) instead of being a
no-op. This lets users iterate on a route via repeated CLI calls —
adding a leg, removing a leg, changing a leg — without the stale
leg set lingering.

| call pattern                                 | round 8 | round 11        |
|----------------------------------------------|---------|-----------------|
| `--add` (new route, no `--leg`)              | insert  | insert (same)   |
| `--add` (existing route, no `--leg`)         | no-op   | no-op (same)    |
| `--add --leg ...` (existing route, with legs)| no-op   | **replace legs**|

This dual behavior keeps the Round 8 test
`test_cli_routes_add_is_idempotent` green and is the smallest
change that lets users iterate on a route via CLI.

### JSON shape — required + optional keys

```jsonc
{
  "kind": "flight",          // required: flight | hotel | shop | transit
  "label": "NRT → HND",      // required: free-form display name
  "cost_usd": 80.0,          // required: numeric
  "duration_min": 75.0,      // optional, default 0.0
  "location": "Tokyo",       // optional, default ""
  "notes": "NH 864",         // optional, default ""
  "seq": 1                   // optional; if absent, position on CLI is used
}
```

JSON was chosen over a `kind:label:cost:duration:...` colon-separated
format because labels can legitimately contain colons (`"PVG → NRT: 7h"`),
which would force callers to escape — ugly in a one-liner. JSON is
unambiguous, trivially extensible (new fields are non-breaking), and
matches the existing JSON-output style of `arb routes --add`.

### Code touched

- `arb/cli.py`:
  - **NEW** `_parse_leg_payload(raw: str) -> dict` — argparse `type=`
    function. Raises `argparse.ArgumentTypeError` on bad JSON / missing
    fields so argparse exits with code 2 and a clean message instead
    of a stack trace.
  - **NEW** `_replace_route_legs(conn, route_id, legs)` — DELETE then
    INSERT. Used by the re-add path so removed legs actually disappear.
  - `cmd_routes(args)` — `--leg` plumbing:
    - Parses each `--leg` JSON payload, assigns `seq` from CLI order.
    - On new route: calls `db.upsert_route` then `db.add_route_legs`
      (same shape as `seed.seed_all`).
    - On existing route: `_replace_route_legs` (delete + insert).
    - JSON output now includes `"legs": N` so callers can confirm the
      write.
- `tests/test_routes_cli.py` — **8 new tests** (round 11 → 16 total):
  1. `test_cli_routes_add_with_single_leg_inserts_route_and_legs`
  2. `test_cli_routes_add_with_multiple_legs_inserts_in_order`
  3. `test_cli_routes_add_leg_missing_required_field_exits_nonzero`
  4. `test_cli_routes_add_leg_invalid_json_exits_nonzero`
  5. `test_cli_routes_add_without_leg_flag_still_works` (backward compat)
  6. `test_cli_routes_add_with_existing_name_replaces_legs`
  7. `test_cli_routes_add_legs_appear_in_decide_api` (end-to-end:
     CLI insert → `db.list_route_legs` → SPA timeline)
  8. `test_parse_leg_payload_helper_accepts_minimal_payload`
     (unit test for the JSON parser helper)

### Tests
- 216/216 pass (was 208 in round 10, +8 new round-11 tests).
- 0 existing tests modified — Round 8 idempotency contract preserved.
- Real DB state after pytest: unchanged from round 10 (10 opportunities,
  2 routes, 10 legs) — round 11 only adds CLI capability, does not
  insert any seed data.

### Smoke-tested end-to-end
```
$ ARB_DB_PATH=/tmp/arb_demo.sqlite python -m arb routes --add \
    --name DEMO-NRT-HND --origin "东京 NRT" --dest "羽田 HND" \
    --flight 80 --hotel 60 \
    --leg '{"kind":"flight","label":"NRT → HND","cost_usd":80,"duration_min":75,"location":"Tokyo"}' \
    --leg '{"kind":"shop","label":"秋叶原采购","cost_usd":0,"duration_min":180,"location":"Akihabara"}' \
    --leg '{"kind":"flight","label":"HND → NRT","cost_usd":80,"duration_min":75,"location":"Tokyo"}'
{"inserted": 1, "name": "DEMO-NRT-HND", "legs": 3}

$ ARB_DB_PATH=/tmp/arb_demo.sqlite python -m arb routes
  [  1] DEMO-NRT-HND       东京 NRT → 羽田 HND
        flight $80  hotel $60  other $0  (固定 $140)  hours 24h  legs=3 (330min)
        target ROI 15%  min ROI 10%  depart None  url https://www.google.com/travel/flights
```

## Risks / open items for round 12+

- **JSON quoting on Windows shells** — `--leg '{...}'` requires the user
  to escape single quotes inside the JSON, which can break on cmd.exe.
  Round 12 could accept a `@file.json` style alternative (`--leg-file`)
  for complex payloads.
- **`--leg --update` mode** — there's no way to *edit* one leg without
  re-supplying the full set. Round 12 could add `--leg-update <seq>` to
  patch a single leg in place.
- **`arb routes --export <name> --out file.json`** — no way to dump a
  route's legs back to a JSON file. Round 12 could add this so users
  can round-trip a route through `git`.
- **The Dyson loss-making case** (round-7 handoff option b) and the
  SPA route-fixed-cost display (round-7 handoff option c) remain
  unaddressed at the engine / UI level.
- **Subprocess DB coupling** — round 11 CLI subprocess writes to
  `ARB_DB_PATH` env var (existing `arb.db.connect` contract), but
  in-process CLI scripts (e.g. calling `cmd_routes(args)` from Python
  without subprocess) bypass this. No current test does that, but a
  future in-process caller will need to pass `conn` explicitly.

## Next action (exactly one)
Round 12 should pick **one**:
(a) add `arb routes --export <name>` so users can round-trip a route
    through git (dump legs → JSON → edit → re-add with `--leg-file`),
    or
(b) stage the Dyson buy-side proposal (`field=purchase_price_usd`) so
    the engine flips it from "不建议" to "谨慎" (the round-7 pending
    option), or
(c) extend the SPA routepicker to show "$300 fixed / $1040 fixed" next
    to each route (the round-8 lesson made visible without the CLI).