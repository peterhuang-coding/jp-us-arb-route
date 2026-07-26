"""CLI entry point: list / decide / report / seed.

Examples:

  python -m arb list
  python -m arb decide --sku JP-SKII-FT230 --units 5
  python -m arb report --sku JP-SKII-FT230 --units 5 --md
  python -m arb seed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db
from .decision import DecisionInputs, judge, DecideError


# ---------- formatting ----------

def _fmt_level(level: str) -> str:
    return {"建议": "✅ 建议", "谨慎": "⚠️ 谨慎", "不建议": "❌ 不建议"}.get(level, level)


def _print_opportunity(o, unit_profit: float | None = None) -> str:
    lines = [
        f"  [{o['id']}] {o['sku']}",
        f"      {o['name']}",
        f"      采购: {o['source_market']}  目的: {o['target_market']}",
        f"      采购价 ${o['purchase_price_usd']:.2f}  目的售价 ${o['sell_price_usd']:.2f}  "
        f"税率 {o['tariff_rate']*100:.0f}%  平台抽成 {o['platform_fee_rate']*100:.0f}%",
        f"      每件耗时 {o['minutes_per_unit']:.0f} 分钟  成功率 {o['success_rate']*100:.0f}%  "
        f"数据: {o['data_freshness_ts']}  验证: {'是' if o['verified'] else '未验证'}",
    ]
    if unit_profit is not None:
        lines.append(f"      单件净利润(剥离时间/旅费前): ${unit_profit:.2f}")
    return "\n".join(lines)


def _print_decision(d, opp, route, num_units: int) -> str:
    L = [
        f"决策: {_fmt_level(d.level)}",
        f"理由: {d.reason}",
        f"  商机: {opp['sku']} - {opp['name']}",
        f"  路线: {route['name']} ({route['origin_city']} → {route['dest_city']})",
        f"  数量: {num_units}",
        f"  毛利率: ROI {d.roi_pct:.1f}%   单件净利润 ${d.per_unit_revenue_usd - d.per_unit_cost_usd:.2f}",
        f"  营收: ${d.total_revenue_usd:.2f}   成本: ${d.total_cost_usd:.2f}   "
        f"净利润: ${d.net_profit_usd:.2f}",
        f"  耗时: {d.hours_used:.1f}h / {route['hours_available']:.1f}h",
        f"  盈亏平衡售价: ${d.breakeven_sell_price_usd:.2f}",
    ]
    return "\n".join(L)


def _build_report_md(opp, route, legs, num_units: int, d) -> str:
    freshness = opp["data_freshness_ts"]
    verified = "✅ 已验证" if opp["verified"] else "⚠️ 未验证"
    trip_cost = route["flight_cost_usd"] + route["hotel_cost_usd"] + route["other_cost_usd"]
    unit_profit_no_trip = opp["sell_price_usd"] * (1 - opp["platform_fee_rate"]) \
        - opp["purchase_price_usd"] * (1 + opp["tariff_rate"]) \
        - opp["shipping_per_unit_usd"]

    md = []
    md.append(f"# 决策报告 — {opp['name']}")
    md.append("")
    md.append(f"- 商机 SKU: `{opp['sku']}`")
    md.append(f"- 路线: {route['name']} ({route['origin_city']} → {route['dest_city']})")
    md.append(f"- 出行日期: {route['departure_date'] or '未指定'}")
    md.append(f"- 决策等级: **{_fmt_level(d.level)}**")
    md.append(f"- 一句话理由: {d.reason}")
    md.append("")
    md.append("## 数据来源")
    md.append(f"- 采购来源: {opp['purchase_source_url'] or '未提供'}")
    md.append(f"- 目的市场来源: {opp['sell_source_url'] or '未提供'}")
    md.append(f"- 机票/酒店来源: {route['source_url'] or '未提供'}")
    md.append(f"- 数据更新: {freshness}  ({verified})")
    md.append("")
    md.append("## 单件成本明细 (USD)")
    md.append(f"- 采购价(JP免税): ${opp['purchase_price_usd']:.2f}")
    md.append(f"- 关税({opp['tariff_rate']*100:.0f}%): ${opp['purchase_price_usd']*opp['tariff_rate']:.2f}")
    md.append(f"- 物流: ${opp['shipping_per_unit_usd']:.2f}")
    md.append(f"- 平台抽成({opp['platform_fee_rate']*100:.0f}%): ${opp['sell_price_usd']*opp['platform_fee_rate']:.2f}")
    md.append(f"- **单件净利润(剥离时间/旅费前) ${unit_profit_no_trip:.2f}**")
    md.append("")
    md.append("## 行程成本 (USD)")
    md.append(f"- 机票(往返): ${route['flight_cost_usd']:.2f}")
    md.append(f"- 酒店: ${route['hotel_cost_usd']:.2f}")
    md.append(f"- 其它: ${route['other_cost_usd']:.2f}")
    md.append(f"- **行程合计 ${trip_cost:.2f}**")
    md.append("")
    md.append("## 行程时间线")
    for leg in legs:
        md.append(f"{leg['seq']}. **{leg['label']}** ({leg['kind']}) — "
                  f"{leg['location'] or ''} "
                  f"耗时 {leg['duration_min']:.0f}min "
                  f"费用 ${leg['cost_usd']:.0f}")
        if leg["notes"]:
            md.append(f"   - {leg['notes']}")
    md.append("")
    md.append("## 综合决策")
    md.append(f"- 采购数量: {num_units}")
    md.append(f"- 总营收: ${d.total_revenue_usd:.2f}")
    md.append(f"- 总成本: ${d.total_cost_usd:.2f}")
    md.append(f"- 净利润: ${d.net_profit_usd:.2f}")
    md.append(f"- ROI: {d.roi_pct:.1f}%")
    md.append(f"- 耗时: {d.hours_used:.1f}h / {route['hours_available']:.1f}h")
    md.append(f"- 盈亏平衡售价: ${d.breakeven_sell_price_usd:.2f}")
    md.append("")
    md.append("## 风险与提示")
    md.append("- 海关政策以出发日两国海关公告为准 (US CBP $800 / 日方 ¥20,000 免税额,未验证)")
    md.append("- 品牌方限购政策可能随时调整;参考各 SKU 实际限购")
    md.append("- 本报告仅服务个人非贸易自用,不构成投资建议")
    md.append("- 数据超过 30 天将被标记 '陈旧待复核'")
    md.append("")
    return "\n".join(md)


# ---------- shared runner ----------

def _decide(conn, sku: str, units: int, route_name: str) -> tuple:
    opp = db.get_opportunity(conn, sku)
    if opp is None:
        raise SystemExit(f"opp not found: {sku}")
    route = db.get_route(conn, route_name)
    if route is None:
        raise SystemExit(f"route not found: {route_name}")
    di = DecisionInputs(
        num_units=units,
        purchase_price_usd=opp["purchase_price_usd"],
        sell_price_usd=opp["sell_price_usd"],
        tariff_rate=opp["tariff_rate"],
        shipping_per_unit_usd=opp["shipping_per_unit_usd"],
        platform_fee_rate=opp["platform_fee_rate"],
        minutes_per_unit=opp["minutes_per_unit"],
        flight_cost_usd=route["flight_cost_usd"],
        hotel_cost_usd=route["hotel_cost_usd"],
        other_trip_cost_usd=route["other_cost_usd"],
        hours_available=route["hours_available"],
        target_hourly_usd=route["target_hourly_usd"],
        target_roi_pct=route["target_roi_pct"],
        min_roi_pct=route["min_roi_pct"],
    )
    d = judge(di)
    db.record_decision(conn, opp["id"], route["id"], units, d)
    return opp, route, d


# ---------- commands ----------

def cmd_list(args):
    conn = db.connect()
    opps = db.list_opportunities(conn)
    routes = db.list_routes(conn)
    print(f"=== Opportunities ({len(opps)}) ===")
    for o in opps:
        unit_profit = (o["sell_price_usd"] * (1 - o["platform_fee_rate"])
                       - o["purchase_price_usd"] * (1 + o["tariff_rate"])
                       - o["shipping_per_unit_usd"])
        print(_print_opportunity(o, unit_profit))
        print("")
    print(f"=== Routes ({len(routes)}) ===")
    for r in routes:
        print(f"  [{r['id']}] {r['name']}: {r['origin_city']} → {r['dest_city']}  "
              f"机票 ${r['flight_cost_usd']:.0f}  酒店 ${r['hotel_cost_usd']:.0f}  "
              f"时间预算 {r['hours_available']:.0f}h")
    conn.close()


def cmd_decide(args):
    conn = db.connect()
    opp, route, d = _decide(conn, args.sku, args.units, args.route)
    print(_print_decision(d, opp, route, args.units))
    conn.close()


def cmd_report(args):
    conn = db.connect()
    opp, route, d = _decide(conn, args.sku, args.units, args.route)
    legs = db.list_route_legs(conn, route["id"])
    md = _build_report_md(opp, route, legs, args.units, d)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"wrote {out_path}")
    else:
        print(md)
    conn.close()


def cmd_seed(args):
    from . import seed
    summary = seed.main()
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def cmd_health(args):
    conn = db.connect()
    opps = db.list_opportunities(conn)
    routes = db.list_routes(conn)
    print(f"opportunities: {len(opps)}  routes: {len(routes)}  db: {db.DB_PATH}")
    conn.close()


# ---------- main ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arb", description="jp-us-arb-route CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list opportunities + routes")
    sub.add_parser("seed", help="seed 6 whitelist opportunities + 1 route")
    sub.add_parser("health", help="DB health check")

    p_dec = sub.add_parser("decide", help="compute per-trip decision")
    p_dec.add_argument("--sku", required=True)
    p_dec.add_argument("--units", type=int, required=True)
    p_dec.add_argument("--route", default="PVG-NRT-LAX-2N")

    p_rep = sub.add_parser("report", help="emit Markdown decision report")
    p_rep.add_argument("--sku", required=True)
    p_rep.add_argument("--units", type=int, required=True)
    p_rep.add_argument("--route", default="PVG-NRT-LAX-2N")
    p_rep.add_argument("--out", help="output file path (default: stdout)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {
        "list": cmd_list,
        "decide": cmd_decide,
        "report": cmd_report,
        "seed": cmd_seed,
        "health": cmd_health,
    }.get(args.cmd)
    if handler is None:
        return 2
    try:
        handler(args)
    except DecideError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
