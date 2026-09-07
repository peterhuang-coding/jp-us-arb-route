"""阶段0: 证据 6 分类映射 + 时间戳/置信度归一."""
from __future__ import annotations

from arb.opp.evidence import (
    EvidenceKind,
    EXECUTABLE_EXIT_KINDS,
    classify_price_type,
    source_kind_for,
    normalize_observed_at,
    MONTH_GRANULARITY_CONFIDENCE,
    SNAPSHOT_CONFIDENCE,
)


def test_six_kinds_complete():
    assert {k.value for k in EvidenceKind} == {
        "retail", "bid", "buyback", "sold", "ask", "rumor"}


def test_executable_exit_kinds():
    assert EXECUTABLE_EXIT_KINDS == {
        EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD}
    # ask/rumor 永远不是可执行退出
    assert EvidenceKind.ASK not in EXECUTABLE_EXIT_KINDS
    assert EvidenceKind.RUMOR not in EXECUTABLE_EXIT_KINDS


def test_legacy_price_type_mapping():
    # tech 方案 + risk §② 的 8 种历史值
    assert classify_price_type("tax-free", "buy") == EvidenceKind.RETAIL
    assert classify_price_type("retail", "buy") == EvidenceKind.RETAIL
    assert classify_price_type("成交", "sell") == EvidenceKind.SOLD
    assert classify_price_type("挂单", "sell") == EvidenceKind.ASK
    assert classify_price_type("挂牌", "sell") == EvidenceKind.ASK
    assert classify_price_type("标价", "sell") == EvidenceKind.ASK
    assert classify_price_type("recycle", "sell") == EvidenceKind.BUYBACK


def test_self_use_baseline_is_side_aware():
    # buy 侧: 中免/日上/天猫 官方零售基线 → retail
    assert classify_price_type("self-use-baseline", "buy") == EvidenceKind.RETAIL
    # sell 侧: 朋友圈/论坛 挂价参考 → ask (risk §②: self-use=6 属 ask)
    assert classify_price_type("self-use-baseline", "sell") == EvidenceKind.ASK


def test_unknown_type_falls_back_to_ask():
    # 保守: 未知类型永远不会被当成官方供给或可执行退出
    k = classify_price_type("某种新类型", "sell")
    assert k == EvidenceKind.ASK
    assert k not in EXECUTABLE_EXIT_KINDS


def test_bid_rumor_have_no_legacy_source():
    # 历史无 bid/rumor 源 (阶段1 补); 分类器不为它们产生映射
    mapped = {classify_price_type(t, s).value
              for t in ("tax-free", "retail", "成交", "挂单", "挂牌",
                        "标价", "recycle", "self-use-baseline")
              for s in ("buy", "sell")}
    assert "bid" not in mapped
    assert "rumor" not in mapped


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
