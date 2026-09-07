"""阶段0: Opportunity 11 态状态机 + 转移 + 证据门槛 + 规格归一."""
from __future__ import annotations

import pytest

from arb.opp.state import (
    ALL_STATUSES,
    TERMINAL_STATUSES,
    FUNNEL_RANK,
    OppStatus,
    IllegalTransition,
    can_transition,
    require_transition,
    evaluate_qualified,
    evaluate_ready,
    specs_conflict,
    alias_merge_decision,
    AUTO_MERGE_MIN_CONFIDENCE,
)


def test_eleven_states_complete():
    assert len(ALL_STATUSES) == 11
    values = {s.value for s in ALL_STATUSES}
    assert values == {
        "discovered", "qualified", "ready", "participating", "acquired",
        "failed", "listed", "sold", "settled", "rejected", "expired",
    }


def test_terminal_states():
    assert TERMINAL_STATUSES == {
        OppStatus.FAILED, OppStatus.SETTLED, OppStatus.REJECTED, OppStatus.EXPIRED
    }


def test_legal_funnel_transitions():
    path = ["discovered", "qualified", "ready", "participating",
            "acquired", "listed", "sold", "settled"]
    for a, b in zip(path, path[1:]):
        assert can_transition(a, b), f"{a} → {b} should be legal"
        require_transition(a, b)  # must not raise


def test_illegal_skip_ahead_transitions():
    # 不能跳级
    assert not can_transition("discovered", "settled")
    assert not can_transition("discovered", "ready")
    assert not can_transition("qualified", "acquired")
    assert not can_transition("ready", "listed")
    with pytest.raises(IllegalTransition):
        require_transition("discovered", "sold")


def test_terminal_states_have_no_outgoing():
    for t in TERMINAL_STATUSES:
        assert can_transition(t, "discovered") is False
        assert can_transition(t, t.value) is False


def test_evidence_expiry_rollback():
    # PRD §5.2: 关键证据过期, ready 自动回退待验证 (qualified),
    # qualified 可回退 discovered.
    assert can_transition("ready", "qualified")
    assert can_transition("qualified", "discovered")
    # listed 下架回库存; sold 买家取消回 listed
    assert can_transition("listed", "acquired")
    assert can_transition("sold", "listed")


def test_participating_outcomes():
    assert can_transition("participating", "acquired")
    assert can_transition("participating", "failed")
    assert can_transition("participating", "expired")
    assert not can_transition("participating", "listed")


# ---------- 证据门槛 ----------

def _ev(kind, side, source_ref, confidence=0.8):
    return {"kind": kind, "side": side, "source_ref": source_ref,
            "source_kind": "marketplace", "confidence": confidence}


def test_qualified_gate_requires_supply_and_two_independent_signals():
    # 空证据
    r = evaluate_qualified([])
    assert not r.ok
    assert len(r.reasons) == 2

    # 只有 1 个官方供给, 0 退出信号
    r = evaluate_qualified([_ev("retail", "buy", "免税店")])
    assert not r.ok
    assert r.supply_count == 1 and r.exit_signal_count == 0

    # 1 供给 + 2 个独立退出信号 (不同来源)
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("ask", "sell", "闲鱼"),
        _ev("sold", "sell", "得物"),
    ])
    assert r.ok, r.reasons
    assert r.supply_count == 1 and r.exit_signal_count == 2


def test_qualified_gate_same_source_counts_once():
    # 同一渠道两条挂单只算 1 个独立信号
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("ask", "sell", "闲鱼"),
        _ev("ask", "sell", "闲鱼"),
    ])
    assert not r.ok
    assert r.exit_signal_count == 1


def test_qualified_gate_rumor_counts_as_demand_signal():
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("rumor", "sell", "微信群A"),
        _ev("ask", "sell", "闲鱼"),
    ])
    assert r.ok


def test_ready_gate_rejects_ask_only_and_rumor_only():
    ask_only = [
        _ev("retail", "buy", "免税店"),
        _ev("ask", "sell", "闲鱼"),
        _ev("ask", "sell", "得物"),
    ]
    r = evaluate_ready(ask_only)
    assert not r.ok
    assert r.only_weak_exit
    assert any("ask/rumor" in reason for reason in r.reasons)

    rumor_only = [
        _ev("retail", "buy", "免税店"),
        _ev("rumor", "sell", "微信群A"),
        _ev("rumor", "sell", "微信群B"),
    ]
    r2 = evaluate_ready(rumor_only)
    assert not r2.ok
    assert r2.only_weak_exit


def test_ready_gate_accepts_bid_buyback_sold():
    for kind in ("bid", "buyback", "sold"):
        evs = [
            _ev("retail", "buy", "免税店"),
            _ev("ask", "sell", "闲鱼"),
            _ev(kind, "sell", "退出渠道"),
        ]
        r = evaluate_ready(evs, net_profit_cny=100.0, min_net_profit_cny=50.0,
                           human_confirmed=True)
        assert r.ok, (kind, r.reasons)
        assert r.has_executable_exit


def test_ready_gate_profit_and_human_confirmation():
    evs = [_ev("retail", "buy", "免税店"), _ev("sold", "sell", "得物"),
           _ev("bid", "sell", "闲鱼")]
    # 利润低于阈值
    r = evaluate_ready(evs, net_profit_cny=10.0, min_net_profit_cny=50.0,
                       human_confirmed=True)
    assert not r.ok
    assert any("阈值" in x for x in r.reasons)
    # 缺人工确认
    r = evaluate_ready(evs, net_profit_cny=100.0, min_net_profit_cny=50.0,
                       human_confirmed=False)
    assert not r.ok
    assert any("人工确认" in x for x in r.reasons)
    # 净利缺失 (NULL) 且给了阈值 → 不臆造
    r = evaluate_ready(evs, net_profit_cny=None, min_net_profit_cny=50.0,
                       human_confirmed=True)
    assert not r.ok
    assert any("净利润缺失" in x for x in r.reasons)


def test_gate_accepts_partial_dicts():
    # 缺省键 (如 sqlite Row 缺列) 走 default, 不抛异常
    r = evaluate_qualified([
        {"kind": "retail", "side": "buy"},
        {"kind": "ask", "side": "sell", "source_ref": "闲鱼"},
        {"kind": "sold", "side": "sell", "source_ref": "得物"},
    ])
    assert r.ok


# ---------- 规格归一 / 别名合并 (PRD §4.2) ----------

def test_specs_conflict_detects_mismatch():
    a = {"brand": "Pokemon", "model": "151", "version": "日版"}
    b = {"brand": "Pokemon", "model": "151", "version": "国版"}
    assert specs_conflict(a, b) is True
    # 缺维度不算冲突
    c = {"brand": "Pokemon", "model": "151"}
    assert specs_conflict(a, c) is False
    # 完全一致
    d = {"brand": "pokemon", "model": " 151", "version": "日版"}
    assert specs_conflict(a, d) is False


def test_alias_merge_decision():
    spec_a = {"brand": "Pokemon", "version": "日版"}
    spec_b = {"brand": "Pokemon", "version": "日版"}
    # 高置信 + 规格一致 → 自动
    assert alias_merge_decision(0.9, spec_a, spec_b) == "auto"
    # 置信度不足 → 人工
    assert alias_merge_decision(AUTO_MERGE_MIN_CONFIDENCE - 0.01, spec_a, spec_b) == "manual_review"
    # 规格不一致 → 即使高置信也人工 (不允许自动合并)
    spec_c = {"brand": "Pokemon", "version": "国版"}
    assert alias_merge_decision(0.99, spec_a, spec_c) == "manual_review"
