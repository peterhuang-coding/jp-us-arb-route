"""Tests for arb.verify — pure helpers + coordinator against in-memory DB.

Tests run in three layers, mirroring the test pattern used in test_refresh.py:

  1. Pure helpers: parse_price_from_hints, compare_price, within_tolerance.
  2. Coordinator happy / drift / currency-mismatch / no-hint paths
     (with a stubbed scraper so we never touch the network).
  3. Proposal apply / reject flows through ``db.resolve_proposed_price``.
"""
from __future__ import annotations

import datetime as _dt

import pytest

from arb import db, refresh, scraper, verify


# ---------- pure helpers ----------

def test_parse_hints_returns_first_when_no_currency_filter():
    hints = [
        {"raw": "$10.00", "amount": 10.0, "currency": "USD"},
        {"raw": "$20.00", "amount": 20.0, "currency": "USD"},
    ]
    out = verify.parse_price_from_hints(hints)
    assert out == {"amount": 10.0, "currency": "USD", "raw": "$10.00"}


def test_parse_hints_filters_by_expected_currency():
    hints = [
        {"raw": "¥12,800", "amount": 12800.0, "currency": "JPY"},
        {"raw": "$85.00", "amount": 85.0, "currency": "USD"},
    ]
    out = verify.parse_price_from_hints(hints, expected_currency="USD")
    assert out["amount"] == 85.0
    assert out["currency"] == "USD"


def test_parse_hints_returns_none_when_no_match():
    hints = [{"raw": "¥12800", "amount": 12800.0, "currency": "JPY"}]
    out = verify.parse_price_from_hints(hints, expected_currency="USD")
    assert out is None


def test_parse_hints_empty_returns_none():
    assert verify.parse_price_from_hints([]) is None
    assert verify.parse_price_from_hints(None) is None


def test_parse_hints_skips_malformed_entries():
    hints = [
        {"raw": "weird", "currency": "USD"},                  # no amount
        {"amount": "nope", "currency": "USD"},                # non-numeric
        {"raw": "$5", "amount": 5.0, "currency": "USD"},      # good
    ]
    out = verify.parse_price_from_hints(hints)
    assert out["amount"] == 5.0


def test_compare_price_drift_pct_is_symmetric_and_relative():
    assert verify.compare_price(100.0, 100.0) == 0.0
    assert abs(verify.compare_price(105.0, 100.0) - 5.0) < 1e-9
    assert abs(verify.compare_price(95.0, 100.0) - 5.0) < 1e-9
    assert verify.compare_price(None, 100.0) is None
    assert verify.compare_price(100.0, None) is None
    assert verify.compare_price(100.0, 0.0) is None     # div-by-zero guard


def test_within_tolerance_uses_fraction_input():
    assert verify.within_tolerance(0.0, tolerance=0.05) is True
    assert verify.within_tolerance(5.0, tolerance=0.05) is True
    assert verify.within_tolerance(5.001, tolerance=0.05) is False
    assert verify.within_tolerance(None, tolerance=0.05) is False


# ---------- DB / coordinator fixtures ----------

class _FakeResp:
    """Reused from test_refresh.py semantics; kept local so tests don't drift."""

    def __init__(self, body: bytes, status: int = 200,
                 ctype: str = "text/html; charset=utf-8"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": ctype}
        self._final = "https://example.com/x"

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


def _seed_opp(conn, **overrides) -> dict:
    opp = dict(
        sku="VRF-001", name="Verify Test", category="misc",
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


# ---------- coordinator: happy path ----------

def test_verify_within_tolerance_marks_verified(conn):
    _seed_opp(conn)
    # stored 85 / 145; scrape hints within 1% drift → accept
    def opener(req_or_url, *a, **kw):
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else req_or_url
        if "/jp" in url:
            return _FakeResp(b"<html>USD 85.50 in stock</html>")
        return _FakeResp(b"<html>USD 145.99</html>")
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.verified_now is True
    assert out.final_verified is True
    assert out.purchase.accepted is True
    assert out.sell.accepted is True
    assert out.purchase.proposal_id is None
    assert out.sell.proposal_id is None
    assert "已验证" in out.message
    row = db.get_opportunity(conn, "VRF-001")
    assert row["verified"] == 1


def test_verify_drifts_stage_proposals_without_overwrite(conn):
    _seed_opp(conn)
    # stored 85/145; scrape 95/200 — both well above 5% tolerance
    def opener(req_or_url, *a, **kw):
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else req_or_url
        if "/jp" in url:
            return _FakeResp(b"<html>USD 95.00</html>")
        return _FakeResp(b"<html>USD 200.00</html>")
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.verified_now is False
    assert out.final_verified is False
    assert out.purchase.proposal_id is not None
    assert out.sell.proposal_id is not None
    assert out.purchase.drift_pct > 5.0
    assert out.sell.drift_pct > 5.0
    # stored prices untouched
    row = db.get_opportunity(conn, "VRF-001")
    assert row["purchase_price_usd"] == 85.0
    assert row["sell_price_usd"] == 145.0
    assert row["verified"] == 0
    # 2 pending proposals added
    pending = db.list_proposed_prices(conn, sku="VRF-001", status="pending")
    assert len(pending) == 2


def test_verify_dry_run_does_not_stage(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>USD 200.00</html>")
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
        auto_stage=False,
    )
    assert out.verified_now is False
    assert out.purchase.proposal_id is None
    assert out.sell.proposal_id is None
    assert db.list_proposed_prices(conn) == []


def test_verify_currency_mismatch_stages_proposal(conn):
    _seed_opp(conn)
    # scrape returns JPY only — can't compare to USD directly
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>JPY 12800  \xc2\xa512,800</html>")
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.verified_now is False
    # both sides see JPY-only → both get staged as currency-mismatch proposals
    assert out.purchase.proposal_id is not None
    assert out.sell.proposal_id is not None
    assert "不直接可比" in out.purchase.note
    row = db.get_opportunity(conn, "VRF-001")
    assert row["verified"] == 0


def test_verify_no_hints_keeps_unverified(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>no prices here at all</html>")
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.verified_now is False
    assert out.purchase.proposal_id is None
    assert out.sell.proposal_id is None
    assert "未抓取" in out.message


def test_verify_bails_out_when_refresh_failed(conn):
    _seed_opp(conn)
    from urllib.error import HTTPError
    def opener(req_or_url, *a, **kw):
        raise HTTPError("https://example.com/jp", 500, "boom", {}, None)
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.refresh_updated is False
    assert out.verified_now is False
    assert "URL 抓取未成功" in out.message
    # no proposals, no verified flip
    assert db.list_proposed_prices(conn) == []
    row = db.get_opportunity(conn, "VRF-001")
    assert row["verified"] == 0


def test_verify_unknown_sku_returns_outcome_without_db_change(conn):
    out = verify.verify_opportunity(
        conn, "NOPE", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": lambda *a, **kw: None,
                        "robots_lookup": lambda *a, **kw: True},
    )
    assert out.verified_now is False
    assert out.message.startswith("opportunity not found")
    assert db.list_proposed_prices(conn) == []


def test_verify_reuses_supplied_refresh_outcome(conn):
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else req_or_url
        if "/jp" in url:
            return _FakeResp(b"<html>USD 85.50</html>")
        return _FakeResp(b"<html>USD 145.99</html>")
    # pre-build a refresh outcome to skip the second URL probe
    refresh_outcome = refresh.refresh_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert refresh_outcome.updated is True
    proposals_before = len(db.list_proposed_prices(conn))
    out = verify.verify_opportunity(
        conn, "VRF-001", refresh_outcome=refresh_outcome,
        today=_dt.date(2026, 7, 26),
    )
    assert out.verified_now is True
    # no new proposals added
    assert len(db.list_proposed_prices(conn)) == proposals_before


def test_verify_only_purchase_drift_keeps_unverified(conn):
    """Edge: one side drifts, the other matches → still no `verified` badge.

    Rationale: marking a row verified while the OTHER side drifted would hide
    a real risk.  Both sides must clear the bar for the green checkmark.
    """
    _seed_opp(conn)
    def opener(req_or_url, *a, **kw):
        url = req_or_url.full_url if hasattr(req_or_url, "full_url") else req_or_url
        if "/jp" in url:
            return _FakeResp(b"<html>USD 85.10</html>")    # 0.1% drift
        return _FakeResp(b"<html>USD 200.00</html>")        # 38% drift
    out = verify.verify_opportunity(
        conn, "VRF-001", today=_dt.date(2026, 7, 26),
        scraper_kwargs={"opener": opener, "robots_lookup": lambda *a, **kw: True},
    )
    assert out.verified_now is False
    assert out.purchase.accepted is True
    assert out.sell.accepted is False
    assert out.purchase.proposal_id is None
    assert out.sell.proposal_id is not None


def test_outcome_as_dict_has_all_keys():
    o = verify.VerifyOutcome(
        sku="X", name="n", refresh_updated=True, refreshed_at="2026-07-26",
        purchase=verify.SideCheck(
            "purchase_price_usd", 85.0, "u", {"amount": 85.0, "currency": "USD", "raw": "$85"},
            0.0, True, None, "ok",
        ),
        sell=verify.SideCheck(
            "sell_price_usd", 145.0, "u2", {"amount": 145.0, "currency": "USD", "raw": "$145"},
            0.0, True, None, "ok",
        ),
        verified_now=True, final_verified=True, final_freshness_ts="2026-07-26",
        message="ok",
    )
    d = verify.outcome_as_dict(o)
    assert set(d) == {
        "sku", "name", "refresh_updated", "refreshed_at",
        "verified_now", "final_verified", "final_freshness_ts",
        "purchase", "sell", "message",
    }
    assert d["verified_now"] is True
    assert d["purchase"]["accepted"] is True


# ---------- proposal apply / reject ----------

def _stage_one_proposal(conn, sku="VRF-001", field="sell_price_usd",
                        proposed_value=200.0, stored_value=145.0) -> int:
    opp = db.get_opportunity(conn, sku)
    return db.add_proposed_price(
        conn, opp["id"], field,
        stored_value=stored_value, proposed_value=proposed_value,
        detected_currency="USD", detected_raw=f"USD {proposed_value}",
        source_url="https://example.com/us", drift_pct=37.93,
    )


def test_resolve_proposal_apply_overwrites_stored_price_and_bumps_ts(conn):
    _seed_opp(conn)
    pid = _stage_one_proposal(conn)
    res = db.resolve_proposed_price(conn, pid, "apply", today="2026-07-26")
    assert res["applied"] is True
    assert res["proposal_status"] == "applied"
    row = db.get_opportunity(conn, "VRF-001")
    assert row["sell_price_usd"] == 200.0
    assert row["data_freshness_ts"] == "2026-07-26"


def test_resolve_proposal_reject_keeps_stored_price(conn):
    _seed_opp(conn)
    pid = _stage_one_proposal(conn)
    res = db.resolve_proposed_price(conn, pid, "reject", today="2026-07-26")
    assert res["applied"] is False
    assert res["proposal_status"] == "rejected"
    row = db.get_opportunity(conn, "VRF-001")
    assert row["sell_price_usd"] == 145.0
    assert row["data_freshness_ts"] == "2026-05-01"     # untouched


def test_resolve_proposal_double_apply_refused(conn):
    _seed_opp(conn)
    pid = _stage_one_proposal(conn)
    db.resolve_proposed_price(conn, pid, "apply", today="2026-07-26")
    res = db.resolve_proposed_price(conn, pid, "apply", today="2026-07-27")
    assert res["applied"] is False
    assert "already applied" in res["message"]


def test_resolve_proposal_unknown_id_returns_clean_dict(conn):
    res = db.resolve_proposed_price(conn, 99999, "apply")
    assert res["applied"] is False
    assert "not found" in res["message"]


def test_resolve_proposal_invalid_action_raises(conn):
    _seed_opp(conn)
    pid = _stage_one_proposal(conn)
    with pytest.raises(ValueError):
        db.resolve_proposed_price(conn, pid, "explode")


def test_list_proposed_prices_filters_by_sku_and_status(conn):
    _seed_opp(conn)
    _stage_one_proposal(conn, field="sell_price_usd", proposed_value=200.0)
    _stage_one_proposal(conn, field="purchase_price_usd",
                        proposed_value=95.0, stored_value=85.0)
    pending = db.list_proposed_prices(conn, sku="VRF-001", status="pending")
    assert len(pending) == 2
    all_for_sku = db.list_proposed_prices(conn, sku="VRF-001")
    assert len(all_for_sku) == 2
    all_pending = db.list_proposed_prices(conn, status="pending")
    assert len(all_pending) == 2


def test_add_proposed_price_rejects_unknown_field(conn):
    _seed_opp(conn)
    with pytest.raises(ValueError):
        db.add_proposed_price(
            conn, db.get_opportunity(conn, "VRF-001")["id"],
            "secret_field",
            stored_value=1.0, proposed_value=2.0,
            detected_currency="USD", detected_raw="$2",
            source_url="x", drift_pct=100.0,
        )