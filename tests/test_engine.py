from collections import Counter
from copy import deepcopy
import pytest
from vending.config import Scenario
from vending.engine import Engine
from vending.models import DomainValidation, Lot, transfer
from vending.scoring import score
from vending.suppliers import negotiate
from vending.demand import expected_daily

def test_supplier_categories_boundaries_and_policies():
    e = Engine(Scenario(), 7)
    assert Counter(q.category for q in e.quotes.values()) == dict(winner=20, loser=20, balanced=60)
    for q in e.quotes.values():
        assert negotiate(q, q.minimum)["outcome"] == "accepted"
        assert negotiate(q, q.listed)["outcome"] == "accepted"
        low, high = negotiate(q, 1), negotiate(q, q.listed + 1)
        if q.kind == "impatient":
            assert low == high == {"outcome": "no_reply"}
        else:
            assert low["unit_price_cents"] == q.minimum
            assert high["unit_price_cents"] == q.listed

def test_purchase_and_conservation():
    e = Engine(Scenario(), 1)
    q = e.quotes['s08', 'p01']
    r = e.execute('make_offer', dict(supplier_id='s08', product_id='p01', quantity=10, unit_price_cents=q.minimum))
    assert r['result']['outcome'] == 'accepted' and 'upsell' in r['result']
    assert score(e)['score_cents'] == 50000
    e.execute('set_price', dict(product_id='p01', unit_price_cents=500))
    e.execute('stock_items', dict(slot_id='r1s1', product_id='p01', quantity=10))
    e.execute('wait', {})
    before = score(e)
    e.execute('collect_cash', {})
    assert score(e)['score_cents'] == 50000 + e.revenue - e.cogs - e.fees_assessed
    assert score(e)['score_cents'] >= before['score_cents']
    e.cash = 0
    r = e.execute('make_offer', dict(supplier_id='s08', product_id='p01', quantity=10, unit_price_cents=q.minimum))
    assert r['result']['outcome'] == 'insufficient_funds'

def test_fifo_round_trip():
    source = [Lot('a', 2, 80, 1), Lot('b', 3, 90, 2)]
    slot = []
    assert transfer(source, slot, 3) == 250
    transfer(slot, source, 1)
    assert transfer(source, [], 2) == 170

def test_fee_debt_and_early_stop():
    e = Engine(Scenario(starting_cash_cents=100), 0)
    e.advance(20 * 1440)
    assert e.minute == 10 * 1440
    assert e.debt == 1900 and e.cash == 0 and e.failures == 10
    assert score(e)['score_cents'] == -1900

def test_arrears_first_and_no_benchmark_day_cap():
    e = Engine(Scenario(), 0)
    e.advance(31 * 1440)
    assert e.state == 'running' and e.cash == 50000 - 31 * 200
    e.cash, e.debt = 250, 100
    e.execute('end_day', {})
    assert e.cash == 0 and e.debt == 50 and e.failures == 1
    e.cash = 250
    e.execute('end_day', {})
    assert e.debt == 0 and e.failures == 0

def test_replay_partition_and_price_demand():
    e = Engine(Scenario(), 44)
    e.prices['p01'] = 100
    e.slots['r1s1'].product_id = 'p01'
    e.slots['r1s1'].lots = [Lot('a', 10, 80, 1)]
    a, b = deepcopy(e), deepcopy(e)
    a.advance(300)
    for _ in range(60):
        b.advance(5)
    assert a.summary() == b.summary() and a.private_events == b.private_events
    p = e.products['p01']
    assert expected_daily(p, 200, 1) < expected_daily(p, 100, 1)
    assert sum(a.sold.values()) <= 10

def test_rejections_consume_time_but_invalid_does_not():
    e = Engine(Scenario(), 0)
    r = e.execute('stock_items', dict(slot_id='r1s1', product_id='p01', quantity=1))
    assert r['result']['reason'] == 'price_required' and e.minute == 75
    with pytest.raises(DomainValidation):
        e.execute('set_price', dict(product_id='bad', unit_price_cents=100))
    assert e.minute == 75
