"""商机评分与推荐(分析环核心算法)。

Phase 1 stub:输入固定价 + 规则评分,输出 score 0-100 + 🟢/🟡/🔴 等级。
Phase 2 (Day 8-14):接 arb.scrapers 真价,替换 stub 输入。
Phase 3 (Day 22-30):learned_weights 训历史成交权重。
"""
from .score_sku import score_sku, classify, SCORE_TABLE
from .recommend import recommend_top_n

__all__ = ["score_sku", "classify", "SCORE_TABLE", "recommend_top_n"]