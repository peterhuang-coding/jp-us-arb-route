# jp-us-arb-route — CN/JP 跨境代购决策引擎

## v3.5 启动

```bash
cd /Volumes/SanDisk2TB/jp-us-arb-route
uvicorn arb.web_api:app --host 127.0.0.1 --port 8765
open http://127.0.0.1:8765/
```

## v3.5 新 API

| Endpoint | Method | 说明 |
|---|---|---|
| `/api/inventory` | GET/POST | 库存 CRUD |
| `/api/inventory/{id}` | PATCH/DELETE | 单项编辑 |
| `/api/inventory/summary` | GET | 按 location 聚合 |
| `/api/orders` | GET | 全部/待处理 订单 |
| `/api/orders/{sku}` | POST | 设置状态 |
| `/api/trips` | GET/POST | 行程 CRUD |
| `/api/trips/{id}` | GET/PATCH/DELETE | 单行程 |
| `/api/trips/{id}/items` | POST | 加 item |
| `/api/quota` | GET | ¥5,000 额度汇总 |
| `/api/quota-window` | POST | 记录入境额度 |
| `/api/alerts` | GET | 价格报警 |

## SPA 区域

1. **simple-section**:今日买什么(看 / 拆 / 不买)
2. **inventory-section**:库存管理(哥们仓 + 在途 + 已上架)
3. **trip-section**:行程规划(大阪 / 东京 / 京都)
