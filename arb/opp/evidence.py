"""证据 6 分类 + 旧 price_type → 新分类映射 (PRD §4.1, tech 阶段0).

6 类:
- retail:  官方事件/官方零售/免税等可验证供给 (采购价)
- bid:     买盘 (退出市场有人出价求购)
- buyback: 回收价 (平台/门店官方回收报价)
- sold:    历史成交 (可信成交价)
- ask:     卖家挂单/挂牌/标价 (不得直接作为预计收入)
- rumor:   私域传闻/聊天线索 (仅待核验)

旧 evidence_log.price_type 混中英 8 种, 映射规则:
  tax-free / retail                → retail
  self-use-baseline (buy 侧)       → retail  (中免/日上/天猫 官方零售基线)
  self-use-baseline (sell 侧)      → ask     (朋友圈/论坛 挂价参考, risk §②)
  成交                              → sold
  挂单 / 挂牌 / 标价                → ask
  recycle                          → buyback (爱回收等回收报价)
  未知类型                          → ask     (保守: 挂单类, 绝不算可执行退出)
competitor_prices (amazon_jp/rakuten/yahoo/mercari 快照) → ask / buy 侧.
bid / rumor 无历史源, 属预期缺口 (阶段1 补).
"""
from __future__ import annotations

from enum import Enum


class EvidenceKind(str, Enum):
    RETAIL = "retail"
    BID = "bid"
    BUYBACK = "buyback"
    SOLD = "sold"
    ASK = "ask"
    RUMOR = "rumor"


ALL_KINDS: tuple[EvidenceKind, ...] = tuple(EvidenceKind)

# 可执行退出证据: 只有这些能支撑 ready 门槛 / 预计收入.
EXECUTABLE_EXIT_KINDS: frozenset[EvidenceKind] = frozenset(
    {EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD}
)

# 旧 price_type → 新 kind (self-use-baseline 侧别相关, 单独处理).
_LEGACY_MAP: dict[str, EvidenceKind] = {
    "tax-free": EvidenceKind.RETAIL,
    "retail": EvidenceKind.RETAIL,
    "成交": EvidenceKind.SOLD,
    "挂单": EvidenceKind.ASK,
    "挂牌": EvidenceKind.ASK,
    "标价": EvidenceKind.ASK,
    "recycle": EvidenceKind.BUYBACK,
}

# 月份粒度证据 (evidence_log.observed_at 仅 'YYYY-MM') 的置信度降级.
MONTH_GRANULARITY_CONFIDENCE = 0.6
# 每日快照 (competitor_prices.fetched_at 完整时间戳 + URL).
SNAPSHOT_CONFIDENCE = 0.8
DEFAULT_CONFIDENCE = 0.5

# 来源分级关键词.
_OFFICIAL_MARKERS = (
    "免税", "公式", "官方", "自营", "ヨドバシ", "bic camera", "松本清",
    "药妆", "堂吉诃德", "ドンキ", "pokemon center", "usj",
)
_PRIVATE_MARKERS = (
    "朋友圈", "微信", "微博", "论坛", "超话", "私聊", "群", "私域",
)


def classify_price_type(price_type: str | None, side: str = "buy") -> EvidenceKind:
    """旧 evidence_log.price_type → EvidenceKind.

    side: 'buy' | 'sell' —— self-use-baseline 在买侧是官方零售基线
    (retail), 在卖侧是民间挂价参考 (ask, risk §② 明确 self-use=6 属 ask).
    未知类型保守映射为 ask (永远不会被当作可执行退出/官方供给).
    """
    raw = (price_type or "").strip()
    if raw == "self-use-baseline":
        return EvidenceKind.RETAIL if side == "buy" else EvidenceKind.ASK
    kind = _LEGACY_MAP.get(raw) or _LEGACY_MAP.get(raw.lower())
    if kind is not None:
        return kind
    return EvidenceKind.ASK


def source_kind_for(channel: str | None = None, platform: str | None = None) -> str:
    """启发式来源分级: 'official' | 'private' | 'marketplace'.

    供 backfill 填 evidence.source_kind; 仅作元数据, 门槛判定以 kind/side 为准.
    """
    text = f"{channel or ''} {platform or ''}".lower()
    if any(m in text for m in _PRIVATE_MARKERS):
        return "private"
    if any(m in text for m in _OFFICIAL_MARKERS):
        return "official"
    return "marketplace"


def normalize_observed_at(observed_at: str) -> tuple[str, float]:
    """把旧 observed_at 归一为 ISO8601 完整时间戳, 返回 (iso_ts, confidence).

    - 'YYYY-MM' (月份粒度) → 当月 1 日 00:00, 置信度降到 0.6 (tech 风险注:
      月份粒度取月初并降 confidence).
    - 'YYYY-MM-DD' / 完整 ISO → 原样 (日期补 T00:00:00), 置信度不变由调用方定.
    """
    s = (observed_at or "").strip()
    if len(s) == 7 and s[4] == "-":  # YYYY-MM
        return f"{s}-01T00:00:00", MONTH_GRANULARITY_CONFIDENCE
    if len(s) == 10 and s[4] == "-" and s[7] == "-":  # YYYY-MM-DD
        return f"{s}T00:00:00", SNAPSHOT_CONFIDENCE
    # 已是完整时间戳 (competitor_prices.fetched_at 形如 '2026-09-08 12:34:56').
    return s.replace(" ", "T"), SNAPSHOT_CONFIDENCE
