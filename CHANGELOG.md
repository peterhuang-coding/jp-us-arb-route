# CHANGELOG

## v3.5 — 库存 + 订单跟踪 + 大阪 trip planner(2026-08-21)

### 新增
- **T5 库存管理**:`inventory` 表 + `/api/inventory` CRUD + summary
- **T4 订单状态**:simple-section 每行加状态 badge,点击循环
- **T9 大阪 trip planner**:trips + trip_items + quota_windows 表
- **T6 价格报警 badge**:`/api/alerts?window_days=7` + ±20% 标签

### 修复
- 静态文件 mount 拦截 /api/* — 移到 web_api.py 文件末尾
- `set_order_status` 别名兼容
- 重复 quota_summary 函数合并

### 数据源
- FastAPI + 本地 SQLite,无外部依赖
- 航班走 flight_price.py(Kiwi/Tequila API)

## v3.4 — 5-Leg 模型

