"""Safe, dependency-free HTTP fetcher for the freshness watchdog.

V0 stance: we do NOT actually parse prices here.  ``fetch_url`` is a small,
testable wrapper around ``urllib.request.urlopen`` that:

  * respects ``robots.txt`` via ``urllib.robotparser``;
  * applies a per-process minimum gap between requests (rate limit);
  * enforces a hard timeout and a response-size cap;
  * returns a structured :class:`ScrapedPage` instead of raising so the
    refresh endpoint can record what happened without try/except ladders.

A future round will add a per-site parser (Amazon JP, Bic Camera, eBay US).
For now ``extract_price_hints`` returns whatever patterns it can grep from
the body — useful as a smoke check, never as the source of truth.

Why stdlib only: the brief lists ``requests`` + ``BeautifulSoup`` as the
intended stack but also says "respect robots.txt" and "限速".  Using
stdlib here keeps the test surface tiny (monkeypatch ``urlopen`` and
``RobotFileParser``), avoids a hard runtime dep on ``requests``, and
makes the scraper safe to import on the PDF test machine where Chromium
is the only thing installed.
"""
from __future__ import annotations

import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable, Optional

# ---------- knobs ----------
DEFAULT_TIMEOUT: float = 8.0          # seconds before giving up
DEFAULT_MAX_BYTES: int = 1_500_000    # 1.5 MB hard cap (HTML pages are <200 KB)
DEFAULT_MIN_GAP_SEC: float = 1.0     # rate limit between any two fetch_url calls
USER_AGENT: str = "jp-us-arb-route/0.3 (+local-only personal use)"


@dataclass(frozen=True)
class ScrapedPage:
    url: str
    ok: bool
    status: int                       # 0 when blocked / errored before HTTP
    final_url: Optional[str]          # after redirects (if any)
    content_type: Optional[str]
    bytes_read: int
    elapsed_ms: int
    robots_allowed: Optional[bool]    # None = robots.txt unreachable / not applicable
    blocked_reason: Optional[str]     # human reason if not ok
    text: Optional[str]               # decoded body when ok and looks like text


# ---------- module-level rate limiter ----------

_last_call_ts: float = 0.0


def _wait_for_slot(min_gap_sec: float = DEFAULT_MIN_GAP_SEC) -> None:
    """Block until ``min_gap_sec`` seconds have elapsed since the last call."""
    global _last_call_ts
    now = time.monotonic()
    wait = min_gap_sec - (now - _last_call_ts)
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.monotonic()


def _reset_rate_limiter_for_tests() -> None:
    """Test helper: forget the last-call timestamp."""
    global _last_call_ts
    _last_call_ts = 0.0


# ---------- robots.txt ----------

def _robots_check(url: str, ua: str, opener: Callable = urllib.request.urlopen) -> Optional[bool]:
    """Return True/False/None for "allowed / disallowed / unknown".

    Uses a tiny inline opener so tests can stub both the network call and the
    parsing.  ``None`` means we couldn't fetch robots.txt (network down,
    4xx/5xx) — we treat unknown as allowed with a logged warning so a dead
    robots.txt never silently kills a refresh.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = opener(robots_url, timeout=3.0)
    except Exception:
        return None
    try:
        body = resp.read(64_000).decode("utf-8", errors="replace")
    except Exception:
        return None
    finally:
        try:
            resp.close()
        except Exception:
            pass
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(io.StringIO(body).readlines())
    try:
        return rp.can_fetch(ua, url)
    except Exception:
        return None


# ---------- public API ----------

def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
    min_gap_sec: float = DEFAULT_MIN_GAP_SEC,
    user_agent: str = USER_AGENT,
    opener: Callable = urllib.request.urlopen,
    robots_lookup: Callable = _robots_check,
) -> ScrapedPage:
    """Fetch ``url`` once.  Never raises — errors are recorded in ScrapedPage.

    ``opener`` is used for both the robots.txt probe and the actual page fetch;
    when robots says "disallowed" the page opener is **not** called at all, so
    tests can stub a single opener and assert that the page request was skipped.
    """
    if not url or not isinstance(url, str):
        return ScrapedPage(
            url=url or "", ok=False, status=0, final_url=None,
            content_type=None, bytes_read=0, elapsed_ms=0,
            robots_allowed=None, blocked_reason="empty url",
            text=None,
        )

    # robots.txt precheck — uses the same opener so test stubs see both calls.
    robots_allowed = robots_lookup(url, user_agent, opener=opener)
    if robots_allowed is False:
        return ScrapedPage(
            url=url, ok=False, status=0, final_url=None,
            content_type=None, bytes_read=0, elapsed_ms=0,
            robots_allowed=False, blocked_reason="blocked by robots.txt",
            text=None,
        )

    _wait_for_slot(min_gap_sec)
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "*/*"})
    try:
        resp = opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        return ScrapedPage(
            url=url, ok=False, status=e.code, final_url=None,
            content_type=None, bytes_read=0,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            robots_allowed=robots_allowed,
            blocked_reason=f"http {e.code}",
            text=None,
        )
    except urllib.error.URLError as e:
        return ScrapedPage(
            url=url, ok=False, status=0, final_url=None,
            content_type=None, bytes_read=0,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            robots_allowed=robots_allowed,
            blocked_reason=f"url error: {e.reason}",
            text=None,
        )
    except Exception as e:  # pragma: no cover - defensive
        return ScrapedPage(
            url=url, ok=False, status=0, final_url=None,
            content_type=None, bytes_read=0,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            robots_allowed=robots_allowed,
            blocked_reason=f"unhandled: {type(e).__name__}: {e}",
            text=None,
        )

    content_type = resp.headers.get("Content-Type")
    raw = resp.read(max_bytes + 1)
    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]
    elapsed = int((time.monotonic() - started) * 1000)
    final_url = resp.geturl()
    try:
        resp.close()
    except Exception:
        pass

    text: Optional[str] = None
    if content_type is None or "text" in content_type.lower() or "html" in content_type.lower() or "xml" in content_type.lower() or "json" in content_type.lower():
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = None

    return ScrapedPage(
        url=url, ok=True, status=resp.status, final_url=final_url,
        content_type=content_type, bytes_read=len(raw), elapsed_ms=elapsed,
        robots_allowed=robots_allowed,
        blocked_reason="truncated" if truncated else None,
        text=text,
    )


# ---------- price-extraction hints (V0 — never source of truth) ----------

_PRICE_RE = re.compile(
    r"(?:US\$|[$€£¥￥]|USD|JPY|EUR|GBP)\s*([0-9]{1,3}(?:[, ][0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


def extract_price_hints(text: str, *, currency_hint: Optional[str] = None) -> list[dict]:
    """Grep visible-looking price strings out of HTML/text.  NOT a parser.

    Returns up to 8 hits: ``[{"raw": "...", "amount": 1234.5, "currency": "USD"}, ...]``.
    Intended for the V0 refresh report — UI must show "estimate, not verified".
    """
    if not text:
        return []
    hits: list[dict] = []
    seen: set[str] = set()
    for m in _PRICE_RE.finditer(text):
        raw = m.group(0)
        amount_str = m.group(1).replace(",", "").replace(" ", "")
        try:
            amount = float(amount_str)
        except ValueError:
            continue
        currency = currency_hint or _infer_currency(raw)
        key = f"{currency}|{amount}|{raw}"
        if key in seen:
            continue
        seen.add(key)
        hits.append({"raw": raw, "amount": amount, "currency": currency})
        if len(hits) >= 8:
            break
    return hits


def _infer_currency(token: str) -> str:
    upper = token.upper()
    if "¥" in token or "￥" in token or "JPY" in upper:
        return "JPY"
    if "€" in token or "EUR" in upper:
        return "EUR"
    if "£" in token or "GBP" in upper:
        return "GBP"
    if "$" in token or "USD" in upper or "US$" in token:
        return "USD"
    return "?"


# ---------- meta ----------

__all__ = [
    "ScrapedPage",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MIN_GAP_SEC",
    "USER_AGENT",
    "fetch_url",
    "extract_price_hints",
    "_reset_rate_limiter_for_tests",
]