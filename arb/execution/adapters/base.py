"""平台适配器统一接口 (spec §6). M0 只定义协议与数据类; 真实实现 M1-M3."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class AdapterError(Exception):
    """适配器执行失败 → pipeline 把订单转 awaiting_human."""


@dataclass(frozen=True)
class Quote:
    """采购端比价结果."""
    sku: str
    unit_cny: float
    url: str = ""
    source: str = "dryrun"


@dataclass(frozen=True)
class PlatformOrder:
    """销售端拉回的买家订单."""
    external_id: str
    sku: str
    qty: int
    paid: bool
    total_cny: float


@dataclass(frozen=True)
class OrderRef:
    """采购端下单后的引用."""
    ref_id: str
    url: str = ""


@dataclass(frozen=True)
class ShipmentStatus:
    """采购端物流状态. state: processing | shipped | delivered"""
    state: str
    tracking: str = ""


@runtime_checkable
class SellAdapter(Protocol):
    def list_item(self, sku: str, title: str, price_cny: float) -> str:
        """上架, 返回平台外部 ID."""
        ...

    def update_price(self, external_id: str, price_cny: float) -> None: ...

    def get_orders(self) -> list[PlatformOrder]:
        """拉取新订单(含付款状态)."""
        ...

    def mark_shipped(self, external_id: str, tracking: str) -> None: ...

    def delist(self, external_id: str) -> None: ...


@runtime_checkable
class BuyAdapter(Protocol):
    def search(self, sku: str, qty: int) -> list[Quote]:
        """比价, 返回候选报价."""
        ...

    def place_order(self, sku: str, qty: int, address: str) -> OrderRef:
        """下单(可能停在待付款)."""
        ...

    def pay(self, ref: OrderRef) -> None:
        """付款. 调用前必须通过 payguard 检查."""
        ...

    def track(self, ref: OrderRef) -> ShipmentStatus:
        """物流跟踪."""
        ...
