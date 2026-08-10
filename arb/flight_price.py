"""Amadeus Self-Service Flight Offers Search client (Round 14).

Half-auto mode: this module fetches live flight prices from the Amadeus
test environment so the user can inspect them and decide whether to
update ``routes.flight_cost_usd`` in the local DB. The results are
**not persisted** — they live in a small in-memory cache keyed by
``(origin, dest, date, adults, cabin, currency)``.

Why stdlib only: this project ships without a packaging manifest, has
no third-party HTTP dep (``scraper.py`` uses ``urllib.request``), and
the Amadeus test endpoints return small JSON (<100 KB). Mirroring the
``scraper.py`` idiom keeps the test surface tiny (stub the injected
``opener`` callable instead of monkeypatching modules) and avoids
introducing a manifest.

Env vars (mirroring ``ARB_DB_PATH`` from ``arb.db``):
  AMADEUS_CLIENT_ID      — required at call time
  AMADEUS_CLIENT_SECRET  — required at call time
  AMADEUS_HOSTNAME       — default ``test.api.amadeus.com``
                           (set to ``api.amadeus.com`` for production)
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------- knobs ----------

DEFAULT_HOSTNAME: str = "test.api.amadeus.com"
DEFAULT_TIMEOUT: float = 8.0
DEFAULT_MAX_BYTES: int = 1_500_000
DEFAULT_MIN_GAP_SEC: float = 1.0
DEFAULT_CACHE_TTL: float = 600.0
DEFAULT_CACHE_CAP: int = 64
USER_AGENT: str = "jp-us-arb-route/0.3 (+local-only personal use)"

VALID_CABINS: tuple[str, ...] = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST")


# ---------- public dataclasses ----------

@dataclass(frozen=True)
class FlightOffer:
    """One flight offer returned by Amadeus, normalized.

    `raw` is the full Amadeus offer dict so callers can inspect
    itineraries, travelerPricings, etc. for things we don't surface
    here. `segments` is a list of dicts with at minimum
    ``{departure_iata, arrival_iata, carrier, flight_number, duration}``.
    """
    offer_id: str
    price_total: float
    currency: str
    validating_carrier: Optional[str]
    num_stops: int
    segments: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FlightSearchOutcome:
    """Result of a flight search call. Never raises — errors live in
    ``ok=False`` + ``blocked_reason`` so the CLI / API can render them
    uniformly (mirrors ``arb.scraper.ScrapedPage``)."""
    origin: str
    dest: str
    date: str
    adults: int
    cabin: str
    currency: str
    ok: bool
    offers: list[FlightOffer]
    cached: bool
    elapsed_ms: int
    blocked_reason: Optional[str]
    message: str


# ---------- module-level rate limiter (mirrors scraper.py) ----------

_last_call_ts: float = 0.0


def _wait_for_slot(min_gap_sec: float) -> None:
    """Block until at least ``min_gap_sec`` seconds have passed since
    the last network call from this module. No-op when 0."""
    global _last_call_ts
    if min_gap_sec <= 0:
        _last_call_ts = time.monotonic()
        return
    now = time.monotonic()
    gap = now - _last_call_ts
    if gap < min_gap_sec:
        time.sleep(min_gap_sec - gap)
    _last_call_ts = time.monotonic()


def _reset_rate_limiter_for_tests() -> None:
    global _last_call_ts
    _last_call_ts = 0.0


# ---------- in-memory cache (LRU + TTL) ----------

_cache: "OrderedDict[tuple, tuple[float, FlightSearchOutcome]]" = OrderedDict()


def _cache_get(key: tuple) -> Optional[FlightSearchOutcome]:
    """Return cached outcome if present and not expired; else None.
    On hit, mark as recently used (move to end of LRU)."""
    now = time.monotonic()
    entry = _cache.get(key)
    if entry is None:
        return None
    expires_at, outcome = entry
    if expires_at <= now:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return outcome


def _cache_put(key: tuple, outcome: FlightSearchOutcome, ttl: float, cap: int) -> None:
    _cache[key] = (time.monotonic() + ttl, outcome)
    _cache.move_to_end(key)
    while len(_cache) > cap:
        _cache.popitem(last=False)  # evict LRU


def _cache_clear() -> None:
    _cache.clear()


# ---------- HTTP helper (stdlib) ----------

def _post_json(
    url: str,
    *,
    headers: dict,
    body: dict,
    timeout: float,
    opener: Callable,
) -> dict:
    """POST JSON to ``url`` using the injected ``opener`` (default
    ``urllib.request.urlopen``). Returns a structured dict — on error
    the dict has ``ok=False`` + ``blocked_reason`` instead of raising,
    matching the ``scraper.fetch_url`` pattern."""
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    started = time.monotonic()
    try:
        resp = opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "blocked_reason": f"http {e.code}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "status": 0,
            "blocked_reason": f"url error: {e.reason}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as e:  # defensive: never raise out
        return {
            "ok": False,
            "status": 0,
            "blocked_reason": f"unexpected: {type(e).__name__}: {e}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    try:
        raw_bytes = resp.read(DEFAULT_MAX_BYTES + 1)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        try:
            status = resp.status
        except AttributeError:
            status = 200
        try:
            resp.close()
        except Exception:
            pass
        if len(raw_bytes) > DEFAULT_MAX_BYTES:
            return {
                "ok": False,
                "status": status,
                "blocked_reason": f"response exceeded {DEFAULT_MAX_BYTES} bytes",
                "elapsed_ms": elapsed_ms,
            }
        try:
            return {
                "ok": True,
                "status": status,
                "body": json.loads(raw_bytes.decode("utf-8")),
                "elapsed_ms": elapsed_ms,
            }
        except (ValueError, UnicodeDecodeError) as e:
            return {
                "ok": False,
                "status": status,
                "blocked_reason": f"decode/json error: {e}",
                "elapsed_ms": elapsed_ms,
            }
    except Exception as e:  # defensive
        return {
            "ok": False,
            "status": 0,
            "blocked_reason": f"read error: {type(e).__name__}: {e}",
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }


# ---------- token cache ----------

_token_cache: "OrderedDict[tuple, tuple[str, float]]" = OrderedDict()
_TOKEN_REFRESH_SAFETY_SEC: float = 60.0


def _reset_token_cache_for_tests() -> None:
    _token_cache.clear()


def _get_access_token(
    hostname: str,
    client_id: str,
    client_secret: str,
    *,
    timeout: float,
    opener: Callable,
    min_gap_sec: float,
) -> tuple[Optional[str], Optional[str]]:
    """Returns (token, blocked_reason). When the second element is set,
    the first is None and the caller should surface the error."""
    key = (hostname, client_id)
    cached = _token_cache.get(key)
    if cached is not None:
        token, expires_at = cached
        if expires_at > time.monotonic() + _TOKEN_REFRESH_SAFETY_SEC:
            _token_cache.move_to_end(key)
            return token, None
        # Expired or about to expire — fall through and refresh.
    url = f"https://{hostname}/v1/security/oauth2/token"
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    _wait_for_slot(min_gap_sec)
    started = time.monotonic()
    try:
        resp = opener(req, timeout=timeout)
        body_bytes = resp.read(DEFAULT_MAX_BYTES + 1)
        status = getattr(resp, "status", 200)
        try:
            resp.close()
        except Exception:
            pass
    except urllib.error.HTTPError as e:
        return None, f"http {e.code} on token"
    except urllib.error.URLError as e:
        return None, f"url error on token: {e.reason}"
    except Exception as e:  # defensive
        return None, f"token fetch failed: {type(e).__name__}: {e}"
    if len(body_bytes) > DEFAULT_MAX_BYTES:
        return None, f"token response exceeded {DEFAULT_MAX_BYTES} bytes"
    try:
        body = json.loads(body_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return None, f"token decode error: {e}"
    if status >= 400 or "access_token" not in body:
        # Amadeus error shape: {"error": "...", "error_description": "..."}
        err = body.get("error") or "missing access_token"
        desc = body.get("error_description") or ""
        return None, f"http {status} on token: {err} {desc}".strip()
    token = body["access_token"]
    expires_in = int(body.get("expires_in") or 0)
    if expires_in <= 0:
        expires_in = 1799  # Amadeus default ~30 min
    expires_at = time.monotonic() + expires_in
    _token_cache[key] = (token, expires_at)
    _token_cache.move_to_end(key)
    return token, None


# ---------- offer parsing ----------

def _parse_offers(body: dict) -> list[FlightOffer]:
    """Normalize the Amadeus ``flight-offers`` response into ``FlightOffer``."""
    out: list[FlightOffer] = []
    for raw in body.get("data", []) or []:
        try:
            price_total = float(raw.get("price", {}).get("total", 0.0))
        except (TypeError, ValueError):
            price_total = 0.0
        currency = raw.get("price", {}).get("currency", "USD")
        validating = raw.get("validatingAirlineCodes", [None])
        validating_carrier = validating[0] if validating else None
        # Count stops across all itineraries. An itinerary with N
        # segments has N-1 stops.
        stops = 0
        segments: list[dict] = []
        for itinerary in raw.get("itineraries", []) or []:
            segs = itinerary.get("segments", []) or []
            stops += max(0, len(segs) - 1)
            for seg in segs:
                segments.append({
                    "departure_iata": (seg.get("departure") or {}).get("iataCode"),
                    "arrival_iata": (seg.get("arrival") or {}).get("iataCode"),
                    "carrier": seg.get("carrierCode"),
                    "flight_number": seg.get("number"),
                    "duration": seg.get("duration"),
                })
        offer_id = raw.get("id", "")
        out.append(FlightOffer(
            offer_id=offer_id,
            price_total=price_total,
            currency=currency,
            validating_carrier=validating_carrier,
            num_stops=stops,
            segments=segments,
            raw=raw,
        ))
    return out


# ---------- main entry ----------

def search_flights(
    origin: str,
    dest: str,
    date: str,
    *,
    adults: int = 1,
    cabin: str = "ECONOMY",
    currency: str = "USD",
    hostname: str = DEFAULT_HOSTNAME,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    use_cache: bool = True,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    cache_cap: int = DEFAULT_CACHE_CAP,
    opener: Callable = urllib.request.urlopen,
) -> FlightSearchOutcome:
    """Search Amadeus Self-Service Flight Offers Search.

    Credentials: read from ``AMADEUS_CLIENT_ID`` / ``AMADEUS_CLIENT_SECRET``
    when not passed explicitly. Returns a ``FlightSearchOutcome`` — never
    raises; on failure the outcome has ``ok=False`` + ``blocked_reason``.
    """
    origin = origin.upper().strip()
    dest = dest.upper().strip()
    cid = client_id or os.environ.get("AMADEUS_CLIENT_ID")
    cs = client_secret or os.environ.get("AMADEUS_CLIENT_SECRET")
    if not cid or not cs:
        return FlightSearchOutcome(
            origin=origin, dest=dest, date=date, adults=adults, cabin=cabin,
            currency=currency, ok=False, offers=[], cached=False, elapsed_ms=0,
            blocked_reason="missing AMADEUS_CLIENT_ID/AMADEUS_CLIENT_SECRET",
            message="Set AMADEUS_CLIENT_ID and AMADEUS_CLIENT_SECRET env vars (or pass client_id/client_secret).",
        )

    cache_key = (origin, dest, date, adults, cabin, currency, hostname)
    if use_cache:
        hit = _cache_get(cache_key)
        if hit is not None:
            return FlightSearchOutcome(
                origin=hit.origin, dest=hit.dest, date=hit.date,
                adults=hit.adults, cabin=hit.cabin, currency=hit.currency,
                ok=hit.ok, offers=hit.offers, cached=True, elapsed_ms=0,
                blocked_reason=hit.blocked_reason, message=hit.message + " (cached)",
            )

    started = time.monotonic()
    token, blocked = _get_access_token(
        hostname, cid, cs, timeout=timeout, opener=opener, min_gap_sec=min_gap_sec,
    )
    if blocked is not None:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        outcome = FlightSearchOutcome(
            origin=origin, dest=dest, date=date, adults=adults, cabin=cabin,
            currency=currency, ok=False, offers=[], cached=False,
            elapsed_ms=elapsed_ms, blocked_reason=blocked,
            message=f"token acquisition failed: {blocked}",
        )
        if use_cache:
            _cache_put(cache_key, outcome, cache_ttl, cache_cap)
        return outcome

    # Search endpoint — POST with JSON body
    url = f"https://{hostname}/v2/shopping/flight-offers"
    body = {
        "currencyCode": currency,
        "originDestinations": [
            {
                "id": "1",
                "originLocationCode": origin,
                "destinationLocationCode": dest,
                "departureDateTimeRange": {"date": date},
            }
        ],
        "travelers": [{"id": str(i + 1), "travelerType": "ADULT"} for i in range(adults)],
        "sources": ["GDS"],
        "searchCriteria": {
            "maxFlightOffers": 20,
            "flightFilters": {"cabinRestrictions": [{"cabin": cabin, "originDestinationIds": ["1"]}]},
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    _wait_for_slot(min_gap_sec)
    resp = _post_json(url, headers=headers, body=body, timeout=timeout, opener=opener)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not resp.get("ok"):
        outcome = FlightSearchOutcome(
            origin=origin, dest=dest, date=date, adults=adults, cabin=cabin,
            currency=currency, ok=False, offers=[], cached=False,
            elapsed_ms=elapsed_ms, blocked_reason=resp.get("blocked_reason"),
            message=f"search failed: {resp.get('blocked_reason')}",
        )
        if use_cache:
            _cache_put(cache_key, outcome, cache_ttl, cache_cap)
        return outcome

    body_json = resp["body"]
    offers = _parse_offers(body_json)
    if not offers:
        outcome = FlightSearchOutcome(
            origin=origin, dest=dest, date=date, adults=adults, cabin=cabin,
            currency=currency, ok=True, offers=[], cached=False, elapsed_ms=elapsed_ms,
            blocked_reason=None, message="no offers returned",
        )
    else:
        outcome = FlightSearchOutcome(
            origin=origin, dest=dest, date=date, adults=adults, cabin=cabin,
            currency=currency, ok=True, offers=offers, cached=False,
            elapsed_ms=elapsed_ms, blocked_reason=None,
            message=f"got {len(offers)} offer(s) in {elapsed_ms}ms",
        )
    if use_cache:
        _cache_put(cache_key, outcome, cache_ttl, cache_cap)
    return outcome


# ---------- JSON shim (mirrors arb.refresh.outcome_as_dict) ----------

def outcome_as_dict(o: FlightSearchOutcome) -> dict:
    return {
        "origin": o.origin,
        "dest": o.dest,
        "date": o.date,
        "adults": o.adults,
        "cabin": o.cabin,
        "currency": o.currency,
        "ok": o.ok,
        "cached": o.cached,
        "elapsed_ms": o.elapsed_ms,
        "blocked_reason": o.blocked_reason,
        "message": o.message,
        "offers": [
            {
                "offer_id": off.offer_id,
                "price_total": off.price_total,
                "currency": off.currency,
                "validating_carrier": off.validating_carrier,
                "num_stops": off.num_stops,
                "segments": off.segments,
            }
            for off in o.offers
        ],
    }


__all__ = [
    "DEFAULT_HOSTNAME",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MIN_GAP_SEC",
    "DEFAULT_CACHE_TTL",
    "DEFAULT_CACHE_CAP",
    "USER_AGENT",
    "VALID_CABINS",
    "FlightOffer",
    "FlightSearchOutcome",
    "search_flights",
    "outcome_as_dict",
    "_reset_rate_limiter_for_tests",
    "_reset_token_cache_for_tests",
    "_cache_clear",
]
