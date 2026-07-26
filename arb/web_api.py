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

from . import db
from .report import (
    decide_for,
    render_html,
    render_markdown,
    render_pdf,
    report_filename,
)


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
        return [_row_to_opp(r) for r in db.list_opportunities(conn)]
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
            opp, route, decision, legs = decide_for(conn, req.sku, req.num_units, req.route)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        db.record_decision(conn, opp["id"], route["id"], req.num_units, decision)
        return {
            "opp": _row_to_opp(opp),
            "route": _row_to_route(route),
            "legs": [dict(lg) for lg in legs],
            "num_units": req.num_units,
            "decision": decision.as_dict(),
        }
    finally:
        conn.close()


def _serve_report(sku: str, fmt: str, num_units: int = 5, route: str = "PVG-NRT-LAX-2N"):
    conn = db.connect()
    try:
        try:
            opp, rt, decision, legs = decide_for(conn, sku, num_units, route)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if fmt == "md":
            return Response(
                content=render_markdown(opp, rt, legs, num_units, decision),
                media_type="text/markdown; charset=utf-8",
                headers={
                    "Content-Disposition": _content_disposition(
                        report_filename(sku, rt["dest_city"], "md")
                    ),
                },
            )
        if fmt == "html":
            return Response(
                content=render_html(opp, rt, legs, num_units, decision),
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": _content_disposition(
                        report_filename(sku, rt["dest_city"], "html")
                    ),
                },
            )
        if fmt == "pdf":
            html_str = render_html(opp, rt, legs, num_units, decision)
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