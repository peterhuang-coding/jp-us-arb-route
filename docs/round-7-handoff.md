# Round 7 Handoff — pending proposals resolved (apply both, honest 不建议)

**Date**: 2026-07-26
**Branch**: pm-loop/20260726-103909-jp-us-arb-route-55490
**Author**: PM Agent (round 7)

## What changed

### Behavior — two pending proposals applied
Both held proposals from round 6 were research-flagged
`confidence=low` / losing-money. Round-7 applies both so the engine
surfaces the *honest* verdict (per the round-6 next-action note and
the brief's "decision-engine honesty" principle):

| SKU | field | stored → proposed | new sell | new engine verdict @ 1u/5u/20u/50u |
|---|---|---|---|---|
| `JP-WS-YAMAZAKI12` | `sell_price_usd` | $320.00 → $120.00 (-62.5%) | $120.00 | 不建议 / 不建议 / 不建议 / 不建议 |
| `JP-ANIME-GK2024`   | `sell_price_usd` | $290.00 → $150.00 (-48.3%) | $150.00 | 不建议 / 不建议 / 不建议 / 不建议 |

Before applying, `JP-WS-YAMAZAKI12` was ROI-positive at `units=20`
(breakeven $288 < stored $320 → "谨慎").  After applying it is
"不建议" across all unit counts, because breakeven ($288 at 20u) is
still well above the new $120 sell price.  This is the correct
"research vs engine consistency" outcome — round-6 left both pending
precisely because applying them *intentionally* flips the SKU to
"不建议" so the user is not misled by an inflated DB sell price.

### DB state
```
opportunities:        10 rows  (6 calibrated + 4 new-SKU inserts from round 6)
proposed_prices:      20 applied, 0 pending, 0 rejected  (was: 18 applied, 2 pending)
```

Both newly-applied rows have a `resolved_at` timestamp (round-7 date)
and the parent opportunity's `data_freshness_ts` was bumped to today.

### Code touched
None.  No production code changed in round 7 — `arb.db.resolve_proposed_price`
already implements the apply/reject lifecycle correctly.  The change
is in the DB *state*, plus a new regression test file.

### Tests added (`tests/test_proposal_resolution.py`, 6 new)
1. `test_apply_proposal_overwrites_parent_price` — apply flips
   `proposed_prices.status=applied`, overwrites `opportunities.sell_price_usd`,
   bumps `data_freshness_ts`.
2. `test_apply_proposal_drives_honest_no_for_yamazaki` — after apply
   at $120, `judge()` returns `不建议` for units ∈ {1, 5, 20, 50}
   and `breakeven > new sell_price` for all.
3. `test_apply_proposal_drives_honest_no_for_anime_gojo` — same
   contract for `JP-ANIME-GK2024` at $150.
4. `test_reject_proposal_leaves_parent_unchanged` — reject does
   *not* touch `opportunities.sell_price_usd` or `data_freshness_ts`.
5. `test_apply_is_idempotent_for_non_pending` — re-applying an
   `applied` row is a no-op (returns `applied=False`,
   `message="proposal already applied"`).
6. `test_apply_unknown_proposal_returns_not_found` — id `99999` →
   `{applied: false, message: "not found"}`.

All 195 tests pass (was 189 in round 6, +6 new).

## Risks / open items for round 8+
- **Two whitelist SKUs now permanently read "不建议"**.  Per the brief
  ("不为代购/二手再销售做教程") the user can still buy these for personal
  use, but the engine will not recommend an arbitrage trip.  If a
  round-8 research refresh brings Yamazaki 12 / Gojo 1/7 back to
  $250+ retail with confidence=high, a *new* proposal (with a fresh
  drift row) can flip them again without touching old history.
- **`JP-DYSON-V12S` was already loss-making at stored prices** (per-unit
  net `$-52.84`) — round-6 hand-off did not stage a proposal for this
  one because it's a purchase-side issue, not a sell-side drift.
  Round 8 may want to stage a buy-side proposal (field=`purchase_price_usd`)
  if research confirms a cheaper JP-side pickup source.
- **`test_apply_proposal_overwrites_parent_price` does not pin a
  specific `data_freshness_ts`** because the function uses
  `_dt.date.today().isoformat()`.  Acceptable for a unit test, but if
  downstream code starts to assert exact dates this will need to be
  adjusted (or freeze `today` via monkeypatch).

## Next action (exactly one)
After this commit lands, round 8 should pick **one** of:
(a) extend `arb.refresh` to retry any `proposed_prices` row older
    than 30 days so the queue self-cleans, or
(b) add a `arb.cli purchase-proposal` path so future rounds can also
    stage `purchase_price_usd` drift (Dyson loss-making case above),
    or
(c) move on to the "cheaper regional route" idea from round 6 — add a
    `routes` row like `LAX-SFO-1N` so the user can see that route
    choice matters as much as SKU choice.
