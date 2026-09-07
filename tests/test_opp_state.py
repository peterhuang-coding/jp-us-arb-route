"""阶段0: Opportunity 11 态状态机 + 转移 + 证据门槛 + 规格归一."""
from __future__ import annotations

import datetime as _dt

import pytest

from arb.opp.state import (
    ALL_STATUSES,
    TERMINAL_STATUSES,
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
    assert {s.value for s in ALL_STATUSES} == {
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
        assert can_transition(a, b)
        require_transition(a, b)


def test_illegal_skip_ahead_transitions():
    assert not can_transition("discovered", "settled")
    assert not can_transition("discovered", "ready")
    assert not can_transition("qualified", "acquired")
    assert not can_transition("ready", "listed")
    with pytest.raises(IllegalTransition):
        require_transition("discovered", "sold")


def test_terminal_states_have_no_outgoing():
    for t in TERMINAL_STATUSES:
        assert can_transition(t, "discovered") is False


def test_evidence_expiry_rollback_edges():
    assert can_transition("ready", "qualified")
    assert can_transition("qualified", "discovered")
    assert can_transition("listed", "acquired")
    assert can_transition("sold", "listed")


def test_participating_outcomes():
    assert can_transition("participating", "acquired")
    assert can_transition("participating", "failed")
    assert can_transition("participating", "expired")
    assert not can_transition("participating", "listed")


# ---------- 证据门槛 ----------

FUTURE = "2099-01-01T00:00:00"   # 新鲜证据

def _ev(kind, side, source_ref, *, expires_at=None, confidence=0.8):
    return {"kind": kind, "side": side, "source_ref": source_ref,
            "source_kind": "marketplace", "confidence": confidence,
            "expires_at": expires_at}


def test_qualified_gate_requires_supply_and_two_independent_signals():
    r = evaluate_qualified([])
    assert not r.ok and len(r.reasons) == 2

    # 1 供给 + 0 退出信号
    r = evaluate_qualified([_ev("retail", "buy", "免税店")])
    assert not r.ok and r.supply_count == 1 and r.exit_signal_count == 0

    # 1 供给 + 2 个独立退出信号 (bid/buyback/sold/heat 之一, 不同来源)
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("sold", "sell", "得物", expires_at=FUTURE),
        _ev("heat", "sell", "小红书热度"),
    ])
    assert r.ok, r.reasons
    assert r.supply_count == 1 and r.exit_signal_count == 2

    # official_event 也算供给
    r = evaluate_qualified([
        _ev("official_event", "buy", "泡泡玛特官方"),
        _ev("bid", "sell", "千岛买盘", expires_at=FUTURE),
        _ev("sold", "sell", "闲鱼成交", expires_at=FUTURE),
    ])
    assert r.ok, r.reasons


def test_qualified_gate_weak_ask_rumor_count_as_signals():
    # PRD §3.4: qualified 要 ≥2 个相互独立的退出价格或需求信号.
    # ask (弱锚点) / rumor (最弱线索) 计入 qualified 入池计数 (仅 ready 才排除).
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("ask", "sell", "闲鱼"),
        _ev("ask", "sell", "得物"),
    ])
    assert r.ok, r.reasons
    assert r.exit_signal_count == 2

    # rumor (需求线索, 不绑定 sell 侧) + sold 不同来源 → 2 个独立信号
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("rumor", "sell", "微信群A"),
        _ev("sold", "sell", "得物", expires_at=FUTURE),
    ])
    assert r.ok, r.reasons
    assert r.exit_signal_count == 2

    # heat 需求信号不限买卖侧
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("heat", "demand", "小红书热度"),
        _ev("ask", "sell", "得物"),
    ])
    assert r.ok, r.reasons
    assert r.exit_signal_count == 2


def test_qualified_gate_same_source_counts_once():
    r = evaluate_qualified([
        _ev("retail", "buy", "免税店"),
        _ev("sold", "sell", "得物", expires_at=FUTURE),
        _ev("bid", "sell", "得物", expires_at=FUTURE),
    ])
    assert not r.ok
    assert r.exit_signal_count == 1


def test_qualified_gate_specs_mismatch_blocks():
    ok_evs = [
        _ev("retail", "buy", "免税店"),
        _ev("sold", "sell", "得物", expires_at=FUTURE),
        _ev("bid", "sell", "闲鱼", expires_at=FUTURE),
    ]
    assert evaluate_qualified(ok_evs, specs_match=True).ok
    r = evaluate_qualified(ok_evs, specs_match=False)
    assert not r.ok
    assert any("规格" in x for x in r.reasons)


def test_ready_gate_rejects_ask_heat_rumor_only():
    for weak_kind in ("ask", "heat", "rumor"):
        evs = [
            _ev("retail", "buy", "免税店"),
            _ev(weak_kind, "sell", "渠道A"),
            _ev(weak_kind, "sell", "渠道B"),
        ]
        r = evaluate_ready(evs)
        assert not r.ok, weak_kind
    # 两个 ask: qualified 能过 (弱信号计入), 但 ready 仍拒绝 (only_weak)
    r = evaluate_ready([
        _ev("retail", "buy", "免税店"),
        _ev("ask", "sell", "闲鱼"),
        _ev("ask", "sell", "得物"),
    ])
    assert not r.ok and r.only_weak_exit


def test_ready_gate_requires_fresh_bid_buyback_sold():
    base = [
        _ev("retail", "buy", "免税店"),
        _ev("ask", "sell", "闲鱼"),
        _ev("heat", "sell", "小红书"),
    ]
    # 新鲜 sold → 证据项过
    fresh = base + [_ev("sold", "sell", "得物", expires_at=FUTURE)]
    r = evaluate_ready(fresh, net_profit_cny=100.0, min_net_profit_cny=50.0,
                       human_confirmed=True)
    assert r.ok, r.reasons
    assert r.has_executable_exit

    # 过期 sold → 退回待验证
    as_of = _dt.datetime(2099, 6, 1)
    expired = base + [_ev("sold", "sell", "得物", expires_at=FUTURE)]
    r2 = evaluate_ready(expired, net_profit_cny=100.0, min_net_profit_cny=50.0,
                        human_confirmed=True, as_of=as_of)
    assert not r2.ok
    assert r2.expired_exit_count == 1
    assert any("过期" in x for x in r2.reasons)

    # legacy 证据 expires_at=NULL (月份粒度) → 阶段0 不套用 72h 新鲜度判断,
    # 存在 sold 即算可执行退出 (NULL 不惩罚; TTL 降级是阶段1 实时逻辑).
    legacy = base + [_ev("sold", "sell", "得物", expires_at=None)]
    r3 = evaluate_ready(legacy, net_profit_cny=100.0, min_net_profit_cny=50.0,
                        human_confirmed=True)
    assert r3.ok, r3.reasons
    assert r3.expired_exit_count == 0
    assert r3.has_executable_exit


def test_ready_gate_buyback_and_bid_also_pass():
    for kind in ("bid", "buyback"):
        evs = [
            _ev("retail", "buy", "免税店"),
            _ev("ask", "sell", "闲鱼"),
            _ev(kind, "sell", "退出渠道", expires_at=FUTURE),
            _ev("heat", "sell", "小红书热度"),   # 第 2 个独立需求信号
        ]
        r = evaluate_ready(evs, net_profit_cny=100.0, min_net_profit_cny=50.0,
                           human_confirmed=True)
        assert r.ok, (kind, r.reasons)


def test_ready_gate_profit_and_human_confirmation():
    evs = [_ev("retail", "buy", "免税店"),
           _ev("sold", "sell", "得物", expires_at=FUTURE),
           _ev("bid", "sell", "闲鱼", expires_at=FUTURE)]
    r = evaluate_ready(evs, net_profit_cny=10.0, min_net_profit_cny=50.0,
                       human_confirmed=True)
    assert not r.ok and any("阈值" in x for x in r.reasons)
    r = evaluate_ready(evs, net_profit_cny=100.0, min_net_profit_cny=50.0,
                       human_confirmed=False)
    assert not r.ok and any("人工确认" in x for x in r.reasons)
    r = evaluate_ready(evs, net_profit_cny=None, min_net_profit_cny=50.0,
                       human_confirmed=True)
    assert not r.ok and any("净利润缺失" in x for x in r.reasons)


def test_gate_accepts_partial_dicts():
    # 缺省键 (sqlite Row 缺列) 走 default, 不抛异常
    r = evaluate_qualified([
        {"kind": "retail", "side": "buy"},
        {"kind": "sold", "side": "sell", "source_ref": "得物",
         "expires_at": FUTURE},
        {"kind": "bid", "side": "sell", "source_ref": "闲鱼",
         "expires_at": FUTURE},
    ])
    assert r.ok


# ---------- 规格归一 / 别名合并 (PRD §4.2) ----------

def test_specs_conflict_detects_mismatch():
    a = {"brand": "Pokemon", "model": "151", "version": "日版"}
    b = {"brand": "Pokemon", "model": "151", "version": "国版"}
    assert specs_conflict(a, b) is True
    c = {"brand": "Pokemon", "model": "151"}
    assert specs_conflict(a, c) is False
    d = {"brand": "pokemon", "model": " 151", "version": "日版"}
    assert specs_conflict(a, d) is False


def test_alias_merge_decision():
    spec_a = {"brand": "Pokemon", "version": "日版"}
    spec_b = {"brand": "Pokemon", "version": "日版"}
    assert alias_merge_decision(0.9, spec_a, spec_b) == "auto"
    assert alias_merge_decision(AUTO_MERGE_MIN_CONFIDENCE - 0.01, spec_a, spec_b) == "manual_review"
    spec_c = {"brand": "Pokemon", "version": "国版"}
    assert alias_merge_decision(0.99, spec_a, spec_c) == "manual_review"
