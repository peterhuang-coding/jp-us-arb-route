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
        return [json.loads(row['payload']) for row in conn.execute('SELECT payload FROM sourcing_watchlist ORDER BY rowid')]
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
