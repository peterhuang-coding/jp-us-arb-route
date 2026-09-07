"""旧表 → opp 新表幂等回填编排.

硬门禁 (risk ①):
- 默认 dry-run, 只输出派生预览, 零写入; 显式 --apply 才落库.
- 不挂 connect(), 只能由 CLI `arb opp-backfill` 显式触发.
- 可重复跑: opp_items/evidence/opp_cases 走 UPSERT, backfill 产生的
  opp_status_events 先按 event_source='backfill' 删除再重插;
  origin='manual' 的手工 case 永不覆盖.
"""
from __future__ import annotations

import json

from . import sync


def build_plan(conn) -> dict:
    """纯读: 扫描全部 legacy item, 产出回填计划."""
    items: list[dict] = []
    evidence: list[dict] = []
    cases: list[dict] = []
    events: list[dict] = []
    gate_checks: list[dict] = []

    for item_key in sync.legacy_item_keys(conn):
        derived = sync.derive_case(conn, item_key)
        items.append(derived["item"])
        evidence.extend(derived["evidence"])
        cases.append(derived["case"])
        events.extend(derived["events"])
        gate_checks.append(derived["gate_check"])

    status_counts: dict[str, int] = {}
    for c in cases:
        status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
    kind_counts: dict[str, int] = {}
    for e in evidence:
        kind_counts[e["kind"]] = kind_counts.get(e["kind"], 0) + 1

    return {
        "items": items,
        "evidence": evidence,
        "cases": cases,
        "events": events,
        "gate_checks": gate_checks,
        "counts": {
            "items": len(items),
            "evidence": len(evidence),
            "cases": len(cases),
            "events": len(events),
            "by_status": status_counts,
            "by_evidence_kind": kind_counts,
        },
        "notes": [
            "ready/participating/failed/expired 无历史对应物, 不回填",
            "est_* 财务字段 + evidence 双币列 (original_*/fx_rate): legacy 一律 NULL, 不强行估算/换算",
            "bid/heat/official_event/rumor 无历史源, 属预期缺口 (阶段1 补)",
            "退出价口径 buyback>bid>sold 中位数+样本量已作 finance 函数保留, 阶段1 实时证据使用; legacy 不套用",
            "legacy 月份粒度证据 expires_at 一律 NULL; 72h TTL + ready→qualified 降级属阶段1 实时摄入",
            "月份粒度证据 observed_at 取月初, confidence 降为 0.6",
        ],
    }


def _upsert_item(conn, item: dict) -> None:
    """按 item_key upsert; 不覆盖人工改过的 merge_status/merged_into."""
    conn.execute(
        "INSERT INTO opp_items (item_key, name, category, brand, series, "
        "spec_json, merge_status, merged_into, notes) "
        "VALUES (:item_key, :name, :category, :brand, :series, "
        " :spec_json, :merge_status, :merged_into, :notes) "
        "ON CONFLICT(item_key) DO UPDATE SET "
        "name=excluded.name, category=excluded.category, "
        "spec_json=excluded.spec_json, updated_at=datetime('now')",
        {**item, "spec_json": json.dumps(item["spec_json"], ensure_ascii=False)},
    )


def _insert_evidence(conn, ev: dict) -> None:
    """按完整去重键 INSERT OR IGNORE — 重跑不产生重复行. 双币列缺省 NULL."""
    conn.execute(
        "INSERT OR IGNORE INTO evidence "
        "(item_key, kind, side, source_kind, source_ref, source_url, "
        " price_cny, original_amount, original_currency, fx_rate, "
        " confidence, observed_at, expires_at, payload_json) "
        "VALUES (:item_key, :kind, :side, :source_kind, :source_ref, :source_url, "
        " :price_cny, :original_amount, :original_currency, :fx_rate, "
        " :confidence, :observed_at, :expires_at, :payload_json)",
        {
            "original_amount": None, "original_currency": None, "fx_rate": None,
            **ev,
            "payload_json": json.dumps(ev["payload_json"], ensure_ascii=False),
        },
    )


def _upsert_case(conn, case: dict) -> str:
    """按 (item_key, opp_type) upsert. 返回 'inserted'|'updated'|'skipped-manual'."""
    existing = conn.execute(
        "SELECT id, origin FROM opp_cases WHERE item_key=? AND opp_type=?",
        (case["item_key"], case["opp_type"]),
    ).fetchone()
    if existing is not None and existing["origin"] != "legacy-backfill":
        return "skipped-manual"
    cols = [k for k in case.keys()]
    marks = ", ".join(f":{k}" for k in cols)
    if existing is None:
        conn.execute(f"INSERT INTO opp_cases ({', '.join(cols)}) VALUES ({marks})", case)
        return "inserted"
    updates = ", ".join(f"{k}=excluded.{k}" for k in cols
                        if k not in ("item_key", "opp_type", "origin"))
    conn.execute(
        f"INSERT INTO opp_cases ({', '.join(cols)}) VALUES ({marks}) "
        f"ON CONFLICT(item_key, opp_type) DO UPDATE SET {updates}, "
        "updated_at=datetime('now')",
        case,
    )
    return "updated"


def apply_plan(conn, plan: dict) -> dict:
    """落库 (幂等). 返回写入计数."""
    counts = {"items": 0, "evidence_new": 0, "cases_inserted": 0,
              "cases_updated": 0, "cases_skipped_manual": 0, "events": 0}
    for item in plan["items"]:
        _upsert_item(conn, item)
        counts["items"] += 1

    ev_before = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
    for ev in plan["evidence"]:
        _insert_evidence(conn, ev)
    ev_after = conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"]
    counts["evidence_new"] = ev_after - ev_before

    case_ids: dict[str, int] = {}
    for case in plan["cases"]:
        outcome = _upsert_case(conn, case)
        if outcome == "inserted":
            counts["cases_inserted"] += 1
        elif outcome == "updated":
            counts["cases_updated"] += 1
        else:
            # 手工 case: 不覆盖, 也不往它身上挂 backfill 事件
            counts["cases_skipped_manual"] += 1
            continue
        row = conn.execute(
            "SELECT id FROM opp_cases WHERE item_key=? AND opp_type=?",
            (case["item_key"], case["opp_type"]),
        ).fetchone()
        if row is not None:
            case_ids[case["item_key"]] = row["id"]

    # 事件流: 清掉本批 backfill 旧事件后重插 (manual 事件保留).
    if case_ids:
        placeholders = ",".join("?" * len(case_ids))
        conn.execute(
            f"DELETE FROM opp_status_events WHERE event_source='backfill' "
            f"AND case_id IN ({placeholders})",
            tuple(case_ids.values()),
        )
    for ev in plan["events"]:
        cid = case_ids.get(ev["item_key"])
        if cid is None:
            continue
        conn.execute(
            "INSERT INTO opp_status_events "
            "(case_id, item_key, from_status, to_status, reason, event_source, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, 'backfill', ?)",
            (cid, ev["item_key"], ev["from_status"], ev["to_status"],
             ev["reason"], ev["occurred_at"]),
        )
        counts["events"] += 1

    conn.commit()
    return counts


def run(conn, *, dry_run: bool = True) -> dict:
    """构建计划; dry_run=True 不落库, False 落库. 返回报告."""
    plan = build_plan(conn)
    report: dict = {
        "dry_run": dry_run,
        "plan_counts": plan["counts"],
        "notes": plan["notes"],
        "gate_checks": plan["gate_checks"],
    }
    if dry_run:
        report["written"] = None
        return report
    report["written"] = apply_plan(conn, plan)
    return report
