"""M0 流水线测试: dry-run 全链路 + 等待 + 异常."""
import pytest

from arb import db
from arb.execution.adapters.dryrun import DryRunBuyAdapter, DryRunSellAdapter
from arb.execution.notify import NullNotifier
from arb.execution.payguard import PayConfig
from arb.execution.pipeline import Pipeline
from arb.execution.state import OrderState


class SpyNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body):
        self.sent.append((title, body))


@pytest.fixture
def conn():
    c = db.connect_memory()
    yield c
    c.close()


def make_pipeline(sell=None, buy=None, notifier=None, cfg=None):
    return Pipeline(
        sell=sell or DryRunSellAdapter(),
        buy=buy or DryRunBuyAdapter(),
        notifier=notifier or NullNotifier(),
        cfg=cfg or PayConfig(),
        dry_run=True,
    )


def seed(conn, **kw):
    row = dict(sku="JP-SKII-FT230", leg="D", sell_price_cny=950.0, ship_cost_cny=30.0)
    row.update(kw)
    return db.create_execution_order(conn, row)


def test_dryrun_full_chain_completes(conn):
    oid = seed(conn)
    result = make_pipeline().run_all(conn, [oid])[0]
    states = [r["state"] for r in result["chain"]]
    assert states[-1] == OrderState.COMPLETED.value
    assert OrderState.AWAITING_FLIGHT.value in states
    row = db.get_execution_order(conn, oid)
    assert row["state"] == OrderState.COMPLETED.value
    assert row["buy_price_cny"] == 123.0
    assert row["buyer_paid_cny"] == 950.0
    assert row["tracking"] == "DRY-TRACK-dry-buy-JP-SKII-FT230"


def test_unpaid_buyer_waits_in_listed(conn):
    oid = seed(conn)
    result = make_pipeline(sell=DryRunSellAdapter(paid=False)).run_all(conn, [oid])[0]
    assert result["chain"][-1].get("noop") is True
    assert db.get_execution_order(conn, oid)["state"] == OrderState.LISTED.value


def test_over_limit_goes_awaiting_human_and_notifies(conn):
    oid = seed(conn)
    spy = SpyNotifier()
    result = make_pipeline(buy=DryRunBuyAdapter(quote_unit_cny=2000.0),
                           notifier=spy).run_all(conn, [oid])[0]
    assert result["chain"][-1]["state"] == OrderState.AWAITING_HUMAN.value
    row = db.get_execution_order(conn, oid)
    assert row["state"] == OrderState.AWAITING_HUMAN.value
    assert "单笔" in row["error"]
    assert len(spy.sent) == 1


def test_unknown_order_raises_keyerror(conn):
    with pytest.raises(KeyError):
        make_pipeline().tick(conn, 999)
