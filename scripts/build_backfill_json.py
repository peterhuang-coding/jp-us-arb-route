"""Build home_price_cny JSON for backfill.

Reads arb/seed.py + arb/seed.sqlite research data and produces a JSON file
of {sku, home_price_cny, max_units_per_trip?, source?} for SKUs whose
home_price_cny is currently NULL.

Heuristics (rough — meant to be hand-edited):
  - Prestige skincare / prestige makeup: target 40-70% markup over JP USD
  - Camera lens / body: target 10-25% markup (China gray market premium)
  - J-Fashion streetwear (HUMANMADE/CE/WTAPS): 2-3x markup (China has no
    direct retail, mostly daigou)
  - Premium J-Fashion (Visvim/Kapital/Sacai): 1.5-2x markup
  - TCG sealed/mystery: 1.5-2x (China TCG active, but limited supply)
  - TCG PSA-graded: ~5-8x markup vs raw JP card price (PSA 10 in China
    is rare + grading fee comparable)
  - Drone (DJI): 1.1x markup (China retail cheaper than JP gray!)
  - Appliances (Dyson): 1.05x (essentially at parity)
  - Spirits (whisky): 0.7x (China has higher import duty + lighter demand)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/Volumes/SanDisk2TB/jp-us-arb-route")
sys.path.insert(0, str(ROOT))

from arb.db import connect  # noqa: E402

# Heuristic multipliers by category substring.
# Use the FIRST matching key; order matters.
CATEGORY_RULES = [
    ("Camera Body",        1.15),  # full-frame mirrorless, China gray
    ("Camera Lens",        1.20),
    ("Drone",              1.05),  # DJI is Chinese; JP slightly pricier
    ("TCG / Graded",       6.0),   # PSA-graded singles: huge China scarcity
    ("TCG",                1.7),   # sealed/mystery/raw
    ("Prestige Skincare",  1.3),   # CPB/POLA/ALBION 在中国专柜正常零售价
    ("Prestige Makeup",    1.4),   # SUQQU/Three 等中高端彩妆
    ("J-Fashion Premium",  1.7),   # Visvim/Kapital/Sacai
    ("J-Fashion Sneaker",  1.8),
    ("J-Fashion / Avant",  1.4),
    ("J-Fashion / Cyberpunk", 2.2),
    ("J-Fashion / Military",  2.5),
    ("J-Fashion / Streetwear Nigo", 2.8),
    ("J-Fashion / Vintage Denim", 1.6),
    ("J-Fashion / Designer Basics", 1.5),
    ("Limited Anime",      2.5),  # park goods
    ("anime_collectibles", 2.5),
]

# Conservative CNY→USD FX (matches seed default 0.14 = USD per CNY; i.e. CNY per USD = 7.14).
FX_CNY_PER_USD = 7.14


def home_price(sell_usd: float, category: str) -> float:
    """Compute a rough home_price_cny from the JP sell price (USD) and category."""
    for needle, mult in CATEGORY_RULES:
        if needle in category:
            return round(sell_usd * FX_CNY_PER_USD * mult, 2)
    # Fallback: 1.3x JP price
    return round(sell_usd * FX_CNY_PER_USD * 1.3, 2)


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--category-contains", action="append", default=[],
                   help="only emit rows whose category contains this substring (repeatable)")
    p.add_argument("--only-null", action="store_true",
                   help="skip rows that already have home_price_cny set")
    args = p.parse_args()
    conn = connect()
    sql = "SELECT sku, category, sell_price_usd, purchase_price_usd, home_price_cny FROM opportunities"
    if args.only_null:
        sql += " WHERE home_price_cny IS NULL"
    sql += " ORDER BY sku"
    rows = conn.execute(sql).fetchall()
    payload = []
    for r in rows:
        if args.category_contains and not any(c in r["category"] for c in args.category_contains):
            continue
        h = home_price(r["sell_price_usd"], r["category"])
        payload.append({
            "sku": r["sku"],
            "home_price_cny": h,
            "source": f"rough-heuristic {r['category'][:25]}/sell=${r['sell_price_usd']:.0f}*7.14",
        })
    print(f"# {len(payload)} rows selected", file=sys.stderr)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    print("", file=sys.stderr)


if __name__ == "__main__":
    main()