"""M0 dry-run 适配器测试."""
from arb.execution.adapters.base import OrderRef, ShipmentStatus
from arb.execution.adapters.dryrun import DryRunBuyAdapter, DryRunSellAdapter


def test_sell_adapter_roundtrip():
    sell = DryRunSellAdapter(paid=True, order_total_cny=950.0)
    ext = sell.list_item("JP-SKII-FT230", "t", 950.0)
    assert ext == "dry-sell-JP-SKII-FT230"
    orders = sell.get_orders()
    assert len(orders) == 1
    assert orders[0].paid is True
    assert orders[0].total_cny == 950.0


def test_sell_adapter_unpaid_returns_nothing_matching():
    sell = DryRunSellAdapter(paid=False)
    sell.list_item("JP-SKII-FT230", "t", 950.0)
    assert not [o for o in sell.get_orders() if o.paid]


def test_buy_adapter_full_cycle():
    buy = DryRunBuyAdapter(quote_unit_cny=123.0)
    quotes = buy.search("JP-SKII-FT230", 1)
    assert quotes[0].unit_cny == 123.0
    ref = buy.place_order("JP-SKII-FT230", 1, "")
    assert isinstance(ref, OrderRef)
    buy.pay(ref)  # no-op, 不应抛异常
    st = buy.track(ref)
    assert st.state == "delivered"
    assert st.tracking.startswith("DRY-TRACK-")
