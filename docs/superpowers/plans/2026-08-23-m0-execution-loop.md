# M0 执行环（execution loop）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 jp-us-arb-route 现有代码库上新增 `arb/execution/` 执行环：订单状态机 + 统一适配器接口（dry-run 桩）+ 限额守卫 + 异常推送，CLI 一键跑通 🅳/🅴 两条腿的全链路 dry-run。

**Architecture:** 复用现有 `arb.db`（新表 `execution_orders` 挂进 SCHEMA）与 CLI 子命令模式。流水线 `Pipeline.tick()` 每次推进一个状态；平台操作全部走注入的适配器（M0 只提供 dry-run 桩，真实适配器 M1–M3 插入）；异常统一转 `awaiting_human` 并推送；等待型条件原地不动（noop）。

**Tech Stack:** Python 3.12 + stdlib（sqlite3 / urllib / dataclasses），无新增依赖。pytest（现有 327 测试 + 本计划约 27 个新测试）。

**Spec:** `docs/superpowers/specs/2026-08-23-automated-ecommerce-pipeline-design.md` §4–§10，M0 里程碑。

**M0 明确不做（后续里程碑）**：真实平台适配器（M1–M3）、采购价漂移 >15% 检查（M1）、重试 3 次退避 1 小时（M1）、密钥进 macOS Keychain（M1，M0 用环境变量 PUSHPLUS_TOKEN）、禁售清单前置过滤（M1+，在「SKU 池 → 订单路由」环节实现；M0 订单全部人工 seed，无路由环节）、SPA execution-section 与 /api/execution（M2+）、AWAITING_FLIGHT 与行程表联动的人肉确认门槛（M4，M0 dry-run 直接推进）、repricer（M4）。

**提交**：全部 commit 落在当前分支 `pm-loop/20260726-103909-jp-us-arb-route-55490`（无 remote，不 push）。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `arb/execution/__init__.py` | 包导出（Pipeline / OrderState） |
| `arb/execution/state.py` | OrderState 枚举 + NEXT_STATE 转移表 + 展示标签 |
| `arb/execution/adapters/__init__.py` | 适配器包导出 |
| `arb/execution/adapters/base.py` | SellAdapter / BuyAdapter 协议 + Quote/PlatformOrder/OrderRef/ShipmentStatus + AdapterError |
| `arb/execution/adapters/dryrun.py` | DryRunSellAdapter / DryRunBuyAdapter 内存桩 |
| `arb/execution/payguard.py` | PayConfig + check_funds + check_pay（纯函数） |
| `arb/execution/notify.py` | Notifier 协议 + NullNotifier + PushPlusNotifier |
| `arb/execution/pipeline.py` | Pipeline.tick / run_all + 各转移实现 |
| `arb/db.py`（改） | SCHEMA 加 `execution_orders` 表 + CRUD 助手 |
| `arb/cli.py`（改） | `execution demo` / `execution list` 子命令 |
| `tests/test_execution_state.py` | 状态机测试 |
| `tests/test_execution_db.py` | 表 CRUD 测试 |
| `tests/test_execution_adapters.py` | dry-run 适配器测试 |
| `tests/test_execution_payguard.py` | 限额守卫测试 |
| `tests/test_execution_notify.py` | 推送测试（拦截 urllib） |
| `tests/test_execution_pipeline.py` | 流水线全链路/等待/异常测试 |
| `tests/test_execution_cli.py` | CLI 子进程 smoke 测试 |

---

### Task 1: 状态机核心 `arb/execution/state.py`

**Files:**
- Create: `arb/execution/__init__.py`
- Create: `arb/execution/state.py`
- Test: `tests/test_execution_state.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_state.py`：

```python
"""M0 状态机核心测试."""
from arb.execution.state import NEXT_STATE, OrderState


def test_next_state_chain_is_linear():
    states = [OrderState.CREATED, OrderState.LISTED, OrderState.ORDER_PAID,
              OrderState.FUNDS_VERIFIED, OrderState.SOURCING, OrderState.PURCHASED,
              OrderState.PAID, OrderState.WAREHOUSED, OrderState.AWAITING_FLIGHT,
              OrderState.SHIPPED, OrderState.COMPLETED]
    for cur, nxt in zip(states, states[1:]):
        assert NEXT_STATE[cur] is nxt


def test_terminal_states_have_no_next():
    for s in (OrderState.COMPLETED, OrderState.AWAITING_HUMAN, OrderState.CANCELLED):
        assert NEXT_STATE[s] is None


def test_all_states_covered_by_table():
    assert set(NEXT_STATE) == set(OrderState)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_state.py -q`
Expected: FAIL（`ModuleNotFoundError: arb.execution`）

- [ ] **Step 3: 写实现**

创建 `arb/execution/__init__.py`：

```python
"""执行环 (M0): 全自动套利流水线的订单状态机 + 平台适配器 + 限额守卫 + 推送."""

from .pipeline import Pipeline  # noqa: F401  (Task 6 就位前注释此行即可)
```

> 注：Task 1 阶段 `pipeline` 还不存在，把 import 行注释掉（`# from .pipeline import Pipeline`），Task 6 完成后取消注释。若执行者愿意，也可在 Task 6 再创建本文件——但本计划按此顺序，Task 6 Step 会提醒取消注释。

创建 `arb/execution/state.py`：

```python
"""执行环状态机核心: OrderState 枚举 + 自动转移表.

M0 — 只定义状态与转移, 不含任何平台逻辑. 转移执行见 pipeline.py.
"""
from __future__ import annotations

from enum import Enum


class OrderState(str, Enum):
    CREATED = "created"
    LISTED = "listed"                  # 已上架销售平台
    ORDER_PAID = "order_paid"          # 买家已付款(预收到账)
    FUNDS_VERIFIED = "funds_verified"  # 预收校验通过
    SOURCING = "sourcing"              # 采购比价中
    PURCHASED = "purchased"            # 已下采购单(可能停在待付款)
    PAID = "paid"                      # 采购款已付(限额内自动付)
    WAREHOUSED = "warehoused"          # 货物入仓: 🅳国内仓 / 🅴哥们仓
    AWAITING_FLIGHT = "awaiting_flight"  # 人肉环节: 飞带出境 / 飞取带回
    SHIPPED = "shipped"                # 已向买家发货
    COMPLETED = "completed"            # 终态
    AWAITING_HUMAN = "awaiting_human"  # 异常: 等人工裁决
    CANCELLED = "cancelled"            # 终态: 已取消


# 状态 → 下一个自动状态. None 表示终态或需人工, tick 不再推进.
NEXT_STATE: dict[OrderState, OrderState | None] = {
    OrderState.CREATED: OrderState.LISTED,
    OrderState.LISTED: OrderState.ORDER_PAID,
    OrderState.ORDER_PAID: OrderState.FUNDS_VERIFIED,
    OrderState.FUNDS_VERIFIED: OrderState.SOURCING,
    OrderState.SOURCING: OrderState.PURCHASED,
    OrderState.PURCHASED: OrderState.PAID,
    OrderState.PAID: OrderState.WAREHOUSED,
    OrderState.WAREHOUSED: OrderState.AWAITING_FLIGHT,
    OrderState.AWAITING_FLIGHT: OrderState.SHIPPED,
    OrderState.SHIPPED: OrderState.COMPLETED,
    OrderState.COMPLETED: None,
    OrderState.AWAITING_HUMAN: None,
    OrderState.CANCELLED: None,
}

# WAREHOUSED 状态的展示名按 leg 区分.
WAREHOUSE_LABELS = {"D": "国内仓", "E": "哥们仓"}

STATE_LABELS: dict[OrderState, str] = {
    OrderState.CREATED: "已创建",
    OrderState.LISTED: "已上架",
    OrderState.ORDER_PAID: "买家已付款",
    OrderState.FUNDS_VERIFIED: "预收已验证",
    OrderState.SOURCING: "采购比价",
    OrderState.PURCHASED: "已下采购单",
    OrderState.PAID: "已付采购款",
    OrderState.WAREHOUSED: "已入仓",
    OrderState.AWAITING_FLIGHT: "待飞行",
    OrderState.SHIPPED: "已发货",
    OrderState.COMPLETED: "完成",
    OrderState.AWAITING_HUMAN: "待人工",
    OrderState.CANCELLED: "已取消",
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_execution_state.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add arb/execution/__init__.py arb/execution/state.py tests/test_execution_state.py
git commit -m "feat(execution): M0 状态机核心 — OrderState + NEXT_STATE 转移表"
```

---

### Task 2: `execution_orders` 表 + CRUD（`arb/db.py`）

**Files:**
- Modify: `arb/db.py`（SCHEMA 末尾追加建表语句；文件末尾追加 CRUD 助手）
- Test: `tests/test_execution_db.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_db.py`：

```python
"""M0 execution_orders 表 CRUD 测试."""
from datetime import date

import pytest

from arb import db


@pytest.fixture
def conn():
    c = db.connect_memory()
    yield c
    c.close()


def test_create_and_get_roundtrip(conn):
    oid = db.create_execution_order(conn, dict(
        sku="JP-SKII-FT230", leg="D", sell_price_cny=950.0))
    assert oid > 0
    row = db.get_execution_order(conn, oid)
    assert row["sku"] == "JP-SKII-FT230"
    assert row["state"] == "created"
    assert row["leg"] == "D"


def test_update_patches_fields_and_bumps_updated_at(conn):
    oid = db.create_execution_order(conn, dict(sku="JP-SKII-FT230", leg="D"))
    before = db.get_execution_order(conn, oid)["updated_at"]
    db.update_execution_order(conn, oid, state="listed",
                              sell_ext_id="dry-sell-JP-SKII-FT230")
    row = db.get_execution_order(conn, oid)
    assert row["state"] == "listed"
    assert row["sell_ext_id"] == "dry-sell-JP-SKII-FT230"
    assert row["updated_at"] >= before


def test_list_filters_by_state(conn):
    db.create_execution_order(conn, dict(sku="A", leg="D"))
    oid = db.create_execution_order(conn, dict(sku="B", leg="E"))
    db.update_execution_order(conn, oid, state="completed")
    rows = db.list_execution_orders(conn, state="completed")
    assert [r["sku"] for r in rows] == ["B"]


def test_sum_paid_cny_on_counts_only_paid_orders(conn):
    a = db.create_execution_order(conn, dict(sku="A", leg="D"))
    b = db.create_execution_order(conn, dict(sku="B", leg="E"))
    db.update_execution_order(conn, a, state="paid", buy_price_cny=100.0)
    db.update_execution_order(conn, b, state="purchased", buy_price_cny=999.0)
    assert db.sum_paid_cny_on(conn, date.today().isoformat()) == 100.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_db.py -q`
Expected: FAIL（`no such table: execution_orders`）

- [ ] **Step 3: 写实现**

`arb/db.py` 两处修改。

（a）在 `SCHEMA` 字符串末尾（`quota_windows` 建表语句之后）追加：

```sql
CREATE TABLE IF NOT EXISTS execution_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    leg TEXT NOT NULL DEFAULT 'D',            -- 'D' 电商带过去 | 'E' 哥们仓
    qty INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'created',
    sell_platform TEXT NOT NULL DEFAULT 'dryrun',
    buy_platform TEXT NOT NULL DEFAULT 'dryrun',
    sell_ext_id TEXT,                          -- 销售平台上架后的外部 ID
    buy_ext_id TEXT,                           -- 采购平台下单后的外部 ID
    sell_price_cny REAL NOT NULL DEFAULT 0,    -- 卖给买家的价格
    buy_price_cny REAL,                        -- 采购价(比价后写入)
    ship_cost_cny REAL NOT NULL DEFAULT 0,     -- 运费预估
    buyer_paid_cny REAL NOT NULL DEFAULT 0,    -- 买家已付(预收确认)
    buy_source_url TEXT,                       -- 采购货源链接(比价选中)
    tracking TEXT,                             -- 发货物流单号
    error TEXT,                                -- 最近一次异常信息
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

（b）在 `db.py` 文件末尾（Round 24 returns 助手之后）追加：

```python
# ---------- M0: execution_orders (执行环订单) ----------

def create_execution_order(conn: sqlite3.Connection, row: dict) -> int:
    """Insert one execution order.  Unknown keys are ignored."""
    fields = ("sku", "leg", "qty", "state", "sell_platform", "buy_platform",
              "sell_ext_id", "buy_ext_id", "sell_price_cny", "buy_price_cny",
              "ship_cost_cny", "buyer_paid_cny", "buy_source_url", "tracking", "error")
    values = {k: row[k] for k in fields if k in row}
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(
        f"INSERT INTO execution_orders ({cols}) VALUES ({marks})",
        tuple(values.values()),
    )
    conn.commit()
    return cur.lastrowid


def get_execution_order(conn: sqlite3.Connection, order_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM execution_orders WHERE id = ?", (order_id,)
    ).fetchone()


def update_execution_order(conn: sqlite3.Connection, order_id: int, **fields) -> None:
    """Patch any subset of columns; bumps updated_at."""
    if not fields:
        return
    fields = {**fields, "updated_at": _dt.datetime.now().isoformat(timespec="seconds")}
    assigns = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE execution_orders SET {assigns} WHERE id = ?",
        (*fields.values(), order_id),
    )
    conn.commit()


def list_execution_orders(conn: sqlite3.Connection, state: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM execution_orders"
    params: tuple = ()
    if state is not None:
        sql += " WHERE state = ?"
        params = (state,)
    sql += " ORDER BY id ASC"
    return list(conn.execute(sql, params))


def sum_paid_cny_on(conn: sqlite3.Connection, date_iso: str) -> float:
    """当日已 PAID 订单的采购款累计(限额守卫用)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(buy_price_cny), 0) AS total FROM execution_orders "
        "WHERE state = 'paid' AND date(updated_at) = date(?)",
        (date_iso,),
    ).fetchone()
    return round(float(row["total"]), 2)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_execution_db.py -q`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add arb/db.py tests/test_execution_db.py
git commit -m "feat(execution): M0 execution_orders 表 + CRUD 助手"
```

---

### Task 3: 适配器接口 + dry-run 桩

**Files:**
- Create: `arb/execution/adapters/__init__.py`
- Create: `arb/execution/adapters/base.py`
- Create: `arb/execution/adapters/dryrun.py`
- Test: `tests/test_execution_adapters.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_adapters.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_adapters.py -q`
Expected: FAIL（`ModuleNotFoundError: arb.execution.adapters`）

- [ ] **Step 3: 写实现**

创建 `arb/execution/adapters/__init__.py`：

```python
"""平台适配器: 统一接口 + dry-run 桩. 真实实现 M1-M3."""
```

创建 `arb/execution/adapters/base.py`：

```python
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
```

创建 `arb/execution/adapters/dryrun.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_execution_adapters.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add arb/execution/adapters/ tests/test_execution_adapters.py
git commit -m "feat(execution): M0 适配器统一接口 + dry-run 桩"
```

---

### Task 4: 限额守卫 `arb/execution/payguard.py`

**Files:**
- Create: `arb/execution/payguard.py`
- Test: `tests/test_execution_payguard.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_payguard.py`：

```python
"""M0 限额守卫测试 (spec §7)."""
from arb.execution.payguard import PayConfig, check_funds, check_pay

CFG = PayConfig(per_order_limit_cny=300.0, daily_limit_cny=2000.0)


def order(buy=200.0, ship=30.0, paid=950.0):
    return {"buy_price_cny": buy, "ship_cost_cny": ship, "buyer_paid_cny": paid}


def test_check_funds_blocks_unpaid():
    assert not check_funds(order(paid=0.0)).allowed
    assert check_funds(order()).allowed


def test_check_pay_allows_under_limits():
    assert check_pay(order(), CFG, paid_today_cny=0.0).allowed


def test_check_pay_per_order_boundary_is_inclusive():
    assert check_pay(order(buy=300.0), CFG, paid_today_cny=0.0).allowed


def test_check_pay_blocks_over_per_order_limit():
    d = check_pay(order(buy=300.01), CFG, paid_today_cny=0.0)
    assert not d.allowed and any("单笔" in r for r in d.reasons)


def test_check_pay_daily_boundary_is_inclusive():
    assert check_pay(order(buy=200.0), CFG, paid_today_cny=1800.0).allowed


def test_check_pay_blocks_over_daily_limit():
    d = check_pay(order(buy=200.0), CFG, paid_today_cny=1800.01)
    assert not d.allowed and any("日累计" in r for r in d.reasons)


def test_check_pay_blocks_non_positive_margin():
    d = check_pay(order(buy=300.0, ship=650.0, paid=950.0), CFG, paid_today_cny=0.0)
    assert not d.allowed and any("毛利" in r for r in d.reasons)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_payguard.py -q`
Expected: FAIL（`ModuleNotFoundError: arb.execution.payguard`）

- [ ] **Step 3: 写实现**

创建 `arb/execution/payguard.py`：

```python
"""限额守卫 (spec §7): 自动付款前的检查, 纯函数无 IO.

两个检查点:
- check_funds: FUNDS_VERIFIED 转移前 — 买家付款是否到账(预收优先)
- check_pay:   PURCHASED → PAID 前 — 单笔限额 / 日累计限额 / 毛利为正
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PayConfig:
    """阈值可在 SPA 配置页改; 默认值即 spec §7. 金额单位 CNY."""
    per_order_limit_cny: float = 300.0
    daily_limit_cny: float = 2000.0


@dataclass(frozen=True)
class PayDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


def check_funds(order: dict) -> PayDecision:
    """预收优先: 买家付款必须 > 0 才允许推进采购."""
    buyer_paid = float(order.get("buyer_paid_cny") or 0)
    if buyer_paid <= 0:
        return PayDecision(False, ["买家付款未到账"])
    return PayDecision(True)


def check_pay(order: dict, cfg: PayConfig, paid_today_cny: float) -> PayDecision:
    """付款前检查: 单笔 ≤ 限额; 当日累计 ≤ 限额; 毛利为正(买家付款 − 采购 − 运费 > 0)."""
    reasons: list[str] = []
    buy_price = float(order.get("buy_price_cny") or 0)
    ship = float(order.get("ship_cost_cny") or 0)
    buyer_paid = float(order.get("buyer_paid_cny") or 0)

    if buy_price > cfg.per_order_limit_cny:
        reasons.append(f"单笔 ¥{buy_price:.2f} 超过上限 ¥{cfg.per_order_limit_cny:.2f}")
    if paid_today_cny + buy_price > cfg.daily_limit_cny:
        reasons.append(
            f"日累计 ¥{paid_today_cny:.2f} + ¥{buy_price:.2f} 超过上限 ¥{cfg.daily_limit_cny:.2f}"
        )
    if buyer_paid - buy_price - ship <= 0:
        reasons.append("毛利非正(买家付款 ≤ 采购+运费)")
    return PayDecision(not reasons, reasons)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_execution_payguard.py -q`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add arb/execution/payguard.py tests/test_execution_payguard.py
git commit -m "feat(execution): M0 限额守卫 payguard — check_funds + check_pay"
```

---

### Task 5: 异常推送 `arb/execution/notify.py`

**Files:**
- Create: `arb/execution/notify.py`
- Test: `tests/test_execution_notify.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_notify.py`：

```python
"""M0 推送测试 — PushPlus 用 monkeypatch 拦截 urllib, 不发真实网络请求."""
import json
import urllib.request

from arb.execution.notify import NullNotifier, PushPlusNotifier


def test_null_notifier_does_nothing():
    NullNotifier().send("t", "b")


def test_pushplus_sends_json_with_token(monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    PushPlusNotifier(token="tok123").send("标题", "正文")
    assert captured["url"] == "https://www.pushplus.plus/send"
    assert captured["data"]["token"] == "tok123"
    assert captured["data"]["title"] == "标题"
    assert captured["data"]["content"] == "正文"


def test_pushplus_without_token_skips(monkeypatch, capsys):
    monkeypatch.delenv("PUSHPLUS_TOKEN", raising=False)
    PushPlusNotifier(token=None).send("t", "b")
    assert "未配置" in capsys.readouterr().err
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_notify.py -q`
Expected: FAIL（`ModuleNotFoundError: arb.execution.notify`）

- [ ] **Step 3: 写实现**

创建 `arb/execution/notify.py`：

```python
"""异常推送 (spec §8). 默认微信 PushPlus; 接口抽象, Telegram 预留.

token 来源: PUSHPLUS_TOKEN 环境变量. 未配置时降级为 no-op + stderr 提示.
(真实平台密钥进 macOS Keychain 的改造随 M1 适配器一起做.)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from typing import Protocol, runtime_checkable


@runtime_checkable
class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class NullNotifier:
    """dry-run / 测试用, 不发任何消息."""

    def send(self, title: str, body: str) -> None:
        return None


class PushPlusNotifier:
    """微信 PushPlus 推送. token 显式传入或读 PUSHPLUS_TOKEN."""

    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.environ.get("PUSHPLUS_TOKEN")

    def send(self, title: str, body: str) -> None:
        if not self.token:
            print("[notify] PUSHPLUS_TOKEN 未配置, 跳过推送", file=sys.stderr)
            return None
        payload = json.dumps({
            "token": self.token, "title": title, "content": body, "template": "txt",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://www.pushplus.plus/send",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_execution_notify.py -q`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add arb/execution/notify.py tests/test_execution_notify.py
git commit -m "feat(execution): M0 异常推送 notify — Notifier 协议 + PushPlus/Null"
```

---

### Task 6: 流水线 `arb/execution/pipeline.py`

**Files:**
- Create: `arb/execution/pipeline.py`
- Modify: `arb/execution/__init__.py`（取消 Task 1 里注释掉的 import）
- Test: `tests/test_execution_pipeline.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_pipeline.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_pipeline.py -q`
Expected: FAIL（`ModuleNotFoundError: arb.execution.pipeline`）

- [ ] **Step 3: 写实现**

创建 `arb/execution/pipeline.py`：

```python
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
```

修改 `arb/execution/__init__.py`，取消 Task 1 注释掉的 import：

```python
"""执行环 (M0): 全自动套利流水线的订单状态机 + 平台适配器 + 限额守卫 + 推送."""

from .pipeline import Pipeline  # noqa: F401
from .state import OrderState

__all__ = ["Pipeline", "OrderState"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_execution_pipeline.py -q`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add arb/execution/pipeline.py arb/execution/__init__.py tests/test_execution_pipeline.py
git commit -m "feat(execution): M0 流水线 Pipeline — tick/run_all + 全状态转移"
```

---

### Task 7: CLI `execution demo` / `execution list` + 全量回归

**Files:**
- Modify: `arb/cli.py`（parser + `cmd_execution` + handler 表）
- Test: `tests/test_execution_cli.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_execution_cli.py`：

```python
"""M0 CLI smoke tests — 子进程跑 `arb execution`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(*args, env=None):
    full_env = os.environ.copy()
    if env is not None:
        full_env["ARB_DB_PATH"] = str(env)
    return subprocess.run(
        [sys.executable, "-m", "arb", *args],
        cwd=ROOT, capture_output=True, text=True, env=full_env,
    )


def test_execution_demo_runs_full_chain_in_memory():
    out = _run("execution", "demo")
    assert out.returncode == 0, out.stderr
    assert "completed" in out.stdout
    assert "awaiting_flight" in out.stdout
    assert "order #1" in out.stdout and "order #2" in out.stdout


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    import arb.db as arb_db
    import arb.seed as arb_seed
    conn = arb_db.connect(db_file)
    try:
        arb_seed.seed_all(conn)
    finally:
        conn.close()
    yield db_file


def test_execution_list_json(scratch_db):
    out = _run("execution", "list", "--json", env=scratch_db)
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert isinstance(data, list)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_execution_cli.py -q`
Expected: FAIL（demo: returncode 2 — 未知命令 `execution`）

- [ ] **Step 3: 写实现**

`arb/cli.py` 三处修改。

（a）在 `p_returns` 的 parser 定义之后追加：

```python
    # Round 25 / M0: execution (执行环 dry-run)
    p_exec = sub.add_parser("execution", help="执行环订单流水线 (M0: dry-run)")
    exec_sub = p_exec.add_subparsers(dest="execution_cmd", required=True)
    p_exec_demo = exec_sub.add_parser("demo", help="内存库跑通 🅳/🅴 两条 demo 订单全链路")
    p_exec_list = exec_sub.add_parser("list", help="列出执行环订单(真实库)")
    p_exec_list.add_argument("--json", action="store_true")
```

（b）在 `cmd_returns` 之后追加：

```python
# ---------- Round 25 / M0: cmd_execution ----------

def cmd_execution(args):
    from arb.execution.adapters.dryrun import DryRunBuyAdapter, DryRunSellAdapter
    from arb.execution.notify import NullNotifier
    from arb.execution.payguard import PayConfig
    from arb.execution.pipeline import Pipeline

    sub = args.execution_cmd
    if sub == "demo":
        conn = db.connect_memory()
        try:
            for row in (
                dict(sku="JP-SKII-FT230", leg="D",
                     sell_price_cny=950.0, ship_cost_cny=30.0),
                dict(sku="JP-HUMANMADE-TEE-GRAPHIC", leg="E",
                     sell_price_cny=700.0, ship_cost_cny=20.0),
            ):
                db.create_execution_order(conn, row)
            pipeline = Pipeline(
                sell=DryRunSellAdapter(), buy=DryRunBuyAdapter(),
                notifier=NullNotifier(), cfg=PayConfig(), dry_run=True,
            )
            for result in pipeline.run_all(conn):
                states = [r["state"] for r in result["chain"]]
                print(f"  order #{result['order_id']}: " + " → ".join(states))
            return 0
        finally:
            conn.close()
    if sub == "list":
        conn = db.connect()
        try:
            rows = db.list_execution_orders(conn)
            if args.json:
                print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
            else:
                for r in rows:
                    print(f"  #{r['id']:3d} {r['sku']:25s} leg={r['leg']} "
                          f"{r['state']:16s} sell=¥{r['sell_price_cny']:>7.2f} "
                          f"buy=¥{(r['buy_price_cny'] or 0):>7.2f}")
            return 0
        finally:
            conn.close()
    return 2
```

（c）在 `main()` 的 handler 表里 `"returns": cmd_returns,` 之后加一行：

```python
        "execution": cmd_execution,
```

- [ ] **Step 4: 跑测试确认通过 + 全量回归**

Run: `python3 -m pytest tests/test_execution_cli.py -q`
Expected: 2 passed

Run: `python3 -m pytest -q`
Expected: 327 旧测试 + 26 新测试全绿（约 353 passed，0 failed）

- [ ] **Step 5: 手动验收（M0 验证点）**

Run: `python3 -m arb execution demo`
Expected（顺序固定，两条链结构相同）:

```
  order #1: created → listed → order_paid → funds_verified → sourcing → purchased → paid → warehoused → awaiting_flight → shipped → completed
  order #2: created → listed → order_paid → funds_verified → sourcing → purchased → paid → warehoused → awaiting_flight → shipped → completed
```

零网络请求、零数据库落盘（demo 跑内存库）、零资金流动。

- [ ] **Step 6: 提交**

```bash
git add arb/cli.py tests/test_execution_cli.py
git commit -m "feat(execution): M0 CLI — execution demo/list + 全链路 dry-run 验收"
```

---

## 完成定义（M0 Done）

- [x] `python3 -m pytest -q` 全绿（327 旧 + 29 新 = 356 passed）
- [x] `python3 -m arb execution demo` 输出两条完整状态链到 completed
- [x] 异常路径有测试覆盖：买家未付款等待、超限转 awaiting_human + 推送
- [x] spec §5 状态机、§6 适配器接口、§7 限额守卫、§8 推送、§10 dry-run 均有对应实现与测试
