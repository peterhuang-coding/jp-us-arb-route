"""执行环流水线 (spec §5): 每次 tick 把一张订单推进一个状态.

M0 范围:
- 平台操作全部走注入的适配器(dry-run 桩或未来真实实现)
- 异常(AdapterError)统一转 awaiting_human 并推送
- 等待型条件(买家未付款/货未到仓)原地不动(noop), 不算异常
- 重试退避策略随 M1 真实适配器接入, M0 不实现
"""
from __future__ import annotations

import datetime as _dt
import sqlite3

from .. import db
from .adapters.base import AdapterError, BuyAdapter, OrderRef, SellAdapter
from .notify import Notifier, NullNotifier
from .payguard import PayConfig, check_funds, check_pay
from .state import NEXT_STATE, OrderState


class Pipeline:
    def __init__(
        self,
        sell: SellAdapter,
        buy: BuyAdapter,
        notifier: Notifier | None = None,
        cfg: PayConfig | None = None,
        dry_run: bool = True,
    ):
        self.sell = sell
        self.buy = buy
        self.notifier = notifier if notifier is not None else NullNotifier()
        self.cfg = cfg if cfg is not None else PayConfig()
        self.dry_run = dry_run

    def tick(self, conn: sqlite3.Connection, order_id: int) -> dict:
        """推进一张订单一个状态. 返回摘要 dict."""
        order = db.get_execution_order(conn, order_id)
        if order is None:
            raise KeyError(f"execution order {order_id} not found")
        state = OrderState(order["state"])
        nxt = NEXT_STATE[state]
        if nxt is None:
            return {"order_id": order_id, "state": state.value, "terminal": True}

        try:
            patch = self._advance(conn, order, state, nxt)
        except AdapterError as exc:
            db.update_execution_order(
                conn, order_id, state=OrderState.AWAITING_HUMAN.value, error=str(exc),
            )
            self.notifier.send(
                f"订单 #{order_id} 需要人工",
                f"sku={order['sku']} 在 {state.value} 失败: {exc}",
            )
            return {"order_id": order_id, "state": OrderState.AWAITING_HUMAN.value,
                    "error": str(exc)}

        if patch.get("noop"):
            return {"order_id": order_id, "state": state.value, "noop": True}

        db.update_execution_order(conn, order_id, state=nxt.value, **patch)
        return {"order_id": order_id, "state": nxt.value,
                "transition": f"{state.value} → {nxt.value}"}

    def run_all(self, conn: sqlite3.Connection, order_ids: list[int] | None = None,
                max_ticks: int = 30) -> list[dict]:
        """把所有(或指定)订单推到终态/异常/等待点. dry-run 下不产生真实副作用."""
        if order_ids is None:
            order_ids = [r["id"] for r in db.list_execution_orders(conn)]
        out: list[dict] = []
        for oid in order_ids:
            chain: list[dict] = []
            for _ in range(max_ticks):
                res = self.tick(conn, oid)
                chain.append(res)
                if res.get("terminal") or res.get("error") or res.get("noop"):
                    break
            out.append({"order_id": oid, "chain": chain})
        return out

    # ---------- 转移实现 ----------

    def _advance(self, conn: sqlite3.Connection, order: sqlite3.Row,
                 state: OrderState, nxt: OrderState) -> dict:
        sku = order["sku"]
        qty = int(order["qty"])

        if state is OrderState.CREATED and nxt is OrderState.LISTED:
            ext = self.sell.list_item(sku, title=f"{sku} 自动上架",
                                      price_cny=float(order["sell_price_cny"]))
            return {"sell_ext_id": ext}

        if state is OrderState.LISTED and nxt is OrderState.ORDER_PAID:
            match = next((o for o in self.sell.get_orders()
                          if o.external_id == order["sell_ext_id"] and o.paid), None)
            if match is None:
                return {"noop": True}          # 等买家付款
            return {"buyer_paid_cny": match.total_cny}

        if state is OrderState.ORDER_PAID and nxt is OrderState.FUNDS_VERIFIED:
            if not check_funds(dict(order)).allowed:
                return {"noop": True}          # 防御: 平台说已付但账上未确认
            return {}

        if state is OrderState.FUNDS_VERIFIED and nxt is OrderState.SOURCING:
            quotes = self.buy.search(sku, qty)
            if not quotes:
                raise AdapterError("无货源报价")
            best = min(quotes, key=lambda q: q.unit_cny)
            return {"buy_price_cny": best.unit_cny, "buy_source_url": best.url}

        if state is OrderState.SOURCING and nxt is OrderState.PURCHASED:
            ref = self.buy.place_order(sku, qty, address="")
            return {"buy_ext_id": ref.ref_id}

        if state is OrderState.PURCHASED and nxt is OrderState.PAID:
            paid_today = db.sum_paid_cny_on(conn, _dt.date.today().isoformat())
            decision = check_pay(dict(order), self.cfg, paid_today)
            if not decision.allowed:
                raise AdapterError("; ".join(decision.reasons))
            self.buy.pay(OrderRef(ref_id=order["buy_ext_id"] or ""))
            return {}

        if state is OrderState.PAID and nxt is OrderState.WAREHOUSED:
            st = self.buy.track(OrderRef(ref_id=order["buy_ext_id"] or ""))
            if st.state != "delivered":
                return {"noop": True}          # 货还在路上
            return {"tracking": st.tracking}

        if state is OrderState.WAREHOUSED and nxt is OrderState.AWAITING_FLIGHT:
            return {}                          # 人肉: 飞带出境 / 飞取带回

        if state is OrderState.AWAITING_FLIGHT and nxt is OrderState.SHIPPED:
            self.sell.mark_shipped(order["sell_ext_id"] or "", order["tracking"] or "")
            return {}

        if state is OrderState.SHIPPED and nxt is OrderState.COMPLETED:
            return {}

        raise AdapterError(f"no transition implemented for {state.value} → {nxt.value}")
