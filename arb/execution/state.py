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
