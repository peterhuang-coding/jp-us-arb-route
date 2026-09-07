"""阶段0 Opportunity 只读端点: /api/opp/*.

不写库, 不碰旧端点; web_api.py 通过 include_router 挂载.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter(prefix="/api/opp", tags=["opp"])


def _rows(sql: str, params=()) -> list[dict]:
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@router.get("/items")
def list_items():
    """统一商品身份列表."""
    rows = _rows("SELECT * FROM opp_items ORDER BY item_key")
    for r in rows:
        r["spec_json"] = json.loads(r.get("spec_json") or "{}")
    return rows


@router.get("/cases")
def list_cases(status: Optional[str] = None):
    """机会实例列表, 可按 11 态过滤."""
    if status:
        return _rows(
            "SELECT * FROM opp_cases WHERE status=? ORDER BY id", (status,)
        )
    return _rows("SELECT * FROM opp_cases ORDER BY id")


@router.get("/cases/{item_key}")
def get_case(item_key: str):
    """单个机会: case + 证据列表 + 漏斗事件流."""
    conn = db.connect()
    try:
        case = conn.execute(
            "SELECT * FROM opp_cases WHERE item_key=? ORDER BY id LIMIT 1",
            (item_key,),
        ).fetchone()
        if case is None:
            raise HTTPException(404, f"no opp_case for item_key={item_key!r}")
        evidences = [dict(r) for r in conn.execute(
            "SELECT * FROM evidence WHERE item_key=? ORDER BY observed_at DESC, id DESC",
            (item_key,),
        ).fetchall()]
        for e in evidences:
            e["payload_json"] = json.loads(e.get("payload_json") or "{}")
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM opp_status_events WHERE item_key=? ORDER BY id",
            (item_key,),
        ).fetchall()]
        return {"case": dict(case), "evidence": evidences, "events": events}
    finally:
        conn.close()


@router.get("/evidence")
def list_evidence(item_key: Optional[str] = None, kind: Optional[str] = None,
                  side: Optional[str] = None):
    """统一证据表, 可按 item/kind/side 过滤."""
    clauses, params = [], []
    if item_key:
        clauses.append("item_key = ?")
        params.append(item_key)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if side:
        clauses.append("side = ?")
        params.append(side)
    sql = "SELECT * FROM evidence"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY observed_at DESC, id DESC"
    rows = _rows(sql, tuple(params))
    for r in rows:
        r["payload_json"] = json.loads(r.get("payload_json") or "{}")
    return rows


@router.get("/funnel")
def funnel():
    """漏斗复盘: 各状态数量 + 阶段间转化率 (PRD §5.6 数据底座)."""
    rows = _rows(
        "SELECT status, COUNT(*) AS n FROM opp_cases GROUP BY status"
    )
    by_status = {r["status"]: r["n"] for r in rows}
    total = sum(by_status.values())

    def pct(num: int, den: int) -> Optional[float]:
        return round(num / den * 100, 1) if den else None

    discovered = total  # 每个 case 都经过 discovered
    qualified = sum(n for s, n in by_status.items() if s in
                    {"qualified", "ready", "participating", "acquired",
                     "listed", "sold", "settled"})
    ready = sum(n for s, n in by_status.items() if s in
                {"ready", "participating", "acquired", "listed", "sold", "settled"})
    acquired = sum(n for s, n in by_status.items() if s in
                   {"acquired", "listed", "sold", "settled"})
    sold = by_status.get("sold", 0) + by_status.get("settled", 0)
    settled = by_status.get("settled", 0)
    settled_positive = _rows(
        "SELECT COUNT(*) AS n FROM opp_cases "
        "WHERE status='settled' AND actual_net_profit_cny IS NOT NULL "
        "AND actual_net_profit_cny > 0"
    )[0]["n"]
    return {
        "by_status": by_status,
        "total_cases": total,
        "conversion_pct": {
            "discovered_to_qualified": pct(qualified, discovered),
            "qualified_to_ready": pct(ready, qualified),
            "ready_to_acquired": pct(acquired, ready),
            "acquired_to_sold": pct(sold, acquired),
            "sold_to_settled": pct(settled, sold),
        },
        "north_star": {
            # 北极星: 正利润回款数 / 批准执行数. 阶段0 无 ready 回填,
            # 分母为 0 时返回 None (不臆造).
            "settled_positive_profit": settled_positive,
            "approved_ready": ready,
            "rate_pct": pct(settled_positive, ready),
        },
    }
