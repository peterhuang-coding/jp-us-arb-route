"""Batch INSERT research-proposed SKUs into the opportunities table.

Loads 4 PM-injected research JSON files and INSERTs new SKUs (skipping any
whose SKU already exists in the DB). Each SKU's platform_fee_rate / minutes
per unit / success_rate are derived from `category` and `confidence`.

Run:
    python3 scripts/insert_research_skus.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arb.db import DB_PATH, connect  # noqa: E402

RESEARCH_DIR = ROOT / "data" / "research"

# Per-category fee / minutes / shipping defaults derived from how each
# marketplace category is actually sold + shipped.
CATEGORY_DEFAULTS = {
    "TCG": {
        "platform_fee_rate": 0.13,
        "shipping_per_unit_usd": 5.0,
        "minutes_per_unit": 10,
    },
    "Sneaker": {
        "platform_fee_rate": 0.09,
        "shipping_per_unit_usd": 15.0,
        "minutes_per_unit": 15,
    },
    "Camera": {
        "platform_fee_rate": 0.08,
        "shipping_per_unit_usd": 25.0,
        "minutes_per_unit": 30,
    },
    "Skincare": {
        "platform_fee_rate": 0.0,
        "shipping_per_unit_usd": 8.0,
        "minutes_per_unit": 5,
    },
    "Fashion": {
        "platform_fee_rate": 0.09,
        "shipping_per_unit_usd": 20.0,
        "minutes_per_unit": 10,
    },
}
CONFIDENCE_TO_SUCCESS = {
    "high": 0.85,
    "medium": 0.70,
    "low": 0.55,
}

# JSON files that contain new SKU candidates (skip price calibrations and ui-references).
FILES = [
    "skincare_2026-07-26.json",
    "jfashion_2026-07-26.json",
    "cameras_2026-07-26.json",
    "tcg_2026-07-26.json",
]

# Explicit blacklist — SKUs whose own research data says don't-buy.
BLACKLIST = {
    "JP-CANON-RF-2470-28",  # ROI -8.4%, US cheaper than JP, agent recommended skip
}


def category_bucket(category: str) -> dict:
    """Map free-form category string to our fee/minutes/shipping defaults."""
    cat = category.lower()
    if "tcg" in cat or "pokemon" in cat or "collectible" in cat:
        return CATEGORY_DEFAULTS["TCG"]
    if "sneaker" in cat or "collab" in cat:
        return CATEGORY_DEFAULTS["Sneaker"]
    if "camera" in cat or "lens" in cat or "drone" in cat or "photography" in cat:
        return CATEGORY_DEFAULTS["Camera"]
    if "skincare" in cat or "makeup" in cat or "cosmetics" in cat:
        return CATEGORY_DEFAULTS["Skincare"]
    if "fashion" in cat or "streetwear" in cat or "denim" in cat or "designer" in cat or "j-fashion" in cat:
        return CATEGORY_DEFAULTS["Fashion"]
    return CATEGORY_DEFAULTS["Skincare"]  # sensible default


def insert_one(conn: sqlite3.Connection, sku: str, d: dict) -> bool:
    """INSERT one SKU, return True if inserted, False if skipped."""
    if sku in BLACKLIST:
        print(f"  skip {sku} (blacklisted — research says don't touch)")
        return False

    cur = conn.execute("SELECT 1 FROM opportunities WHERE sku = ?", (sku,))
    if cur.fetchone() is not None:
        print(f"  skip {sku} (already exists)")
        return False

    cat = category_bucket(d.get("category", ""))
    confidence = d.get("confidence", "medium")
    success_rate = CONFIDENCE_TO_SUCCESS.get(confidence, 0.65)

    notes = (d.get("rationale") or "")[:200]
    conn.execute(
        """
        INSERT INTO opportunities (
            sku, name, category,
            source_market, target_market,
            purchase_price_usd, sell_price_usd, tariff_rate,
            shipping_per_unit_usd, platform_fee_rate,
            minutes_per_unit, success_rate,
            purchase_source_url, sell_source_url,
            data_freshness_ts, verified, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sku,
            d["name"],
            d.get("category", "Other"),
            d.get("source_market", "JP"),
            d.get("target_market", "US"),
            d["buy_price_usd"],
            d["sell_price_usd"],
            0.0,
            cat["shipping_per_unit_usd"],
            cat["platform_fee_rate"],
            cat["minutes_per_unit"],
            success_rate,
            d.get("source_jp_url", ""),
            d.get("source_us_url", ""),
            "2026-07-26",
            1 if confidence == "high" else 0,
            notes,
        ),
    )
    print(f"  inserted {sku} ({d.get('category', '')[:30]}, ROI={d.get('roi_pct_estimate', 0):.1f}%, conf={confidence})")
    return True


def main() -> None:
    conn = connect()
    conn.execute("PRAGMA foreign_keys = ON")

    total_seen = 0
    total_inserted = 0
    for fn in FILES:
        path = RESEARCH_DIR / fn
        if not path.exists():
            print(f"  WARN: {path} not found")
            continue
        items = json.loads(path.read_text(encoding="utf-8"))
        print(f"\n[{fn}] processing {len(items)} SKUs")
        for d in items:
            total_seen += 1
            sku = d.get("sku_prefix", "")
            if not sku:
                continue
            if insert_one(conn, sku, d):
                total_inserted += 1

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
    print(f"\n=== summary ===")
    print(f"  seen: {total_seen}")
    print(f"  inserted: {total_inserted}")
    print(f"  total opportunities: {total}")


if __name__ == "__main__":
    main()
