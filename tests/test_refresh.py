"""Tests for the refresh coordinator — pure-ish, uses in-memory DB + stub opener."""
from __future__ import annotations

import datetime as _dt
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from arb import db, freshness, refresh, scraper


# ---------- helpers ----------

class _FakeResp:
    def __init__(self, body: bytes, status: int = 200,
                 ctype: str = "text/html; charset=utf-8",
                 final_url: str = "https://example.com/x"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": ctype}
        self._final = final_url

    def read(self, n: int = -1) -> bytes:
        if n < 0 or n >= len(self._body):
            return self._body
        return self._body[:n]

    def geturl(self) -> str:
        return self._final

    def close(self) -> None:
        pass


@pytest.fixture
def conn():
    scraper._reset_rate_limiter_for_tests()
    c = db.connect_memory()
    yield c
    c.close()
    scraper._reset_rate_limiter_for_tests()


def _seed_opp(conn, **overrides):
    opp = dict(
        sku="RFR-001", name="Refresh Test", category="misc",
        source_market="JP", target_market="US",
        purchase_price_usd=85.0, tariff_rate=0.0,
        sell_price_usd=145.0, shipping_per_unit_usd=4.0,
        platform_fee_rate=0.13, minutes_per_unit=20.0,
        success_rate=0.7,
        purchase_source_url="https://example.com/jp",
        sell_source_url="https://example.com/us",
        notes="", data_freshness_ts="2026-05-01", verified=0,
    )
    opp.update(overrides)
    db.upsert_opportunity(conn, opp)
    return opp


# ---------- happy path ----------

def test_refresh_bumps_ts_when_both_probes_succeed(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>USD 145.00 in stock</html>")
    out = refresh.refresh_opportunity(
        conn, "RFR-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.updated is True
    assert out.previous_freshness_ts == "2026-05-01"
    assert out.new_freshness_ts == "2026-07-26"
    assert out.verdict_before["status"] == "stale"
    assert out.verdict_after["status"] == "fresh"
    assert out.purchase.ok and out.sell.ok
    assert any(h["amount"] == 145.0 for h in out.purchase.price_hints)
    # DB row updated
    row = db.get_opportunity(conn, "RFR-001")
    assert row["data_freshness_ts"] == "2026-07-26"


def test_refresh_does_not_overwrite_when_probe_fails(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        raise HTTPError("https://example.com/jp", 500, "boom", {}, None)
    out = refresh.refresh_opportunity(
        conn, "RFR-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.updated is False
    assert out.new_freshness_ts is None
    assert out.message
    row = db.get_opportunity(conn, "RFR-001")
    # original 2026-05-01 must be preserved
    assert row["data_freshness_ts"] == "2026-05-01"


def test_refresh_only_purchase_url_failing_blocks_update(conn):
    _seed_opp(conn, sell_source_url=None)  # no sell URL
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>USD 145</html>")
    out = refresh.refresh_opportunity(
        conn, "RFR-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    # No sell URL → no fail possible → update proceeds using purchase only.
    assert out.updated is True
    assert out.sell is None


def test_refresh_returns_price_hints_from_both_sides(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        if isinstance(req_or_url, str):
            url = req_or_url
        else:
            url = req_or_url.full_url
        if "/jp" in url:
            return _FakeResp(b"<html>JPY 12800 </html>")
        return _FakeResp(b"<html>USD 145.00</html>")
    out = refresh.refresh_opportunity(
        conn, "RFR-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.updated
    assert any(h["currency"] == "JPY" for h in out.purchase.price_hints)
    assert any(h["currency"] == "USD" for h in out.sell.price_hints)


# ---------- missing SKU ----------

def test_refresh_unknown_sku_returns_outcome_without_db_change(conn):
    out = refresh.refresh_opportunity(
        conn, "NOPE", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": lambda *a, **kw: None,
                        "robots_lookup": lambda *a, **kw: True},
    )
    assert out.updated is False
    assert out.message.startswith("opportunity not found")
    assert out.verdict_after is None


# ---------- robots.txt path ----------

def test_refresh_records_robots_block_in_probe(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"")
    out = refresh.refresh_opportunity(
        conn, "RFR-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: False},
    )
    # Both URLs disallowed → update blocked
    assert out.updated is False
    assert out.purchase.blocked_reason == "blocked by robots.txt"
    assert out.sell.blocked_reason == "blocked by robots.txt"


# ---------- outcome_as_dict shape ----------

def test_outcome_as_dict_has_all_keys():
    o = refresh.RefreshOutcome(
        sku="X", name="n", previous_freshness_ts="2026-01-01",
        new_freshness_ts="2026-07-26", updated=True,
        verdict_before={"status": "stale"}, verdict_after={"status": "fresh"},
        purchase=None, sell=None, message="ok",
    )
    d = refresh.outcome_as_dict(o)
    assert set(d) == {
        "sku", "name", "previous_freshness_ts", "new_freshness_ts",
        "updated", "verdict_before", "verdict_after",
        "purchase", "sell", "message",
    }
    assert d["updated"] is True