"""Round 24 (F2) — price-difference alerts + Discord webhook.

For each enabled alert config, scan the latest competitor_prices snapshot
and compute diff vs the stored purchase_price_usd.  When the absolute diff
exceeds threshold_pct, emit a webhook POST to DISCORD_WEBHOOK_URL (if set)
and update the alert's last_triggered_at.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from . import db
from .prices import price_diff_cny


def evaluate_alerts(conn, *, sku: Optional[str] = None) -> list[dict]:
    """For each enabled alert, compare latest snapshot vs stored price.

    Returns a list of triggered alerts: [{sku, source, threshold_pct,
    snapshot_cny, stored_cny, diff_pct, fetched_at}], plus triggers a
    Discord webhook if DISCORD_WEBHOOK_URL is set.
    """
    alerts = db.list_price_alerts(conn, sku=sku, enabled_only=True)
    triggered: list[dict] = []
    for alert in alerts:
        diff = price_diff_cny(conn, alert["sku"], alert["source"])
        if diff is None:
            continue
        if abs(diff["diff_pct"]) < float(alert["threshold_pct"]):
            continue
        # Trigger
        db.mark_alert_triggered(conn, alert["sku"], alert["source"])
        triggered.append({**diff, "threshold_pct": float(alert["threshold_pct"])})
    if triggered:
        _emit_discord(triggered)
    return triggered


def _emit_discord(triggered: list[dict]) -> None:
    """POST a Discord webhook summary.  No-op if env not set."""
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return
    lines = ["**价差报警** (jp-us-arb-route)"]
    for t in triggered:
        arrow = "📈" if t["diff_pct"] > 0 else "📉"
        lines.append(
            f"{arrow} {t['sku']} @ {t['source']}: "
            f"¥{t['snapshot_cny']:.0f} vs ¥{t['stored_cny']:.0f} "
            f"({t['diff_pct']:+.1f}%, 阈值 {t['threshold_pct']:.0f}%)"
        )
    payload = json.dumps({"content": "\n".join(lines)}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        # Webhook failure is non-fatal — caller still has triggered list.
        pass


def setup_default_alerts(conn, threshold_pct: float = 5.0) -> int:
    """Seed 6 SKUs × 4 sources alerts with the given threshold.  Returns count."""
    sources = ("amazon_jp", "rakuten", "yahoo", "mercari")
    skus = ("JP-SKII-FT230", "JP-WS-YAMAZAKI12", "JP-NINTENDO-SWOLED",
            "JP-DYSON-V12S", "JP-LUX-PATEK", "JP-ANIME-GK2024")
    n = 0
    for sku in skus:
        for src in sources:
            db.upsert_price_alert(conn, dict(
                sku=sku, source=src, threshold_pct=threshold_pct, enabled=1,
                notes="default 5% threshold",
            ))
            n += 1
    return n
