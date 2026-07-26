"""Shared report renderer: Markdown + HTML + PDF.

One source of truth for the decision report — used by:
  * CLI: `python -m arb report --out ...` (markdown / pdf)
  * FastAPI: GET /api/report/{sku}.md, .html, .pdf
  * Web SPA: inline HTML view

Single-page PDF is rendered via Playwright's chromium headless print, so the
visual output matches what the user sees in the browser exactly (Goal Brief
§11 verification #4: filename must include date + destination).
"""
from __future__ import annotations

import datetime as _dt
import html
import re
from pathlib import Path
from typing import Iterable, Optional

from . import db, freshness
from .decision import Decision, DecisionInputs, judge
from .scenarios import ScenarioResult, summarize as scenarios_summarize


# ---------- helpers shared by md + html ----------

def _level_badge(level: str) -> str:
    return {
        "建议": ("✅", "建议", "#137333"),
        "谨慎": ("⚠️", "谨慎", "#b06000"),
        "不建议": ("❌", "不建议", "#c5221f"),
    }.get(level, ("•", level, "#202124"))


def _format_money(x: float) -> str:
    return f"${x:,.2f}"


def _success_rate(opp) -> float:
    """Read success rate from dict-like rows while preserving legacy fixtures."""
    try:
        return float(opp["success_rate"])
    except (KeyError, IndexError):
        return 1.0


def _safe_filename_part(s: str) -> str:
    """Strip path separators / whitespace for cross-platform filenames."""
    s = re.sub(r"[\\/:\s]+", "_", s.strip())
    return s or "report"


def report_filename(sku: str, dest_city: str, ext: str = "md") -> str:
    date = _dt.date.today().isoformat()
    return f"jp-us-arb_{date}_{_safe_filename_part(sku)}_{_safe_filename_part(dest_city)}.{ext}"


def decide_for(conn, sku: str, num_units: int, route_name: str):
    """Load opp + route from DB, run judge(), return (opp, route, decision, legs).

    Backward-compatible 4-tuple. The 中性 scenario is used as the canonical
    decision (numerically identical to plain judge() under default shifts).
    """
    opp, route, decision, legs, _scenarios = decide_for_full(
        conn, sku, num_units, route_name
    )
    return opp, route, decision, legs


def decide_for_full(conn, sku: str, num_units: int, route_name: str):
    """Same as decide_for but also returns the 3-band scenarios.

    Returns: (opp, route, decision, legs, scenarios)
      * scenarios: list of 3 ScenarioResult [保守, 中性, 乐观]. The middle one
        is numerically identical to ``decision`` so existing callers that
        rely on the single Decision keep their guarantees.
    """
    opp = db.get_opportunity(conn, sku)
    if opp is None:
        raise ValueError(f"opportunity not found: {sku}")
    route = db.get_route(conn, route_name)
    if route is None:
        raise ValueError(f"route not found: {route_name}")
    di = DecisionInputs(
        num_units=num_units,
        purchase_price_usd=opp["purchase_price_usd"],
        sell_price_usd=opp["sell_price_usd"],
        tariff_rate=opp["tariff_rate"],
        shipping_per_unit_usd=opp["shipping_per_unit_usd"],
        platform_fee_rate=opp["platform_fee_rate"],
        minutes_per_unit=opp["minutes_per_unit"],
        success_rate=_success_rate(opp),
        flight_cost_usd=route["flight_cost_usd"],
        hotel_cost_usd=route["hotel_cost_usd"],
        other_trip_cost_usd=route["other_cost_usd"],
        hours_available=route["hours_available"],
        target_hourly_usd=route["target_hourly_usd"],
        target_roi_pct=route["target_roi_pct"],
        min_roi_pct=route["min_roi_pct"],
    )
    scenarios = scenarios_summarize(di)
    decision = scenarios[1].decision  # 中性 band = canonical judge() result
    legs = db.list_route_legs(conn, route["id"])
    return opp, route, decision, legs, scenarios


# ---------- scenario blocks (shared by md + html) ----------

def _scenario_block_markdown(opp, route, scenarios: list[ScenarioResult]) -> str:
    """Markdown block: 保守 / 中性 / 乐观 table + delta + cross-check."""
    L: list[str] = []
    L.append("## 三档情景分析 (保守 / 中性 / 乐观)")
    L.append("")
    L.append("> 单一数字估算易高估收益。下方三档把售价、采购、关税/物流、机票/酒店、时薪做上下行扰动，"
             "便于看到「最坏情况下这趟还值不值得去」。中性等同当前决策。")
    L.append("")
    L.append("| 情景 | 售价(USD) | 采购价(USD) | 机票(USD) | 酒店(USD) | 时薪(USD) | 净利润(USD) | ROI | 等级 |")
    L.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for s in scenarios:
        icon, _, _ = _level_badge(s.decision.level)
        sh = s.shifts
        shifted_sell = opp["sell_price_usd"] * sh.sell_price_factor
        shifted_purchase = opp["purchase_price_usd"] * sh.purchase_price_factor
        shifted_flight = route["flight_cost_usd"] * sh.flight_factor
        shifted_hotel = route["hotel_cost_usd"] * sh.hotel_factor
        shifted_hourly = route["target_hourly_usd"] * sh.target_hourly_factor
        L.append(
            f"| **{icon} {s.name}** | {_format_money(shifted_sell)} | "
            f"{_format_money(shifted_purchase)} | "
            f"{_format_money(shifted_flight)} | "
            f"{_format_money(shifted_hotel)} | "
            f"{_format_money(shifted_hourly)} | "
            f"{_format_money(s.decision.net_profit_usd)} | "
            f"{s.decision.roi_pct:.1f}% | {s.decision.level} |"
        )
    L.append("")
    L.append("**与中性的差值**:")
    for s in scenarios:
        if s.name == "中性":
            continue
        sign_roi = "+" if s.delta_roi_pct >= 0 else ""
        sign_np = "+" if s.delta_net_profit >= 0 else ""
        L.append(
            f"- {s.name}: ROI {sign_roi}{s.delta_roi_pct:.1f}pp, "
            f"净利润 {sign_np}{_format_money(s.delta_net_profit)}"
        )
    L.append("")
    for s in scenarios:
        if s.cross_check:
            L.append(f"> {s.cross_check}")
    L.append("")
    return "\n".join(L)


def _scenario_block_html(opp, route, scenarios: list[ScenarioResult]) -> str:
    """HTML block: same content, styled for the SPA report."""
    rows = []
    for s in scenarios:
        icon, _, _ = _level_badge(s.decision.level)
        sh = s.shifts
        shifted_sell = opp["sell_price_usd"] * sh.sell_price_factor
        shifted_purchase = opp["purchase_price_usd"] * sh.purchase_price_factor
        shifted_flight = route["flight_cost_usd"] * sh.flight_factor
        shifted_hotel = route["hotel_cost_usd"] * sh.hotel_factor
        shifted_hourly = route["target_hourly_usd"] * sh.target_hourly_factor
        delta_roi = (
            f'<span class="delta-pp">{"+" if s.delta_roi_pct >= 0 else ""}'
            f'{s.delta_roi_pct:.1f}pp</span>' if s.name != "中性" else "—"
        )
        delta_np = (
            f'<span class="delta-usd">{"+" if s.delta_net_profit >= 0 else ""}'
            f'${s.delta_net_profit:,.2f}</span>' if s.name != "中性" else "—"
        )
        rows.append(
            f'<tr><td><strong>{icon} {html.escape(s.name)}</strong></td>'
            f'<td>{_format_money(shifted_sell)}</td>'
            f'<td>{_format_money(shifted_purchase)}</td>'
            f'<td>{_format_money(shifted_flight)}</td>'
            f'<td>{_format_money(shifted_hotel)}</td>'
            f'<td>{_format_money(shifted_hourly)}</td>'
            f'<td>{_format_money(s.decision.net_profit_usd)}</td>'
            f'<td>{s.decision.roi_pct:.1f}%</td>'
            f'<td>{s.decision.level}</td>'
            f'<td>{delta_roi}</td>'
            f'<td>{delta_np}</td></tr>'
        )
    cross_checks = "".join(
        f'<div class="scenario-cross-check">{html.escape(s.cross_check)}</div>'
        for s in scenarios if s.cross_check
    )
    if not cross_checks:
        cross_checks = ""
    return (
        '<h2>三档情景分析 (保守 / 中性 / 乐观)</h2>'
        '<p class="scenario-intro">单一数字估算易高估收益。下表把售价、采购、关税/物流、'
        '机票/酒店、时薪做上下行扰动；中性等同当前决策。</p>'
        '<table class="scenario-table">'
        '<thead><tr>'
        '<th>情景</th><th>售价</th><th>采购价</th><th>机票</th><th>酒店</th>'
        '<th>时薪</th><th>净利润</th><th>ROI</th><th>等级</th>'
        '<th>Δ ROI</th><th>Δ 净利</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
        f'{cross_checks}'
    )


# ---------- Markdown ----------

def render_markdown(
    opp,
    route,
    legs,
    num_units: int,
    decision: Decision,
    scenarios: Optional[list[ScenarioResult]] = None,
) -> str:
    icon, level_text, _ = _level_badge(decision.level)
    freshness_ts = opp["data_freshness_ts"]
    verified = "✅ 已验证" if opp["verified"] else "⚠️ 未验证"
    fv = freshness.classify(freshness_ts, sku=opp["sku"]).as_dict()
    freshness_badge = fv["badge"]
    freshness_age = freshness.humanize_age(fv["age_days"])
    trip_cost = route["flight_cost_usd"] + route["hotel_cost_usd"] + route["other_cost_usd"]
    pending = _pending_proposals(opp)
    unit_profit_no_trip = (
        opp["sell_price_usd"] * (1 - opp["platform_fee_rate"]) * _success_rate(opp)
        - opp["purchase_price_usd"] * (1 + opp["tariff_rate"])
        - opp["shipping_per_unit_usd"]
    )
    L = []
    L.append(f"# 决策报告 — {opp['name']}")
    L.append("")
    L.append(f"- 商机 SKU: `{opp['sku']}`")
    L.append(f"- 路线: {route['name']} ({route['origin_city']} → {route['dest_city']})")
    L.append(f"- 出行日期: {route['departure_date'] or '未指定'}")
    L.append(f"- 决策等级: **{icon} {level_text}**")
    L.append(f"- 一句话理由: {decision.reason}")
    L.append("")
    L.append("## 数据来源")
    L.append(f"- 采购来源: {opp['purchase_source_url'] or '未提供'}")
    L.append(f"- 目的市场来源: {opp['sell_source_url'] or '未提供'}")
    L.append(f"- 机票/酒店来源: {route['source_url'] or '未提供'}")
    L.append(f"- 数据更新: {freshness_ts}  ({verified})  {freshness_badge} ({freshness_age})")
    L.append("")
    L.append("## 单件成本明细 (USD)")
    L.append(f"- 采购价(JP免税): {_format_money(opp['purchase_price_usd'])}")
    L.append(f"- 关税({opp['tariff_rate']*100:.0f}%): {_format_money(opp['purchase_price_usd']*opp['tariff_rate'])}")
    L.append(f"- 物流: {_format_money(opp['shipping_per_unit_usd'])}")
    L.append(f"- 平台抽成({opp['platform_fee_rate']*100:.0f}%): "
             f"{_format_money(opp['sell_price_usd']*opp['platform_fee_rate'])}")
    L.append(f"- **成功率: {_success_rate(opp)*100:.0f}%** (按预期售出比例折算营收)")
    L.append(f"- **单件净利润(剥离时间/旅费前) {_format_money(unit_profit_no_trip)}**")
    L.append("")
    L.append("## 行程成本 (USD)")
    L.append(f"- 机票(往返): {_format_money(route['flight_cost_usd'])}")
    L.append(f"- 酒店: {_format_money(route['hotel_cost_usd'])}")
    L.append(f"- 其它: {_format_money(route['other_cost_usd'])}")
    L.append(f"- **行程合计 {_format_money(trip_cost)}**")
    L.append("")
    L.append("## 行程时间线")
    for leg in legs:
        L.append(f"{leg['seq']}. **{leg['label']}** ({leg['kind']}) — "
                 f"{leg['location'] or ''} 耗时 {leg['duration_min']:.0f}min "
                 f"费用 {_format_money(leg['cost_usd'])}")
        if leg["notes"]:
            L.append(f"   - {leg['notes']}")
    L.append("")
    L.append("## 综合决策")
    L.append(f"- 采购数量: {num_units}")
    L.append(f"- 总营收: {_format_money(decision.total_revenue_usd)}")
    L.append(f"- 总成本: {_format_money(decision.total_cost_usd)}")
    L.append(f"- 净利润: {_format_money(decision.net_profit_usd)}")
    L.append(f"- ROI: {decision.roi_pct:.1f}%")
    L.append(f"- 耗时: {decision.hours_used:.1f}h / {route['hours_available']:.1f}h")
    L.append(f"- 盈亏平衡售价: {_format_money(decision.breakeven_sell_price_usd)}")
    L.append("")
    if scenarios:
        L.append(_scenario_block_markdown(opp, route, scenarios))
    L.append("## 风险与提示")
    L.append("- 海关政策以出发日两国海关公告为准 (US CBP $800 / 日方 ¥20,000 免税额,未验证)")
    L.append("- 品牌方限购政策可能随时调整;参考各 SKU 实际限购")
    L.append("- 本报告仅服务个人非贸易自用,不构成投资建议")
    if pending:
        L.append("")
        L.append("## 待人工核对的提案 (proposed_prices)")
        for p in pending:
            L.append(f"- [#{p['id']}] {p['field']}: 存储 ${p['stored_value']:.2f} → "
                     f"建议 ${p['proposed_value']:.2f} ({p['detected_currency']} {p['detected_raw']!r}, "
                     f"drift {p['drift_pct']:.2f}%) 来源: {p['source_url']}")
        L.append(f"  → 接受:`arb proposals apply <id>`  拒绝:`arb proposals reject <id>`")
    if fv["is_stale"]:
        L.append(f"- ⚠️ **数据陈旧 ({freshness_age})** — 超过 30 天阈值,请运行 "
                 f"`python -m arb refresh --sku {opp['sku']}` 重新核对价格,或人工更新 data_freshness_ts。")
    else:
        L.append(f"- 数据新鲜度: {freshness_badge} ({freshness_age})")
    L.append("")
    return "\n".join(L)


# ---------- HTML (single-page printable) ----------

_HTML_CSS = """
:root { --bg:#fafafa; --fg:#202124; --muted:#5f6368; --ok:#137333; --warn:#b06000; --bad:#c5221f; --line:#e0e0e0; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font-family: -apple-system, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; color: var(--fg); background: var(--bg); line-height: 1.5; }
.report { max-width: 820px; margin: 0 auto; background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 28px 36px; }
h1 { font-size: 22px; margin: 0 0 8px; }
h2 { font-size: 15px; margin: 24px 0 8px; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
.meta { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
.badge { display: inline-block; padding: 4px 12px; border-radius: 14px; font-weight: 600; font-size: 14px; color: #fff; }
.badge.ok { background: var(--ok); }
.badge.warn { background: var(--warn); }
.badge.bad { background: var(--bad); }
.reason { margin: 12px 0 4px; padding: 10px 14px; background: #f1f3f4; border-left: 4px solid #1a73e8; border-radius: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 4px; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--line); }
th { background: #f8f9fa; font-weight: 600; }
tr.total td { font-weight: 600; background: #fef7e0; }
ol.timeline { padding-left: 20px; margin: 8px 0; }
ol.timeline li { margin-bottom: 6px; font-size: 13px; }
ol.timeline .leg-kind { display: inline-block; min-width: 56px; padding: 1px 6px; font-size: 11px; border-radius: 3px; color: #fff; text-align: center; }
ol.timeline .leg-kind.flight { background: #1a73e8; }
ol.timeline .leg-kind.hotel  { background: #9334e6; }
ol.timeline .leg-kind.shop   { background: #137333; }
ol.timeline .leg-kind.transit { background: #5f6368; }
ol.timeline .leg-notes { display: block; color: var(--muted); font-size: 12px; margin-left: 64px; }
.warn-box { margin-top: 18px; padding: 12px 16px; border: 1px solid #fdd663; background: #fefff3; border-radius: 4px; font-size: 13px; color: var(--warn); }
.warn-box.stale-box { background: #fde7e9; border-color: #c5221f; color: #c5221f; }
.freshness-badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.freshness-badge.stale { background: #c5221f; color: #fff; }
.freshness-badge.aging { background: #b06000; color: #fff; }
.freshness-badge.fresh { background: #137333; color: #fff; }
.freshness-age { color: var(--muted); font-size: 12px; }
.scenario-table { margin-top: 6px; font-size: 12px; }
.scenario-table th, .scenario-table td { padding: 4px 8px; }
.scenario-intro { color: var(--muted); font-size: 12px; margin: 4px 0 8px; }
.scenario-cross-check { margin-top: 8px; padding: 8px 12px; background: #fef7e0; border-left: 4px solid #b06000; border-radius: 4px; font-size: 13px; color: var(--warn); }
.delta-pp { color: var(--muted); font-variant-numeric: tabular-nums; }
.delta-usd { color: var(--muted); font-variant-numeric: tabular-nums; }
@media print { body { padding: 0; background: #fff; } .report { border: none; } }
"""

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<title>{title}</title>
<style>{css}</style>
</head><body>
<div class="report">
  <h1>决策报告 — {opp_name}</h1>
  <div class="meta">
    商机 SKU: <code>{sku}</code> · 路线: {route_name} ({origin_city} → {dest_city}) · 出行: {departure_date}
  </div>
  <div>
    决策等级: <span class="badge {badge_class}">{icon} {level_text}</span>
  </div>
  <div class="reason">{reason}</div>

  <h2>数据来源</h2>
  <table>
    <tr><th>采购来源</th><td>{purchase_source}</td></tr>
    <tr><th>目的市场来源</th><td>{sell_source}</td></tr>
    <tr><th>机票/酒店来源</th><td>{route_source}</td></tr>
    <tr><th>数据更新</th><td>{freshness} ({verified}) — <span class="freshness-badge {stale_class}">{freshness_badge}</span> <span class="freshness-age">({freshness_age})</span></td></tr>
  </table>

  <h2>单件成本明细 (USD)</h2>
  <table>
    <tr><th>采购价(JP免税)</th><td>{purchase_price}</td></tr>
    <tr><th>关税({tariff_pct}%)</th><td>{tariff_amt}</td></tr>
    <tr><th>物流</th><td>{shipping}</td></tr>
    <tr><th>平台抽成({fee_pct}%)</th><td>{fee_amt}</td></tr>
    <tr><th>成功率</th><td>{success_rate}</td></tr>
    <tr class="total"><td>单件净利润(剥离时间/旅费前)</td><td>{unit_profit}</td></tr>
  </table>

  <h2>行程成本 (USD)</h2>
  <table>
    <tr><th>机票(往返)</th><td>{flight_cost}</td></tr>
    <tr><th>酒店</th><td>{hotel_cost}</td></tr>
    <tr><th>其它</th><td>{other_cost}</td></tr>
    <tr class="total"><td>行程合计</td><td>{trip_total}</td></tr>
  </table>

  <h2>行程时间线</h2>
  <ol class="timeline">{legs_html}</ol>

  <h2>综合决策</h2>
  <table>
    <tr><th>采购数量</th><td>{num_units}</td></tr>
    <tr><th>总营收</th><td>{total_revenue}</td></tr>
    <tr><th>总成本</th><td>{total_cost}</td></tr>
    <tr><th>净利润</th><td>{net_profit}</td></tr>
    <tr class="total"><td>ROI</td><td>{roi_pct}</td></tr>
    <tr><th>耗时</th><td>{hours_used} / {hours_available}</td></tr>
    <tr><th>盈亏平衡售价</th><td>{breakeven}</td></tr>
  </table>

  <div class="warn-box">
    ⚠️ 海关政策以出发日两国海关公告为准 (US CBP $800 / 日方 ¥20,000 免税额,未验证)。<br>
    ⚠️ 品牌方限购政策可能随时调整;参考各 SKU 实际限购。<br>
    ⚠️ 本报告仅服务个人非贸易自用,不构成投资建议;非商业再销售。<br>
    ⚠️ 数据新鲜度: <span class="freshness-badge {stale_class}">{freshness_badge}</span> ({freshness_age})。
  </div>
  {scenario_block}
  {pending_proposals_html}
  {stale_warning_html}
</div>
</body></html>"""


def _legs_html(legs: Iterable) -> str:
    parts = []
    for leg in legs:
        kind = leg["kind"]
        notes = leg["notes"] or ""
        notes_html = f'<span class="leg-notes">{html.escape(notes)}</span>' if notes else ""
        parts.append(
            f'<li>'
            f'<span class="leg-kind {kind}">{kind}</span> '
            f'<strong>{html.escape(leg["label"])}</strong> — '
            f'{html.escape(leg["location"] or "")} · '
            f'耗时 {leg["duration_min"]:.0f}min · 费用 {html.escape(_format_money(leg["cost_usd"]))}'
            f'{notes_html}'
            f'</li>'
        )
    return "\n".join(parts)


# ---------- pending proposals (Round 4) ----------

def _pending_proposals(opp) -> list[dict]:
    """Read pending proposed_prices for the given opp row.

    The opp dict only carries id / sku, so we open a short-lived connection
    to read pending rows.  When the report is being rendered inside a test
    that already holds an open conn we fall back to the opp's own attributes
    (the proposal rows are stashed in ``opp['_pending_proposals']`` for tests).
    """
    extra = opp.get("_pending_proposals") if isinstance(opp, dict) else None
    if extra is not None:
        return list(extra)
    opp_id = opp["id"] if hasattr(opp, "__getitem__") else opp.id
    try:
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT p.* FROM proposed_prices p "
                "WHERE p.opportunity_id = ? AND p.status = 'pending' "
                "ORDER BY p.detected_at DESC, p.id DESC",
                (opp_id,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    return [dict(r) for r in rows]


def _pending_proposals_html(opp, pending: list[dict]) -> str:
    if not pending:
        return ""
    rows_html = []
    for p in pending:
        rows_html.append(
            f"<tr><td>#{p['id']}</td><td>{html.escape(p['field'])}</td>"
            f"<td>${p['stored_value']:.2f}</td>"
            f"<td>${p['proposed_value']:.2f} ({html.escape(p['detected_currency'])} "
            f"{html.escape(repr(p['detected_raw']))})</td>"
            f"<td>{p['drift_pct']:.2f}%</td>"
            f"<td>{html.escape(p['source_url'] or '')}</td></tr>"
        )
    return (
        '<div class="warn-box propose-box">'
        '<strong>📋 待人工核对的提案 (proposed_prices)</strong> '
        f'— {len(pending)} 条漂移超出容差,价格未自动覆盖。<br>'
        '<table style="margin-top:6px;font-size:12px;">'
        '<tr><th>ID</th><th>字段</th><th>存储</th><th>建议</th><th>drift</th><th>来源</th></tr>'
        + "\n".join(rows_html) +
        '</table>'
        '<div style="margin-top:6px;font-size:12px;">接受:<code>arb proposals apply &lt;id&gt;</code> · '
        '拒绝:<code>arb proposals reject &lt;id&gt;</code></div>'
        '</div>'
    )


def render_html(
    opp,
    route,
    legs,
    num_units: int,
    decision: Decision,
    scenarios: Optional[list[ScenarioResult]] = None,
) -> str:
    icon, level_text, _ = _level_badge(decision.level)
    badge_class = {"建议": "ok", "谨慎": "warn", "不建议": "bad"}[decision.level]
    trip_cost = route["flight_cost_usd"] + route["hotel_cost_usd"] + route["other_cost_usd"]
    pending = _pending_proposals(opp)
    unit_profit_no_trip = (
        opp["sell_price_usd"] * (1 - opp["platform_fee_rate"]) * _success_rate(opp)
        - opp["purchase_price_usd"] * (1 + opp["tariff_rate"])
        - opp["shipping_per_unit_usd"]
    )
    fv = freshness.classify(opp["data_freshness_ts"], sku=opp["sku"]).as_dict()
    freshness_badge = fv["badge"]
    freshness_age = freshness.humanize_age(fv["age_days"])
    stale_class = "stale" if fv["status"] in ("stale", "missing", "future") else fv["status"]
    stale_warning_html = (
        f'<div class="warn-box stale-box">⚠️ 数据已 <strong>{freshness_age}</strong> '
        f'({freshness_badge})。建议运行 <code>python -m arb refresh --sku '
        f'{html.escape(opp["sku"])}</code> 重新核对价格。</div>'
        if fv["is_stale"] else ""
    )
    pending_proposals_html = _pending_proposals_html(opp, pending)
    scenario_block = (
        _scenario_block_html(opp, route, scenarios) if scenarios else ""
    )
    return _HTML_TEMPLATE.format(
        title=f"决策报告 — {opp['name']}",
        css=_HTML_CSS,
        opp_name=html.escape(opp["name"]),
        sku=html.escape(opp["sku"]),
        route_name=html.escape(route["name"]),
        origin_city=html.escape(route["origin_city"]),
        dest_city=html.escape(route["dest_city"]),
        departure_date=html.escape(route["departure_date"] or "未指定"),
        badge_class=badge_class,
        icon=icon,
        level_text=level_text,
        reason=html.escape(decision.reason),
        purchase_source=html.escape(opp["purchase_source_url"] or "未提供"),
        sell_source=html.escape(opp["sell_source_url"] or "未提供"),
        route_source=html.escape(route["source_url"] or "未提供"),
        freshness=html.escape(opp["data_freshness_ts"]),
        verified="✅ 已验证" if opp["verified"] else "⚠️ 未验证",
        stale_class=stale_class,
        freshness_badge=freshness_badge,
        freshness_age=freshness_age,
        stale_warning_html=stale_warning_html,
        purchase_price=_format_money(opp["purchase_price_usd"]),
        tariff_pct=f"{opp['tariff_rate']*100:.0f}",
        tariff_amt=_format_money(opp["purchase_price_usd"] * opp["tariff_rate"]),
        shipping=_format_money(opp["shipping_per_unit_usd"]),
        fee_pct=f"{opp['platform_fee_rate']*100:.0f}",
        fee_amt=_format_money(opp["sell_price_usd"] * opp["platform_fee_rate"]),
        success_rate=f"{_success_rate(opp)*100:.0f}%",
        unit_profit=_format_money(unit_profit_no_trip),
        flight_cost=_format_money(route["flight_cost_usd"]),
        hotel_cost=_format_money(route["hotel_cost_usd"]),
        other_cost=_format_money(route["other_cost_usd"]),
        trip_total=_format_money(trip_cost),
        legs_html=_legs_html(legs),
        num_units=num_units,
        total_revenue=_format_money(decision.total_revenue_usd),
        total_cost=_format_money(decision.total_cost_usd),
        net_profit=_format_money(decision.net_profit_usd),
        roi_pct=f"{decision.roi_pct:.1f}%",
        hours_used=f"{decision.hours_used:.1f}h",
        hours_available=f"{route['hours_available']:.1f}h",
        breakeven=_format_money(decision.breakeven_sell_price_usd),
        scenario_block=scenario_block,
        pending_proposals_html=pending_proposals_html,
    )


# ---------- PDF ----------

def render_pdf(html_str: str, out_path: Path) -> Path:
    """Render the report HTML to a single-page PDF via headless Chromium.

    Uses playwright sync API under the hood. Caller is responsible for ensuring
    chromium is installed (run `playwright install chromium` once).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Late import so the report module can still be imported on systems without
    # playwright (e.g. test runs that only exercise Markdown).
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_str, wait_until="domcontentloaded")
            page.pdf(
                path=str(out_path),
                format="A4",
                margin={"top": "12mm", "right": "12mm", "bottom": "12mm", "left": "12mm"},
                print_background=True,
            )
        finally:
            browser.close()
    return out_path