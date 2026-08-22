"""Round 25 (T2): 实时数据源 — buyee + eBay sold + Amazon JP + URL paste fallback.

Most public search engines return 403 to plain urllib (anti-bot). This module:
- tries the public search first
- falls back to returning {ok: false, reason: 'anti-bot blocked'} so the SPA can
  show a useful message + offer paste-URL fallback
- exposes `extract_url(html)` so the user can paste a search-result page's HTML
  (from browser View Source) and we pull out prices + titles
"""
from __future__ import annotations
import urllib.parse
import urllib.request
import re
from typing import Optional
from datetime import datetime

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Accept-Language": "ja,en;q=0.9,zh;q=0.8",
    "Accept": "text/html,application/xhtml+xml",
}


def _fetch_url(url: str, timeout: int = 15) -> tuple[Optional[str], Optional[str]]:
    """Returns (html_or_none, error_or_none)."""
    try:
        req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), None
    except Exception as e:
        return None, str(e)


def _blocked_response(source: str, err: str) -> dict:
    """Standard response when anti-bot blocks us."""
    return {
        "source": source,
        "ok": False,
        "blocked": True,
        "reason": err or "anti-bot blocked (HTTP 403)",
        "hint": "请在浏览器打开搜索结果页 → 复制源码(View Source) → 粘贴到 /api/live-extract",
        "items": [],
    }


def search_buyee(query: str, limit: int = 10) -> dict:
    """buyee.jp public search."""
    if not HAS_BS4:
        return {"source": "buyee", "ok": False, "reason": "beautifulsoup4 not installed", "items": []}
    url = f"https://buyee.jp/item/search/query/{urllib.parse.quote(query)}"
    html, err = _fetch_url(url)
    if not html:
        return _blocked_response("buyee", err)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for item in soup.select("li.itemCard")[:limit]:
        title_el = item.select_one("p.itemCard__itemName")
        price_el = item.select_one("span.itemCard__itemPrice")
        link_el = item.select_one("a.itemCard__link")
        title = title_el.get_text(strip=True) if title_el else ""
        price_text = price_el.get_text(strip=True) if price_el else ""
        price_jpy_match = re.search(r"[\d,]+", price_text.replace("¥", ""))
        price_jpy = int(price_jpy_match.group().replace(",", "")) if price_jpy_match else 0
        href = link_el.get("href", "") if link_el else ""
        if href and not href.startswith("http"):
            href = "https://buyee.jp" + href
        if title and price_jpy:
            out.append({"title": title, "price_jpy": price_jpy, "url": href})
    if not out:
        return _blocked_response("buyee", "HTML parsed but no items found (likely bot-detection page)")
    return {"source": "buyee", "ok": True, "items": out, "count": len(out)}


def search_ebay_sold(query: str, limit: int = 10) -> dict:
    """eBay sold listings (LH_Sold=1)."""
    if not HAS_BS4:
        return {"source": "ebay_sold", "ok": False, "reason": "beautifulsoup4 not installed", "items": []}
    q = urllib.parse.quote(query)
    url = f"https://www.ebay.com/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1&_ipg=50"
    html, err = _fetch_url(url)
    if not html:
        return _blocked_response("ebay_sold", err)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for item in soup.select("li.s-item")[:limit]:
        title_el = item.select_one("h3.s-item__title")
        price_el = item.select_one("span.s-item__price")
        link_el = item.select_one("a.s-item__link")
        title = title_el.get_text(strip=True) if title_el else ""
        price_text = price_el.get_text(strip=True) if price_el else ""
        price_match = re.search(r"[\d.]+", price_text.replace("$", "").replace(",", ""))
        price_usd = float(price_match.group()) if price_match else 0
        href = link_el.get("href", "") if link_el else ""
        if title and price_usd and "Shop on eBay" not in title:
            out.append({"title": title, "price_usd": price_usd, "url": href})
    if not out:
        return _blocked_response("ebay_sold", "HTML parsed but no items found")
    return {"source": "ebay_sold", "ok": True, "items": out, "count": len(out)}


def search_amazon_jp(query: str, limit: int = 10) -> dict:
    """Amazon.co.jp search."""
    if not HAS_BS4:
        return {"source": "amazon_jp", "ok": False, "reason": "beautifulsoup4 not installed", "items": []}
    q = urllib.parse.quote(query)
    url = f"https://www.amazon.co.jp/s?k={q}&i=aps"
    html, err = _fetch_url(url)
    if not html:
        return _blocked_response("amazon_jp", err)
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for item in soup.select("[data-component-type=s-search-result]")[:limit]:
        title_el = item.select_one("h2 span")
        whole_el = item.select_one("span.a-price-whole")
        frac_el = item.select_one("span.a-price-fraction")
        link_el = item.select_one("a.a-link-normal")
        title = title_el.get_text(strip=True) if title_el else ""
        whole = whole_el.get_text(strip=True).replace(",", "").replace(".", "") if whole_el else "0"
        frac = frac_el.get_text(strip=True) if frac_el else "00"
        try:
            price_jpy = int(whole) if whole else 0
        except (TypeError, ValueError):
            price_jpy = 0
        href = link_el.get("href", "") if link_el else ""
        if href and not href.startswith("http"):
            href = "https://www.amazon.co.jp" + href
        if title and price_jpy:
            out.append({"title": title, "price_jpy": price_jpy, "url": href.split("?")[0]})
    if not out:
        return _blocked_response("amazon_jp", "HTML parsed but no items found (Amazon often serves bot-block page)")
    return {"source": "amazon_jp", "ok": True, "items": out, "count": len(out)}


def extract_url(html: str, source_hint: str = "auto") -> dict:
    """Extract prices from pasted HTML. Auto-detects buyee/ebay/amazon-jp format."""
    if not HAS_BS4:
        return {"ok": False, "reason": "beautifulsoup4 not installed", "items": []}
    soup = BeautifulSoup(html, "html.parser")
    out = []

    # buyee.jp format
    if source_hint == "buyee" or soup.select("li.itemCard"):
        for item in soup.select("li.itemCard"):
            t = item.select_one("p.itemCard__itemName")
            p_ = item.select_one("span.itemCard__itemPrice")
            a = item.select_one("a.itemCard__link")
            if t and p_:
                mt = re.search(r"[\d,]+", p_.get_text().replace("¥", ""))
                jpy = int(mt.group().replace(",", "")) if mt else 0
                if jpy:
                    href = a.get("href", "") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://buyee.jp" + href
                    out.append({"title": t.get_text(strip=True), "price_jpy": jpy, "url": href})
        return {"source": "buyee", "ok": True, "items": out, "count": len(out), "extracted_from": "pasted_html"}

    # eBay format
    if source_hint == "ebay" or soup.select("li.s-item"):
        for item in soup.select("li.s-item"):
            t = item.select_one("h3.s-item__title")
            p_ = item.select_one("span.s-item__price")
            a = item.select_one("a.s-item__link")
            if t and p_ and "Shop on eBay" not in t.get_text():
                mt = re.search(r"[\d.]+", p_.get_text().replace("$", "").replace(",", ""))
                usd = float(mt.group()) if mt else 0
                if usd:
                    out.append({"title": t.get_text(strip=True), "price_usd": usd, "url": a.get("href", "") if a else ""})
        return {"source": "ebay_sold", "ok": True, "items": out, "count": len(out), "extracted_from": "pasted_html"}

    # Amazon JP format
    if source_hint == "amazon_jp" or soup.select("[data-component-type=s-search-result]"):
        for item in soup.select("[data-component-type=s-search-result]"):
            t = item.select_one("h2 span")
            w = item.select_one("span.a-price-whole")
            a = item.select_one("a.a-link-normal")
            if t and w:
                try:
                    jpy = int(w.get_text(strip=True).replace(",", "").replace(".", ""))
                except ValueError:
                    jpy = 0
                if jpy:
                    href = a.get("href", "") if a else ""
                    if href and not href.startswith("http"):
                        href = "https://www.amazon.co.jp" + href
                    out.append({"title": t.get_text(strip=True), "price_jpy": jpy, "url": href.split("?")[0]})
        return {"source": "amazon_jp", "ok": True, "items": out, "count": len(out), "extracted_from": "pasted_html"}

    # Generic price/title scrape (very loose)
    for tag in soup.select("[data-price], .price, .a-price-whole, .s-item__price, .itemCard__itemPrice"):
        text = tag.get_text(strip=True)
        mt = re.search(r"[¥$]?[\d,]+(?:\.\d+)?", text)
        if mt:
            out.append({"raw": text, "parsed": mt.group(), "tag": tag.name})
    return {"source": "generic", "ok": True, "items": out[:20], "count": min(20, len(out)), "extracted_from": "pasted_html"}


def search_all(query: str, limit: int = 5) -> dict:
    """Multi-source search. Always returns results dict with per-source ok flag."""
    return {
        "query": query,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "buyee": search_buyee(query, limit),
        "ebay_sold": search_ebay_sold(query, limit),
        "amazon_jp": search_amazon_jp(query, limit),
    }
