"""Opportunity 11 态状态机 + 合法转移 + 证据门槛 (PRD §3.3/§3.4).

状态: discovered → qualified → ready → participating → acquired
      → listed → sold → settled; 终态 failed / rejected / expired.

转移规则与 evidence/finance 解耦: 本模块只做枚举、转移合法性和证据门槛
判定, 不碰数据库.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

from .evidence import EvidenceKind, EXECUTABLE_EXIT_KINDS


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

# 漏斗正向排名 (终态 failed/rejected/expired 不在正向漏斗内).
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

# 合法转移表. 回退边: 证据过期时 ready→qualified、qualified→discovered
# (PRD §5.2 "关键证据过期时, 机会自动回退为待验证状态"); 下架回库
# listed→acquired; 买家取消/退款 sold→listed.
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


# ---------- 证据门槛 (PRD §3.4) ----------

# qualified 门槛要求的独立退出/需求信号数.
QUALIFIED_MIN_SUPPLY = 1
QUALIFIED_MIN_EXIT_SIGNALS = 2

# 证据归一化: 接受 dict 或 sqlite3.Row.
def _ev(ev) -> dict:
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
    }


@dataclass
class GateResult:
    gate: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    supply_count: int = 0
    exit_signal_count: int = 0          # 独立来源数
    has_executable_exit: bool = False  # 含 bid/buyback/sold
    only_weak_exit: bool = False       # 仅 ask/rumor


def _exit_signal_source(e: dict) -> Optional[str]:
    """返回退出/需求信号的独立来源标识; 非退出信号返回 None.

    bid/buyback/sold/ask 算退出价格信号; rumor 算需求线索. 同一 source_ref
    只计一次 (相互独立).
    """
    if e["side"] != "sell":
        return None
    if e["kind"] in (EvidenceKind.BID.value, EvidenceKind.BUYBACK.value,
                     EvidenceKind.SOLD.value, EvidenceKind.ASK.value,
                     EvidenceKind.RUMOR.value):
        return e["source_ref"] or f"anon:{e['kind']}"
    return None


def evaluate_qualified(evidences: Iterable[dict]) -> GateResult:
    """qualified 门槛: ≥1 官方/可验证供给证据 + ≥2 独立退出/需求信号.

    供给证据 = buy 侧 retail (官方发售/免税/零售). 退出信号按 source_ref
    去重计数; rumor 作为需求线索计入但等级最弱.
    """
    evs = [_ev(e) for e in evidences]
    supply = [e for e in evs if e["side"] == "buy" and e["kind"] == EvidenceKind.RETAIL.value]
    exit_sources = {s for e in evs if (s := _exit_signal_source(e)) is not None}
    reasons: list[str] = []
    if len(supply) < QUALIFIED_MIN_SUPPLY:
        reasons.append(f"官方/可验证供给证据不足: {len(supply)} < {QUALIFIED_MIN_SUPPLY}")
    if len(exit_sources) < QUALIFIED_MIN_EXIT_SIGNALS:
        reasons.append(
            f"独立退出/需求信号不足: {len(exit_sources)} < {QUALIFIED_MIN_EXIT_SIGNALS}"
        )
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
                   human_confirmed: bool = False) -> GateResult:
    """ready 门槛 (在 qualified 之上的额外要求):

    - 必须存在可执行买盘/回收价/可信历史成交 (bid/buyback/sold 之一);
      仅有 ask(挂单)/rumor(传闻) 一律拒绝 —— 挂单价不得作为预计收入.
    - 预计净利润超过用户阈值 (阈值未给则跳过该项, 不臆造).
    - 资格/预算/时间窗口人工确认.
    """
    evs = [_ev(e) for e in evidences]
    q = evaluate_qualified(evs)
    reasons = list(q.reasons)
    executable = [
        e for e in evs
        if e["side"] == "sell" and e["kind"] in {k.value for k in EXECUTABLE_EXIT_KINDS}
    ]
    weak = [e for e in evs if e["side"] == "sell"
            and e["kind"] in (EvidenceKind.ASK.value, EvidenceKind.RUMOR.value)]
    has_exec = len(executable) >= 1
    only_weak = (not has_exec) and len(weak) >= 1
    if not has_exec:
        if only_weak:
            reasons.append("仅依赖挂单价/私域传闻 (ask/rumor), 无买盘/回收/成交证据, 不得进入 ready")
        else:
            reasons.append("缺少可执行退出证据 (bid/buyback/sold)")
    if min_net_profit_cny is not None:
        if net_profit_cny is None:
            reasons.append("预计净利润缺失 (缺数据留 NULL, 不臆造)")
        elif net_profit_cny < min_net_profit_cny:
            reasons.append(
                f"预计净利润 {net_profit_cny} < 阈值 {min_net_profit_cny}"
            )
    if not human_confirmed:
        reasons.append("采购资格/地区/库存/时间窗口尚未人工确认")
    return GateResult(
        gate="ready",
        ok=not reasons,
        reasons=reasons,
        supply_count=q.supply_count,
        exit_signal_count=q.exit_signal_count,
        has_executable_exit=has_exec,
        only_weak_exit=only_weak,
    )


# ---------- 规格归一 / 别名合并 (PRD §4.2) ----------

# 规格匹配维度. 两边都声明且值不一致 => 冲突, 不自动合并.
SPEC_FIELDS: tuple[str, ...] = (
    "brand", "series", "model", "color", "size",
    "version", "region", "condition", "packaging",
)

# 置信度低于此值的别名一律人工复核.
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
    """返回 'auto' (可自动合并) 或 'manual_review' (必须人工确认).

    规则: 置信度 ≥ 0.8 且规格无冲突才允许自动合并; 否则降为人工复核,
    系统不允许自动合并价格/身份.
    """
    if float(confidence) < AUTO_MERGE_MIN_CONFIDENCE:
        return "manual_review"
    if specs_conflict(spec_a, spec_b):
        return "manual_review"
    return "auto"
