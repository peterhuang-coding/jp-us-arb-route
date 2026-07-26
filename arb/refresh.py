"""Refresh coordinator: tie freshness + scraper together for the /refresh endpoint.

The watchdog contract is intentionally tiny in V0:

  * ``refresh_opportunity(conn, sku, *, scraper_kwargs=None)`` returns a
    ``RefreshOutcome`` describing what happened — no exceptions bubble up.
  * The DB is updated ONLY when the scrape succeeded (so we don't claim a
    "fresh" ts for an opp whose URLs are dead).
  * Prices are NOT auto-overwritten in V0 — the brief calls for "manual +
    semi-automatic" data entry, and a half-correct auto-update is worse than
    no update.  The endpoint returns ``price_hints`` so the UI can show
    "found USD 145 on amazon.com — verify before adopting".

Why this lives in its own module: ``web_api`` and ``cli`` both call it, and
having a single place to change the policy later (per-site parsers, partial
overwrite, optimistic vs conservative update) keeps both surfaces in sync.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Optional

from . import db, freshness, scraper


@dataclass
class UrlProbe:
    url: Optional[str]
    ok: bool
    status: int
    blocked_reason: Optional[str]
    price_hints: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass
class RefreshOutcome:
    sku: str
    name: str
    previous_freshness_ts: Optional[str]
    new_freshness_ts: Optional[str]      # None when nothing changed
    updated: bool                        # True iff DB row was touched
    verdict_before: dict
    verdict_after: Optional[dict]        # None when not updated
    purchase: Optional[UrlProbe]
    sell: Optional[UrlProbe]
    message: str


def _probe(url: Optional[str], **kwargs) -> Optional[UrlProbe]:
    if not url:
        return None
    page = scraper.fetch_url(url, **kwargs)
    hints = scraper.extract_price_hints(page.text or "") if page.text else []
    return UrlProbe(
        url=url,
        ok=page.ok,
        status=page.status,
        blocked_reason=page.blocked_reason,
        price_hints=hints,
        elapsed_ms=page.elapsed_ms,
    )


def refresh_opportunity(
    conn,
    sku: str,
    *,
    today: Optional[_dt.date] = None,
    scraper_kwargs: Optional[dict] = None,
) -> RefreshOutcome:
    """Probe an opportunity's URLs and bump freshness if both probes succeeded.

    Args:
        conn:        sqlite3 connection (callers are responsible for closing).
        sku:         the opportunity to refresh.
        today:       override "now" for tests.
        scraper_kwargs: forwarded to ``scraper.fetch_url`` (timeout, ua, ...).

    Returns:
        :class:`RefreshOutcome` describing what happened.  No exceptions bubble
        out — the watchdog never crashes a request.
    """
    today = today or _dt.date.today()
    kw = dict(scraper_kwargs or {})

    opp = db.get_opportunity(conn, sku)
    if opp is None:
        # Mirror CLI behaviour: empty record, message explains.
        return RefreshOutcome(
            sku=sku, name="(unknown)", previous_freshness_ts=None,
            new_freshness_ts=None, updated=False,
            verdict_before={"status": "missing", "badge": "⚠️ 数据缺失"},
            verdict_after=None, purchase=None, sell=None,
            message=f"opportunity not found: {sku}",
        )

    verdict_before = freshness.classify(opp["data_freshness_ts"], today=today, sku=sku).as_dict()
    purchase = _probe(opp["purchase_source_url"], **kw)
    sell = _probe(opp["sell_source_url"], **kw)

    both_ok = (
        (purchase is None or purchase.ok)
        and (sell is None or sell.ok)
        and (purchase is not None or sell is not None)  # at least one URL exists
    )

    if not both_ok:
        return RefreshOutcome(
            sku=sku, name=opp["name"], previous_freshness_ts=opp["data_freshness_ts"],
            new_freshness_ts=None, updated=False,
            verdict_before=verdict_before, verdict_after=None,
            purchase=purchase, sell=sell,
            message=("至少一条 URL 抓取失败,未更新 freshness_ts;请人工复核。" if (
                (purchase is not None and not purchase.ok) or
                (sell is not None and not sell.ok)
            ) else "无 URL 可抓取,未更新。"),
        )

    new_ts = today.isoformat()
    db.upsert_opportunity(conn, dict(opp, data_freshness_ts=new_ts))
    verdict_after = freshness.classify(new_ts, today=today, sku=sku).as_dict()

    return RefreshOutcome(
        sku=sku, name=opp["name"], previous_freshness_ts=opp["data_freshness_ts"],
        new_freshness_ts=new_ts, updated=True,
        verdict_before=verdict_before, verdict_after=verdict_after,
        purchase=purchase, sell=sell,
        message="已更新 freshness_ts;价格未自动写入,请人工核对 price_hints 后再覆盖。",
    )


def _probe_to_dict(p: Optional[UrlProbe]) -> Optional[dict]:
    if p is None:
        return None
    return {
        "url": p.url,
        "ok": p.ok,
        "status": p.status,
        "blocked_reason": p.blocked_reason,
        "price_hints": p.price_hints,
        "elapsed_ms": p.elapsed_ms,
    }


def outcome_as_dict(o: RefreshOutcome) -> dict:
    return {
        "sku": o.sku,
        "name": o.name,
        "previous_freshness_ts": o.previous_freshness_ts,
        "new_freshness_ts": o.new_freshness_ts,
        "updated": o.updated,
        "verdict_before": o.verdict_before,
        "verdict_after": o.verdict_after,
        "purchase": _probe_to_dict(o.purchase),
        "sell": _probe_to_dict(o.sell),
        "message": o.message,
    }