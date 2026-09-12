import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from arb import day_plans, sourcing

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr('arb.db.DB_PATH',tmp_path/'plans.sqlite')
    app=FastAPI();app.include_router(day_plans.router);app.include_router(sourcing.router)
    return TestClient(app)

def sample():
    return {'date':'2026-10-02','start':{'id':'base','name':'东京站','lat':35.681,'lng':139.767},'end':{'id':'end','name':'东京站','lat':35.681,'lng':139.767},'extra_cny':0,'records':[]}

def test_day_plan_persists_and_days_are_separate(client):
    assert client.get('/api/day-plans').json()==[]
    day=sample();day['records']=[{'item_id':'x','name':'商品快照','color':'黑色','size':'27','status':'bought','units':1,'cost_cny':200,'expected_net_cny':300}]
    assert client.put('/api/day-plans/2026-10-02',json=day).status_code==200
    day['date']='2026-10-03';day['records']=[]
    assert client.put('/api/day-plans/2026-10-03',json=day).status_code==200
    result=client.get('/api/day-plans').json();assert len(result)==2
    assert result[0]['records'][0]['cost_cny']==200
    assert result[0]['records'][0]['actual_net_cny'] is None
    assert result[0]['records'][0]['color']=='黑色'
    assert result[0]['records'][0]['size']=='27'

@pytest.mark.parametrize('change',[{'start_time':'25:00'},{'end_time':'09:00'},{'extra_cny':-1},{'limit_cny':10001},{'start':{'id':'x','name':'x','lat':91,'lng':139}}, {'records':[{'item_id':'x','status':'bought','units':0,'cost_cny':100}]}, {'records':[{'item_id':'x','status':'bought','units':1,'cost_cny':100}]*2}])
def test_invalid_plans_rejected(client,change):
    day=sample();day.update(change);assert client.put('/api/day-plans/2026-10-02',json=day).status_code==422

def test_url_date_must_match_body(client):
    assert client.put('/api/day-plans/2026-10-03',json=sample()).status_code==422

def test_visit_roundtrip_and_naive_release_rejected(client):
    item=client.get('/api/sourcing').json()[0]
    item['visit']={'mode':'online','duration_min':10,'release_at':'2026-10-02T10:00:30+09:00','release_source':'https://example.com/event'}
    assert client.put('/api/sourcing/'+item['id'],json=item).status_code==200
    item['visit']['release_at']='2026-10-02T10:00:30'
    assert client.put('/api/sourcing/'+item['id'],json=item).status_code==422

def test_stale_tab_cannot_overwrite_saved_purchases(client):
    original=sample()
    saved=client.put('/api/day-plans/2026-10-02',json=original).json()
    saved['records']=[{'item_id':'x','status':'bought','units':1,'cost_cny':200}]
    assert client.put('/api/day-plans/2026-10-02',json=saved).status_code==200
    assert client.put('/api/day-plans/2026-10-02',json=saved).status_code==409
    assert client.get('/api/day-plans').json()[0]['records'][0]['cost_cny']==200
