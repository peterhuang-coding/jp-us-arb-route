"""Unit tests for arb.freshness — pure functions, no I/O."""
from __future__ import annotations

import datetime as _dt

import pytest

from arb.freshness import (
    AGING_DAYS,
    STALE_DAYS,
    FreshnessVerdict,
    attach,
    classify,
    humanize_age,
    summary,
)


# Reference date pinned so verdicts don't drift with wall-clock time.
TODAY = _dt.date(2026, 7, 26)


# ---------- classify() thresholds ----------

def test_fresh_when_under_aging_threshold():
    v = classify("2026-07-20", today=TODAY, sku="X")
    assert v.status == "fresh"
    assert v.age_days == 6
    assert v.is_stale is False
    assert "新鲜" in v.badge


def test_aging_when_between_thresholds():
    v = classify("2026-07-10", today=TODAY, sku="X")
    assert v.status == "aging"
    assert v.age_days == 16
    assert v.is_stale is False
    assert "临近" in v.badge


def test_stale_when_over_stale_threshold():
    v = classify("2026-06-20", today=TODAY, sku="X")
    assert v.status == "stale"
    assert v.age_days == STALE_DAYS + 6
    assert v.is_stale is True
    assert "陈旧" in v.badge


def test_stale_threshold_boundary():
    """Exactly STALE_DAYS days old is considered stale (>= boundary)."""
    v = classify("2026-06-26", today=TODAY, sku="X")
    assert v.age_days == STALE_DAYS
    assert v.status == "stale"


def test_aging_threshold_boundary():
    """AGING_DAYS-1 stays fresh; exactly AGING_DAYS flips to aging."""
    # TODAY=07-26 → 07-12 is 14 days old (fresh); 07-11 is 15 days old (aging)
    assert classify("2026-07-12", today=TODAY, sku="X").status == "fresh"
    assert classify("2026-07-11", today=TODAY, sku="X").status == "aging"


# ---------- missing / malformed ----------

def test_missing_when_no_timestamp():
    v = classify(None, today=TODAY, sku="X")
    assert v.status == "missing"
    assert v.age_days is None
    assert v.is_stale is True
    assert "缺失" in v.badge


def test_missing_when_blank_timestamp():
    v = classify("   ", today=TODAY, sku="X")
    assert v.status == "missing"


def test_missing_when_unparsable_timestamp():
    v = classify("2026/07/01", today=TODAY, sku="X")
    assert v.status == "missing"


def test_future_timestamp_is_flagged():
    v = classify("2026-08-01", today=TODAY, sku="X")
    assert v.status == "future"
    assert v.age_days == -6
    assert v.is_stale is True
    assert "未来" in v.badge or "异常" in v.badge


# ---------- verdict fields ----------

def test_verdict_echoes_sku_and_today():
    v = classify("2026-07-20", today=TODAY, sku="ABC-1")
    assert v.sku == "ABC-1"
    assert v.today == "2026-07-26"
    assert v.freshness_ts == "2026-07-20"


def test_verdict_as_dict_has_all_keys():
    v = classify("2026-07-20", today=TODAY, sku="X")
    d = v.as_dict()
    assert set(d) == {
        "sku", "freshness_ts", "today", "age_days",
        "status", "badge", "is_stale",
    }


# ---------- attach() ----------

def test_attach_adds_freshness_to_each_row():
    opps = [
        {"sku": "A", "data_freshness_ts": "2026-07-25"},   # fresh
        {"sku": "B", "data_freshness_ts": "2026-06-01"},   # stale
        {"sku": "C", "data_freshness_ts": None},           # missing
    ]
    out = attach(opps, today=TODAY)
    assert len(out) == 3
    assert [r["sku"] for r in out] == ["A", "B", "C"]
    assert out[0]["freshness"]["status"] == "fresh"
    assert out[1]["freshness"]["status"] == "stale"
    assert out[2]["freshness"]["status"] == "missing"
    # originals preserved
    assert out[0]["data_freshness_ts"] == "2026-07-25"


def test_attach_does_not_mutate_input_rows():
    opps = [{"sku": "A", "data_freshness_ts": "2026-07-25"}]
    attach(opps, today=TODAY)
    assert "freshness" not in opps[0]


# ---------- summary() ----------

def test_summary_counts_and_most_stale():
    verdicts = [
        classify("2026-07-25", today=TODAY, sku="A"),
        classify("2026-06-01", today=TODAY, sku="B"),  # stale, oldest
        classify("2026-06-15", today=TODAY, sku="C"),  # stale
        classify("2026-07-10", today=TODAY, sku="D"),  # aging
    ]
    s = summary(verdicts)
    assert s["counts"] == {"fresh": 1, "aging": 1, "stale": 2, "missing": 0, "future": 0}
    assert s["total"] == 4
    assert s["most_stale_sku"] == "B"
    assert s["any_stale"] is True


def test_summary_when_all_fresh():
    verdicts = [
        classify("2026-07-25", today=TODAY, sku="A"),
        classify("2026-07-24", today=TODAY, sku="B"),
    ]
    s = summary(verdicts)
    assert s["any_stale"] is False
    assert s["most_stale_sku"] is None


# ---------- humanize_age() ----------

@pytest.mark.parametrize("days,expected_fragment", [
    (None, "未知"),
    (-3, "未来"),
    (0, "今天"),
    (1, "昨天"),
    (5, "5 天前"),
    (60, "个月"),
    (400, "年"),
])
def test_humanize_age(days, expected_fragment):
    assert expected_fragment in humanize_age(days)