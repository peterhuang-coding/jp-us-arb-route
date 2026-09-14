"""Tokyo sourcing watchlist. Quotes are user observations, never executed orders."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import db

router = APIRouter(prefix='/api/sourcing', tags=['sourcing'])

EXIT_EVIDENCE_TTL = dt.timedelta(hours=72)


class SaleEvidence(BaseModel):
    """One observed domestic exit price for an exact product specification."""

    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=100)
    kind: Literal['ask', 'sold', 'offer', 'order']
    channel: Literal['得物', '闲鱼']
    amount_cny: float = Field(..., gt=0)
    amount_basis: Literal['net', 'gross'] = 'net'
    fees_cny: float | None = Field(None, ge=0)
    observed_at: dt.datetime
    source_ref: str = Field(..., min_length=1, max_length=500)
    source_url: str = Field('', max_length=2000)
    note: str = Field('', max_length=1000)
    code: str = Field('', max_length=100)
    color: str = Field('', max_length=100)
    size: str = Field('', max_length=100)

    @field_validator('observed_at')
    @classmethod
    def aware_observed_at(cls, value):
        if value.utcoffset() is None:
            raise ValueError('销售依据时间须注明时区，中国平台为 +08:00')
        return value

    @field_validator('source_url')
    @classmethod
    def safe_source_url(cls, value):
        from urllib.parse import urlparse
        if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
            raise ValueError('销售依据链接须以 http:// 或 https:// 开头')
        return value

    @field_validator('source_ref')
    @classmethod
    def nonblank_source_ref(cls, value):
        if not value.strip():
            raise ValueError('销售依据来源说明不能为空')
        return value.strip()

    @model_validator(mode='after')
    def gross_amount_has_fees(self):
        if self.amount_basis == 'gross' and self.fees_cny is None:
            raise ValueError('销售毛额必须填写平台费、物流等销售侧扣款；确实没有才填 0')
        if self.amount_basis == 'gross' and self.fees_cny is not None and self.fees_cny >= self.amount_cny:
            raise ValueError('销售侧扣款必须小于销售毛额')
        return self

    def net_amount(self) -> float:
        if self.amount_basis == 'net':
            return round(self.amount_cny, 2)
        return round(self.amount_cny - float(self.fees_cny or 0), 2)


class Quote(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    buy_jpy: float | None = Field(None, gt=0)
    fx: float | None = Field(None, gt=0)
    extra_cny: float | None = Field(None, ge=0)
    net_cny: float | None = Field(None, gt=0)
    target_profit: float = Field(100, gt=0)
    units: int = Field(1, ge=1, le=1000)
    checked_at: dt.date | None = None
    evidence_at: dt.date | None = None
    evidence_kind: Literal['unknown', 'ask', 'sold', 'offer', 'order'] = 'unknown'
    evidence: str = Field('', max_length=2000)
    evidence_records: list[SaleEvidence] = Field(default_factory=list, max_length=100)
    stock: bool = False
    delivery: bool = False
    tax: bool = False
    seller: bool = False


class Visit(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    mode: Literal['store', 'online'] = 'store'
    place_id: str = Field('', max_length=200)
    lat: float | None = Field(None, ge=35, le=36.5)
    lng: float | None = Field(None, ge=138.5, le=140.5)
    open_time: str = Field('', pattern=r'^$|^([01]\d|2[0-3]):[0-5]\d$')
    close_time: str = Field('', pattern=r'^$|^([01]\d|2[0-3]):[0-5]\d$')
    duration_min: int = Field(30, ge=1, le=240)
    release_at: dt.datetime | None = None
    release_source: str = Field('', max_length=2000)

    @model_validator(mode='after')
    def release_has_timezone(self):
        if self.release_at and self.release_at.utcoffset() is None:
            raise ValueError('发售时间须注明时区，日本为 +09:00')
        if self.open_time and self.close_time and self.close_time <= self.open_time:
            raise ValueError('闭店时间须晚于开店时间')
        if self.release_source:
            from urllib.parse import urlparse
            if urlparse(self.release_source).scheme not in ('http', 'https') or not urlparse(self.release_source).netloc:
                raise ValueError('发售来源须为 http(s) 链接')
        return self


class Deal(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    kind: Literal['retail', 'auction', 'drop'] = 'retail'
    current_jpy: float | None = Field(None, ge=0)
    increment_jpy: float | None = Field(None, gt=0)
    fee_pct: float | None = Field(None, ge=0, le=100)
    fixed_jpy: float | None = Field(None, ge=0)
    observed_at: dt.datetime | None = None
    ends_at: dt.datetime | None = None

    @field_validator('observed_at', 'ends_at')
    @classmethod
    def aware_time(cls, value):
        if value and value.utcoffset() is None:
            raise ValueError('竞拍时间须注明时区，日本为 +09:00')
        return value


class Item(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    id: str = ''
    name: str = Field(..., min_length=1, max_length=200)
    brand: str = Field('', max_length=100)
    pool: Literal['stable', 'hot'] = 'stable'
    code: str = Field('', max_length=100)
    color: str = Field('', max_length=100)
    size: str = Field('', max_length=100)
    source_name: str = Field('', max_length=150)
    source_url: str = Field('', max_length=2000)
    store_url: str = Field('', max_length=2000)
    address: str = Field('', max_length=300)
    image_url: str = Field('', max_length=2000)
    reference_jpy: float | None = Field(None, gt=0)
    reference_at: dt.date | None = None
    stock_note: str = Field('库存待核', max_length=300)
    reason: str = Field('', max_length=1000)
    channel: Literal['得物', '闲鱼'] = '得物'
    selected: bool = False
    archived: bool = False
    quote: Quote = Field(default_factory=Quote)
    visit: Visit = Field(default_factory=Visit)
    deal: Deal = Field(default_factory=Deal)
    updated_at: str = ''

    @field_validator('source_url', 'store_url', 'image_url')
    @classmethod
    def safe_url(cls, value):
        from urllib.parse import urlparse
        if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
            raise ValueError('链接须以 http:// 或 https:// 开头')
        return value

    @field_validator('name')
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError('请填写商品名')
        return value.strip()

    @model_validator(mode='after')
    def derive_exit_price_from_evidence(self):
        """Make traceable evidence authoritative over the legacy manual net field."""
        seen: set[str] = set()
        for evidence in self.quote.evidence_records:
            if evidence.id in seen:
                raise ValueError('销售依据 id 不能重复')
            seen.add(evidence.id)

        now = dt.datetime.now(dt.timezone.utc)
        actionable: list[SaleEvidence] = []
        for evidence in self.quote.evidence_records:
            exact_spec = all(
                getattr(evidence, key).strip().lower() == getattr(self, key).strip().lower()
                and bool(getattr(self, key).strip())
                for key in ('code', 'color', 'size')
            )
            age = now - evidence.observed_at.astimezone(dt.timezone.utc)
            if (
                exact_spec
                and evidence.channel == self.channel
                and evidence.kind in {'sold', 'offer', 'order'}
                and dt.timedelta(0) <= age <= EXIT_EVIDENCE_TTL
            ):
                actionable.append(evidence)

        if actionable:
            selected = min(actionable, key=lambda evidence: evidence.net_amount())
            self.quote.net_cny = selected.net_amount()
            self.quote.evidence_kind = selected.kind
            self.quote.evidence_at = selected.observed_at.date()
            self.quote.evidence = selected.source_ref
        else:
            # Legacy free-text evidence remains visible in stored JSON, but it cannot
            # silently qualify a new purchase decision without a traceable record.
            self.quote.net_cny = None
            self.quote.evidence_kind = 'unknown'
            self.quote.evidence_at = None
            self.quote.evidence = ''
            self.selected = False
        return self


def connection():
    conn = db.connect()
    try:
        # Seed once, only when introducing the table. Existing edits are never overwritten.
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sourcing_watchlist'").fetchone()
            if not exists:
                conn.execute('CREATE TABLE sourcing_watchlist (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                seed = json.loads((Path(__file__).resolve().parent.parent / 'web' / 'sourcing-seed.json').read_text())
                for raw in seed:
                    item = Item(**raw)
                    conn.execute('INSERT INTO sourcing_watchlist VALUES (?, ?)', (item.id, item.model_dump_json()))
        return conn
    except Exception:
        conn.close()
        raise


@router.get('')
def list_items():
    conn = connection()
    try:
        # Revalidate on every read so evidence that has naturally expired cannot
        # leave a stale derived net amount in API responses.
        return [Item(**json.loads(row['payload'])).model_dump(mode='json')
                for row in conn.execute('SELECT payload FROM sourcing_watchlist ORDER BY rowid')]
    finally:
        conn.close()


@router.post('')
def create_item(item: Item):
    item.id = uuid4().hex
    item.selected = False
    return save_item(item, create=True)


@router.put('/{item_id}')
def update_item(item_id: str, item: Item):
    item.id = item_id
    return save_item(item)


def save_item(item: Item, create=False):
    item.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    conn = connection()
    try:
        with conn:
            if create:
                conn.execute('INSERT INTO sourcing_watchlist VALUES (?, ?)', (item.id, item.model_dump_json()))
            else:
                cur = conn.execute('UPDATE sourcing_watchlist SET payload = ? WHERE id = ?', (item.model_dump_json(), item.id))
                if cur.rowcount == 0:
                    raise HTTPException(404, '观察项不存在，请刷新列表')
        return item.model_dump(mode='json')
    finally:
        conn.close()
