"""Round 24 (F1) — competitor price fetchers.

Per-source stub fetcher that returns a hard-coded JPY price for the 6
whitelist SKUs.  Designed so a real scraper (PA-API 5 / Rakuten Ichiba /
Yahoo Shopping / Mercari) can drop in by replacing `_stub_price_jpy`.

CLI: ``python -m arb prices fetch --sku JP-SKII-FT230 --source amazon_jp``
"""
from __future__ import annotations

import datetime as _dt
import json
import urllib.request
from typing import Optional

from . import db


# Supported sources
SUPPORTED_SOURCES = ("amazon_jp", "rakuten", "yahoo", "mercari", "manual")

# Reference URL per (sku, source) — would be real ASIN/item URLs in production
SOURCE_URLS: dict[tuple[str, str], str] = {
    ("JP-SKII-FT230", "amazon_jp"): "https://www.amazon.co.jp/dp/B000VOHH8I",
    ("JP-WS-YAMAZAKI12", "amazon_jp"): "https://www.amazon.co.jp/dp/B00KDQ0H4K",
    ("JP-NINTENDO-SWOLED", "amazon_jp"): "https://www.amazon.co.jp/dp/B09XXKZ1BX",
    ("JP-DYSON-V12S", "amazon_jp"): "https://www.amazon.co.jp/dp/B0CFX1JK4L",
    ("JP-LUX-PATEK", "mercari"): "https://jp.mercari.com/search?keyword=Patek+Calatrava",
    ("JP-ANIME-GK2024", "amazon_jp"): "https://www.amazon.co.jp/dp/B0DJ8HJK7Q",
    ("JP-WS-YAMAZAKI12", "rakuten"): "https://search.rakuten.co.jp/search/mall/山崎12年/",
    ("JP-SKII-FT230", "rakuten"): "https://search.rakuten.co.jp/search/mall/SK-II+230ml/",
}


# Stub JPY prices — replace with real scraper.  These are deliberately
# slightly off the seed.py values so the price-diff badge is visible.
STUB_PRICES_JPY: dict[tuple[str, str], float] = {
    ("JP-SKII-FT230", "amazon_jp"): 21500.0,
    ("JP-SKII-FT230", "rakuten"): 19800.0,
    ("JP-SKII-FT230", "yahoo"): 22700.0,
    ("JP-WS-YAMAZAKI12", "amazon_jp"): 11000.0,
    ("JP-WS-YAMAZAKI12", "rakuten"): 10500.0,
    ("JP-NINTENDO-SWOLED", "amazon_jp"): 37980.0,
    ("JP-NINTENDO-SWOLED", "rakuten"): 36500.0,
    ("JP-DYSON-V12S", "amazon_jp"): 69800.0,
    ("JP-ANIME-GK2024", "amazon_jp"): 19800.0,
    ("JP-ANIME-GK2024", "mercari"): 16200.0,
    ("JP-LUX-PATEK", "mercari"): 850000.0,
}


def _stub_price_jpy(sku: str, source: str) -> Optional[float]:
    return STUB_PRICES_JPY.get((sku, source))


# FX: 1 CNY = N JPY (e.g. 20.83).  CC0 source via fawazahmed0 CDN.
DEFAULT_FX_CNY_PER_JPY = 20.83  # 1 CNY ≈ 20.83 JPY (i.e. 1 JPY ≈ 0.048 CNY)


def fetch_fx_cny_per_jpy() -> float:
    """Best-effort FX fetch.  Falls back to DEFAULT if the CDN is unreachable."""
    try:
        today = _dt.date.today().isoformat()
        url = (
            f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@"
            f"{today}/v1/currencies/jpy.json"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        jpy_to_cny = float(data["jpy"]["cny"])
        return 1.0 / jpy_to_cny if jpy_to_cny > 0 else DEFAULT_FX_CNY_PER_JPY
    except Exception:
        return DEFAULT_FX_CNY_PER_JPY


def fetch_one(conn, sku: str, source: str,
              *, fetched_at: Optional[str] = None) -> dict:
    """Fetch one (sku, source) snapshot and persist. Returns the row dict.

    Real implementation would replace _stub_price_jpy with a per-source
    fetcher (PA-API 5 / Rakuten Ichiba / Yahoo Shopping / Mercari).  The
    stub path keeps the system end-to-end testable without credentials.
    """
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported source: {source!r} (allowed: {SUPPORTED_SOURCES})")
    opp = db.get_opportunity(conn, sku)
    if opp is None:
        raise ValueError(f"unknown sku: {sku!r}")
    price_jpy = _stub_price_jpy(sku, source)
    if price_jpy is None:
        raise ValueError(f"no stub for {sku}/{source}; add a real fetcher")
    fx = fetch_fx_cny_per_jpy()
    price_cny = round(price_jpy / fx, 2)
    fetched_at = fetched_at or _dt.datetime.now().isoformat(timespec="seconds")
    row = dict(
        opportunity_id=opp["id"],
        sku=sku,
        source=source,
        price_jpy=price_jpy,
        price_cny=price_cny,
        fx_rate_at_fetch=fx,
        fx_source="fawazahmed0" if fx != DEFAULT_FX_CNY_PER_JPY else "manual",
        url=SOURCE_URLS.get((sku, source)),
        fetched_at=fetched_at,
    )
    row_id = db.upsert_competitor_price(conn, row)
    row["id"] = row_id
    return row


def fetch_all(conn, *, sku: Optional[str] = None) -> list[dict]:
    """Fetch every (sku, source) pair for the 6 whitelist SKUs (or one sku).

    Returns a list of inserted row dicts.  Skips (sku, source) pairs without
    a stub price (so calling without a full price table is non-fatal).
    """
    target_skus = [sku] if sku else [
        "JP-SKII-FT230", "JP-WS-YAMAZAKI12", "JP-NINTENDO-SWOLED",
        "JP-DYSON-V12S", "JP-LUX-PATEK", "JP-ANIME-GK2024",
    ]
    out = []
    for s in target_skus:
        for src in SUPPORTED_SOURCES:
            if (s, src) in STUB_PRICES_JPY:
                try:
                    out.append(fetch_one(conn, s, src))
                except ValueError as e:
                    # Skip silently — caller can inspect unfetched pairs in logs
                    continue
    return out


def price_diff_cny(conn, sku: str, source: str) -> dict | None:
    """Compare latest competitor snapshot vs stored purchase_price_usd.

    Returns dict with sku, source, snapshot_cny, stored_cny, diff_pct,
    or None if no snapshot exists yet.
    """
    opp = db.get_opportunity(conn, sku)
    if opp is None:
        return None
    snap = db.latest_competitor_price(conn, sku, source)
    if snap is None:
        return None
    stored_cny = float(opp["purchase_price_usd"]) * 7.14
    diff_pct = (float(snap["price_cny"]) - stored_cny) / stored_cny * 100
    return {
        "sku": sku,
        "source": source,
        "snapshot_cny": float(snap["price_cny"]),
        "snapshot_jpy": float(snap["price_jpy"]),
        "stored_cny": round(stored_cny, 2),
        "diff_pct": round(diff_pct, 2),
        "fetched_at": snap["fetched_at"],
    }
