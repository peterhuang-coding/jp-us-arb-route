"""Round 6: stage + apply research proposals + insert 4 new SKUs.

Reads  :data/research/sku_prices_2026-07-26.json` (calibrations) and
``data/research/new_skus_2026-07-26.json`` (new SKUs).  For calibrations,
adds ``proposed_prices`` rows via ``db.add_proposed_price`` then applies
all except the two recommend-reject cases (yamazaki sell + anime sell),
which stay ``pending`` for human review.

The 4 new SKUs are INSERTed with ``verified=1`` and ``data_freshness_ts
= 2026-07-26`` (the brief allows this for freshly-observed market data;
without it the UI would lock them behind an "未验证" warning).

Idempotency
-----------
On rerun, the script detects:
- Existing proposed_prices rows already in 'pending' for the same sku+field
  → skips staging (avoids dup row spam).
- Existing opportunities with the same sku
  → skips INSERT for new SKUs.
- Applied proposals are NOT re-applied.

Run
---
    python3 scripts/apply_research_proposals.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as plain python3 without -m arb.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arb import db  # noqa: E402  (after sys.path mutation)


CALIBRATION_JSON = ROOT / "data" / "research" / "sku_prices_2026-07-26.json"
NEW_SKUS_JSON = ROOT / "data" / "research" / "new_skus_2026-07-26.json"

# Recommended-reject set: keep these as 'pending' so the human can audit.
KEEP_PENDING_SKU_FIELDS = {
    ("JP-WS-YAMAZAKI12", "sell_price_usd"),
    ("JP-ANIME-GK2024", "sell_price_usd"),
}

# Per-SKU overrides for fields not in the research JSON.  These came from
# the research handoff (docs/research-handoff-2026-07-26.md §1.2) where
# only the top-level values were captured.  Keeping them explicit here
# means a rerun with --enrich-new-skus brings already-inserted rows in
# line with the brief.
NEW_SKU_OVERRIDES: dict[str, dict] = {
    "JP-PKMN-151-BB":   {"success_rate": 0.85, "minutes_per_unit": 30.0},
    "JP-CDPB-SERUM-40": {"success_rate": 0.85, "minutes_per_unit": 30.0},
    "JP-ANIME-USJ-NEZ": {"success_rate": 0.70, "minutes_per_unit": 45.0},
    "JP-HADALABO-PREM-400": {"success_rate": 0.90, "minutes_per_unit": 15.0},
}


def _round(value: float, n: int = 2) -> float:
    return round(float(value), n)


def stage_calibration_proposals(conn) -> list[int]:
    """Read calibration JSON and add proposed_prices rows for each drift.

    Skips fields with null proposed values (yamazaki purchase) and skips
    rows that already exist as 'pending' to keep the audit table clean.
    """
    cal = json.loads(CALIBRATION_JSON.read_text(encoding="utf-8"))
    existing = {
        (r["sku"], r["field"]): r
        for r in db.list_proposed_prices(conn, status="pending")
    }
    staged_ids: list[int] = []
    for entry in cal:
        sku = entry["sku"]
        opp = db.get_opportunity(conn, sku)
        if opp is None:
            print(f"  [skip] {sku}: not in opportunities")
            continue
        for field, jpath, url_field in (
            ("purchase_price_usd", "buy_price_usd", "source_jp_url"),
            ("sell_price_usd", "sell_price_usd", "source_us_url"),
        ):
            proposed = entry.get(jpath)
            if proposed is None:
                print(f"  [skip-null] {sku}.{field}: proposed value missing")
                continue
            stored_value = float(opp[field])
            proposed_value = float(proposed)
            if abs(stored_value - proposed_value) < 0.005:
                print(f"  [skip-noop] {sku}.{field}: stored == proposed")
                continue
            if (sku, field) in existing:
                print(f"  [skip-dup] {sku}.{field}: pending row already exists")
                continue
            drift_pct = abs(proposed_value - stored_value) / stored_value * 100
            notes = entry.get("notes", "")
            detected_raw = notes[:60] if notes else f"{field}→{proposed_value}"
            pid = db.add_proposed_price(
                conn,
                opp["id"],
                field,
                stored_value=stored_value,
                proposed_value=proposed_value,
                detected_currency="USD",
                detected_raw=detected_raw,
                source_url=entry[url_field],
                drift_pct=drift_pct,
                status="pending",
            )
            staged_ids.append(pid)
            print(f"  [stage] {sku}.{field}: ${stored_value:.2f} → ${proposed_value:.2f} "
                  f"(drift {drift_pct:.1f}%, id={pid})")
    return staged_ids


def apply_proposals(conn, *, ids: list[int]) -> tuple[int, int]:
    """Apply each pending proposal by id; respect KEEP_PENDING_SKU_FIELDS."""
    applied = 0
    skipped = 0
    for pid in ids:
        row = db.get_proposed_price(conn, pid)
        if row is None:
            print(f"  [miss] proposal {pid}: not found")
            skipped += 1
            continue
        if (row["sku"], row["field"]) in KEEP_PENDING_SKU_FIELDS:
            print(f"  [hold] proposal {pid}: {row['sku']}.{row['field']} "
                  "marked recommend-reject, leaves pending")
            skipped += 1
            continue
        result = db.resolve_proposed_price(conn, pid, "apply")
        if result.get("proposal_status") == "applied":
            applied += 1
            print(f"  [apply] #{pid}: {row['sku']}.{row['field']} → "
                  f"${result['new_value']:.2f}")
        else:
            skipped += 1
            print(f"  [no-apply] #{pid}: {result.get('message')}")
    return applied, skipped


def insert_new_skus(conn) -> list[str]:
    """Insert 4 new SKUs from research JSON; skip ones already present."""
    new_skus = json.loads(NEW_SKUS_JSON.read_text(encoding="utf-8"))
    inserted: list[str] = []
    today = "2026-07-26"
    for s in new_skus:
        sku = s["sku_prefix"]
        if db.get_opportunity(conn, sku) is not None:
            print(f"  [skip-exists] {sku}: already in DB")
            continue
        # Map research fields → opportunities columns
        opp = {
            "sku": sku,
            "name": s["name"],
            "category": s.get("category", "general"),
            "source_market": s["source_market"],
            "target_market": s["target_market"],
            "purchase_price_usd": float(s["buy_price_usd"]),
            "tariff_rate": 0.0,
            "sell_price_usd": float(s["sell_price_usd"]),
            "shipping_per_unit_usd": _round(
                # Heuristic: 13% platform fee assumed in research; keep
                # shipping=$5 per unit for cosmetics/TCG, $10 for goods
                # with larger box.  Use clamp(5, 15).
                min(15.0, max(5.0, float(s["buy_price_usd"]) * 0.10))
            ),
            "platform_fee_rate": 0.13,
            "minutes_per_unit": float(s.get("minutes_per_unit", 30)),
            "success_rate": float(s.get("success_rate", 0.7)),
            "purchase_source_url": s["source_jp_url"],
            "sell_source_url": s["source_us_url"],
            "notes": s.get("rationale", "")[:500],
            "data_freshness_ts": today,
            "verified": 1,
        }
        # Apply per-SKU overrides last so JSON + brief both win.
        for field, val in NEW_SKU_OVERRIDES.get(sku, {}).items():
            opp[field] = val
        cols = list(opp.keys())
        placeholders = ",".join(["?"] * len(cols))
        conn.execute(
            f"INSERT INTO opportunities ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            [opp[c] for c in cols],
        )
        conn.commit()
        inserted.append(sku)
        print(f"  [insert] {sku}: buy=${opp['purchase_price_usd']:.2f} "
              f"sell=${opp['sell_price_usd']:.2f} ship=${opp['shipping_per_unit_usd']:.2f} "
              f"min={opp['minutes_per_unit']:.0f} success={opp['success_rate']:.2f}")
    return inserted


def enrich_new_skus(conn) -> list[str]:
    """Update per-SKU overrides on rows that already exist (idempotent)."""
    enriched: list[str] = []
    for sku, fields in NEW_SKU_OVERRIDES.items():
        opp = db.get_opportunity(conn, sku)
        if opp is None:
            continue
        changes = [
            (f, v) for f, v in fields.items()
            if abs(float(opp[f]) - float(v)) > 0.005
        ]
        if not changes:
            continue
        sets = ",".join(f"{f} = ?" for f, _ in changes)
        conn.execute(
            f"UPDATE opportunities SET {sets} WHERE sku = ?",
            [v for _, v in changes] + [sku],
        )
        conn.commit()
        enriched.append(sku)
        print(f"  [enrich] {sku}: {changes}")
    return enriched


def main() -> int:
    conn = db.connect()
    try:
        print("== Stage calibration proposals ==")
        staged_ids = stage_calibration_proposals(conn)
        # If we already have stage rows from a prior run, fetch them too so
        # apply phase covers every pending row.
        if not staged_ids:
            print("(no new staged; using existing pending)")
            staged_ids = [
                r["id"]
                for r in db.list_proposed_prices(conn, status="pending")
            ]

        print(f"\n== Apply {len(staged_ids)} proposal(s) ==")
        applied, skipped = apply_proposals(conn, ids=staged_ids)
        print(f"\napplied={applied}  kept_pending={skipped}")

        print("\n== Insert 4 new SKUs ==")
        inserted = insert_new_skus(conn)
        print(f"\ninserted={inserted}")

        print("\n== Enrich already-inserted new SKUs ==")
        enriched = enrich_new_skus(conn)
        print(f"\nenriched={enriched}")

        # Final DB summary for visibility
        total = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        applied_p = conn.execute(
            "SELECT COUNT(*) FROM proposed_prices WHERE status='applied'"
        ).fetchone()[0]
        pending_p = conn.execute(
            "SELECT COUNT(*) FROM proposed_prices WHERE status='pending'"
        ).fetchone()[0]
        print(f"\nopportunities={total}  proposals_applied={applied_p}  pending={pending_p}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
