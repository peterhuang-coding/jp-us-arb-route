"""Scraper 接口基类 — 所有数据源爬虫统一实现。

Phase 1:接口定义 + docstring,无真实现。
Phase 2 (Day 8-14):每个数据源继承 BaseScraper,实现 fetch_one / fetch_all。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypedDict


class ScrapeResult(TypedDict):
    """单源抓取结果(标准化输出)。"""
    sku: str
    source: str            # 平台名,如 "buyee" / "ebay_sold" / "amazon_jp"
    price_local: float     # 本币价(未税)
    currency: str          # "JPY" / "USD" / "CNY"
    price_cny: float       # 标准化到 CNY(用 fx.Convert)
    fx_rate: float         # 抓取时汇率
    fx_source: str         # "manual" / "ecb" / "stub"
    url: str               # 商品 URL
    fetched_at: str        # ISO 时间戳
    raw: dict              # 平台原始字段(可调试)


class BaseScraper(ABC):
    """所有数据源爬虫继承此类。"""

    source: str = ""  # 子类必须设置,如 "buyee"

    @abstractmethod
    def fetch_one(self, sku: str) -> ScrapeResult:
        """抓单个 SKU 单源数据。

        Phase 1:返回 stub(arb.prices 表里查)。
        Phase 2:真请求 + 反爬 + 缓存。
        """

    @abstractmethod
    def fetch_all(self, skus: list[str]) -> list[ScrapeResult]:
        """批量抓取多个 SKU。"""