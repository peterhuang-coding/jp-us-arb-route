"""Phase 0 Opportunity model: 统一机会对象 (PRD jp2bj 阶段0 口径统一).

子模块:
- state.py:    11 态状态机 + 合法转移 + qualified/ready 证据门槛
- evidence.py: 8 类证据枚举 + 旧 price_type 映射 + 规格归一规则
- finance.py:  统一 CNY 净利/资金占用口径 (缺数据留 NULL, 不臆造)
- sync.py:     legacy 表 → opp 新表的状态派生 (纯读)
- backfill.py: 幂等回填编排 (默认 dry-run, 显式 --apply)
- api.py:      FastAPI APIRouter /api/opp/* (只读)
"""
