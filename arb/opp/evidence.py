"""证据 8 分类 + 旧 price_type → 新分类映射 (PRD §4.1, 总控交叉复核).

8 类:
- official_event: 官方事件/发售抽签 (供给侧事件)
- retail:  采购价/官方零售/免税等可验证供给
- bid:     买盘 (退出市场有人出价求购)
- buyback: 回收价/寄售闪购价 (平台/门店官方回收报价)
- sold:    历史成交 (可信成交价)
- ask:     卖家挂单/挂牌/标价 (仅作锚点, 不得直接作为预计收入)
- heat:    热度/需求信号 (只算需求, 永远不作收入)
- rumor:   私域传闻/聊天线索 (仅待核验, 不计入门槛)

旧 evidence_log.price_type 混中英 8 种, 映射规则:
  tax-free / retail                → retail
  self-use-baseline (buy 侧)       → retail  (中免/日上/天猫 官方零售基线)
  self-use-baseline (sell 侧)      → ask     (朋友圈/论坛 挂价参考, risk §②)
  成交                              → sold
  挂单 / 挂牌 / 标价                → ask
  recycle                          → buyback (爱回收等回收报价)
  未知类型                          → ask     (保守: 挂单类, 绝不算可执行退出)
competitor_prices (amazon_jp/rakuten/yahoo/mercari 快照) → ask / buy 侧.
official_event / bid / heat / rumor 无历史源, 属预期缺口 (阶段1 补).

双币口径: evidence 行同时存 price_cny (报告币) + original_amount/currency
+ fx_rate 快照; 抓取时换算, 之后不做事后汇率重算.
"""
from __future__ import annotations

import datetime as _dt
from enum import Enum
from typing import Optional


class EvidenceKind(str, Enum):
    OFFICIAL_EVENT = "official_event"
    RETAIL = "retail"
    BID = "bid"
    BUYBACK = "buyback"
    SOLD = "sold"
    ASK = "ask"
    HEAT = "heat"
    RUMOR = "rumor"


ALL_KINDS: tuple[EvidenceKind, ...] = tuple(EvidenceKind)

# 可执行退出证据 (可作收入依据): 只有这些能支撑 ready 门槛/预计收入.
EXECUTABLE_EXIT_KINDS: frozenset[EvidenceKind] = frozenset(
    {EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD}
)

# qualified 门槛认可的退出/需求信号 (ask 仅锚点不计; rumor 待核验不计).
QUALIFIED_SIGNAL_KINDS: frozenset[EvidenceKind] = frozenset(
    {EvidenceKind.BID, EvidenceKind.BUYBACK, EvidenceKind.SOLD, EvidenceKind.HEAT}
)

# 供给侧证据 (官方事件 或 可验证零售供给).
SUPPLY_KINDS: frozenset[EvidenceKind] = frozenset(
    {EvidenceKind.OFFICIAL_EVENT, EvidenceKind.RETAIL}
)

# exit 类证据有效期 (PRD §5.2/总控复核④): 72 小时后过期, ready 退回待验证.
EXIT_EVIDENCE_TTL_HOURS = 72

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
    """启发式来源分级: 'official' | 'private' | 'marketplace'."""
    text = f"{channel or ''} {platform or ''}".lower()
    if any(m in text for m in _PRIVATE_MARKERS):
        return "private"
    if any(m in text for m in _OFFICIAL_MARKERS):
        return "official"
    return "marketplace"


def normalize_observed_at(observed_at: str) -> tuple[str, float]:
    """把旧 observed_at 归一为 ISO8601 完整时间戳, 返回 (iso_ts, confidence).

    - 'YYYY-MM' (月份粒度) → 当月 1 日 00:00, 置信度降到 0.6.
    - 'YYYY-MM-DD' / 完整 ISO → 归一为 'YYYY-MM-DDTHH:MM[:SS]'.
    """
    s = (observed_at or "").strip()
    if len(s) == 7 and s[4] == "-":  # YYYY-MM
        return f"{s}-01T00:00:00", MONTH_GRANULARITY_CONFIDENCE
    if len(s) == 10 and s[4] == "-" and s[7] == "-":  # YYYY-MM-DD
        return f"{s}T00:00:00", SNAPSHOT_CONFIDENCE
    return s.replace(" ", "T"), SNAPSHOT_CONFIDENCE


def _parse_ts(ts: str) -> Optional[_dt.datetime]:
    s = (ts or "").strip().replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def expiry_for(observed_at: str,
               ttl_hours: int = EXIT_EVIDENCE_TTL_HOURS) -> Optional[str]:
    """exit 类证据过期时间 = observed_at + ttl (默认 72h). 无法解析返回 None."""
    ts = _parse_ts(observed_at)
    if ts is None:
        return None
    return (ts + _dt.timedelta(hours=ttl_hours)).strftime("%Y-%m-%dT%H:%M:%S")


def is_expired(expires_at: Optional[str],
               as_of: Optional[_dt.datetime] = None) -> bool:
    """expires_at 早于 as_of (默认现在) → True. 无 expires_at → 不过期."""
    if not expires_at:
        return False
    exp = _parse_ts(expires_at)
    if exp is None:
        return False
    return exp < (as_of or _dt.datetime.now())
