from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from fastapi.testclient import TestClient
from vending.api import create_app
from vending.registry import Registry, APIError
from vending.engine import Engine

@pytest.fixture
def setup(tmp_path):
    now = [100.]
    registry = Registry(clock=lambda: now[0], artifact_dir=tmp_path)
    with TestClient(create_app(registry)) as client:
        yield client, registry, now

def create(client, **options):
    r = client.post('/env', json=options)
    assert r.status_code == 201 and set(r.json()) == {'env_id'}
    return r.json()['env_id']

def test_contract_expiry_and_retention(setup):
    c, registry, now = setup
    eid = create(c, runtime_seconds=10)
    assert c.get(f'/env/{eid}/status').json() == {'state':'running'}
    assert c.get(f'/env/{eid}/result').status_code == 409
    now[0] += 10
    registry.sweep()
    assert c.get(f'/env/{eid}/status').json() == {'state':'ended'}
    assert c.post(f'/env/{eid}/observe', json={}).status_code == 410
    assert c.post(f'/env/{eid}/unknown', json={}).status_code == 404
    summary = c.get(f'/env/{eid}/result').json()
    assert summary['score']['score_cents'] == 50000
    summary['score']['score_cents'] = 0
    assert c.get(f'/env/{eid}/result').json()['score']['score_cents'] == 50000
    for _ in range(2):
        r = c.delete(f'/env/{eid}')
        assert r.status_code == 204 and r.content == b''
    assert c.get(f'/env/{eid}/status').status_code == 404

def test_validation(setup):
    c, r, _ = setup
    eid = create(c)
    path = f'/env/{eid}/make_offer'
    base = dict(supplier_id='s01', product_id='p01', quantity=1, unit_price_cents=100)
    for update in ({'quantity':-1}, {'quantity':1.5}, {'quantity':True}, {'extra':1}, {'unit_price_cents':1.1}, {'product_id':'x'}, {'quantity':1001}):
        assert c.post(path, json=base | update).status_code == 422
    assert c.post(path, content='NaN').status_code == 400
    assert c.post(path, content='{').status_code == 400
    assert c.post(path, content='x' * 65537).status_code == 413
    assert r.lookup(eid).engine.minute == 0
    assert c.post('/env', json={'max_days':10}).status_code == 422
    assert c.post('/env', json={'seed':True}).status_code == 422

def test_idempotency_and_concurrent_purchase(setup):
    c, r, _ = setup
    eid = create(c)
    engine = r.lookup(eid).engine
    price = engine.quotes['s01','p01'].listed
    data = dict(supplier_id='s01', product_id='p01', quantity=10, unit_price_cents=price)
    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(lambda _: r.action(eid, 'make_offer', data, 'same'), range(4)))
    assert all(x == responses[0] for x in responses)
    assert r.lookup(eid).engine.cash == 50000 - price * 10
    assert r.lookup(eid).engine.minute == 75
    with pytest.raises(APIError) as err:
        r.action(eid, 'make_offer', data | {'quantity':11}, 'same')
    assert err.value.status == 409

def test_deadline_discards_staged_action(setup, monkeypatch):
    c, r, now = setup
    eid = create(c, runtime_seconds=10)
    original = Engine.execute
    def slow(self, action, payload):
        result = original(self, action, payload)
        now[0] += 10
        return result
    monkeypatch.setattr(Engine, 'execute', slow)
    response = c.post(f'/env/{eid}/end_day', json={})
    assert response.status_code == 410
    summary = c.get(f'/env/{eid}/result').json()
    assert summary['simulated_minutes'] == 0 and summary['score']['cash_cents'] == 50000

def test_fault_and_isolation(setup, monkeypatch):
    c, r, _ = setup
    a, b = create(c), create(c)
    def fail(*args):
        raise RuntimeError('private details')
    monkeypatch.setattr(Engine, 'execute', fail)
    assert c.post(f'/env/{a}/observe', json={}).status_code == 500
    assert c.get(f'/env/{a}/status').json() == {'state':'unavailable'}
    assert c.post(f'/env/{a}/observe', json={}).status_code == 409
    assert c.get(f'/env/{a}/result').json()['complete'] is False
    assert c.get(f'/env/{b}/status').json() == {'state':'running'}

def test_public_observation_has_no_hidden_fields(setup):
    c, _, _ = setup
    eid = create(c, seed=987)
    text = c.post(f'/env/{eid}/observe', json={}).text
    for field in ('seed', 'elasticity', 'base_demand', 'category', 'minimum', 'stockouts'):
        assert f'"{field}"' not in text

def test_final_action_and_idle_retention(setup):
    c, registry, now = setup
    eid = create(c, scenario_id='smoke-v1', max_days=1)
    response = c.post(f'/env/{eid}/end_day', json={}, headers={'Idempotency-Key':'a'})
    assert response.status_code == 200 and response.json()['state'] == 'ended'
    assert c.post(f'/env/{eid}/end_day', json={}, headers={'Idempotency-Key':'a'}).status_code == 410
    now[0] += 3600
    registry.sweep()
    assert c.get(f'/env/{eid}/result').status_code == 404

def test_competing_actions_and_delete_race(setup, monkeypatch):
    from vending.models import Lot
    c, r, _ = setup
    monkeypatch.setattr('vending.demand.sample', lambda *args: 0)
    eid = create(c)
    engine = r.lookup(eid).engine
    engine.storage['p01'] = [Lot('a', 10, 80, 1)]
    engine.prices['p01'] = 100
    payload = dict(slot_id='r1s1', product_id='p01', quantity=6)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: r.action(eid,'stock_items',payload), range(2)))
    assert sum(x['result'].get('moved_quantity',0) for x in results) == 6
    assert r.lookup(eid).engine.slots['r1s1'].quantity == 6
    def act():
        try:
            return r.action(eid,'collect_cash',{})
        except APIError as exc:
            assert exc.status == 404
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(act), pool.submit(r.delete,eid)]
        for future in futures:
            future.result()
    assert eid not in r.entries


def test_competing_purchases_cannot_overspend(setup):
    c, r, _ = setup
    eid = create(c)
    e = r.lookup(eid).engine
    price = e.quotes['s01','p01'].listed
    e.cash = price * 10
    payload = dict(supplier_id='s01', product_id='p01', quantity=10, unit_price_cents=price)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: r.action(eid,'make_offer',payload), range(2)))
    assert {x['result']['outcome'] for x in results} == {'accepted','insufficient_funds'}
    assert r.lookup(eid).engine.cash == 0


def test_background_sweeper_expires_idle_environment(tmp_path, monkeypatch):
    from threading import Event

    now = [100.0]
    registry = Registry(clock=lambda: now[0], artifact_dir=tmp_path)
    expired = Event()
    original = registry.finish

    def finish(env_id, entry, state, reason):
        original(env_id, entry, state, reason)
        if reason == 'real_deadline':
            expired.set()

    monkeypatch.setattr(registry, 'finish', finish)
    with TestClient(create_app(registry)) as client:
        env_id = create(client, runtime_seconds=10)
        now[0] += 10
        # No API calls or manual sweep: the application's lifespan task must expire it.
        assert expired.wait(timeout=5), 'Background sweeper did not expire the idle environment'
        result = json.loads((tmp_path / f'{env_id}.json').read_text())['summary']
        assert result['termination_reason'] == 'real_deadline'
        assert result['committed_action_count'] == 0
