"""Regression: API money/count fields must not coerce bool into numbers."""
import datetime as dt
import pytest
from pydantic import ValidationError
from arb.sourcing import Deal, Item, Quote, SaleEvidence

def aware(hours=0, day=11):
    return (dt.datetime(2026, 3, day, 12, tzinfo=dt.timezone(dt.timedelta(hours=8)))
            + dt.timedelta(hours=hours)).isoformat()

def evidence(**changes):
    data = {
        'id': 'ev-1',
        'kind': 'sold',
        'channel': '得物',
        'amount_cny': 900,
        'amount_basis': 'net',
        'observed_at': aware(-2),
        'source_ref': '同款同码成交记录',
        'code': 'SKU-1',
        'color': '黑',
        'size': '27 cm',
    }
    data.update(changes)
    return data

def item(**changes):
    data = {
        'name': '证据输入商品',
        'code': 'SKU-1',
        'color': '黑',
        'size': '27 cm',
        'channel': '得物',
        'quote': {'evidence_records': [evidence()]},
    }
    data.update(changes)
    return data

@pytest.mark.parametrize(('model', 'field', 'value'), [
    (SaleEvidence, 'amount_cny', True),
    (SaleEvidence, 'fees_cny', True),
    (Quote, 'buy_jpy', True),
    (Quote, 'fx', True),
    (Quote, 'extra_cny', True),
    (Quote, 'net_cny', True),
    (Quote, 'target_profit', True),
    (Quote, 'units', True),
    (Deal, 'current_jpy', True),
    (Deal, 'increment_jpy', True),
    (Deal, 'fee_pct', True),
    (Deal, 'fixed_jpy', True),
    (Item, 'reference_jpy', True),
])
def test_booleans_are_not_coerced_into_money_count_or_percent_fields(model, field, value):
    kwargs = {'name': '测试'} if model is Item else {}
    with pytest.raises(ValidationError):
        if model is SaleEvidence:
            model(**evidence(**{field: value}))
        elif model is Item:
            model(**item(**{field: value}))
        else:
            model(**{field: value, **kwargs})

def test_numeric_strings_and_numeric_defaults_remain_supported():
    record = SaleEvidence(**evidence(amount_cny='900.50', fees_cny='0'))
    assert record.amount_cny == 900.5
    assert record.fees_cny == 0.0

    quote = Quote(buy_jpy='10000', fx='0.05', extra_cny='100', units='2')
    assert (quote.buy_jpy, quote.fx, quote.extra_cny, quote.units, quote.target_profit) == (
        10000.0, 0.05, 100.0, 2, 100)

    deal = Deal(current_jpy='0', fixed_jpy='200')
    assert deal.current_jpy == 0.0
    assert deal.fixed_jpy == 200.0
