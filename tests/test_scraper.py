"""Tests for arb.scraper — stdlib-only, monkeypatch urlopen + robots lookup."""
from __future__ import annotations

import io
import time
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from arb import scraper


# ---------- helpers ----------

class _FakeResp:
    def __init__(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8",
                 final_url: str = "https://example.com/page"):
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


@pytest.fixture(autouse=True)
def _reset_rate():
    scraper._reset_rate_limiter_for_tests()
    yield
    scraper._reset_rate_limiter_for_tests()


# ---------- empty / bad input ----------

def test_empty_url_returns_blocked_page():
    p = scraper.fetch_url("", robots_lookup=lambda *a, **kw: None)
    assert p.ok is False
    assert p.status == 0
    assert "empty url" in (p.blocked_reason or "")


def test_non_string_url_returns_blocked_page():
    p = scraper.fetch_url(None, robots_lookup=lambda *a, **kw: None)  # type: ignore[arg-type]
    assert p.ok is False


# ---------- robots.txt integration ----------

def test_robots_disallowed_short_circuits_via_lookup():
    """When the robots_lookup returns False, the page opener is never called."""
    page_calls: list[str] = []
    def opener(req_or_url, *a, **kw):
        page_calls.append(str(req_or_url))
        return _FakeResp(b"<html></html>")
    p = scraper.fetch_url("https://ex.com/foo", opener=opener,
                          robots_lookup=lambda *a, **kw: False)
    assert p.ok is False
    assert p.robots_allowed is False
    assert p.blocked_reason == "blocked by robots.txt"
    assert page_calls == []


def test_robots_allowed_proceeds():
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>hi</html>")
    p = scraper.fetch_url("https://ex.com/foo", opener=opener,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is True
    assert p.robots_allowed is True


def test_robots_unknown_treated_as_allowed():
    """robots.txt unreachable → we proceed (with no robots_allowed hint)."""
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html>x</html>")
    p = scraper.fetch_url("https://ex.com/foo", opener=opener,
                          robots_lookup=lambda *a, **kw: None)
    assert p.ok is True
    assert p.robots_allowed is None


# ---------- HTTP error paths ----------

def test_http_404_recorded_not_raised():
    def opener(req_or_url, *a, **kw):
        raise HTTPError(req_or_url if isinstance(req_or_url, str) else req_or_url.full_url,
                        404, "Not Found", {}, io.BytesIO(b""))
    p = scraper.fetch_url("https://ex.com/x", opener=opener,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is False
    assert p.status == 404
    assert "404" in (p.blocked_reason or "")


def test_url_error_recorded():
    def opener(req_or_url, *a, **kw):
        raise URLError("dns failure")
    p = scraper.fetch_url("https://ex.com/x", opener=opener,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is False
    assert p.status == 0
    assert "dns failure" in (p.blocked_reason or "")


def test_generic_exception_recorded():
    def opener(req_or_url, *a, **kw):
        raise RuntimeError("boom")
    p = scraper.fetch_url("https://ex.com/x", opener=opener,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is False
    assert "boom" in (p.blocked_reason or "")


# ---------- success path + truncation ----------

def test_success_returns_text():
    body = b"<html><body>USD 145.00 in stock</body></html>"
    def opener(req_or_url, *a, **kw):
        return _FakeResp(body)
    p = scraper.fetch_url("https://ex.com/x", opener=opener,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is True
    assert p.status == 200
    assert p.text is not None
    assert "145.00" in p.text
    assert p.bytes_read == len(body)
    assert p.final_url == "https://example.com/page"


def test_oversized_body_truncated_to_max_bytes():
    body = b"x" * 5_000
    def opener(req_or_url, *a, **kw):
        return _FakeResp(body)
    p = scraper.fetch_url("https://ex.com/x", opener=opener,
                          max_bytes=1000,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is True
    assert p.bytes_read == 1000
    assert p.blocked_reason == "truncated"


def test_non_text_content_leaves_text_none():
    body = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    def opener(req_or_url, *a, **kw):
        return _FakeResp(body, ctype="image/png")
    p = scraper.fetch_url("https://ex.com/x.png", opener=opener,
                          robots_lookup=lambda *a, **kw: True)
    assert p.ok is True
    assert p.text is None


# ---------- rate limiter ----------

def test_rate_limiter_sleeps_between_calls(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(scraper.time, "sleep", lambda s: sleeps.append(s))
    def opener(req_or_url, *a, **kw):
        return _FakeResp(b"<html></html>")
    scraper.fetch_url("https://ex.com/a", opener=opener,
                      min_gap_sec=0.5, robots_lookup=lambda *a, **kw: True)
    scraper.fetch_url("https://ex.com/b", opener=opener,
                      min_gap_sec=0.5, robots_lookup=lambda *a, **kw: True)
    # First call resets the timer (no sleep).  Second call should sleep ~0.5s.
    assert len(sleeps) == 1
    assert 0.4 < sleeps[0] <= 0.5


# ---------- extract_price_hints ----------

def test_extract_price_hints_finds_usd_and_jpy():
    text = "Buy now for USD 145.00 (was $199). 日本售价 ¥12,800."
    hints = scraper.extract_price_hints(text)
    amts = [(h["amount"], h["currency"]) for h in hints]
    assert (145.0, "USD") in amts
    assert (199.0, "USD") in amts
    assert (12800.0, "JPY") in amts


def test_extract_price_hints_dedupes_same_currency_amount():
    text = "$100 $100 $100 $100 $100"
    hints = scraper.extract_price_hints(text)
    # dedupe by (currency, amount, raw-token) — same raw appears 5x → 1 hit
    assert len(hints) == 1


def test_extract_price_hints_capped_at_eight():
    text = " ".join(f"USD {i}.00" for i in range(20))
    hints = scraper.extract_price_hints(text)
    assert len(hints) == 8


def test_extract_price_hints_empty_input():
    assert scraper.extract_price_hints("") == []
    assert scraper.extract_price_hints(None) == []  # type: ignore[arg-type]


def test_extract_price_hints_currency_hint_override():
    hints = scraper.extract_price_hints("€99", currency_hint="EUR")
    assert hints[0]["currency"] == "EUR"
    assert hints[0]["amount"] == 99.0