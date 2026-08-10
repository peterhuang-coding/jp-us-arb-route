"""Unit tests for the Amadeus flight-price client (Round 14).

Mirrors the testing idiom from ``tests/test_scraper.py``: a tiny
``_FakeResp`` stub, a per-test reset of the rate limiter + cache, and
injected opener callables instead of monkeypatching ``urllib``.
"""
from __future__ import annotations

import json

import pytest

from arb import flight_price as fp


# ---------- helpers (copied from test_scraper.py:16-33) ----------

class _FakeResp:
    """Mimics the urllib response object the Amadeus client reads."""

    def __init__(self, body: bytes, status: int = 200,
                 ctype: str = "application/json; charset=utf-8"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": ctype}

    def read(self, n: int = -1) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class _Recorder:
    """Records every (url, headers, body) the client passes in.

    Decodes the request body as JSON when possible, otherwise as
    form-encoded data, otherwise leaves the raw string. This mirrors
    what the Amadeus client actually sends (token call is form, search
    call is JSON).
    """

    def __init__(self, scripted: list[_FakeResp]):
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def __call__(self, req, timeout=None):
        body = req.data.decode("utf-8") if req.data else ""
        parsed: object
        if not body:
            parsed = None
        else:
            try:
                parsed = json.loads(body)
            except (ValueError, TypeError):
                try:
                    from urllib.parse import parse_qs
                    parsed = {k: v[0] for k, v in parse_qs(body).items()}
                except Exception:
                    parsed = body
        self.calls.append({
            "url": req.full_url,
            "method": req.get_method(),
            "headers": dict(req.headers),
            "body": parsed,
            "timeout": timeout,
        })
        return self._scripted.pop(0)


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _reset():
    fp._reset_rate_limiter_for_tests()
    fp._reset_token_cache_for_tests()
    fp._cache_clear()
    yield
    fp._reset_rate_limiter_for_tests()
    fp._reset_token_cache_for_tests()
    fp._cache_clear()


def _token_body(expires_in: int = 1800) -> bytes:
    return json.dumps({
        "access_token": "TOK123",
        "token_type": "Bearer",
        "expires_in": expires_in,
    }).encode()


def _search_body(offers: list[dict] | None = None) -> bytes:
    """Build a minimal Amadeus ``flight-offers`` response body."""
    if offers is None:
        offers = [{
            "id": "1",
            "price": {"total": "599.99", "currency": "USD"},
            "validatingAirlineCodes": ["NH"],
            "itineraries": [{
                "segments": [
                    {
                        "departure": {"iataCode": "PVG"},
                        "arrival": {"iataCode": "NRT"},
                        "carrierCode": "NH",
                        "number": "920",
                        "duration": "PT3H00M",
                    },
                    {
                        "departure": {"iataCode": "NRT"},
                        "arrival": {"iataCode": "LAX"},
                        "carrierCode": "NH",
                        "number": "105",
                        "duration": "PT10H00M",
                    },
                ],
            }],
        }]
    return json.dumps({"data": offers, "dictionaries": {}}).encode()


# ---------- cases ----------

def test_happy_path_one_offer():
    recorder = _Recorder([_FakeResp(_token_body()), _FakeResp(_search_body())])
    out = fp.search_flights("PVG", "LAX", "2026-09-15",
                            client_id="CID", client_secret="CS", opener=recorder)
    assert out.ok is True
    assert len(out.offers) == 1
    offer = out.offers[0]
    assert offer.price_total == pytest.approx(599.99)
    assert offer.currency == "USD"
    assert offer.validating_carrier == "NH"
    assert offer.num_stops == 1   # 2 segments → 1 stop
    assert len(offer.segments) == 2
    assert offer.segments[0]["departure_iata"] == "PVG"
    assert offer.segments[0]["arrival_iata"] == "NRT"


def test_token_then_search_ordering():
    recorder = _Recorder([_FakeResp(_token_body()), _FakeResp(_search_body())])
    fp.search_flights("PVG", "LAX", "2026-09-15",
                      client_id="CID", client_secret="CS", opener=recorder)
    assert len(recorder.calls) == 2
    token_call, search_call = recorder.calls
    assert token_call["url"].endswith("/v1/security/oauth2/token")
    assert token_call["method"] == "POST"
    # Token call is form-encoded; recorder decodes into a dict.
    assert token_call["body"]["grant_type"] == "client_credentials"
    assert token_call["body"]["client_id"] == "CID"
    assert token_call["body"]["client_secret"] == "CS"
    assert search_call["url"].endswith("/v2/shopping/flight-offers")
    assert search_call["method"] == "POST"
    assert search_call["headers"]["Authorization"] == "Bearer TOK123"
    assert search_call["body"]["originDestinations"][0]["originLocationCode"] == "PVG"
    assert search_call["body"]["originDestinations"][0]["destinationLocationCode"] == "LAX"
    assert search_call["body"]["travelers"][0]["travelerType"] == "ADULT"


def test_token_reused_across_different_dates():
    """Two calls with DIFFERENT dates → result cache misses both times, but
    the token (which is keyed by hostname+client_id, not by query) is
    fetched only once."""
    recorder = _Recorder([
        _FakeResp(_token_body()), _FakeResp(_search_body()),
        _FakeResp(_search_body()),
    ])
    args = dict(client_id="CID", client_secret="CS", opener=recorder)
    fp.search_flights("PVG", "LAX", "2026-09-15", **args)
    fp.search_flights("PVG", "LAX", "2026-09-16", **args)
    assert len(recorder.calls) == 3  # 1 token + 2 search
    assert recorder.calls[1]["url"].endswith("/v2/shopping/flight-offers")
    assert recorder.calls[2]["url"].endswith("/v2/shopping/flight-offers")
    # No second token call.
    assert sum(c["url"].endswith("/v1/security/oauth2/token") for c in recorder.calls) == 1


def test_token_refreshed_when_near_expiry():
    """Two calls with different dates; first token has 30s lifetime (below
    the 60s safety window) so the second call should refresh."""
    recorder = _Recorder([
        _FakeResp(_token_body(expires_in=30)),  # near-expiry
        _FakeResp(_search_body()),
        _FakeResp(_token_body(expires_in=1800)),  # refreshed
        _FakeResp(_search_body()),
    ])
    args = dict(client_id="CID", client_secret="CS", opener=recorder)
    fp.search_flights("PVG", "LAX", "2026-09-15", **args)
    fp.search_flights("PVG", "LAX", "2026-09-16", **args)
    # 2 token + 2 search = 4 calls; the 2nd token call is the refresh.
    assert len(recorder.calls) == 4
    token_urls = [c["url"] for c in recorder.calls if c["url"].endswith("/v1/security/oauth2/token")]
    assert len(token_urls) == 2


def test_missing_credentials_returns_error(monkeypatch):
    monkeypatch.delenv("AMADEUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMADEUS_CLIENT_SECRET", raising=False)
    out = fp.search_flights("PVG", "LAX", "2026-09-15", opener=lambda *a, **k: None)
    assert out.ok is False
    assert "missing AMADEUS" in (out.blocked_reason or "")


def test_401_on_token_short_circuits():
    # Return a 401 on the token call — no search call should follow.
    import urllib.error
    def fake_opener(req, timeout=None):
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", {}, None,
        )
    out = fp.search_flights("PVG", "LAX", "2026-09-15",
                            client_id="CID", client_secret="CS", opener=fake_opener)
    assert out.ok is False
    assert "http 401" in (out.blocked_reason or "")
    assert out.offers == []


def test_429_on_search_returns_blocked():
    # Token succeeds; search returns 429.
    import urllib.error
    responses = [
        _FakeResp(_token_body()),
    ]
    def fake_opener(req, timeout=None):
        if req.full_url.endswith("/v1/security/oauth2/token"):
            return responses[0]
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
    out = fp.search_flights("PVG", "LAX", "2026-09-15",
                            client_id="CID", client_secret="CS", opener=fake_opener)
    assert out.ok is False
    assert "http 429" in (out.blocked_reason or "")


def test_empty_offer_list_is_ok_with_message():
    recorder = _Recorder([_FakeResp(_token_body()), _FakeResp(_search_body([]))])
    out = fp.search_flights("PVG", "LAX", "2026-09-15",
                            client_id="CID", client_secret="CS", opener=recorder)
    assert out.ok is True
    assert out.offers == []
    assert "no offers" in out.message.lower()


def test_cache_hit_within_ttl():
    # First call: token + search. Second call within TTL: no HTTP at all.
    recorder = _Recorder([_FakeResp(_token_body()), _FakeResp(_search_body())])
    args = dict(client_id="CID", client_secret="CS", opener=recorder)
    fp.search_flights("PVG", "LAX", "2026-09-15", **args)
    fp.search_flights("PVG", "LAX", "2026-09-15", **args)
    assert len(recorder.calls) == 2  # second call served from cache


def test_no_cache_bypasses():
    """With use_cache=False, identical params still produce a fresh search."""
    recorder = _Recorder([
        _FakeResp(_token_body()), _FakeResp(_search_body()),
        _FakeResp(_search_body()),
    ])
    args = dict(client_id="CID", client_secret="CS", opener=recorder)
    fp.search_flights("PVG", "LAX", "2026-09-15", use_cache=False, **args)
    fp.search_flights("PVG", "LAX", "2026-09-15", use_cache=False, **args)
    # 1 token (cached) + 2 search = 3 calls. The result cache is what
    # gets bypassed; the token cache still applies (same client_id).
    assert len(recorder.calls) == 3
    token_count = sum(c["url"].endswith("/v1/security/oauth2/token") for c in recorder.calls)
    assert token_count == 1


def test_outcome_as_dict_shape():
    recorder = _Recorder([_FakeResp(_token_body()), _FakeResp(_search_body())])
    out = fp.search_flights("PVG", "LAX", "2026-09-15",
                            client_id="CID", client_secret="CS", opener=recorder)
    d = fp.outcome_as_dict(out)
    assert d["origin"] == "PVG"
    assert d["dest"] == "LAX"
    assert d["date"] == "2026-09-15"
    assert d["ok"] is True
    assert isinstance(d["offers"], list)
    assert d["offers"][0]["price_total"] == pytest.approx(599.99)
    assert d["offers"][0]["validating_carrier"] == "NH"
    # Re-asserting for raw round-trip — as_dict must be JSON-serializable.
    json.dumps(d)
