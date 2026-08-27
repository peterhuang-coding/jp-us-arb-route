"""FastAPI backend for the jp-us-arb-route Web SPA.

Local-only dev server (Goal Brief §9: 127.0.0.1). Mounts the static SPA at / and
serves JSON endpoints under /api/.  All endpoints reuse arb.db + arb.decision +
arb.report — no business logic duplicated here.

Run:
    uvicorn arb.web_api:app --host 127.0.0.1 --port 8765
or  python -m arb serve
"""
from __future__ import annotations

import urllib.parse
import json
from pathlib import Path
import datetime as _dt
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, freshness, prices, alerts, tax_codes
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


def _content_disposition(filename: str) -> str:
    """Build an RFC 5987 Content-Disposition with ASCII fallback + UTF-8 form.

    Starlette serializes headers as latin-1, so filenames with CJK characters
    must be encoded as `filename*=UTF-8''...` (RFC 5987).  We supply both
    forms: a short ASCII fallback for legacy clients, and the full UTF-8 form
    for modern browsers.
    """
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace("?", "_")
    utf8_form = urllib.parse.quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{utf8_form}"


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


app = FastAPI(
    title="jp-us-arb-route",
    description="Per-trip arbitrage decision engine — local API.",
    version="0.2.0",
)


@app.on_event("startup")
def _backfill_leg_times() -> None:
    """Stamp depart_at / arrive_at on every route's legs that has
    departure_date set.  Skips silently when no departure_date (legacy
    routes that the user hasn't filled in yet)."""
    from .db import backfill_route_leg_times, connect, list_routes
    conn = connect()
    try:
        for r in list_routes(conn):
            try:
                backfill_route_leg_times(conn, r["id"])
            except ValueError:
                # No departure_date → skip; user must fill manually.
                pass
    finally:
        conn.close()


# ---------- request / response models ----------

class DecideRequest(BaseModel):
    sku: str = Field(..., min_length=1)
    num_units: int = Field(..., ge=1)
    route: str = "PVG-NRT-LAX-2N"


class Opportunity(BaseModel):
    sku: str
    name: str
    category: str
    source_market: str
    target_market: str
    purchase_price_usd: float
    tariff_rate: float
    sell_price_usd: float
    shipping_per_unit_usd: float
    platform_fee_rate: float
    minutes_per_unit: float
    success_rate: float
    purchase_source_url: Optional[str]
    sell_source_url: Optional[str]
    notes: Optional[str]
    data_freshness_ts: str
    verified: bool
    freshness: Optional[dict] = None        # verdict embedded by /api/opportunities
    # Round 19: multi-channel buy/sell lists (JSON-encoded in DB, decoded here)
    purchase_channels: list[dict] = []
    sell_channels: list[dict] = []


class RefreshResponse(BaseModel):
    sku: str
    name: str
    previous_freshness_ts: Optional[str]
    new_freshness_ts: Optional[str]
    updated: bool
    verdict_before: dict
    verdict_after: Optional[dict]
    purchase: Optional[dict]
    sell: Optional[dict]
    message: str


class VerifySideCheck(BaseModel):
    field: str
    stored_value: float
    source_url: Optional[str]
    extracted: Optional[dict]
    drift_pct: Optional[float]
    accepted: bool
    proposal_id: Optional[int]
    note: str


class VerifyResponse(BaseModel):
    sku: str
    name: str
    refresh_updated: bool
    refreshed_at: Optional[str]
    verified_now: bool
    final_verified: bool
    final_freshness_ts: Optional[str]
    purchase: VerifySideCheck
    sell: VerifySideCheck
    message: str


class ProposalRow(BaseModel):
    id: int
    sku: str
    field: str
    stored_value: float
    proposed_value: float
    detected_currency: str
    detected_raw: str
    source_url: str
    drift_pct: float
    status: str
    detected_at: str
    resolved_at: Optional[str] = None


class ProposalResolveResponse(BaseModel):
    applied: bool
    proposal_status: Optional[str]
    field: Optional[str]
    new_value: Optional[float]
    message: str


class EvidenceRow(BaseModel):
    id: int
    sku: str
    side: str
    channel_name: str
    channel_url: Optional[str] = None
    price_cny: float
    price_type: str
    source_url: Optional[str] = None
    observed_at: str
    notes: Optional[str] = None
    verified: bool


class RouteSummary(BaseModel):
    name: str
    origin_city: str
    dest_city: str
    flight_cost_usd: float
    hotel_cost_usd: float
    other_cost_usd: float
    hours_available: float
    target_hourly_usd: float
    target_roi_pct: float
    min_roi_pct: float
    departure_date: Optional[str]
    source_url: Optional[str]
    notes: Optional[str]
    region: Optional[str] = "cn-jp"               # Round 23: 'cn-jp' | 'us-domestic' | 'cn-jp-us'
    transfer_cost_cny: Optional[float] = 0.0      # 北京 0;上海 +¥600;天津 +¥200
    flight_source_url: Optional[str] = None       # 机票比价/订票链接
    legs: list[dict]


class DecisionResponse(BaseModel):
    opp: dict
    route: dict
    legs: list[dict]
    num_units: int
    decision: dict
    scenarios: list[dict] = []  # [保守, 中性, 乐观] ScenarioResult.as_dict()


# ---------- helpers ----------

def _row_to_opp(r) -> dict:
    # Round 19: parse JSON-encoded channel lists; default to [] for legacy rows
    # where the column is null or empty (e.g. older SKU not yet enriched).
    def _decode(key: str) -> list[dict]:
        raw = r[key] if key in r.keys() else None
        if not raw:
            return []
        try:
            v = json.loads(raw)
            return v if isinstance(v, list) else []
        except (TypeError, ValueError):
            return []
    return dict(r) | {
        "verified": bool(r["verified"]),
        "purchase_channels": _decode("purchase_channels"),
        "sell_channels": _decode("sell_channels"),
    }


def _row_to_route(r) -> dict:
    return dict(r)


def _row_to_leg(lg) -> dict:
    """Decode a route_legs row to its dict form, JSON-parsing the Round 20
    ``stops`` column so the SPA gets a native list."""
    leg = dict(lg)
    raw = leg.get("stops")
    if not raw:
        leg["stops"] = []
        return leg
    try:
        v = json.loads(raw)
        leg["stops"] = v if isinstance(v, list) else []
    except (TypeError, ValueError):
        leg["stops"] = []
    return leg


# ---------- API routes ----------

@app.get("/api/health")
def health():
    conn = db.connect()
    try:
        return {
            "ok": True,
            "opportunities": len(db.list_opportunities(conn)),
            "routes": len(db.list_routes(conn)),
            "db": str(db.DB_PATH),
        }
    finally:
        conn.close()


@app.get("/api/opportunities", response_model=list[Opportunity])
def list_opportunities():
    conn = db.connect()
    try:
        opps = [_row_to_opp(r) for r in db.list_opportunities(conn)]
        return freshness.attach(opps)  # type: ignore[return-value]
    finally:
        conn.close()


@app.post("/api/opportunities/{sku}/refresh", response_model=RefreshResponse)
def refresh_opportunity_endpoint(sku: str):
    """Probe the opp's URLs and bump ``data_freshness_ts`` if both succeeded.

    Prices are NOT auto-overwritten — V0 only refreshes the freshness stamp
    so the UI can demote stale SKUs.  ``price_hints`` is returned so a human
    can decide whether to manually update the opp's purchase / sell price.
    """
    conn = db.connect()
    try:
        outcome = refresh_opportunity(conn, sku)
        if not outcome.message.startswith("opportunity not found"):
            conn.commit()
        return outcome_as_dict(outcome)
    finally:
        conn.close()


@app.post("/api/opportunities/{sku}/verify", response_model=VerifyResponse)
def verify_opportunity_endpoint(sku: str, dry_run: bool = False):
    """Refresh + compare scraped price_hints to stored prices.

    When both sides match within ±5% (or the override ``dry_run`` skips
    proposal insertion), mark ``verified=1``.  When they drift beyond
    tolerance, stage ``proposed_prices`` rows for human review instead of
    overwriting.  Never auto-overwrites stored prices.
    """
    conn = db.connect()
    try:
        outcome = verify_opportunity(conn, sku, auto_stage=not dry_run)
        if not outcome.message.startswith("opportunity not found"):
            conn.commit()
        return verify_outcome_as_dict(outcome)
    finally:
        conn.close()


@app.get("/api/proposals", response_model=list[ProposalRow])
def list_proposals(sku: Optional[str] = None, status: Optional[str] = None):
    """List proposed_prices rows, optional filters by sku / status."""
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_proposed_prices(conn, sku=sku, status=status)]
    finally:
        conn.close()


@app.post("/api/proposals/{proposal_id}/apply", response_model=ProposalResolveResponse)
def apply_proposal(proposal_id: int):
    """Apply a proposal: overwrite the stored price, mark proposal applied."""
    conn = db.connect()
    try:
        res = db.resolve_proposed_price(conn, proposal_id, "apply")
        conn.commit()
        if res["applied"] is False and res["proposal_status"] is None:
            raise HTTPException(status_code=404, detail=res["message"])
        return res
    finally:
        conn.close()


@app.post("/api/proposals/{proposal_id}/reject", response_model=ProposalResolveResponse)
def reject_proposal(proposal_id: int):
    """Reject a proposal: keep the stored price, mark proposal rejected."""
    conn = db.connect()
    try:
        res = db.resolve_proposed_price(conn, proposal_id, "reject")
        conn.commit()
        if res["applied"] is False and res["proposal_status"] is None:
            raise HTTPException(status_code=404, detail=res["message"])
        return res
    finally:
        conn.close()


# ---------- Round 21: evidence audit trail ----------

@app.get("/api/evidence", response_model=list[EvidenceRow])
def list_evidence_endpoint(sku: Optional[str] = None, side: Optional[str] = None):
    """List evidence_log rows. Filterable by sku and/or side (buy | sell).
    The SPA hits this once at load time and then looks up by id from channel
    dicts (each channel carries evidence_ids referencing rows here)."""
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_evidence(conn, sku=sku, side=side)]
    finally:
        conn.close()


@app.get("/api/routes", response_model=list[RouteSummary])
def list_routes():
    conn = db.connect()
    try:
        out = []
        for r in db.list_routes(conn):
            legs = [_row_to_leg(lg) for lg in db.list_route_legs(conn, r["id"])]
            out.append(_row_to_route(r) | {"legs": legs})
        return out
    finally:
        conn.close()


@app.post("/api/decide", response_model=DecisionResponse)
def decide(req: DecideRequest):
    conn = db.connect()
    try:
        try:
            opp, route, decision, legs, scenarios = decide_for_full(
                conn, req.sku, req.num_units, req.route
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        db.record_decision(conn, opp["id"], route["id"], req.num_units, decision)
        return {
            "opp": _row_to_opp(opp),
            "route": _row_to_route(route),
            "legs": [dict(lg) for lg in legs],
            "num_units": req.num_units,
            "decision": decision.as_dict(),
            "scenarios": [s.as_dict() for s in scenarios],
        }
    finally:
        conn.close()


def _serve_report(sku: str, fmt: str, num_units: int = 5, route: str = "PVG-NRT-LAX-2N"):
    conn = db.connect()
    try:
        try:
            opp, rt, decision, legs, scenarios = decide_for_full(
                conn, sku, num_units, route
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if fmt == "md":
            return Response(
                content=render_markdown(opp, rt, legs, num_units, decision, scenarios),
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": _content_disposition(
                        report_filename(sku, rt["dest_city"], "md")
                    ),
                },
            )
        if fmt == "html":
            return Response(
                content=render_html(opp, rt, legs, num_units, decision, scenarios),
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": _content_disposition(
                        report_filename(sku, rt["dest_city"], "html")
                    ),
                },
            )
        if fmt == "pdf":
            html_str = render_html(opp, rt, legs, num_units, decision, scenarios)
            tmp = Path("/tmp") / report_filename(sku, rt["dest_city"], "pdf")
            render_pdf(html_str, tmp)
            return FileResponse(
                path=str(tmp),
                media_type="application/pdf",
                filename=report_filename(sku, rt["dest_city"], "pdf"),
            )
        raise HTTPException(status_code=400, detail=f"unsupported format: {fmt}")
    finally:
        conn.close()


@app.get("/api/report/{sku}.md")
def report_md(sku: str, num_units: int = 5, route: str = "PVG-NRT-LAX-2N"):
    return _serve_report(sku, "md", num_units, route)


@app.get("/api/report/{sku}.html")
def report_html(sku: str, num_units: int = 5, route: str = "PVG-NRT-LAX-2N"):
    return _serve_report(sku, "html", num_units, route)


@app.get("/api/report/{sku}.pdf")
def report_pdf(sku: str, num_units: int = 5, route: str = "PVG-NRT-LAX-2N"):
    return _serve_report(sku, "pdf", num_units, route)


# ---------- Round 13: 5000元 optimal basket ----------

class BasketRequest(BaseModel):
    budget_cny: float = Field(5000.0, ge=0)
    customs_limit_cny: float = Field(5000.0, ge=0)
    route: str = "PVG-NRT-LAX-2N"


class BasketPickOut(BaseModel):
    sku: str
    name: str
    category: str
    num_units: int
    jp_price_per_unit_cny: float
    home_price_per_unit_cny: float
    savings_per_unit_cny: float
    subtotal_cny: float
    total_savings_cny: float


class BasketResponse(BaseModel):
    route: str
    fx_rate: float
    budget_cny: float
    customs_limit_cny: float
    trip_cost_usd: float
    total_spend_cny: float
    total_savings_cny: float
    payback_rate_pct: float
    leftover_cny: float
    customs_headroom_cny: float
    algorithm: str
    notes: list[str]
    skipped_skus: list[str]
    picks: list[BasketPickOut]


@app.post("/api/basket", response_model=BasketResponse)
def basket(req: BasketRequest):
    conn = db.connect()
    try:
        route = db.get_route(conn, req.route)
        if route is None:
            raise HTTPException(status_code=404, detail=f"route not found: {req.route}")
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
            budget_cny=req.budget_cny,
            customs_limit_cny=req.customs_limit_cny,
            trip_cost_usd=trip_cost_usd,
            fx_rate=fx,
        )
        return BasketResponse(
            route=route["name"],
            fx_rate=sol.fx_rate,
            budget_cny=sol.budget_cny,
            customs_limit_cny=sol.customs_limit_cny,
            trip_cost_usd=sol.trip_cost_usd,
            total_spend_cny=sol.total_spend_cny,
            total_savings_cny=sol.total_savings_cny,
            payback_rate_pct=sol.payback_rate_pct,
            leftover_cny=sol.leftover_cny,
            customs_headroom_cny=sol.customs_headroom_cny,
            algorithm=sol.algorithm,
            notes=sol.notes,
            skipped_skus=sol.skipped_skus,
            picks=[
                BasketPickOut(
                    sku=p.sku, name=p.name, category=p.category,
                    num_units=p.num_units,
                    jp_price_per_unit_cny=p.jp_price_per_unit_cny,
                    home_price_per_unit_cny=p.home_price_per_unit_cny,
                    savings_per_unit_cny=p.savings_per_unit_cny,
                    subtotal_cny=p.subtotal_cny,
                    total_savings_cny=p.total_savings_cny,
                )
                for p in sol.picks
            ],
        )
    finally:
        conn.close()


# ---------- Round 16: Amadeus flight search (live if creds, else stub) ----------

@app.get("/api/flight")
def flight(origin: str, dest: str, date: str,
           adults: int = 1, cabin: str = "ECONOMY",
           currency: str = "USD"):
    """Proxy Amadeus Flight Offers Search.

    Returns 503 if AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET are unset
    (still includes a ``reason`` field so the SPA can render an instructive
    message instead of a generic error).
    """
    import os
    cid = os.environ.get("AMADEUS_CLIENT_ID")
    cs = os.environ.get("AMADEUS_CLIENT_SECRET")
    if not cid or not cs:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "reason": "AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET not set",
                "hint": ("Register at https://developers.amadeus.com/ and export "
                         "the test-env credentials, then restart the server."),
                "origin": origin.upper(),
                "dest": dest.upper(),
                "date": date,
                "offers": [],
            },
        )
    outcome = search_flights(
        origin.upper(), dest.upper(), date,
        adults=adults, cabin=cabin, currency=currency,
        use_cache=True,
    )
    payload = flight_outcome_as_dict(outcome)
    if not outcome.ok:
        return JSONResponse(status_code=502, content=payload)
    return payload


# ---------- static SPA mounted last so /api/* wins ----------

# Round 24: F1 — competitor_prices CRUD
@app.get("/api/prices")
def list_prices(sku: Optional[str] = None, source: Optional[str] = None,
                days: Optional[int] = None):
    conn = db.connect()
    try:
        rows = db.list_competitor_prices(conn, sku=sku, source=source, days=days)
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/prices/fetch")
def fetch_prices(sku: Optional[str] = None, source: Optional[str] = None):
    """Fetch one (sku, source) or all (sku=None, source=None)."""
    conn = db.connect()
    try:
        if sku and source:
            return prices.fetch_one(conn, sku, source)
        return prices.fetch_all(conn, sku=sku)
    finally:
        conn.close()


@app.get("/api/prices/diff")
def prices_diff(sku: str, source: str):
    conn = db.connect()
    try:
        return prices.price_diff_cny(conn, sku, source) or {}
    finally:
        conn.close()


# Round 24: F2 — price alerts
@app.get("/api/alerts")
def list_alerts_endpoint(sku: Optional[str] = None):
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_price_alerts(conn, sku=sku)]
    finally:
        conn.close()


@app.post("/api/alerts/evaluate")
def evaluate_alerts(sku: Optional[str] = None):
    conn = db.connect()
    try:
        triggered = alerts.evaluate_alerts(conn, sku=sku)
        return {"triggered": triggered, "count": len(triggered)}
    finally:
        conn.close()


# Round 24: F3 — quota
@app.get("/api/quota")
def quota_summary_endpoint(as_of: Optional[str] = None):
    conn = db.connect()
    try:
        return db.quota_summary(conn, as_of=as_of)
    finally:
        conn.close()


@app.get("/api/quota/entries")
def list_quota_entries(since: Optional[str] = None, sku: Optional[str] = None):
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_quota_entries(conn, since=since, sku=sku)]
    finally:
        conn.close()


@app.post("/api/quota/entries")
def add_quota_entry(payload: dict):
    conn = db.connect()
    try:
        new_id = db.record_quota_entry(conn, payload)
        return {"id": new_id}
    finally:
        conn.close()


# T9: quota_window endpoint (跨多趟 ¥5,000 入境额度)
@app.post("/api/quota-window")
def add_quota_window_endpoint(payload: dict):
    """Record an entry-day quota usage (Round 24 F3: china_quota_usage ledger).

    Payload: {entry_date: 'YYYY-MM-DD', entry_cny: 5000, trip_id: int, notes: str}
    Legacy SPA fields map onto the per-SKU ledger as one manual row so the
    summary in ``db.quota_summary`` sees them.
    """
    conn = db.connect()
    try:
        new_id = db.record_quota_entry(conn, dict(
            entry_date=payload['entry_date'],
            sku='MANUAL-ENTRY',
            quantity=1,
            unit_price_cny=float(payload['entry_cny']),
            trip_label=f"trip#{payload['trip_id']}" if payload.get('trip_id') else None,
            notes=payload.get('notes'),
        ))
        return {"id": new_id}
    finally:
        conn.close()


# Round 24: F4 — returns
@app.get("/api/returns")
def list_returns_endpoint(sku: Optional[str] = None, returned_only: bool = False):
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_returns(conn, sku=sku, returned_only=returned_only)]
    finally:
        conn.close()


@app.post("/api/returns")
def add_return(payload: dict):
    conn = db.connect()
    try:
        new_id = db.record_return(conn, payload)
        return {"id": new_id}
    finally:
        conn.close()


@app.get("/api/margin")
def monthly_margin_endpoint(month: str):
    conn = db.connect()
    try:
        return db.monthly_margin(conn, month)
    finally:
        conn.close()


# Round 24: F5 — tax codes
@app.get("/api/tax")
def list_tax_codes():
    return tax_codes.summary_table()


@app.get("/api/tax/{sku}")
def get_tax_code(sku: str):
    info = tax_codes.get_tax_info(sku)
    if info is None:
        raise HTTPException(status_code=404, detail=f"sku not in whitelist: {sku}")
    return info


# Round 25: Inventory (哥们仓 + 在途 + 已上架)
@app.get("/api/inventory")
def list_inventory_endpoint(location: Optional[str] = None,
                            include_sold: bool = False,
                            sku: Optional[str] = None):
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_inventory(conn, location=location,
                                                    include_sold=include_sold,
                                                    sku=sku)]
    finally:
        conn.close()


@app.post("/api/inventory")
def add_inventory_endpoint(payload: dict):
    conn = db.connect()
    try:
        new_id = db.add_inventory(conn, payload)
        return {"id": new_id}
    finally:
        conn.close()


@app.patch("/api/inventory/{item_id}")
def update_inventory_endpoint(item_id: int, payload: dict):
    conn = db.connect()
    try:
        return {"rowcount": db.update_inventory(conn, item_id, payload)}
    finally:
        conn.close()


@app.delete("/api/inventory/{item_id}")
def delete_inventory_endpoint(item_id: int):
    conn = db.connect()
    try:
        return {"rowcount": db.delete_inventory(conn, item_id)}
    finally:
        conn.close()


@app.get("/api/inventory/summary")
def inventory_summary_endpoint():
    conn = db.connect()
    try:
        return db.inventory_summary(conn)
    finally:
        conn.close()


# Round 25: Order status (下单/在途/到货/上架/售出)
@app.get("/api/orders")
def list_orders_endpoint(pending_only: bool = False):
    conn = db.connect()
    try:
        if pending_only:
            return [dict(r) for r in db.list_pending_orders(conn)]
        return [dict(r) for r in db.list_all_status(conn)]
    finally:
        conn.close()


@app.get("/api/orders/{sku}")
def get_order_status_endpoint(sku: str):
    conn = db.connect()
    try:
        row = db.get_order_status(conn, sku)
        return dict(row) if row else {}
    finally:
        conn.close()


@app.post("/api/orders/{sku}")
def set_order_status_endpoint(sku: str, payload: dict):
    conn = db.connect()
    try:
        status = payload.pop("status")
        new_id = db.set_order_status(conn, sku, status, **payload)
        return {"id": new_id}
    finally:
        conn.close()



# ---------- T9: trip planner endpoints ----------

@app.get("/api/trips")
def list_trips_endpoint(status: Optional[str] = None):
    conn = db.connect()
    try:
        rows = db.list_trips(conn, status=status)
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.post("/api/trips")
def create_trip_endpoint(payload: dict):
    conn = db.connect()
    try:
        trip_id = db.create_trip(
            conn,
            destination=payload['destination'],
            start_date=payload['start_date'],
            end_date=payload['end_date'],
            flight_out_cny=payload.get('flight_out_cny', 0),
            flight_back_cny=payload.get('flight_back_cny', 0),
            hotel_total_cny=payload.get('hotel_total_cny', 0),
            notes=payload.get('notes', ''),
        )
        return {'id': trip_id}
    finally:
        conn.close()


@app.get("/api/trips/{trip_id}")
def get_trip_endpoint(trip_id: int):
    conn = db.connect()
    try:
        trip = db.get_trip(conn, trip_id)
        if not trip:
            raise HTTPException(404, 'trip not found')
        items = db.list_trip_items(conn, trip_id)
        return {'trip': dict(trip), 'items': [dict(r) for r in items]}
    finally:
        conn.close()


@app.patch("/api/trips/{trip_id}")
def update_trip_endpoint(trip_id: int, payload: dict):
    conn = db.connect()
    try:
        return {'rowcount': db.update_trip(conn, trip_id, **payload)}
    finally:
        conn.close()


@app.delete("/api/trips/{trip_id}")
def delete_trip_endpoint(trip_id: int):
    conn = db.connect()
    try:
        return {'rowcount': db.delete_trip(conn, trip_id)}
    finally:
        conn.close()


@app.post("/api/trips/{trip_id}/items")
def add_trip_item_endpoint(trip_id: int, payload: dict):
    conn = db.connect()
    try:
        item_id = db.add_trip_item(
            conn, trip_id,
            day_index=payload.get('day_index', 1),
            channel=payload['channel'],
            sku_slug=payload['sku_slug'],
            sku_label=payload['sku_label'],
            est_cny=payload['est_cny'],
            location_label=payload.get('location_label'),
        )
        return {'id': item_id}
    finally:
        conn.close()


@app.delete("/api/trip-items/{item_id}")
def delete_trip_item_endpoint(item_id: int):
    conn = db.connect()
    try:
        return {'rowcount': db.delete_trip_item(conn, item_id)}
    finally:
        conn.close()


# ---------- SKU 反馈标注 (面板简化: 用户 re 商机机制) ----------

class FeedbackIn(BaseModel):
    sku: str
    status: str            # 'ok' 能卖 | 'bad' 不OK(从推荐排除)
    reason: str = ""


@app.get("/api/feedback", response_model=list[dict])
def feedback_list():
    conn = db.connect()
    try:
        return [dict(r) for r in db.list_sku_feedback(conn)]
    finally:
        conn.close()


@app.post("/api/feedback", response_model=dict)
def feedback_set(req: FeedbackIn):
    if req.status not in ("ok", "bad"):
        raise HTTPException(status_code=422, detail="status must be 'ok' or 'bad'")
    conn = db.connect()
    try:
        db.upsert_sku_feedback(conn, req.sku, req.status, req.reason.strip()[:200])
        row = conn.execute(
            "SELECT * FROM sku_feedback WHERE sku = ?", (req.sku,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


@app.delete("/api/feedback/{sku}", response_model=dict)
def feedback_delete(sku: str):
    conn = db.connect()
    try:
        db.delete_sku_feedback(conn, sku)
        return {"deleted": sku}
    finally:
        conn.close()


# ---------- SKU 实测闭环 (候选池 → 实测 → 能卖/淘汰) ----------

class CandidateIn(BaseModel):
    sku: str | None = None
    name: str
    category: str = ""
    buy_price_usd: float = 0.0
    sell_price_usd: float = 0.0
    source_market: str = ""
    target_market: str = ""
    evidence: list[dict] = []
    reason: str = ""


class CandidateStatusIn(BaseModel):
    status: str            # testing | ok | bad | candidate
    reason: str = ""


def _candidate_out(row) -> dict:
    d = dict(row)
    try:
        d["evidence"] = json.loads(d.get("evidence") or "[]")
    except (ValueError, TypeError):
        d["evidence"] = []
    return d


@app.get("/api/candidates", response_model=list[dict])
def candidates_list(status: Optional[str] = None):
    conn = db.connect()
    try:
        return [_candidate_out(r) for r in db.list_sku_candidates(conn, status)]
    finally:
        conn.close()


@app.post("/api/candidates", response_model=dict)
def candidates_create(req: CandidateIn):
    conn = db.connect()
    try:
        cid = db.create_sku_candidate(conn, {
            "sku": req.sku, "name": req.name, "category": req.category,
            "buy_price_usd": req.buy_price_usd, "sell_price_usd": req.sell_price_usd,
            "source_market": req.source_market, "target_market": req.target_market,
            "evidence": req.evidence, "reason": req.reason,
        })
        row = conn.execute(
            "SELECT * FROM sku_candidates WHERE id = ?", (cid,)
        ).fetchone()
        return _candidate_out(row)
    finally:
        conn.close()


@app.post("/api/candidates/{cid}/status", response_model=dict)
def candidates_status(cid: int, req: CandidateStatusIn):
    if req.status not in ("candidate", "testing", "ok", "bad"):
        raise HTTPException(
            status_code=422,
            detail="status must be one of candidate/testing/ok/bad",
        )
    conn = db.connect()
    try:
        if req.status == "ok":
            row = db.promote_candidate(conn, cid, req.reason.strip()[:200])
            if row is None:
                raise HTTPException(status_code=404, detail=f"candidate {cid} not found")
        else:
            row = conn.execute(
                "SELECT * FROM sku_candidates WHERE id = ?", (cid,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"candidate {cid} not found")
            db.set_candidate_status(conn, cid, req.status, req.reason.strip()[:200])
            row = conn.execute(
                "SELECT * FROM sku_candidates WHERE id = ?", (cid,)
            ).fetchone()
        return _candidate_out(row)
    finally:
        conn.close()


# ---------- Round 24 static SPA mounted last so /api/* wins ----------

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
else:
    @app.get("/")
    def _root_fallback():
        return JSONResponse({
            "ok": True,
            "msg": "web/ not built yet; API is live at /api/*",
            "endpoints": [
                "/api/health", "/api/opportunities", "/api/routes",
                "/api/decide (POST)", "/api/report/{sku}.{md|html|pdf}",
                "/api/prices", "/api/prices/fetch", "/api/prices/diff",
                "/api/alerts", "/api/alerts/evaluate",
                "/api/quota", "/api/quota/entries",
                "/api/returns", "/api/margin",
                "/api/tax",
                "/api/inventory", "/api/inventory/summary",
                "/api/orders",
                "/api/trips", "/api/trip-items",
            ],
        })


# ---------- T2: live search endpoint ----------
@app.get("/api/live-search")
def live_search_endpoint(q: str, sources: str = "buyee,ebay_sold,amazon_jp"):
    """Multi-source live price search. Returns {ok, items, count} per source.
    On anti-bot block returns {ok: false, blocked: true, reason, hint, items: []}.
    """
    try:
        from .live_search import search_buyee, search_ebay_sold, search_amazon_jp, search_all
        src_list = [s.strip() for s in sources.split(",")]
        if len(src_list) == 3 and {"buyee", "ebay_sold", "amazon_jp"} == set(src_list):
            return search_all(q, limit=5)
        results = {"query": q, "fetched_at": _dt.datetime.now().isoformat(timespec="seconds")}
        if "buyee" in src_list:
            results["buyee"] = search_buyee(q, limit=5)
        if "ebay_sold" in src_list:
            results["ebay_sold"] = search_ebay_sold(q, limit=5)
        if "amazon_jp" in src_list:
            results["amazon_jp"] = search_amazon_jp(q, limit=5)
        return results
    except Exception as e:
        return {"error": str(e), "query": q}


@app.post("/api/live-extract")
def live_extract_endpoint(payload: dict):
    """Extract prices from pasted HTML (when search engine blocked our bot).
    Body: {html: "<paste>", source: "auto|buyee|ebay|amazon_jp"}
    """
    try:
        from .live_search import extract_url
        html = payload.get("html", "")
        source = payload.get("source", "auto")
        if not html or len(html) < 100:
            return {"ok": False, "reason": "html too short — paste full page source"}
        return extract_url(html, source_hint=source)
    except Exception as e:
        return {"ok": False, "error": str(e)}
