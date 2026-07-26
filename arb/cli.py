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
import datetime as _dt
import json
import sys
from pathlib import Path

from . import db, freshness
from .decision import judge, DecideError, DecisionInputs
from .refresh import outcome_as_dict, refresh_opportunity
from .verify import outcome_as_dict as verify_outcome_as_dict, verify_opportunity
from .report import (
    decide_for,
    decide_for_full,
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


def _print_decision(d, opp, route, num_units: int, scenarios=None) -> str:
    L = [
        f"决策: {_fmt_level(d.level)}",
        f"理由: {d.reason}",
        f"  商机: {opp['sku']} - {opp['name']}",
        f"  路线: {route['name']} ({route['origin_city']} → {route['dest_city']})",
        f"  数量: {num_units}",
        f"  成功率: {opp['success_rate']*100:.0f}% (按预期售出比例折算)",
        f"  毛利率: ROI {d.roi_pct:.1f}%   单件净利润 ${d.per_unit_revenue_usd - d.per_unit_cost_usd:.2f}",
        f"  营收: ${d.total_revenue_usd:.2f}   成本: ${d.total_cost_usd:.2f}   "
        f"净利润: ${d.net_profit_usd:.2f}",
        f"  耗时: {d.hours_used:.1f}h / {route['hours_available']:.1f}h",
        f"  盈亏平衡售价: ${d.breakeven_sell_price_usd:.2f}",
    ]
    if scenarios:
        L.append("")
        L.append("三档情景:")
        for s in scenarios:
            sign_roi = "+" if s.delta_roi_pct >= 0 else ""
            sign_np = "+" if s.delta_net_profit >= 0 else ""
            L.append(
                f"  [{_fmt_level(s.decision.level)}] {s.name}: "
                f"净利润 ${s.decision.net_profit_usd:,.2f}  ROI {s.decision.roi_pct:.1f}%  "
                f"(Δ ROI {sign_roi}{s.delta_roi_pct:.1f}pp, "
                f"Δ 净利 {sign_np}${s.delta_net_profit:,.2f})"
            )
            if s.cross_check:
                L.append(f"        {s.cross_check}")
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
    opp, route, decision, legs, scenarios = decide_for_full(
        conn, args.sku, args.units, args.route
    )
    db.record_decision(conn, opp["id"], route["id"], args.units, decision)
    print(_print_decision(decision, opp, route, args.units, scenarios))
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
        opp, route, decision, legs, scenarios = decide_for_full(
            conn, args.sku, args.units, args.route
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    fmt = args.format
    out = Path(args.out) if args.out else None

    # Resolve target: --out can be a file path or an existing directory.
    # No --out for md -> stdout; for html/pdf -> exports/<auto-name>.
    if fmt == "md":
        body = render_markdown(opp, route, legs, args.units, decision, scenarios)
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
        body = render_html(opp, route, legs, args.units, decision, scenarios)
        target = _resolve_target(out, opp, route, "html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(f"wrote {target}")
    elif fmt == "pdf":
        body = render_html(opp, route, legs, args.units, decision, scenarios)
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


def _parse_leg_payload(raw: str) -> dict:
    """Parse a single `--leg` JSON payload into a route_leg dict.

    Required keys: ``kind``, ``label``, ``cost_usd``.  Optional keys
    (``duration_min``, ``location``, ``notes``, ``seq``) default to
    neutral values so callers can pass minimal payloads for short legs.

    Raises ``argparse.ArgumentTypeError`` on bad JSON / missing fields so
    argparse converts it to a clean CLI exit code 2 instead of a stack trace.
    """
    import argparse as _ap
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise _ap.ArgumentTypeError(f"--leg: invalid JSON ({e.msg} at pos {e.pos})")
    if not isinstance(payload, dict):
        raise _ap.ArgumentTypeError(
            f"--leg: expected JSON object, got {type(payload).__name__}"
        )
    missing = [k for k in ("kind", "label", "cost_usd") if k not in payload]
    if missing:
        raise _ap.ArgumentTypeError(
            f"--leg: missing required field(s): {', '.join(missing)}"
        )
    return dict(
        seq=int(payload.get("seq", 0)),  # 0 sentinel — caller assigns real seq
        kind=str(payload["kind"]),
        label=str(payload["label"]),
        cost_usd=float(payload["cost_usd"]),
        duration_min=float(payload.get("duration_min", 0.0)),
        location=str(payload.get("location", "")),
        notes=str(payload.get("notes", "")),
    )


def cmd_routes(args):
    """List routes in the DB (default), or insert a new route via --add.

    Examples:
        python -m arb routes
        python -m arb routes --add --name LAX-SFO-1N --origin "洛杉矶 LAX" \\
            --dest "旧金山 SFO" --flight 150 --hotel 120 --other 30 \\
            --hours 16 --depart 2026-09-16
        python -m arb routes --add --name JFK-LAX-1N --origin JFK --dest LAX \\
            --flight 200 --hotel 150 \\
            --leg '{"kind":"flight","label":"JFK → LAX","cost_usd":200,"duration_min":360}' \\
            --leg '{"kind":"hotel","label":"LAX Hotel 1N","cost_usd":150,"duration_min":0}'
    """
    conn = db.connect()
    try:
        if args.add:
            # Assign seq from the order of --leg flags on the command line.
            # Callers can override via explicit "seq" in the JSON payload.
            parsed_legs = []
            for i, leg in enumerate(args.leg or [], start=1):
                if not leg.get("seq"):
                    leg = dict(leg, seq=i)
                parsed_legs.append(leg)
            existing = db.get_route(conn, args.name)
            if existing is not None:
                # Re-add WITHOUT --leg stays a no-op (Round 8 contract:
                # "already exists; no changes made").  Re-add WITH --leg
                # replaces the leg set so the user can iterate on a route.
                if not parsed_legs:
                    print(f"route '{args.name}' already exists (id={existing['id']});"
                          " no changes made")
                    return 0
                rid = existing["id"]
                _replace_route_legs(conn, rid, parsed_legs)
                print(json.dumps({
                    "updated": True,
                    "id": rid,
                    "name": args.name,
                    "legs": len(parsed_legs),
                }, ensure_ascii=False))
                return 0
            new_route = dict(
                name=args.name,
                origin_city=args.origin,
                dest_city=args.dest,
                flight_cost_usd=args.flight,
                hotel_cost_usd=args.hotel,
                other_cost_usd=args.other,
                hours_available=args.hours,
                target_hourly_usd=20.0,
                target_roi_pct=15.0,
                min_roi_pct=10.0,
                departure_date=args.depart,
                source_url=args.source_url or "https://www.google.com/travel/flights",
                notes=args.notes or "",
            )
            rid = db.upsert_route(conn, new_route)
            if parsed_legs:
                db.add_route_legs(conn, rid, parsed_legs)
            print(json.dumps({
                "inserted": rid,
                "name": args.name,
                "legs": len(parsed_legs),
            }, ensure_ascii=False))
            return 0
        # default: list
        routes = db.list_routes(conn)
        if not routes:
            print("no routes in DB; run `python -m arb seed` first")
            return 0
        for r in routes:
            legs = db.list_route_legs(conn, r["id"])
            total_min = sum(l["duration_min"] for l in legs)
            fixed = r["flight_cost_usd"] + r["hotel_cost_usd"] + r["other_cost_usd"]
            print(
                f"  [{r['id']:>3}] {r['name']:18s} {r['origin_city']} → {r['dest_city']}\n"
                f"        flight ${r['flight_cost_usd']:.0f}  hotel ${r['hotel_cost_usd']:.0f}  "
                f"other ${r['other_cost_usd']:.0f}  (固定 ${fixed:.0f})  "
                f"hours {r['hours_available']:.0f}h  legs={len(legs)} ({total_min:.0f}min)\n"
                f"        target ROI {r['target_roi_pct']:.0f}%  min ROI {r['min_roi_pct']:.0f}%  "
                f"depart {r['departure_date']}  url {r['source_url']}"
            )
        return 0
    finally:
        conn.close()


def _replace_route_legs(conn, route_id: int, legs: list[dict]) -> None:
    """Delete every existing leg for a route, then insert the new set.

    We delete first (instead of relying on ``INSERT OR REPLACE``) so that
    *removed* legs (in the new payload) actually go away and a stale label
    cannot linger on the route.
    """
    conn.execute("DELETE FROM route_legs WHERE route_id=?", (route_id,))
    conn.commit()
    if legs:
        db.add_route_legs(conn, route_id, legs)


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


def cmd_verify(args):
    """Refresh an opportunity and compare scraped hints to stored prices.

    When hints match within ``--tolerance`` (default 5%), mark the opp as
    ``verified=1``.  When they drift beyond tolerance (or come back in a
    different currency), stage a proposal in ``proposed_prices`` instead of
    overwriting — the human is responsible for ``arb proposals apply`` / reject.
    """
    conn = db.connect()
    try:
        kwargs = {"today": _dt.date.today()}
        if args.dry_run:
            kwargs["auto_stage"] = False
        if args.tolerance is not None:
            kwargs["tolerance"] = args.tolerance
        outcome = verify_opportunity(conn, args.sku, **kwargs)
        if not outcome.message.startswith("opportunity not found"):
            conn.commit()
        d = verify_outcome_as_dict(outcome)
        print(json.dumps(d, ensure_ascii=False, indent=2))
        if outcome.message.startswith("opportunity not found"):
            return 1
        return 0 if (outcome.verified_now or outcome.purchase.proposal_id is not None
                     or outcome.sell.proposal_id is not None) else 1
    finally:
        conn.close()


def cmd_proposals(args):
    """List / apply / reject proposed_prices rows."""
    conn = db.connect()
    try:
        if args.action in ("apply", "reject"):
            res = db.resolve_proposed_price(conn, args.id, args.action)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0 if res["applied"] or res["proposal_status"] == "rejected" else 1
        # default: list
        rows = db.list_proposed_prices(
            conn, sku=args.sku, status=args.status,
        )
        if not rows:
            print("no proposals match filter")
            return 0
        for r in rows:
            print(f"  [{r['id']:>4}] {r['sku']:25s} {r['field']:22s} "
                  f"stored=${r['stored_value']:.2f} → proposed=${r['proposed_value']:.2f} "
                  f"({r['detected_currency']} drift={r['drift_pct']:.2f}%) "
                  f"status={r['status']:8s} url={r['source_url']}")
        return 0
    finally:
        conn.close()


def cmd_scenarios(args):
    """Print the 保守 / 中性 / 乐观 three-band verdict for a SKU."""
    conn = db.connect()
    try:
        try:
            opp, route, decision, legs, scenarios = decide_for_full(
                conn, args.sku, args.units, args.route
            )
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if args.json:
            out = {
                "sku": opp["sku"],
                "name": opp["name"],
                "route": route["name"],
                "num_units": args.units,
                "scenarios": [s.as_dict() for s in scenarios],
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        print(_print_decision(decision, opp, route, args.units, scenarios))
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

    p_verify = sub.add_parser("verify", help="refresh + compare hints to stored prices; mark verified or stage proposal")
    p_verify.add_argument("--sku", required=True)
    p_verify.add_argument("--tolerance", type=float, default=None,
                          help="drift fraction allowed before staging a proposal (default 0.05)")
    p_verify.add_argument("--dry-run", action="store_true",
                          help="compute the verdict but do not insert proposed_prices rows")

    p_prop = sub.add_parser("proposals", help="list / apply / reject proposed_prices rows")
    p_prop.add_argument("--sku", help="filter list to one SKU")
    p_prop.add_argument("--status", choices=["pending", "applied", "rejected"],
                        help="filter list by status (default: all)")
    p_prop.add_argument("action", nargs="?", choices=["apply", "reject"],
                        help="apply or reject a specific proposal")
    p_prop.add_argument("id", type=int, nargs="?",
                        help="proposal id (required with apply/reject)")

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

    p_sc = sub.add_parser("scenarios", help="show 保守/中性/乐观 three-band verdict")
    p_sc.add_argument("--sku", required=True)
    p_sc.add_argument("--units", type=int, required=True)
    p_sc.add_argument("--route", default="PVG-NRT-LAX-2N")
    p_sc.add_argument("--json", action="store_true",
                       help="emit machine-readable JSON instead of text")

    p_routes = sub.add_parser("routes", help="list routes (default) or --add a new route")
    p_routes.add_argument("--add", action="store_true",
                          help="insert a new route from CLI flags")
    p_routes.add_argument("--name", help="route unique name (required with --add)")
    p_routes.add_argument("--origin", help="origin city label, e.g. '洛杉矶 LAX'")
    p_routes.add_argument("--dest", help="dest city label, e.g. '旧金山 SFO'")
    p_routes.add_argument("--flight", type=float,
                          help="flight cost USD (required with --add)")
    p_routes.add_argument("--hotel", type=float,
                          help="hotel cost USD (required with --add)")
    p_routes.add_argument("--other", type=float, default=0.0,
                          help="other cost USD (default 0)")
    p_routes.add_argument("--hours", type=float, default=24.0,
                          help="hours available for the trip (default 24)")
    p_routes.add_argument("--depart", default=None,
                          help="departure date YYYY-MM-DD (optional)")
    p_routes.add_argument("--source-url", default=None,
                          help="source URL for the flight/hotel prices")
    p_routes.add_argument("--notes", default=None, help="route notes")
    p_routes.add_argument("--leg", action="append", type=_parse_leg_payload,
                          default=[],
                          help=("repeatable route leg as JSON, e.g. "
                                "'{\"kind\":\"flight\",\"label\":\"JFK→LAX\","
                                "\"cost_usd\":200,\"duration_min\":360}'. "
                                "Order on the command line = leg seq."))

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
        "verify": cmd_verify,
        "proposals": cmd_proposals,
        "scenarios": cmd_scenarios,
        "routes": cmd_routes,
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