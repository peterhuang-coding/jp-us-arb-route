"""阶段0: 证据 8 分类映射 + 双币 + 时间戳/TTL 归一."""
from __future__ import annotations

import datetime as _dt

from arb.opp.evidence import (
    EvidenceKind,
    EXECUTABLE_EXIT_KINDS,
    QUALIFIED_SIGNAL_KINDS,
    SUPPLY_KINDS,
    EXIT_EVIDENCE_TTL_HOURS,
    classify_price_type,
    source_kind_for,
    normalize_observed_at,
    expiry_for,
    is_expired,
    MONTH_GRANULARITY_CONFIDENCE,
    SNAPSHOT_CONFIDENCE,
)


def test_eight_kinds_complete():
    assert {k.value for k in EvidenceKind} == {
        "official_event", "retail", "bid", "buyback",
        "sold", "ask", "heat", "rumor"}


def test_kind_sets():
    # 可执行退出 (可作收入): bid/buyback/sold
    assert EXECUTABLE_EXIT_KINDS == {
        EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD}
    for k in (EvidenceKind.ASK, EvidenceKind.HEAT, EvidenceKind.RUMOR,
              EvidenceKind.RETAIL, EvidenceKind.OFFICIAL_EVENT):
        assert k not in EXECUTABLE_EXIT_KINDS
    # qualified 认可的退出/需求信号: bid/buyback/sold/heat (ask 仅锚点, rumor 不计)
    assert QUALIFIED_SIGNAL_KINDS == {
        EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD, EvidenceKind.HEAT}
    # 供给: official_event + retail
    assert SUPPLY_KINDS == {EvidenceKind.OFFICIAL_EVENT, EvidenceKind.RETAIL}


def test_legacy_price_type_mapping():
    assert classify_price_type("tax-free", "buy") == EvidenceKind.RETAIL
    assert classify_price_type("retail", "buy") == EvidenceKind.RETAIL
    assert classify_price_type("成交", "sell") == EvidenceKind.SOLD
    assert classify_price_type("挂单", "sell") == EvidenceKind.ASK
    assert classify_price_type("挂牌", "sell") == EvidenceKind.ASK
    assert classify_price_type("标价", "sell") == EvidenceKind.ASK
    assert classify_price_type("recycle", "sell") == EvidenceKind.BUYBACK


def test_self_use_baseline_is_side_aware():
    assert classify_price_type("self-use-baseline", "buy") == EvidenceKind.RETAIL
    assert classify_price_type("self-use-baseline", "sell") == EvidenceKind.ASK


def test_unknown_type_falls_back_to_ask():
    k = classify_price_type("某种新类型", "sell")
    assert k == EvidenceKind.ASK
    assert k not in EXECUTABLE_EXIT_KINDS


def test_official_event_bid_heat_rumor_have_no_legacy_source():
    mapped = {classify_price_type(t, s).value
              for t in ("tax-free", "retail", "成交", "挂单", "挂牌",
                        "标价", "recycle", "self-use-baseline")
              for s in ("buy", "sell")}
    for missing in ("official_event", "bid", "heat", "rumor"):
        assert missing not in mapped


def test_source_kind_classification():
    assert source_kind_for(channel="Fa-So-La 免税") == "official"
    assert source_kind_for(channel="ヨドバシ Akiba") == "official"
    assert source_kind_for(channel="朋友圈 / 微商") == "private"
    assert source_kind_for(channel="微博 (腕表超话)") == "private"
    assert source_kind_for(channel="闲鱼") == "marketplace"
    assert source_kind_for(platform="amazon_jp") == "marketplace"


def test_normalize_month_granularity_downgrades_confidence():
    ts, conf = normalize_observed_at("2026-08")
    assert ts == "2026-08-01T00:00:00"
    assert conf == MONTH_GRANULARITY_CONFIDENCE < SNAPSHOT_CONFIDENCE


def test_normalize_full_timestamps():
    ts, conf = normalize_observed_at("2026-09-08 12:34:56")
    assert ts == "2026-09-08T12:34:56"
    assert conf == SNAPSHOT_CONFIDENCE
    ts2, _ = normalize_observed_at("2026-08-15")
    assert ts2 == "2026-08-15T00:00:00"


def test_exit_evidence_ttl_72h():
    assert EXIT_EVIDENCE_TTL_HOURS == 72
    exp = expiry_for("2026-09-08T10:00:00")
    assert exp == "2026-09-11T10:00:00"


def test_is_expired():
    as_of = _dt.datetime(2026, 9, 12, 10, 0, 0)
    # expires 9-11 → 对 9-12 已过期
    assert is_expired("2026-09-11T10:00:00", as_of) is True
    # expires 9-13 → 未过期
    assert is_expired("2026-09-13T10:00:00", as_of) is False
    # 无 expires_at → 不过期 (ask/heat 等)
    assert is_expired(None, as_of) is False
