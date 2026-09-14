import datetime as dt
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from arb import sourcing


def evidence(**changes):
    observed = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    result = {
        'id': 'ev-1',
        'kind': 'sold',
        'channel': '得物',
        'amount_cny': 900,
        'amount_basis': 'net',
        'fees_cny': None,
        'observed_at': observed.isoformat(),
        'source_ref': '得物卖家端，同货号同尺码成交记录',
        'source_url': 'https://example.com/evidence',
        'note': '',
        'code': 'SKU-1',
        'color': '黑',
        'size': '27 cm',
    }
    result.update(changes)
    return result


def evidence_item(**quote_changes):
    quote = {
        'buy_jpy': 10000,
        'fx': 0.05,
        'extra_cny': 100,
        'target_profit': 100,
        'units': 1,
        'evidence_records': [evidence()],
    }
    quote.update(quote_changes)
    return {
        'name': '证据测试商品',
        'code': 'SKU-1',
        'color': '黑',
        'size': '27 cm',
        'channel': '得物',
        'quote': quote,
    }

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


def test_structured_evidence_persists_and_derives_legacy_fields(client):
    response = client.post('/api/sourcing', json=evidence_item())
    assert response.status_code == 200
    item = response.json()
    assert item['quote']['net_cny'] == 900
    assert item['quote']['evidence_kind'] == 'sold'
    assert item['quote']['evidence'] == '得物卖家端，同货号同尺码成交记录'
    assert item['quote']['evidence_records'][0]['source_url'] == 'https://example.com/evidence'
    stored = next(x for x in client.get('/api/sourcing').json() if x['id'] == item['id'])
    assert stored['quote']['evidence_records'] == item['quote']['evidence_records']


def test_gross_evidence_subtracts_fees_and_uses_lowest_valid_net(client):
    item = evidence_item(evidence_records=[
        evidence(id='ev-gross', amount_cny=1000, amount_basis='gross', fees_cny=80),
        evidence(id='ev-offer', kind='offer', amount_cny=880, source_ref='更低的真实买家报价'),
    ])
    response = client.post('/api/sourcing', json=item)
    assert response.status_code == 200
    assert response.json()['quote']['net_cny'] == 880
    assert response.json()['quote']['evidence_kind'] == 'offer'


@pytest.mark.parametrize('change', [
    {'kind': 'ask'},
    {'channel': '闲鱼'},
    {'code': 'OTHER'},
    {'color': '白'},
    {'size': '28 cm'},
    {'observed_at': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=73)).isoformat()},
    {'observed_at': (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()},
])
def test_non_actionable_evidence_does_not_derive_exit_price(client, change):
    item = evidence_item(evidence_records=[evidence(**change)], net_cny=999,
                         evidence_kind='sold', evidence_at=dt.date.today().isoformat(), evidence='旧手填依据')
    response = client.post('/api/sourcing', json=item)
    assert response.status_code == 200
    quote = response.json()['quote']
    assert quote['net_cny'] is None
    assert quote['evidence_kind'] == 'unknown'
    assert quote['evidence_at'] is None
    assert quote['evidence'] == ''


def test_legacy_manual_exit_fields_no_longer_qualify(client):
    item = evidence_item(evidence_records=[], net_cny=999, evidence_kind='sold',
                         evidence_at=dt.date.today().isoformat(), evidence='旧手填依据')
    response = client.post('/api/sourcing', json=item)
    assert response.status_code == 200
    assert response.json()['quote']['net_cny'] is None


def test_list_revalidates_evidence_that_expired_after_write(client):
    response = client.post('/api/sourcing', json=evidence_item())
    assert response.status_code == 200
    item = response.json()
    conn = sourcing.connection()
    try:
        payload = json.loads(conn.execute(
            'SELECT payload FROM sourcing_watchlist WHERE id = ?', (item['id'],)
        ).fetchone()['payload'])
        payload['quote']['evidence_records'][0]['observed_at'] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=73)
        ).isoformat()
        # Simulate time passing without another user edit: legacy derived fields
        # remain in storage until the API read validates the evidence again.
        with conn:
            conn.execute('UPDATE sourcing_watchlist SET payload = ? WHERE id = ?',
                         (json.dumps(payload), item['id']))
    finally:
        conn.close()
    refreshed = next(x for x in client.get('/api/sourcing').json() if x['id'] == item['id'])
    assert refreshed['quote']['net_cny'] is None
    assert refreshed['quote']['evidence_kind'] == 'unknown'


@pytest.mark.parametrize('records', [
    [evidence(), evidence()],
    [evidence(observed_at='2026-09-14T10:00:00')],
    [evidence(source_url='javascript:alert(1)')],
    [evidence(source_ref='   ')],
    [evidence(amount_basis='gross', fees_cny=None)],
    [evidence(amount_basis='gross', fees_cny=900)],
])
def test_invalid_structured_evidence_rejected(client, records):
    assert client.post('/api/sourcing', json=evidence_item(evidence_records=records)).status_code == 422

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
