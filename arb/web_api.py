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
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, freshness
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
    return dict(r) | {"verified": bool(r["verified"])}


def _row_to_route(r) -> dict:
    return dict(r)


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


@app.get("/api/routes", response_model=list[RouteSummary])
def list_routes():
    conn = db.connect()
    try:
        out = []
        for r in db.list_routes(conn):
            legs = [dict(lg) for lg in db.list_route_legs(conn, r["id"])]
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
            ],
        })