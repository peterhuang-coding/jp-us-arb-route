"""CLI entry point: list / decide / report / seed / serve.

Examples:

  python -m arb list
  python -m arb decide --sku JP-SKII-FT230 --units 5
  python -m arb report --sku JP-SKII-FT230 --units 5 --md
  python -m arb report --sku JP-SKII-FT230 --units 5 --pdf --out exports/foo.pdf
  python -m arb serve --port 8765
  python -m arb seed
  python -m arb basket --budget 5000 --customs 5000 --json
  python -m arb flight --origin PVG --dest LAX --date 2026-09-15 --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
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
from .basket import solve_basket, item_from_opportunity
from .flight_price import search_flights, outcome_as_dict as flight_outcome_as_dict


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
        f"  成功率: {opp['success_rate']*100:.0f}% (自用默认 100%,此字段保留向后兼容)",
        f"  回本率: {d.payback_rate_pct:.1f}%  行程净值: ${d.trip_net_value_usd:,.2f}  "
        f"累计节省: ${d.total_savings_usd:,.2f}",
        f"  行程成本: ${d.total_cost_usd:,.2f}  ROI: {d.roi_pct:.1f}%",
        f"  耗时: {d.hours_used:.1f}h / {route['hours_available']:.1f}h",
        f"  盈亏平衡中国参考价: ${d.breakeven_sell_price_usd:.2f}",
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


def cmd_basket(args):
    """Solve the optimal shopping basket within budget + customs cap (default 5000元)."""
    conn = db.connect()
    try:
        route = db.get_route(conn, args.route)
        if route is None:
            print(f"error: route not found: {args.route}", file=sys.stderr)
            return 1
        fx = float(route["cn_to_usd_fx"]) if "cn_to_usd_fx" in route.keys() else 0.14
        opps = db.list_opportunities(conn)
        items = [item_from_opportunity(dict(o), fx_rate=fx) for o in opps]
        trip_cost_usd = (
            float(route["flight_cost_usd"])
            + float(route["hotel_cost_usd"])
            + float(route["other_cost_usd"])
        )
        sol = solve_basket(
            items,
            budget_cny=args.budget,
            customs_limit_cny=args.customs,
            trip_cost_usd=trip_cost_usd,
            fx_rate=fx,
        )
        if args.json:
            out = {
                "route": route["name"],
                "fx_rate": sol.fx_rate,
                "budget_cny": sol.budget_cny,
                "customs_limit_cny": sol.customs_limit_cny,
                "trip_cost_usd": sol.trip_cost_usd,
                "total_spend_cny": sol.total_spend_cny,
                "total_savings_cny": sol.total_savings_cny,
                "payback_rate_pct": sol.payback_rate_pct,
                "leftover_cny": sol.leftover_cny,
                "customs_headroom_cny": sol.customs_headroom_cny,
                "algorithm": sol.algorithm,
                "notes": sol.notes,
                "skipped_skus": sol.skipped_skus,
                "picks": [
                    {
                        "sku": p.sku,
                        "name": p.name,
                        "category": p.category,
                        "num_units": p.num_units,
                        "jp_price_per_unit_cny": p.jp_price_per_unit_cny,
                        "home_price_per_unit_cny": p.home_price_per_unit_cny,
                        "savings_per_unit_cny": p.savings_per_unit_cny,
                        "subtotal_cny": p.subtotal_cny,
                        "total_savings_cny": p.total_savings_cny,
                    }
                    for p in sol.picks
                ],
            }
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        # human-readable text
        print(f"=== 购物清单求解 (5000元 额度) ===")
        print(f"路线: {route['name']}  行程成本: ${trip_cost_usd:.0f}  "
              f"FX: {fx:.4f} USD/CNY  预算 ¥{args.budget:.0f}  海关额度 ¥{args.customs:.0f}")
        print()
        if not sol.picks:
            print("(无可用 SKU)")
        else:
            print(f"{'SKU':<22} {'数量':>4} {'日单价¥':>10} {'中国¥':>10} {'节省¥':>10} {'小计¥':>10} {'累计节省¥':>12}")
            cum = 0.0
            for p in sol.picks:
                cum += p.total_savings_cny
                print(f"{p.sku:<22} {p.num_units:>4} "
                      f"{p.jp_price_per_unit_cny:>10.1f} {p.home_price_per_unit_cny:>10.1f} "
                      f"{p.savings_per_unit_cny:>10.1f} {p.subtotal_cny:>10.1f} {cum:>12.1f}")
        print()
        print(f"总花费: ¥{sol.total_spend_cny:.1f}  总节省: ¥{sol.total_savings_cny:.1f}")
        if math.isinf(sol.payback_rate_pct):
            print(f"回本率: ∞  (行程成本为 0)")
        else:
            print(f"回本率: {sol.payback_rate_pct:.1f}%")
        print(f"剩余预算: ¥{sol.leftover_cny:.1f}  海关余量: ¥{sol.customs_headroom_cny:.1f}")
        if sol.skipped_skus:
            print()
            print(f"跳过 {len(sol.skipped_skus)} 条 (无中国参考价 或 单件节省≤0):")
            for s in sol.skipped_skus[:5]:
                print(f"  - {s}")
            if len(sol.skipped_skus) > 5:
                print(f"  ... 共 {len(sol.skipped_skus)} 条")
        return 0
    finally:
        conn.close()


def cmd_flight(args):
    """Query Amadeus Self-Service Flight Offers Search (Round 14, half-auto)."""
    # Resolve creds from env so a missing one is reported once with a clear message.
    import os
    cid = os.environ.get("AMADEUS_CLIENT_ID")
    cs = os.environ.get("AMADEUS_CLIENT_SECRET")
    if not cid or not cs:
        print(
            "error: AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET not set. "
            "Register at https://developers.amadeus.com/ and export the test-env credentials.",
            file=sys.stderr,
        )
        return 1
    outcome = search_flights(
        args.origin, args.dest, args.date,
        adults=args.adults, cabin=args.cabin, currency=args.currency,
        use_cache=not args.no_cache,
    )
    if args.json:
        print(json.dumps(flight_outcome_as_dict(outcome), ensure_ascii=False, indent=2))
        return 0 if outcome.ok else 2
    # Human-readable
    if not outcome.ok:
        print(f"error: {outcome.blocked_reason}", file=sys.stderr)
        print(f"({outcome.message})", file=sys.stderr)
        return 2
    if not outcome.offers:
        print(f"=== {outcome.origin} → {outcome.dest} {outcome.date} "
              f"({outcome.cabin}, {outcome.adults} pax) ===")
        print("(no offers returned)")
        return 0
    print(f"=== {outcome.origin} → {outcome.dest} {outcome.date} "
          f"({outcome.cabin}, {outcome.adults} pax)  {outcome.message} ===")
    if outcome.cached:
        print("(cached)")
    print()
    print(f"{'#':<3} {'价格':>10} {'航司':>5} {'经停':>4}  行程")
    for i, off in enumerate(outcome.offers, 1):
        seg_strs = []
        for seg in off.segments[:4]:
            d, a = seg.get("departure_iata"), seg.get("arrival_iata")
            seg_strs.append(f"{d}→{a} ({seg.get('carrier')}{seg.get('flight_number')})")
        if len(off.segments) > 4:
            seg_strs.append(f"...+{len(off.segments) - 4}")
        print(f"{i:<3} {off.price_total:>8.2f} {off.currency:<3} "
              f"{(off.validating_carrier or '-'):>5} {off.num_stops:>4}  "
              f"{' / '.join(seg_strs)}")
    return 0


# ---------- backfill (Round 15) ----------

# Validation bounds for home_price_cny.  ¥0 is allowed only as an explicit
# marker meaning "no China reference price" (basket will skip with reason);
# any non-zero value must be reasonable.  ¥100k cap blocks accidental
# comma/shift typos (e.g. typing 1500 vs 15000).
_MIN_PRICE = 0.0
_MAX_PRICE = 100000.0
_MIN_MAX_UNITS = 1


def _coerce_backfill_rows(payload) -> list[dict]:
    """Normalize the JSON payload into a list of row dicts.

    Accepts either a list of dicts or a single dict (single-row shorthand).
    Each returned row has at minimum ``sku`` and ``home_price_cny`` keys;
    optional keys ``max_units_per_trip`` and ``source`` are preserved if
    present.  Raises ValueError on type-shape mismatch.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValueError(f"payload must be a list or dict, got {type(payload).__name__}")
    rows = []
    for i, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise ValueError(f"row #{i} must be a dict, got {type(raw).__name__}")
        if "sku" not in raw or "home_price_cny" not in raw:
            raise ValueError(f"row #{i} missing required key 'sku' or 'home_price_cny'")
        if isinstance(raw.get("sku"), str) and not raw["sku"].strip():
            raise ValueError(f"row #{i} sku must be a non-empty string")
        rows.append(dict(raw))  # shallow copy
    return rows


def _validate_backfill_row(row: dict) -> str | None:
    """Return None if the row is valid, else a human-readable reason string."""
    sku = row.get("sku")
    if not isinstance(sku, str) or not sku.strip():
        return "sku must be a non-empty string"
    price = row.get("home_price_cny")
    if not isinstance(price, (int, float)):
        return "home_price_cny must be a number"
    if price < _MIN_PRICE or price > _MAX_PRICE:
        return f"home_price_cny {price} out of bounds [{_MIN_PRICE}, {_MAX_PRICE}]"
    if "max_units_per_trip" in row:
        mu = row["max_units_per_trip"]
        if not isinstance(mu, int) or mu < _MIN_MAX_UNITS:
            return f"max_units_per_trip must be int >= {_MIN_MAX_UNITS}, got {mu!r}"
    return None


def cmd_backfill_home_prices(args):
    """Batch-update ``home_price_cny`` (and optionally ``max_units_per_trip``).

    Reads a JSON payload (list of dicts, or single dict) from ``--file`` or
    stdin.  Each row needs ``sku`` and ``home_price_cny``; ``max_units_per_trip``
    and ``source`` are optional.  Validation errors skip individual rows; the
    transaction is per-row so a later bad row does not block earlier good ones.
    By default rows are committed; ``--dry-run`` parses + validates only.
    Prints a JSON or human report of updated / skipped rows.
    """
    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            payload_text = fh.read()
    else:
        payload_text = sys.stdin.read()
    try:
        payload = json.loads(payload_text) if payload_text.strip() else []
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON in backfill payload: {e}", file=sys.stderr)
        return 2
    try:
        rows = _coerce_backfill_rows(payload)
    except ValueError as e:
        print(f"error: invalid backfill payload: {e}", file=sys.stderr)
        return 2

    conn = db.connect()
    today = _dt.date.today().isoformat()
    updated: list[dict] = []
    skipped: list[dict] = []

    with db.tx(conn):
        for row in rows:
            sku = row["sku"]
            reason = _validate_backfill_row(row)
            if reason:
                skipped.append({"sku": sku, "reason": reason})
                continue
            existing = db.get_opportunity(conn, sku)
            if existing is None:
                skipped.append({"sku": sku, "reason": "sku not found in DB"})
                continue
            new_price = float(row["home_price_cny"])
            old_price = existing["home_price_cny"]
            old_max = existing["max_units_per_trip"]
            patch: dict = {"home_price_cny": new_price,
                           "data_freshness_ts": today}
            new_max: int | None = None
            if "max_units_per_trip" in row:
                new_max = int(row["max_units_per_trip"])
                patch["max_units_per_trip"] = new_max
            if args.dry_run:
                updated.append({
                    "sku": sku,
                    "old_home_price_cny": old_price,
                    "new_home_price_cny": new_price,
                    "old_max_units_per_trip": old_max,
                    "new_max_units_per_trip": new_max,
                    "dry_run": True,
                })
                continue
            conn.execute(
                "UPDATE opportunities SET home_price_cny = ?, "
                "max_units_per_trip = COALESCE(?, max_units_per_trip), "
                "data_freshness_ts = ? WHERE sku = ?",
                (new_price,
                 int(row["max_units_per_trip"]) if "max_units_per_trip" in row else None,
                 today, sku),
            )
            updated.append({
                "sku": sku,
                "old_home_price_cny": old_price,
                "new_home_price_cny": new_price,
                "old_max_units_per_trip": old_max,
                "new_max_units_per_trip": new_max,
            })

    if args.dry_run:
        conn.rollback()
    report = {"updated": updated, "skipped": skipped,
              "dry_run": bool(args.dry_run), "today": today}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"[{'DRY-RUN ' if args.dry_run else ''}backfill-home-prices] "
              f"{len(updated)} updated, {len(skipped)} skipped  (today={today})")
        for u in updated:
            old = f"{u['old_home_price_cny']}" if u['old_home_price_cny'] is not None else "NULL"
            new = f"{u['new_home_price_cny']}"
            print(f"  ✓ {u['sku']:30s} home_price_cny {old} -> {new}")
        for s in skipped:
            print(f"  ✗ {s['sku']:30s} {s['reason']}")
    return 0 if not skipped else 1 if not args.dry_run and not updated else 0


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

    p_basket = sub.add_parser("basket", help="solve 5000元 额度内最优购物清单 (有界 0/1 背包)")
    p_basket.add_argument("--budget", type=float, default=5000.0,
                          help="总预算 (元,默认 5000)")
    p_basket.add_argument("--customs", type=float, default=5000.0,
                          help="海关免税额度 (元,默认 5000)")
    p_basket.add_argument("--route", default="PVG-NRT-LAX-2N",
                          help="对应路线 (决定 FX 与行程成本)")
    p_basket.add_argument("--json", action="store_true",
                          help="emit machine-readable JSON instead of text")

    p_flight = sub.add_parser(
        "flight",
        help="query Amadeus Self-Service Flight Offers Search (half-auto, not persisted)",
    )
    p_flight.add_argument("--origin", required=True, help="IATA origin, e.g. PVG")
    p_flight.add_argument("--dest", required=True, help="IATA dest, e.g. LAX")
    p_flight.add_argument("--date", required=True, help="departure date YYYY-MM-DD")
    p_flight.add_argument("--adults", type=int, default=1, help="passenger count (default 1)")
    p_flight.add_argument(
        "--cabin", default="ECONOMY",
        choices=["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"],
        help="cabin class (default ECONOMY)",
    )
    p_flight.add_argument("--currency", default="USD", help="price currency (default USD)")
    p_flight.add_argument("--no-cache", action="store_true",
                          help="bypass the in-memory cache (default: cache 10min)")
    p_flight.add_argument("--json", action="store_true",
                          help="emit machine-readable JSON instead of text")

    p_backfill = sub.add_parser(
        "backfill-home-prices",
        help="batch-set home_price_cny (and optionally max_units_per_trip) from JSON on stdin or --file",
    )
    p_backfill.add_argument("--file", default=None,
                           help="read JSON from this path instead of stdin")
    p_backfill.add_argument("--dry-run", action="store_true",
                           help="parse + validate but do not write to DB")
    p_backfill.add_argument("--json", action="store_true",
                           help="emit machine-readable JSON report")

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
        "basket": cmd_basket,
        "flight": cmd_flight,
        "backfill-home-prices": cmd_backfill_home_prices,
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