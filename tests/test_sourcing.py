from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from arb import sourcing

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr('arb.db.DB_PATH', tmp_path / 'sourcing.sqlite')
    app = FastAPI()
    app.include_router(sourcing.router)
    return TestClient(app)

def test_seed_has_no_fabricated_sales_or_purchase_orders(client):
    items = client.get('/api/sourcing').json()
    assert len(items) == 3
    assert all(x['quote']['net_cny'] is None and not x['selected'] for x in items)
    assert all(x['source_url'].startswith('https://') for x in items)
    assert any(x['stock_note'] == '官网显示售罄；门店库存待核' for x in items)

def test_update_persists_without_reseeding(client):
    item = client.get('/api/sourcing').json()[0]
    item['size'] = '27 cm'
    item['quote']['buy_jpy'] = 14000
    r = client.put('/api/sourcing/' + item['id'], json=item)
    assert r.status_code == 200
    result = next(x for x in client.get('/api/sourcing').json() if x['id'] == item['id'])
    assert result['size'] == '27 cm'
    assert result['quote']['buy_jpy'] == 14000

def test_add_hot_item_and_archive(client):
    r = client.post('/api/sourcing', json={'name':'联名测试商品','pool':'hot','source_url':'https://example.com/item'})
    assert r.status_code == 200
    item = r.json()
    assert item['quote']['net_cny'] is None
    item['archived'] = True
    assert client.put('/api/sourcing/' + item['id'], json=item).status_code == 200
    assert next(x for x in client.get('/api/sourcing').json() if x['id'] == item['id'])['archived']

@pytest.mark.parametrize('payload', [
    {'name':'测试','source_url':'javascript:alert(1)'},
    {'name':'测试','quote':{'buy_jpy':-1}},
    {'name':'测试','quote':{'units':0}},
    {'name':'测试','quote':{'fx':0}},
    {'name':'测试','pool':'unknown'},
])
def test_invalid_data_rejected(client, payload):
    assert client.post('/api/sourcing', json=payload).status_code == 422

def test_missing_record_does_not_create_on_update(client):
    assert client.put('/api/sourcing/missing', json={'name':'测试'}).status_code == 404

def test_auction_details_persist(client):
    r=client.post('/api/sourcing',json={'name':'拍卖测试','deal':{'kind':'auction','current_jpy':10000,'increment_jpy':100,'fee_pct':10,'fixed_jpy':200,'observed_at':'2026-10-02T09:55:00+09:00','ends_at':'2026-10-02T12:00:00+09:00'}})
    assert r.status_code==200
    assert r.json()['deal']['fee_pct']==10

@pytest.mark.parametrize('deal',[{'kind':'auction','fee_pct':-1},{'kind':'auction','observed_at':'2026-10-02T10:00:00'},{'kind':'auction','increment_jpy':0}])
def test_invalid_auction_input_rejected(client,deal):
    assert client.post('/api/sourcing',json={'name':'测试','deal':deal}).status_code==422
