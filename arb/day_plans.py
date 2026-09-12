"""Local day plans and actual purchase snapshots. No external orders are placed."""
from __future__ import annotations
import datetime as dt
import json
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from . import db

router=APIRouter(prefix='/api/day-plans',tags=['day-plans'])
class StrictModel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

class Location(StrictModel):
    id:str=Field(...,min_length=1,max_length=200)
    name:str=Field(...,min_length=1,max_length=200)
    lat:float=Field(...,ge=-90,le=90)
    lng:float=Field(...,ge=-180,le=180)
    address:str=Field('',max_length=300)

class Record(StrictModel):
    item_id:str=Field(...,min_length=1,max_length=200)
    name:str=Field('',max_length=200)
    code:str=Field('',max_length=200)
    color:str=Field('',max_length=100)
    size:str=Field('',max_length=100)
    channel:str=Field('',max_length=50)
    status:Literal['bought','skipped']
    units:int=Field(0,ge=0,le=1000)
    cost_cny:float=Field(0,ge=0)
    expected_net_cny:float|None=Field(None,ge=0)
    actual_net_cny:float|None=Field(None,ge=0)
    recorded_at:str=''

    @model_validator(mode='after')
    def valid_purchase(self):
        if self.status=='bought' and (self.units<1 or self.cost_cny<=0):
            raise ValueError('实购需要正数件数和实际全成本')
        if self.status=='skipped' and (self.units or self.cost_cny or self.actual_net_cny is not None or self.expected_net_cny is not None):
            raise ValueError('跳过不产生采购或收入')
        return self

class DayPlan(StrictModel):
    date:dt.date
    start:Location
    end:Location
    start_time:str=Field('10:00',pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    end_time:str=Field('19:00',pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    extra_cny:float|None=Field(None,ge=0)
    limit_cny:float=Field(7000,ge=0,le=10000)
    candidate_ids:list[str]|None=Field(None,max_length=200)
    travel:dict[str,float]=Field(default_factory=dict,max_length=200)
    records:list[Record]=Field(default_factory=list,max_length=1000)
    updated_at:str=''

    @field_validator('travel')
    @classmethod
    def valid_travel(cls,v):
        if any(not 0<=t<=1440 for t in v.values()): raise ValueError('交通时间为 0—1440 分钟')
        return v

    @model_validator(mode='after')
    def valid_day(self):
        if self.end_time<=self.start_time: raise ValueError('结束时间应晚于开始时间')
        ids=[r.item_id for r in self.records]
        if len(ids)!=len(set(ids)): raise ValueError('同日同商品只能有一条累计记录，请修改原记录')
        return self

def connect():
    conn=db.connect()
    with conn: conn.execute('CREATE TABLE IF NOT EXISTS sourcing_day_plans (date TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    return conn

@router.get('')
def list_plans():
    conn=connect()
    try: return [json.loads(r['payload']) for r in conn.execute('SELECT payload FROM sourcing_day_plans ORDER BY date')]
    finally: conn.close()

@router.put('/{date}')
def save_plan(date:dt.date,plan:DayPlan):
    if date!=plan.date: raise HTTPException(422,'日期与保存位置不一致')
    conn=connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT payload FROM sourcing_day_plans WHERE date=?',(date.isoformat(),)).fetchone()
            if row and json.loads(row['payload']).get('updated_at','')!=plan.updated_at:
                raise HTTPException(409,'另一页面已更新该日计划，当前输入未覆盖服务器记录。请重新读取已保存日计划后核对。')
            plan.updated_at=dt.datetime.now(dt.timezone.utc).isoformat()
            conn.execute('INSERT INTO sourcing_day_plans VALUES (?,?) ON CONFLICT(date) DO UPDATE SET payload=excluded.payload',(date.isoformat(),plan.model_dump_json()))
        return plan.model_dump(mode='json')
    finally: conn.close()
