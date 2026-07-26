"""CLI entry point: list / decide / report / seed / serve.

Examples:

  python -m arb list
  python -m arb decide --sku JP-SKII-FT230 --units 5
  python -m arb report --sku JP-SKII-FT230 --units 5 --md
  python -m arb report --sku JP-SKII-FT230 --units 5 --pdf --out exports/foo.pdf
  python -m arb serve --port 8765
  python -m arb seed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, freshness
from .decision import judge, DecideError, DecisionInputs
from .refresh import outcome_as_dict, refresh_opportunity
from .report import (
    decide_for,
    render_html,
    render_markdown,
    render_pdf,
    report_filename,
)


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


def _resolve_target(out: Path | None, opp, route, ext: str) -> Path:
    """Pick a write target: --out as file path, --out as existing dir, or auto."""
    if out is None:
        return Path("exports") / report_filename(opp["sku"], route["dest_city"], ext)
    if out.is_dir():
        return out / report_filename(opp["sku"], route["dest_city"], ext)
    return out


# ---------- shared runner ----------

def _decide(conn, sku: str, units: int, route_name: str):
    """Backward-compatible helper: returns (opp, route, decision) tuple."""
    opp, route, decision, _legs = decide_for(conn, sku, units, route_name)
    db.record_decision(conn, opp["id"], route["id"], units, decision)
    return opp, route, decision


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
    """Render the decision report in --md / --html / --pdf format.

    Default behavior is unchanged from Round 1: Markdown to stdout or --out file.
    Use --html or --pdf for the new formats.  Output filename follows the brief:
    `jp-us-arb_<date>_<sku>_<dest>.<ext>`.  If --out is a directory, auto-name;
    if it's a file path, write to that path.
    """
    conn = db.connect()
    try:
        opp, route, decision, legs = decide_for(conn, args.sku, args.units, args.route)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    fmt = args.format
    out = Path(args.out) if args.out else None

    # Resolve target: --out can be a file path or an existing directory.
    # No --out for md -> stdout; for html/pdf -> exports/<auto-name>.
    if fmt == "md":
        body = render_markdown(opp, route, legs, args.units, decision)
        if out is None:
            print(body)
        elif out.is_dir():
            target = out / report_filename(opp["sku"], route["dest_city"], "md")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
            print(f"wrote {target}")
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body, encoding="utf-8")
            print(f"wrote {out}")
    elif fmt == "html":
        body = render_html(opp, route, legs, args.units, decision)
        target = _resolve_target(out, opp, route, "html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(f"wrote {target}")
    elif fmt == "pdf":
        body = render_html(opp, route, legs, args.units, decision)
        target = _resolve_target(out, opp, route, "pdf")
        render_pdf(body, target)
        print(f"wrote {target}")
    else:
        print(f"error: unsupported format {fmt!r}", file=sys.stderr)
        return 2

    db.record_decision(conn, opp["id"], route["id"], args.units, decision)
    conn.close()
    return 0


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


def cmd_serve(args):
    """Launch the FastAPI app on 127.0.0.1:<port>.  Blocks until SIGINT."""
    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn is required for `serve`.  pip install uvicorn fastapi",
              file=sys.stderr)
        return 1
    from .web_api import app
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_refresh(args):
    """Probe an opportunity's URLs and bump freshness_ts if reachable."""
    conn = db.connect()
    try:
        outcome = refresh_opportunity(conn, args.sku)
        if not outcome.message.startswith("opportunity not found"):
            conn.commit()
        d = outcome_as_dict(outcome)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0 if (d["updated"] or d["message"].startswith("opportunity not found")) else 1
    finally:
        conn.close()


def cmd_freshness(args):
    """Print the freshness verdict for one SKU (or all)."""
    conn = db.connect()
    try:
        if args.sku:
            opp = db.get_opportunity(conn, args.sku)
            if opp is None:
                print(f"error: unknown sku {args.sku!r}", file=sys.stderr)
                return 1
            opps = [opp]
        else:
            opps = db.list_opportunities(conn)
        rows = freshness.attach([dict(o) for o in opps])
        for r in rows:
            f = r["freshness"]
            print(f"  [{f['status']:7s}] {r['sku']:25s} "
                  f"freshness_ts={f['freshness_ts']!s:10s} age={f['age_days']!s:4s}  {f['badge']}")
        return 0
    finally:
        conn.close()


# ---------- main ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="arb", description="jp-us-arb-route CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list opportunities + routes")
    sub.add_parser("seed", help="seed 6 whitelist opportunities + 1 route")
    sub.add_parser("health", help="DB health check")

    p_serve = sub.add_parser("serve", help="launch FastAPI Web SPA on 127.0.0.1")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)

    p_refresh = sub.add_parser("refresh", help="re-probe an opp's URLs; bump freshness_ts if reachable")
    p_refresh.add_argument("--sku", required=True)

    p_fresh = sub.add_parser("freshness", help="show freshness verdict per opportunity")
    p_fresh.add_argument("--sku", help="restrict to one SKU (default: all)")

    p_dec = sub.add_parser("decide", help="compute per-trip decision")
    p_dec.add_argument("--sku", required=True)
    p_dec.add_argument("--units", type=int, required=True)
    p_dec.add_argument("--route", default="PVG-NRT-LAX-2N")

    p_rep = sub.add_parser("report", help="emit decision report (md / html / pdf)")
    p_rep.add_argument("--sku", required=True)
    p_rep.add_argument("--units", type=int, required=True)
    p_rep.add_argument("--route", default="PVG-NRT-LAX-2N")
    p_rep.add_argument("--format", choices=["md", "html", "pdf"], default="md",
                       help="output format (default md)")
    p_rep.add_argument("--md", action="store_const", const="md", dest="format",
                       help="shorthand for --format md")
    p_rep.add_argument("--html", action="store_const", const="html", dest="format",
                       help="shorthand for --format html")
    p_rep.add_argument("--pdf", action="store_const", const="pdf", dest="format",
                       help="shorthand for --format pdf")
    p_rep.add_argument("--out", help="output file path or directory (default: cwd)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = {
        "list": cmd_list,
        "decide": cmd_decide,
        "report": cmd_report,
        "seed": cmd_seed,
        "health": cmd_health,
        "serve": cmd_serve,
        "refresh": cmd_refresh,
        "freshness": cmd_freshness,
    }.get(args.cmd)
    if handler is None:
        return 2
    try:
        rc = handler(args)
        return 0 if rc is None else rc
    except DecideError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())