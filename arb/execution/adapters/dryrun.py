"""M0 dry-run 适配器: 纯内存桩, 零真实资金/网络. (spec §10 dry-run 模式)"""
from __future__ import annotations

from .base import OrderRef, PlatformOrder, Quote, ShipmentStatus


class DryRunSellAdapter:
    """上架即回显 ID; get_orders 返回已付款订单(paid / 金额可注入)."""

    def __init__(self, paid: bool = True, order_total_cny: float = 950.0):
        self._paid = paid
        self._total = order_total_cny
        self.listed: list[str] = []
        self.shipped: list[tuple[str, str]] = []

    def list_item(self, sku: str, title: str, price_cny: float) -> str:
        ext = f"dry-sell-{sku}"
        self.listed.append(ext)
        return ext

    def update_price(self, external_id: str, price_cny: float) -> None:
        return None

    def get_orders(self) -> list[PlatformOrder]:
        return [
            PlatformOrder(external_id=ext, sku=ext.removeprefix("dry-sell-"),
                          qty=1, paid=self._paid, total_cny=self._total)
            for ext in self.listed
        ]

    def mark_shipped(self, external_id: str, tracking: str) -> None:
        self.shipped.append((external_id, tracking))

    def delist(self, external_id: str) -> None:
        return None


class DryRunBuyAdapter:
    """固定报价, 下单/付款/物流全桩. quote_unit_cny 可注入以测试限额/毛利路径."""

    def __init__(self, quote_unit_cny: float = 123.0):
        self.quote_unit_cny = quote_unit_cny
        self.placed: list[OrderRef] = []

    def search(self, sku: str, qty: int) -> list[Quote]:
        return [Quote(sku=sku, unit_cny=self.quote_unit_cny,
                      url="https://dry.example/item", source="dryrun")]

    def place_order(self, sku: str, qty: int, address: str) -> OrderRef:
        ref = OrderRef(ref_id=f"dry-buy-{sku}", url="https://dry.example/order")
        self.placed.append(ref)
        return ref

    def pay(self, ref: OrderRef) -> None:
        return None

    def track(self, ref: OrderRef) -> ShipmentStatus:
        return ShipmentStatus(state="delivered", tracking=f"DRY-TRACK-{ref.ref_id}")
