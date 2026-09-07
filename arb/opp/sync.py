"""legacy 表 → opp 新表的状态派生 (纯读, 不写库).

backfill.py 负责编排/落库; 本模块只从旧表读信号, 产出:
  - item 主数据 (opp_items 行)
  - evidence 行 (6 类映射后)
  - case 行 (11 态 + CNY 口径字段, 缺数 NULL)
  - status events (漏斗事件流)

派生为启发式, 每个 case 必写 status_reason 记录依据 (tech 风险注).
ready 无历史审批对应物, 一律不回填; participating/failed/expired 同理.
"""
from __future__ import annotations

import statistics
from typing import Optional

from . import finance
from .evidence import (
    EvidenceKind,
    classify_price_type,
    normalize_observed_at,
    source_kind_for,
)
from .state import (
    FUNNEL_RANK,
    OppStatus,
    evaluate_qualified,
    evaluate_ready,
)

# ---------- item_key 集合 ----------

def legacy_item_keys(conn) -> list[str]:
    """全部 legacy 表里出现过的 sku (候选无 sku 时用 CAND-{id}, 同 promote 约定)."""
    keys: list[str] = []
    seen: set[str] = set()

    def add(k: Optional[str]):
        if k and k not in seen:
            seen.add(k)
            keys.append(k)

    for (sku,) in conn.execute("SELECT sku FROM opportunities ORDER BY id"):
        add(sku)
    for cid, sku in conn.execute("SELECT id, sku FROM sku_candidates ORDER BY id"):
        add(sku or f"CAND-{cid}")
    for table in ("evidence_log", "competitor_prices", "inventory",
                  "order_status", "returns", "sku_feedback"):
        for (sku,) in conn.execute(f"SELECT DISTINCT sku FROM {table} WHERE sku IS NOT NULL"):
            add(sku)
    return keys


# ---------- 证据派生 ----------

def derive_evidence(conn, item_key: str) -> list[dict]:
    """旧 evidence_log + competitor_prices → 统一 evidence 行 (不落库)."""
    rows: list[dict] = []
    # evidence_log: sku 直接等于 item_key (CAND-* 候选无证据).
    if not item_key.startswith("CAND-"):
        for e in conn.execute(
            "SELECT * FROM evidence_log WHERE sku = ? ORDER BY id", (item_key,)
        ):
            kind = classify_price_type(e["price_type"], e["side"])
            observed, conf = normalize_observed_at(e["observed_at"])
            rows.append({
                "item_key": item_key,
                "kind": kind.value,
                "side": e["side"],
                "source_kind": source_kind_for(channel=e["channel_name"]),
                "source_ref": e["channel_name"],
                "source_url": e["source_url"],
                "price_cny": e["price_cny"],
                "confidence": conf,
                "observed_at": observed,
                "expires_at": None,
                "payload_json": {
                    "legacy_table": "evidence_log",
                    "legacy_price_type": e["price_type"],
                    "channel_url": e["channel_url"],
                    "notes": e["notes"],
                    "verified": e["verified"],
                },
            })
        for c in conn.execute(
            "SELECT * FROM competitor_prices WHERE sku = ? ORDER BY id", (item_key,)
        ):
            observed, conf = normalize_observed_at(c["fetched_at"])
            rows.append({
                "item_key": item_key,
                "kind": EvidenceKind.ASK.value,   # 挂牌快照, 非成交
                "side": "buy",                     # JP 平台报价, 对比采购价用
                "source_kind": "marketplace",
                "source_ref": c["source"],
                "source_url": c["url"],
                "price_cny": c["price_cny"],
                "confidence": conf,
                "observed_at": observed,
                "expires_at": None,
                "payload_json": {
                    "legacy_table": "competitor_prices",
                    "price_jpy": c["price_jpy"],
                    "fx_rate_at_fetch": c["fx_rate_at_fetch"],
                    "fx_source": c["fx_source"],
                    "notes": c["notes"],
                },
            })
    return rows


# ---------- 信号收集 ----------

def _median(xs: list[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return round(statistics.median(xs), 2)


def derive_case(conn, item_key: str, evidences: Optional[list[dict]] = None) -> dict:
    """派生单个 item 的 opp_item + opp_case + events. 返回 dict."""
    evs = evidences if evidences is not None else derive_evidence(conn, item_key)

    opp = None
    if not item_key.startswith("CAND-"):
        opp = conn.execute(
            "SELECT * FROM opportunities WHERE sku = ?", (item_key,)
        ).fetchone()
    candidates = []
    if item_key.startswith("CAND-"):
        cid = int(item_key.split("-", 1)[1])
        candidates = list(conn.execute(
            "SELECT * FROM sku_candidates WHERE id = ?", (cid,)
        ))
    else:
        candidates = list(conn.execute(
            "SELECT * FROM sku_candidates WHERE sku = ?", (item_key,)
        ))
    inventory = list(conn.execute(
        "SELECT * FROM inventory WHERE sku = ? ORDER BY id", (item_key,)
    ))
    order = conn.execute(
        "SELECT * FROM order_status WHERE sku = ?", (item_key,)
    ).fetchone()
    returns = list(conn.execute(
        "SELECT * FROM returns WHERE sku = ? ORDER BY sold_at, id", (item_key,)
    ))
    feedback = conn.execute(
        "SELECT * FROM sku_feedback WHERE sku = ?", (item_key,)
    ).fetchone()

    # --- item 主数据 ---
    name = opp["name"] if opp else (candidates[0]["name"] if candidates else None)
    category = opp["category"] if opp else (
        candidates[0]["category"] if candidates else None)
    spec_json: dict = {}
    if opp:
        spec_json = {
            "unit_volume_ml": opp["unit_volume_ml"],
            "source_market": opp["source_market"],
            "target_market": opp["target_market"],
        }
    item = {
        "item_key": item_key,
        "name": name,
        "category": category or None,
        "brand": None,
        "series": None,
        "spec_json": spec_json,
        "merge_status": "active",
        "merged_into": None,
        "notes": None,
    }

    # --- 漏斗信号 (正向排名) ---
    # 每项: (status, occurred_at, reason)
    signals: list[tuple[OppStatus, Optional[str], str]] = []
    timestamps: dict[str, Optional[str]] = {
        f"{s.value}_at": None for s in OppStatus
    }

    # discovered: 进过任意旧表即算发现
    discover_date = None
    if opp:
        discover_date = opp["created_at"]
    elif candidates:
        discover_date = candidates[0]["created_at"]
    signals.append((OppStatus.DISCOVERED, discover_date, "存在于 legacy 表 (opportunities/candidates/evidence)"))

    # qualified: opportunities.verified=1
    if opp and opp["verified"]:
        signals.append((OppStatus.QUALIFIED, None,
                        f"legacy opportunities.verified=1 (data_freshness={opp['data_freshness_ts']})"))

    # acquired / listed / sold: inventory + order_status.
    # 库存行可能同时承载多段历史 (已上架且已售出 → listed + sold 都发).
    acquired_date = None
    for inv in inventory:
        loc = inv["location"] or ""
        acquired_date = acquired_date or inv["acquired_at"]
        if loc.startswith("已上架"):
            signals.append((OppStatus.LISTED, inv["listed_at"],
                            f"inventory 行 #{inv['id']} location={loc}"))
        if inv["sold_at"]:
            signals.append((OppStatus.SOLD, inv["sold_at"],
                            f"inventory 行 #{inv['id']} sold_at={inv['sold_at']} ({inv['sold_channel'] or ''})"))
        elif not loc.startswith("已上架"):
            signals.append((OppStatus.ACQUIRED, inv["acquired_at"],
                            f"inventory 行 #{inv['id']} location={loc}"))
    if order:
        st = order["status"]
        if st == "已售出":
            signals.append((OppStatus.SOLD, order["sold_at"],
                            "order_status=已售出"))
        elif st == "已上架":
            signals.append((OppStatus.LISTED, order["updated_at"],
                            "order_status=已上架"))
        elif st == "已退货":
            signals.append((OppStatus.ACQUIRED, order["updated_at"],
                            "order_status=已退货 (货已退回, 按在手处理)"))
            acquired_date = acquired_date or order["arrived_at"] or order["ordered_at"]
        elif st in ("已下单", "在途", "已到货"):
            d = order["arrived_at"] or order["ordered_at"]
            signals.append((OppStatus.ACQUIRED, d,
                            f"order_status={st}"))
            acquired_date = acquired_date or d

    # settled: returns (回款/退款完成)
    for r in returns:
        settle_date = r["returned_at"] or r["sold_at"]
        note = f"returns 行 #{r['id']} sold_at={r['sold_at']} ¥{r['sold_price_cny']}"
        if r["returned_at"]:
            note += f", 退货 {r['returned_at']} 退款¥{r['refund_cny']}"
        signals.append((OppStatus.SETTLED, settle_date, note))

    # rejected: sku_feedback bad / candidate bad — 仅在没有超过 discovered 的
    # 正向信号时否决 (已真实流转的历史不抹掉, 原因记入 status_reason).
    positive_rank = max(
        (FUNNEL_RANK[s] for s, _, _ in signals if s in FUNNEL_RANK),
        default=0,
    )
    reject_reason = None
    reject_date = None
    if feedback and feedback["status"] == "bad":
        reject_reason = f"sku_feedback=bad ({feedback['reason'] or '无原因'})"
        reject_date = feedback["updated_at"]
    for c in candidates:
        if c["status"] == "bad":
            r = f"sku_candidates=bad ({c['reason'] or '无原因'})"
            reject_reason = reject_reason or r
            reject_date = reject_date or c["updated_at"]
    rejected = reject_reason is not None and positive_rank <= FUNNEL_RANK[OppStatus.DISCOVERED]
    if rejected:
        signals.append((OppStatus.REJECTED, reject_date, reject_reason))

    # 去重 (同一 to_status 保留最早日期), 按漏斗排名排序
    by_status: dict[OppStatus, tuple[Optional[str], str]] = {}
    for s, when, why in signals:
        if s not in by_status:
            by_status[s] = (when, why)
    ordered = sorted(
        ((s, w, r) for s, (w, r) in by_status.items() if s in FUNNEL_RANK),
        key=lambda t: FUNNEL_RANK[t[0]],
    )
    if rejected:
        ordered.append((OppStatus.REJECTED, by_status[OppStatus.REJECTED][0],
                        by_status[OppStatus.REJECTED][1]))

    final_status = ordered[-1][0] if ordered else OppStatus.DISCOVERED

    # 时间戳
    for s, when, _ in ordered:
        if when:
            timestamps[f"{s.value}_at"] = when

    # events (漏斗事件流)
    events: list[dict] = []
    prev: Optional[str] = None
    for s, when, why in ordered:
        events.append({
            "item_key": item_key,
            "from_status": prev,
            "to_status": s.value,
            "reason": why,
            "event_source": "backfill",
            "occurred_at": when,
        })
        prev = s.value

    status_reason = "; ".join(f"[{s.value}] {why}" for s, _, why in ordered)
    if reject_reason and not rejected:
        status_reason += f"; 注: {reject_reason} (已有正向流转, 不否决)"

    # --- 财务口径 (CNY; 缺数 NULL, 不做 USD 换算) ---
    buy_retail = [e["price_cny"] for e in evs
                  if e["side"] == "buy" and e["kind"] == EvidenceKind.RETAIL.value
                  and e["price_cny"] is not None]
    exec_exit = [e["price_cny"] for e in evs
                 if e["side"] == "sell"
                 and e["kind"] in {k.value for k in (
                     EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD)}
                 and e["price_cny"] is not None]
    est_buy = round(min(buy_retail), 2) if buy_retail else None
    est_exit = _median(exec_exit)
    # 费用/周期 legacy 无 CNY 数据 → 净利/利润率/占用/周期一律 NULL (不臆造).
    actual_buy = min((i["acquired_cny"] for i in inventory
                      if i["acquired_cny"] is not None), default=None)
    actual_exit = None
    settle_date = None
    refund_total = 0.0
    restock_total = 0.0
    if returns:
        latest = returns[-1]
        actual_exit = latest["sold_price_cny"]
        settle_date = latest["returned_at"] or latest["sold_at"]
        refund_total = sum(float(r["refund_cny"] or 0) for r in returns)
        restock_total = sum(float(r["restocking_cost_cny"] or 0) for r in returns)
    actual_net = None
    if actual_buy is not None and actual_exit is not None:
        actual_net = round(actual_exit - refund_total - restock_total - actual_buy, 2)
    cap_days = finance.capital_days(acquired_date, settle_date)

    # --- 证据门槛复算 (新口径; dry-run 预期管理用, 不改变回填状态) ---
    q = evaluate_qualified(evs)
    rdy = evaluate_ready(evs, human_confirmed=False)
    grade = finance.evidence_grade(q.supply_count, q.exit_signal_count,
                                   rdy.has_executable_exit)

    case = {
        "item_key": item_key,
        "opp_type": "spread",
        "status": final_status.value,
        "status_reason": status_reason,
        "leg": None,
        "route_id": None,
        "trip_id": None,
        "est_buy_cny": est_buy,
        "est_exit_cny": est_exit,
        "est_net_profit_cny": None,
        "margin_pct": None,
        "sell_cycle_days": None,
        "capital_occupation_cny": None,
        "success_prob": None,
        "evidence_grade": grade,
        "event_at": None,
        "mechanism": None,
        "eligibility": None,
        "discovered_at": timestamps["discovered_at"],
        "qualified_at": timestamps["qualified_at"],
        "ready_at": None,
        "participating_at": None,
        "acquired_at": timestamps["acquired_at"],
        "failed_at": None,
        "listed_at": timestamps["listed_at"],
        "sold_at": timestamps["sold_at"],
        "settled_at": timestamps["settled_at"],
        "rejected_at": timestamps["rejected_at"],
        "expired_at": None,
        "actual_buy_cny": actual_buy,
        "actual_exit_cny": actual_exit,
        "actual_net_profit_cny": actual_net,
        "actual_fees_cny": None,
        "capital_days": cap_days,
        "forecast_error_cny": None,
        "origin": "legacy-backfill",
    }

    gate_check = {
        "item_key": item_key,
        "legacy_verified": bool(opp and opp["verified"]),
        "qualified_gate_ok": q.ok,
        "qualified_reasons": q.reasons,
        "ready_gate_ok": rdy.ok,
        "ready_reasons": rdy.reasons,
        "supply_count": q.supply_count,
        "exit_signal_count": q.exit_signal_count,
        "has_executable_exit": rdy.has_executable_exit,
        "only_weak_exit": rdy.only_weak_exit,
        "evidence_grade": grade,
    }

    return {"item": item, "evidence": evs, "case": case,
            "events": events, "gate_check": gate_check}
