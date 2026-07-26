"""Verified-badge coordinator: turns price_hints into `verified=1` or a proposal.

Brief §6 (risk #4 + #8) — round 3 left a hook here: "manual + semi-automatic"
data entry means prices never auto-overwrite, but a *signal* that the stored
price still matches reality is the highest-leverage next step because the UI
already shows "⚠️ 未验证" on every seed row.

Round 4 ships that signal:

  1. ``parse_price_from_hints`` — pure: pick the best hint matching an expected
     currency, or the first hint when no expectation is set.  Returns the
     ``(amount, currency, raw)`` triple so the caller can display provenance.
  2. ``compare_price`` — pure: drift_pct = abs(extracted - stored) / stored.
  3. ``verify_opportunity`` — coordinator that runs ``refresh`` first (so we
     never ``verified=1`` a row whose URL is dead), then compares both sides,
     then either marks ``verified=1`` (both sides within tolerance) or stages
     ``proposed_prices`` rows for the drifting sides.

Currency mismatch (e.g., scraped hint is JPY but stored price is USD) is
handled by treating the mismatch as a proposal — the user gets a visible cue
that an FX-aware recheck is needed.  We do NOT silently drop the hint.

Why this lives in its own module (parallel to ``refresh``): ``web_api`` and
``cli`` both call it, and ``verify`` itself calls ``refresh`` so a future
round can swap the policy (per-site parsers, optimistic vs conservative
update, FX conversion) without breaking either surface.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Iterable, Optional

from . import db, freshness, refresh


DEFAULT_TOLERANCE: float = 0.05    # ±5% — round 3 handoff's chosen threshold


# ---------- pure helpers ----------

def parse_price_from_hints(
    hints: Optional[Iterable[dict]],
    *,
    expected_currency: Optional[str] = None,
) -> Optional[dict]:
    """Pick the best hint out of a list returned by ``scraper.extract_price_hints``.

    Returns ``{"amount": float, "currency": str, "raw": str}`` or ``None``.

    Selection rule:
      * If ``expected_currency`` is set: return the first hint whose currency
        matches (case-insensitive).  Mismatch = no match.
      * Otherwise: return the first hint (most-visible-looking wins).
      * Empty / None input returns ``None`` (NOT an error).
    """
    if not hints:
        return None
    for h in hints:
        if not isinstance(h, dict):
            continue
        amt = h.get("amount")
        cur = h.get("currency") or "?"
        raw = h.get("raw") or ""
        if not isinstance(amt, (int, float)):
            continue
        if expected_currency and cur.upper() != expected_currency.upper():
            continue
        return {"amount": float(amt), "currency": cur, "raw": raw}
    return None


def compare_price(extracted: Optional[float], stored: Optional[float]) -> Optional[float]:
    """Return drift_pct = abs(extracted - stored) / stored * 100, or None.

    ``None`` for either input → ``None`` (no signal — caller treats as skip).
    ``stored <= 0`` → ``None`` (avoid divide-by-zero; brief disallows this
    anyway via the decision validator but defensive here too).
    """
    if extracted is None or stored is None:
        return None
    if stored <= 0:
        return None
    return abs(extracted - stored) / stored * 100.0


def within_tolerance(drift_pct: Optional[float], tolerance: float = DEFAULT_TOLERANCE) -> bool:
    """True iff drift_pct is not None and within the tolerance (interpreted as a fraction, e.g. 0.05)."""
    if drift_pct is None:
        return False
    return drift_pct <= tolerance * 100.0


# ---------- coordinator dataclasses ----------

@dataclass
class SideCheck:
    field: str                         # 'purchase_price_usd' | 'sell_price_usd'
    stored_value: float
    source_url: Optional[str]
    extracted: Optional[dict]          # {amount, currency, raw} | None
    drift_pct: Optional[float]         # None when no extract / mismatch
    accepted: bool                     # drift_pct within tolerance
    proposal_id: Optional[int]         # set when staged
    note: str                          # human explanation


@dataclass
class VerifyOutcome:
    sku: str
    name: str
    refresh_updated: bool
    refreshed_at: Optional[str]        # ISO date of freshness_ts post-refresh
    purchase: SideCheck
    sell: SideCheck
    verified_now: bool                 # True iff both sides accepted
    final_verified: bool               # DB value after this call
    final_freshness_ts: Optional[str]
    message: str


# ---------- coordinator ----------

def verify_opportunity(
    conn,
    sku: str,
    *,
    refresh_outcome: Optional[refresh.RefreshOutcome] = None,
    tolerance: float = DEFAULT_TOLERANCE,
    today: Optional[_dt.date] = None,
    scraper_kwargs: Optional[dict] = None,
    auto_stage: bool = True,
) -> VerifyOutcome:
    """Compare refreshed price_hints to the stored prices; mark verified or stage.

    Args:
        conn:             sqlite3 connection; updated in place when verified or staged.
        sku:              opportunity to verify.
        refresh_outcome:  reuse a fresh refresh (skips re-fetching).  When ``None``,
                          a refresh is run first — *never* verify a row whose URL
                          is dead, because that would mask a stale price.
        tolerance:        drift fraction (0.05 = 5%).  Defaults to the round-3 hook.
        today:            override "now" for tests.
        scraper_kwargs:   forwarded to ``scraper.fetch_url`` when we have to refresh.
        auto_stage:       when True, insert proposed_prices rows for drift > tol.
                          Set False (e.g., from CLI --dry-run) to report-only.

    Returns:
        :class:`VerifyOutcome` — never raises.  Unknown SKU returns a
        ``VerifyOutcome`` whose ``message`` starts with "opportunity not found".
    """
    today = today or _dt.date.today()
    today_str = today.isoformat()

    opp = db.get_opportunity(conn, sku)
    if opp is None:
        return _unknown_sku_outcome(sku)

    # 1. Refresh (or reuse) — URLs must be live before we certify a price.
    if refresh_outcome is None:
        refresh_outcome = refresh.refresh_opportunity(
            conn, sku, today=today, scraper_kwargs=scraper_kwargs,
        )
        # refresh_opportunity already committed (it calls upsert_opportunity).
        # Re-read so we see the new data_freshness_ts.
        opp = db.get_opportunity(conn, sku)
        if opp is None:
            return _unknown_sku_outcome(sku)

    if not refresh_outcome.updated:
        # URL dead — surface the message but DO NOT mark verified.
        return VerifyOutcome(
            sku=sku, name=opp["name"],
            refresh_updated=False, refreshed_at=None,
            purchase=_skip_side("purchase_price_usd", opp,
                                refresh_outcome.purchase),
            sell=_skip_side("sell_price_usd", opp,
                            refresh_outcome.sell),
            verified_now=False, final_verified=bool(opp["verified"]),
            final_freshness_ts=opp["data_freshness_ts"],
            message=("URL 抓取未成功,无法验证。" + refresh_outcome.message),
        )

    # 2. Compare each side.
    purchase = _check_side(
        conn, opp, "purchase_price_usd",
        hints=refresh_outcome.purchase.price_hints if refresh_outcome.purchase else None,
        tolerance=tolerance, today=today_str, auto_stage=auto_stage,
    )
    sell = _check_side(
        conn, opp, "sell_price_usd",
        hints=refresh_outcome.sell.price_hints if refresh_outcome.sell else None,
        tolerance=tolerance, today=today_str, auto_stage=auto_stage,
    )

    # 3. If both sides accepted → mark verified=1 and bump ts (refresh already
    #    bumped; we re-affirm).
    both_accepted = purchase.accepted and sell.accepted
    final_verified = bool(opp["verified"])
    final_ts = opp["data_freshness_ts"]
    if both_accepted:
        db.upsert_opportunity(conn, dict(opp, verified=1))
        final_verified = True
        # refresh already wrote today's ts; only overwrite if it's still missing.
        if not final_ts:
            db.upsert_opportunity(conn, dict(opp, verified=1, data_freshness_ts=today_str))
            final_ts = today_str

    proposals_added = sum(1 for s in (purchase, sell) if s.proposal_id is not None)
    if both_accepted:
        msg = f"已验证:采购 / 售价 均在容差内 (±{tolerance*100:.1f}%)。"
    elif proposals_added:
        msg = (f"价格漂移超出容差 ±{tolerance*100:.1f}%;已 stage "
               f"{proposals_added} 条提案至 proposed_prices 表(未自动覆盖价格)。")
    else:
        msg = "未抓取到可比较的价格提示,保持未验证状态。"

    return VerifyOutcome(
        sku=sku, name=opp["name"],
        refresh_updated=True, refreshed_at=today_str,
        purchase=purchase, sell=sell,
        verified_now=both_accepted, final_verified=final_verified,
        final_freshness_ts=final_ts,
        message=msg,
    )


# ---------- helpers ----------

def _check_side(conn, opp, field: str, *, hints, tolerance: float,
                today: str, auto_stage: bool) -> SideCheck:
    stored = float(opp[field])
    # Always take the first hint so we can detect currency-mismatch too;
    # the currency check happens AFTER parsing.
    extracted = parse_price_from_hints(hints)
    source_url = (opp["purchase_source_url"] if field == "purchase_price_usd"
                  else opp["sell_source_url"])
    drift = compare_price(extracted["amount"] if extracted else None, stored)
    accepted = within_tolerance(drift, tolerance)
    proposal_id: Optional[int] = None
    note: str
    if extracted is None:
        note = "未抓到该侧的有效价格提示"
    elif extracted["currency"].upper() != "USD":
        # Currency mismatch — can't compare apples to apples; stage a proposal
        # so a human sees that FX-aware recheck is required.
        if auto_stage:
            proposal_id = db.add_proposed_price(
                conn, opp["id"], field,
                stored_value=stored,
                proposed_value=extracted["amount"],
                detected_currency=extracted["currency"],
                detected_raw=extracted["raw"],
                source_url=source_url or "",
                drift_pct=0.0,
                status="pending",
            )
        note = (f"抓到 {extracted['currency']} 提示 {extracted['raw']},与存储 "
                f"USD 不直接可比,已 stage 提案待人工核对")
    elif accepted:
        note = (f"抓到 USD {extracted['amount']:.2f},与存储 ${stored:.2f} "
                f"相差 {drift:.2f}% (容差 ±{tolerance*100:.1f}%)")
    else:
        # Drift too large — stage a proposal but DO NOT overwrite.
        if auto_stage:
            proposal_id = db.add_proposed_price(
                conn, opp["id"], field,
                stored_value=stored,
                proposed_value=extracted["amount"],
                detected_currency=extracted["currency"],
                detected_raw=extracted["raw"],
                source_url=source_url or "",
                drift_pct=drift or 0.0,
                status="pending",
            )
        note = (f"抓到 USD {extracted['amount']:.2f},与存储 ${stored:.2f} "
                f"相差 {drift:.2f}%,超出容差 ±{tolerance*100:.1f}%,"
                f"已 stage 提案待人工核对(未自动覆盖)")
    return SideCheck(
        field=field, stored_value=stored, source_url=source_url,
        extracted=extracted, drift_pct=drift, accepted=accepted,
        proposal_id=proposal_id, note=note,
    )


def _skip_side(field: str, opp, probe) -> SideCheck:
    return SideCheck(
        field=field, stored_value=float(opp[field]),
        source_url=(opp["purchase_source_url"] if field == "purchase_price_usd"
                    else opp["sell_source_url"]),
        extracted=None, drift_pct=None, accepted=False, proposal_id=None,
        note=f"refresh 未成功:{(probe.blocked_reason if probe else 'no url')}",
    )


def _unknown_sku_outcome(sku: str) -> VerifyOutcome:
    return VerifyOutcome(
        sku=sku, name="(unknown)",
        refresh_updated=False, refreshed_at=None,
        purchase=SideCheck("purchase_price_usd", 0.0, None, None, None, False, None,
                           "opportunity not found"),
        sell=SideCheck("sell_price_usd", 0.0, None, None, None, False, None,
                       "opportunity not found"),
        verified_now=False, final_verified=False, final_freshness_ts=None,
        message=f"opportunity not found: {sku}",
    )


# ---------- dict view (for JSON endpoints) ----------

def outcome_as_dict(o: VerifyOutcome) -> dict:
    return {
        "sku": o.sku,
        "name": o.name,
        "refresh_updated": o.refresh_updated,
        "refreshed_at": o.refreshed_at,
        "verified_now": o.verified_now,
        "final_verified": o.final_verified,
        "final_freshness_ts": o.final_freshness_ts,
        "purchase": _side_as_dict(o.purchase),
        "sell": _side_as_dict(o.sell),
        "message": o.message,
    }


def _side_as_dict(s: SideCheck) -> dict:
    return {
        "field": s.field,
        "stored_value": s.stored_value,
        "source_url": s.source_url,
        "extracted": s.extracted,
        "drift_pct": s.drift_pct,
        "accepted": s.accepted,
        "proposal_id": s.proposal_id,
        "note": s.note,
    }


__all__ = [
    "DEFAULT_TOLERANCE",
    "SideCheck",
    "VerifyOutcome",
    "compare_price",
    "outcome_as_dict",
    "parse_price_from_hints",
    "verify_opportunity",
    "within_tolerance",
]