# Round 6 Handoff — research data applied + scratch DB fixture fixed

**Date**: 2026-07-26
**Branch**: pm-loop/20260726-103909-jp-us-arb-route-55490
**Author**: PM Agent (round 6)

## What changed

### Behavior
- 6 whitelist SKUs got **real-market price calibrations** via the
  `proposed_prices` approval flow (audit trail preserved, no direct
  UPDATEs to `opportunities`):
  - `JP-SKII-FT230`        buy $85→$150, sell $145→$185 (Fa-So-La / Amazon US)
  - `JP-NINTENDO-SWOLED`   buy $270→$319.87, sell $360→$399.99 (Yodobashi / Amazon US)
  - `JP-DYSON-V12S`        buy $510→$593.33, sell $620→$649.99 (Dyson JP / US)
  - `JP-LUX-PATEK`         buy $8200→$6333.33, sell $11500→$7800 (BrandOff / Chrono24)
  - `JP-ANIME-GK2024`      buy $175→$198.67, sell $290→$290 (kept) — see held below
- 2 sales-price proposals **held pending** for human review (research
  flagged these as confidence=low / losing-money):
  - `JP-WS-YAMAZAKI12.sell_price_usd`: proposed $120 vs stored $320 (drift
    −62.5%) — Yamazaki 12 yr is effectively discontinued for arbitrage.
  - `JP-ANIME-GK2024.sell_price_usd`: proposed $150 vs stored $290 (drift
    −48.3%) — applying would flip the SKU from profit to loss.
  - Bash to review: `python3 -m arb.cli proposals --status pending`
- 4 **new SKUs** inserted from `data/research/new_skus_2026-07-26.json`,
  all `verified=1` with `data_freshness_ts=2026-07-26`:
  - `JP-PKMN-151-BB`      (Pokémon Card 151 Booster Box, ROI est. ~107% per-unit)
  - `JP-CDPB-SERUM-40`    (Cle de Peau Beauté The Serum 40ml, ROI est. ~33%)
  - `JP-ANIME-USJ-NEZ`    (Demon Slayer USJ Limited Popcorn Bucket, ROI est. ~63%)
  - `JP-HADALABO-PREM-400`(Hada Labo Premium Lotion 400ml refill, ROI est. ~5%)
- Per-SKU overrides for `success_rate` + `minutes_per_unit` (not in
  research JSON) added via `NEW_SKU_OVERRIDES` in the apply script.

### Test fixture (latent bug, fixed)
- **Before round 6**: `tests/test_cli.py::scratch_db` ran
  `subprocess.check_call([sys.executable, "-m", "arb", "seed"], ...)` to
  seed a tmp DB.  But monkeypatch on `arb.db.DB_PATH` only affects the
  parent test process — the subprocess inherited the original
  `data/db.sqlite`.  So the seed call was clobbering the **real** DB on
  every `pytest` run.  After my `apply_research_proposals.py`, running
  pytest reset all 6 SKUs to their original seeded values, undoing the
  research effort.
- **Fix**:
  - Added `ARB_DB_PATH` env var override to `arb.db.connect()`.  Tests
    set this env var; CLI now respects the override even inside
    subprocesses.
  - Refactored `scratch_db` fixture to seed in-process via
    `arb_seed.seed_all()` instead of shelling out, and to set
    `ARB_DB_PATH` for the subprocess CLI.
- Net effect: `pytest` no longer touches the real DB; round-6 research
  data persists across re-runs.

### Tests
- 22/22 `tests/test_cli.py` pass.
- 189/189 total pass (no change from round 5's 189).
- Real DB state after pytest:
  - `opportunities`: 10 (vs. round-5 6).
  - `proposed_prices`: 18 applied, 2 pending.
- `python3 -m arb.cli list` → lists all 10 SKUs with calibrated prices.

## Files touched
- `scripts/apply_research_proposals.py` (new, 232 lines)
- `arb/db.py` (`connect()` now reads `ARB_DB_PATH`)
- `tests/test_cli.py` (`scratch_db` fixture + subprocess env passing)
- `data/research/{sku_prices,new_skus,ui_references}_2026-07-26.json`
  (staged but not authored — these came from the round-5 PM handoff)
- `docs/research-handoff-2026-07-26.md` (PM handoff doc, staged)
- `docs/round-6-handoff.md` (this file)

## Verification
```
$ sqlite3 data/db.sqlite "SELECT COUNT(*) FROM opportunities;"
10
$ sqlite3 data/db.sqlite "SELECT COUNT(*), status FROM proposed_prices GROUP BY status;"
18|applied
2|pending
$ python3 -m pytest tests/ -q
189 passed in 14.14s
$ python3 -m arb.cli list                # 10 SKUs printed
$ python3 -m arb.cli decide --sku JP-PKMN-151-BB --units 3 --route PVG-NRT-LAX-2N
```
The CLI surfaces the **net** trip ROI (flight + hotel + labor factored
in), which is negative at low unit counts because the route costs
dominate.  Per-unit gross margin on Pokémon 151 is `$80.50 / ($45 + $30)
= 107.3%`, well above the brief's 50% threshold; the engine reports it
correctly at the trip level.  See `三档情景` panel for 保守/中性/乐观
sensitivity.

## Risks / open items for round 7+
- **Yamazaki 12 + Anime Gojo sell prices stay at stored values**
  ($320 / $290).  In real conditions these SKUs are losing-money or
  out-of-stock, so the current DB inflates their ROI.  Round 7 should
  decide apply-vs-reject for proposals #3 and #11 (currently pending);
  applying either would flip the relevant SKU to "不建议" in the engine,
  which is the *honest* answer per the research confidence=low / lose-money
  notes.
- **Decision-engine net-trip assumption**: with the canonical
  PVG→NRT→LAX→2N route (flight $690 + hotel $240 = $930 fixed), most
  6-whitelist SKUs only break even at ≥5–10 units.  Round 7+ might want
  to add a "cheaper regional" route (e.g., LAX↔SFO domestic hop)
  showing how ROI changes on a low-fixed-cost leg, so the user can see
  that the route choice is as important as the SKU choice.
- **scratch_db env propagation**: the new `ARB_DB_PATH` resolution is
  read at `connect()` call time, not at module import time, so CLI
  subcommands that look up `DB_PATH` directly (none today, but worth
  grepping) could leak.  Quick grep for `DB_PATH` shows only the
  scratch fixture touches it.  If a new code path materializes, route
  it through `connect()` instead.

## Next action (exactly one)
Run `python3 -m arb.cli proposals --status pending` to triage the two
held proposals; apply or reject each, then commit a small round-7
proposal-resolution commit on this branch.
