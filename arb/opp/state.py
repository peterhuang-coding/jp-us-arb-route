"""Opportunity 11 态状态机 + 合法转移 + 证据门槛 (PRD §3.3/§3.4, 总控交叉复核).

状态: discovered → qualified → ready → participating → acquired
      → listed → sold → settled; 终态 failed / rejected / expired.

门槛口径 (8 类证据):
- qualified: ≥1 官方事件/可验证零售供给 (official_event/retail, buy 侧)
  + ≥2 个相互独立来源的退出/需求信号 (bid/buyback/sold/heat; ask 仅锚点,
  rumor 待核验, 均不计) + 规格可匹配.
- ready: 在 qualified 之上, 必须含新鲜 (未过 72h) 的 bid/buyback/sold
  至少一条; ask/heat/rumor 单独不能进 ready (heat 永远不作收入);
  净利阈值 + 人工确认.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from .evidence import (
    EXECUTABLE_EXIT_KINDS,
    QUALIFIED_SIGNAL_KINDS,
    SUPPLY_KINDS,
    EvidenceKind,
    is_expired,
)


class OppStatus(str, Enum):
    DISCOVERED = "discovered"        # 已发现
    QUALIFIED = "qualified"          # 证据与利润达入池标准
    READY = "ready"                  # 资格/预算/时间人工确认完毕
    PARTICIPATING = "participating"  # 抢购/抽签/采购中
    ACQUIRED = "acquired"            # 已经买到
    FAILED = "failed"                # 未买到/采购失败 (终态)
    LISTED = "listed"                # 已进入销售渠道
    SOLD = "sold"                    # 已成交, 尚未完全回款
    SETTLED = "settled"              # 已回款并完成实际利润核算 (终态)
    REJECTED = "rejected"            # 人工否决 (终态)
    EXPIRED = "expired"              # 时间窗口/利润条件失效 (终态)


ALL_STATUSES: tuple[OppStatus, ...] = tuple(OppStatus)

FUNNEL_RANK: dict[OppStatus, int] = {
    OppStatus.DISCOVERED: 1,
    OppStatus.QUALIFIED: 2,
    OppStatus.READY: 3,
    OppStatus.PARTICIPATING: 4,
    OppStatus.ACQUIRED: 5,
    OppStatus.LISTED: 6,
    OppStatus.SOLD: 7,
    OppStatus.SETTLED: 8,
}

TERMINAL_STATUSES: frozenset[OppStatus] = frozenset(
    {OppStatus.FAILED, OppStatus.SETTLED, OppStatus.REJECTED, OppStatus.EXPIRED}
)

# 合法转移表. 回退边: 证据过期 ready→qualified、qualified→discovered
# (PRD §5.2); 下架回库 listed→acquired; 买家取消/退款 sold→listed.
TRANSITIONS: dict[OppStatus, frozenset[OppStatus]] = {
    OppStatus.DISCOVERED: frozenset(
        {OppStatus.QUALIFIED, OppStatus.REJECTED, OppStatus.EXPIRED}
    ),
    OppStatus.QUALIFIED: frozenset(
        {OppStatus.READY, OppStatus.DISCOVERED, OppStatus.REJECTED, OppStatus.EXPIRED}
    ),
    OppStatus.READY: frozenset(
        {OppStatus.PARTICIPATING, OppStatus.QUALIFIED, OppStatus.REJECTED, OppStatus.EXPIRED}
    ),
    OppStatus.PARTICIPATING: frozenset(
        {OppStatus.ACQUIRED, OppStatus.FAILED, OppStatus.EXPIRED}
    ),
    OppStatus.ACQUIRED: frozenset({OppStatus.LISTED}),
    OppStatus.FAILED: frozenset(),
    OppStatus.LISTED: frozenset(
        {OppStatus.SOLD, OppStatus.ACQUIRED, OppStatus.EXPIRED}
    ),
    OppStatus.SOLD: frozenset({OppStatus.SETTLED, OppStatus.LISTED}),
    OppStatus.SETTLED: frozenset(),
    OppStatus.REJECTED: frozenset(),
    OppStatus.EXPIRED: frozenset(),
}


class IllegalTransition(ValueError):
    """非法状态转移."""


def can_transition(src: OppStatus | str, dst: OppStatus | str) -> bool:
    s = OppStatus(src)
    d = OppStatus(dst)
    return d in TRANSITIONS[s]


def require_transition(src: OppStatus | str, dst: OppStatus | str) -> None:
    """转移合法则返回, 否则抛 IllegalTransition."""
    s = OppStatus(src)
    d = OppStatus(dst)
    if d not in TRANSITIONS[s]:
        raise IllegalTransition(f"非法状态转移: {s.value} → {d.value}")


# ---------- 证据门槛 (PRD §3.4 + 总控交叉复核) ----------

QUALIFIED_MIN_SUPPLY = 1
QUALIFIED_MIN_EXIT_SIGNALS = 2


def _ev(ev) -> dict:
    """归一化证据: 接受 dict 或 sqlite3.Row."""
    def get(key, default=None):
        try:
            v = ev[key]
        except (KeyError, IndexError):
            return default
        return v if v is not None else default
    return {
        "kind": str(get("kind", "")),
        "side": str(get("side", "")),
        "source_ref": str(get("source_ref", "") or get("channel_name", "") or ""),
        "source_kind": str(get("source_kind", "")),
        "confidence": float(get("confidence", 0.5) or 0.5),
        "expires_at": get("expires_at"),
    }


@dataclass
class GateResult:
    gate: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    supply_count: int = 0
    exit_signal_count: int = 0          # 独立来源数 (bid/buyback/sold/heat)
    has_executable_exit: bool = False  # 含新鲜 bid/buyback/sold
    expired_exit_count: int = 0         # 已过期的 bid/buyback/sold 条数
    only_weak_exit: bool = False        # 仅 ask/heat/rumor (无任何可执行退出)


def _signal_source(e: dict) -> Optional[str]:
    """退出/需求信号的独立来源标识; 非信号返回 None.

    只认 bid/buyback/sold/heat (ask 仅锚点, rumor 待核验, 都不计).
    同一 source_ref 只计一次 (相互独立).
    """
    if e["side"] != "sell":
        return None
    if e["kind"] in {k.value for k in QUALIFIED_SIGNAL_KINDS}:
        return e["source_ref"] or f"anon:{e['kind']}"
    return None


def evaluate_qualified(evidences: Iterable[dict], *,
                       specs_match: bool = True) -> GateResult:
    """qualified 门槛: ≥1 官方/零售供给 + ≥2 独立退出/需求信号 + 规格可匹配."""
    evs = [_ev(e) for e in evidences]
    supply = [e for e in evs
              if e["side"] == "buy" and e["kind"] in {k.value for k in SUPPLY_KINDS}]
    exit_sources = {s for e in evs if (s := _signal_source(e)) is not None}
    reasons: list[str] = []
    if len(supply) < QUALIFIED_MIN_SUPPLY:
        reasons.append(f"官方事件/可验证零售供给证据不足: {len(supply)} < {QUALIFIED_MIN_SUPPLY}")
    if len(exit_sources) < QUALIFIED_MIN_EXIT_SIGNALS:
        reasons.append(
            f"独立退出/需求信号不足 (仅认 bid/buyback/sold/heat): "
            f"{len(exit_sources)} < {QUALIFIED_MIN_EXIT_SIGNALS}"
        )
    if not specs_match:
        reasons.append("规格/版本/成色无法匹配, 需人工确认 (不允许自动合并)")
    return GateResult(
        gate="qualified",
        ok=not reasons,
        reasons=reasons,
        supply_count=len(supply),
        exit_signal_count=len(exit_sources),
    )


def evaluate_ready(evidences: Iterable[dict], *,
                   net_profit_cny: Optional[float] = None,
                   min_net_profit_cny: Optional[float] = None,
                   human_confirmed: bool = False,
                   specs_match: bool = True,
                   as_of: Optional[_dt.datetime] = None) -> GateResult:
    """ready 门槛 (qualified 之上的额外要求):

    - 必须存在新鲜 (未过 expires_at, 默认 72h) 的 bid/buyback/sold;
      ask/heat/rumor 单独一律拒绝 —— 挂单价/热度/传闻不得作为预计收入.
    - 可执行退出证据全部过期 → 退回待验证 (qualified).
    - 预计净利润超过用户阈值 (阈值未给跳过; 净利缺失留 NULL 不臆造).
    - 资格/预算/时间窗口人工确认.
    """
    evs = [_ev(e) for e in evidences]
    q = evaluate_qualified(evs, specs_match=specs_match)
    reasons = list(q.reasons)

    exec_kind_vals = {k.value for k in EXECUTABLE_EXIT_KINDS}
    exec_evs = [e for e in evs if e["side"] == "sell" and e["kind"] in exec_kind_vals]
    fresh_exec = [e for e in exec_evs if not is_expired(e["expires_at"], as_of)]
    expired_n = len(exec_evs) - len(fresh_exec)
    weak = [e for e in evs if e["side"] == "sell"
            and e["kind"] in (EvidenceKind.ASK.value, EvidenceKind.HEAT.value,
                              EvidenceKind.RUMOR.value)]
    has_fresh = len(fresh_exec) >= 1
    only_weak = (not exec_evs) and len(weak) >= 1
    if not has_fresh:
        if exec_evs:
            reasons.append(
                f"可执行退出证据 (bid/buyback/sold) 已过期 {expired_n} 条, "
                "退回待验证 (ready→qualified)"
            )
        elif only_weak:
            reasons.append("仅依赖挂单/热度/私域传闻 (ask/heat/rumor), 无买盘/回收/成交证据, 不得进入 ready")
        else:
            reasons.append("缺少可执行退出证据 (bid/buyback/sold)")
    if min_net_profit_cny is not None:
        if net_profit_cny is None:
            reasons.append("预计净利润缺失 (缺数据留 NULL, 不臆造)")
        elif net_profit_cny < min_net_profit_cny:
            reasons.append(f"预计净利润 {net_profit_cny} < 阈值 {min_net_profit_cny}")
    if not human_confirmed:
        reasons.append("采购资格/地区/库存/时间窗口尚未人工确认")
    return GateResult(
        gate="ready",
        ok=not reasons,
        reasons=reasons,
        supply_count=q.supply_count,
        exit_signal_count=q.exit_signal_count,
        has_executable_exit=has_fresh,
        expired_exit_count=expired_n,
        only_weak_exit=only_weak,
    )


# ---------- 规格归一 / 别名合并 (PRD §4.2) ----------

SPEC_FIELDS: tuple[str, ...] = (
    "brand", "series", "model", "color", "size",
    "version", "region", "condition", "packaging",
)

AUTO_MERGE_MIN_CONFIDENCE = 0.8


def _norm_spec_value(v) -> str:
    return str(v or "").strip().lower().replace(" ", "")


def specs_conflict(spec_a: dict, spec_b: dict) -> bool:
    """两边都显式声明了同一维度且值不同 → True (冲突). 缺维度不算冲突."""
    for key in SPEC_FIELDS:
        va = spec_a.get(key) if hasattr(spec_a, "get") else None
        vb = spec_b.get(key) if hasattr(spec_b, "get") else None
        if va is None or vb is None:
            continue
        if _norm_spec_value(va) != _norm_spec_value(vb):
            return True
    return False


def alias_merge_decision(confidence: float, spec_a: dict, spec_b: dict) -> str:
    """返回 'auto' (可自动合并) 或 'manual_review' (必须人工确认)."""
    if float(confidence) < AUTO_MERGE_MIN_CONFIDENCE:
        return "manual_review"
    if specs_conflict(spec_a, spec_b):
        return "manual_review"
    return "auto"
