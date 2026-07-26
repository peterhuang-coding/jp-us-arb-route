"""Data-freshness watchdog.

Brief §6 Risk #8 — "数据陈旧: 每个商机附"数据更新时间",超过 30 天的标"陈旧待复核"".
This module turns the stored ``data_freshness_ts`` into a verdict the UI and
PDF report can render, plus a small in-memory summary the SPA / CLI use to
aggregate per-portfolio staleness.

Pure functions only: no I/O, no DB calls.  Pass ``today=date(2026, 7, 26)`` in
tests so verdicts don't drift with wall-clock time.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

# ---------- thresholds ----------
# Aging starts at 15 days, stale at 30 — matches the brief's "30 天 陈旧待复核"
# rule and gives the SPA a yellow tier before things go red.
AGING_DAYS: int = 15
STALE_DAYS: int = 30

Status = Literal["fresh", "aging", "stale", "missing", "future"]


@dataclass(frozen=True)
class FreshnessVerdict:
    sku: Optional[str]                # echo back for callers
    freshness_ts: Optional[str]       # raw stored value (YYYY-MM-DD or None)
    today: str                        # ISO date of "now" used for the verdict
    age_days: Optional[int]           # None when ts unparsable / missing
    status: Status                    # fresh / aging / stale / missing / future
    badge: str                        # human label, e.g. "⚠️ 陈旧待复核"
    is_stale: bool                    # convenience for UI conditional rendering


def _parse(ts: Optional[str]) -> Optional[_dt.date]:
    if not ts:
        return None
    try:
        return _dt.date.fromisoformat(ts.strip())
    except (ValueError, AttributeError):
        return None


def classify(
    freshness_ts: Optional[str],
    today: Optional[_dt.date] = None,
    sku: Optional[str] = None,
) -> FreshnessVerdict:
    """Compute the freshness verdict for one opportunity row.

    Rules:
      * No / unparsable ts                -> "missing" (treat as stale so UI warns).
      * ts is in the future (>today)      -> "future" (clock skew or bad data; warn).
      * ts older than STALE_DAYS days     -> "stale" + badge "⚠️ 陈旧待复核".
      * ts older than AGING_DAYS days     -> "aging" + badge "🟡 临近复核".
      * otherwise                         -> "fresh" + badge "✅ 新鲜".
    """
    today = today or _dt.date.today()
    today_str = today.isoformat()
    parsed = _parse(freshness_ts)
    if parsed is None:
        return FreshnessVerdict(
            sku=sku, freshness_ts=freshness_ts, today=today_str,
            age_days=None, status="missing",
            badge="⚠️ 数据缺失", is_stale=True,
        )
    age = (today - parsed).days
    if age < 0:
        return FreshnessVerdict(
            sku=sku, freshness_ts=freshness_ts, today=today_str,
            age_days=age, status="future",
            badge="⚠️ 数据异常(未来日期)", is_stale=True,
        )
    if age >= STALE_DAYS:
        return FreshnessVerdict(
            sku=sku, freshness_ts=freshness_ts, today=today_str,
            age_days=age, status="stale",
            badge="⚠️ 陈旧待复核", is_stale=True,
        )
    if age >= AGING_DAYS:
        return FreshnessVerdict(
            sku=sku, freshness_ts=freshness_ts, today=today_str,
            age_days=age, status="aging",
            badge="🟡 临近复核", is_stale=False,
        )
    return FreshnessVerdict(
        sku=sku, freshness_ts=freshness_ts, today=today_str,
        age_days=age, status="fresh",
        badge="✅ 新鲜", is_stale=False,
    )


def attach(opportunities: Iterable[dict], today: Optional[_dt.date] = None) -> list[dict]:
    """Return a shallow-copied list with a ``freshness`` verdict attached to each row.

    The SPA / CLI / report renderer can call this once and then read both the
    original fields and the embedded verdict without re-implementing the rules.
    """
    out = []
    for o in opportunities:
        row = dict(o)
        row["freshness"] = classify(
            row.get("data_freshness_ts"), today=today, sku=row.get("sku"),
        ).as_dict()
        out.append(row)
    return out


def summary(verdicts: Iterable[FreshnessVerdict]) -> dict:
    """Aggregate counts + most-stale SKU for a portfolio verdict."""
    counts = {"fresh": 0, "aging": 0, "stale": 0, "missing": 0, "future": 0}
    most_stale = None
    most_stale_age = -1
    for v in verdicts:
        counts[v.status] += 1
        if v.status in ("stale", "missing", "future") and v.age_days is not None:
            if v.age_days > most_stale_age:
                most_stale_age = v.age_days
                most_stale = v.sku
    return {
        "counts": counts,
        "total": sum(counts.values()),
        "most_stale_sku": most_stale,
        "any_stale": (counts["stale"] + counts["missing"] + counts["future"]) > 0,
    }


# ---------- dict view used by SPA / JSON ----------

def _verdict_as_dict(v: FreshnessVerdict) -> dict:
    return {
        "sku": v.sku,
        "freshness_ts": v.freshness_ts,
        "today": v.today,
        "age_days": v.age_days,
        "status": v.status,
        "badge": v.badge,
        "is_stale": v.is_stale,
    }


# Monkey-patch as_dict onto the dataclass without losing frozen=True.
FreshnessVerdict.as_dict = _verdict_as_dict  # type: ignore[attr-defined]


def humanize_age(age_days: Optional[int]) -> str:
    """Render a short human age label (Chinese)."""
    if age_days is None:
        return "未知"
    if age_days < 0:
        return f"未来 {-age_days} 天"
    if age_days == 0:
        return "今天"
    if age_days == 1:
        return "昨天"
    if age_days < 30:
        return f"{age_days} 天前"
    months = age_days // 30
    if age_days < 365:
        return f"{months} 个月前 ({age_days} 天)"
    years = age_days // 365
    return f"{years} 年前 ({age_days} 天)"