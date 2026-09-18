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
    assert Counter(q.category for q in e.quotes.values()) == dict(
        winner=20, loser=20, balanced=60
    )
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
    q = e.quotes["s08", "p01"]
    r = e.execute(
        "make_offer",
        dict(
            supplier_id="s08", product_id="p01", quantity=10, unit_price_cents=q.minimum
        ),
    )
    assert r["result"]["outcome"] == "accepted" and "upsell" in r["result"]
    assert score(e)["score_cents"] == 50000
    e.execute("set_price", dict(product_id="p01", unit_price_cents=500))
    e.execute("stock_items", dict(slot_id="r1s1", product_id="p01", quantity=10))
    e.execute("wait", {})
    before = score(e)
    e.execute("collect_cash", {})
    assert score(e)["score_cents"] == 50000 + e.revenue - e.cogs - e.fees_assessed
    assert score(e)["score_cents"] >= before["score_cents"]
    e.cash = 0
    r = e.execute(
        "make_offer",
        dict(
            supplier_id="s08", product_id="p01", quantity=10, unit_price_cents=q.minimum
        ),
    )
    assert r["result"]["outcome"] == "insufficient_funds"


def test_fifo_round_trip():
    source = [Lot("a", 2, 80, 1), Lot("b", 3, 90, 2)]
    slot = []
    assert transfer(source, slot, 3) == 250
    transfer(slot, source, 1)
    assert transfer(source, [], 2) == 170


def test_fee_debt_and_early_stop():
    e = Engine(Scenario(starting_cash_cents=100), 0)
    e.advance(20 * 1440)
    assert e.minute == 10 * 1440
    assert e.debt == 1900 and e.cash == 0 and e.failures == 10
    assert score(e)["score_cents"] == -1900


def test_arrears_first_and_no_benchmark_day_cap():
    e = Engine(Scenario(), 0)
    e.advance(31 * 1440)
    assert e.state == "running" and e.cash == 50000 - 31 * 200
    e.cash, e.debt = 250, 100
    e.execute("end_day", {})
    assert e.cash == 0 and e.debt == 50 and e.failures == 1
    e.cash = 250
    e.execute("end_day", {})
    assert e.debt == 0 and e.failures == 0


def test_replay_partition_and_price_demand():
    e = Engine(Scenario(), 44)
    e.prices["p01"] = 100
    e.slots["r1s1"].product_id = "p01"
    e.slots["r1s1"].lots = [Lot("a", 10, 80, 1)]
    a, b = deepcopy(e), deepcopy(e)
    a.advance(300)
    for _ in range(60):
        b.advance(5)
    assert a.summary() == b.summary() and a.private_events == b.private_events
    p = e.products["p01"]
    assert expected_daily(p, 200, 1) < expected_daily(p, 100, 1)
    assert sum(a.sold.values()) <= 10


def test_sales_resolve_only_at_midnight(monkeypatch):
    monkeypatch.setattr("vending.demand.sample", lambda *args: 1)
    e = Engine(Scenario(), 0)
    e.prices["p01"] = 100
    e.slots["r1s1"].product_id = "p01"
    e.slots["r1s1"].lots = [Lot("a", 10, 80, 1)]
    assert e.advance(1435) == [] and e.sold["p01"] == 0
    assert e.advance(5)[0] == dict(type="sales", product_id="p01", quantity=1)


def test_rejections_consume_time_but_invalid_does_not():
    e = Engine(Scenario(), 0)
    r = e.execute("stock_items", dict(slot_id="r1s1", product_id="p01", quantity=1))
    assert r["result"]["reason"] == "price_required" and e.minute == 75
    with pytest.raises(DomainValidation):
        e.execute("set_price", dict(product_id="bad", unit_price_cents=100))
    assert e.minute == 75


def test_duplicate_slots_do_not_duplicate_demand():
    e = Engine(Scenario(), 123)
    e.prices["p01"] = 25
    e.slots["r1s1"].product_id = "p01"
    e.slots["r1s1"].lots = [Lot("a", 10, 80, 1)]
    b = deepcopy(e)
    b.slots["r1s1"].lots[0].quantity = 5
    b.slots["r1s2"].product_id = "p01"
    b.slots["r1s2"].lots = [Lot("a", 5, 80, 1)]
    e.advance(1440)
    b.advance(1440)
    assert e.sold == b.sold and e.private_events == b.private_events
    assert e.cogs == b.cogs and e.machine_cash == b.machine_cash


def test_poisson_calibration_over_independent_ticks():
    from vending.demand import sample
    import math

    means = [0.05, 0.2]
    for mean in means:
        n = 10000
        observed = sum(sample(55, 0, tick, mean) for tick in range(n))
        # Six standard deviations: P(false rejection) is negligible, fixed seed.
        assert abs(observed - n * mean) < 6 * math.sqrt(n * mean)


def test_unstock_and_all_or_nothing(monkeypatch):
    monkeypatch.setattr("vending.demand.sample", lambda *args: 0)
    e = Engine(Scenario(), 0)
    e.storage["p01"] = [Lot("a", 10, 80, 1)]
    e.prices["p01"] = 100
    e.execute("stock_items", dict(slot_id="r1s1", product_id="p01", quantity=8))
    result = e.execute(
        "stock_items", dict(slot_id="r1s1", product_id="p01", quantity=3)
    )
    assert result["result"]["reason"] == "slot_full"
    assert e.slots["r1s1"].quantity == 8 and e.inventory()["p01"]["quantity"] == 2
    e.execute("unstock_items", dict(slot_id="r1s1", quantity=8))
    assert e.slots["r1s1"].product_id is None and e.inventory()["p01"]["quantity"] == 10
    assert score(e)["inventory_value_cents"] == 800


def test_supplier_reshuffle_boundary_replay_and_inventory():
    e = Engine(Scenario(), 7)
    initial = dict(e.quotes)
    q = initial['s01', 'p01']
    e.execute('make_offer', dict(supplier_id=q.supplier_id, product_id=q.product_id,
                                quantity=2, unit_price_cents=q.minimum))
    inventory = deepcopy(e.inventory())
    e.advance(30 * 1440 - e.minute - 5)
    assert e.quotes == initial
    events = e.advance(5)
    assert dict(type='supplier_reshuffle', day=31) in events
    assert e.quotes != initial
    assert any(e.quotes[key].category != quote.category for key, quote in initial.items())
    assert Counter(q.category for q in e.quotes.values()) == dict(winner=20, loser=20, balanced=60)
    assert e.inventory() == inventory
    assert all(q.kind == initial[key].kind for key, q in e.quotes.items())
    period_one = dict(e.quotes)
    e.advance(30 * 1440)
    assert e.quotes != period_one
    replay = Engine(Scenario(), 7)
    for _ in range(60):
        replay.execute('end_day', {})
    assert replay.quotes == e.quotes
    assert replay.private_events == e.private_events


def test_configurable_reshuffle_and_search_at_boundary():
    e = Engine(Scenario(supplier_reshuffle_days=2), 42)
    assert e.observe()['rules']['supplier_reshuffle_days'] == 2
    old = dict(e.quotes)
    e.advance(2 * 1440 - 25)
    result = e.execute('search_products', {})
    assert e.quotes != old
    assert result['result']['quotes'] == e.catalog()['quotes']
    assert dict(type='supplier_reshuffle', day=3) in result['events']
    # New offers must use the current period's minimum and listed prices.
    q = e.quotes['s01', 'p01']
    result = e.execute('make_offer', dict(supplier_id=q.supplier_id, product_id=q.product_id,
                                        quantity=1, unit_price_cents=q.minimum))
    assert result['result']['outcome'] == 'accepted'


def test_terminal_day_does_not_reshuffle():
    e = Engine(Scenario(scenario_id='smoke-v1', max_days=30), 7)
    initial = dict(e.quotes)
    events = e.advance(31 * 1440)
    assert e.state == 'ended' and e.quotes == initial
    assert not any(event['type'] == 'supplier_reshuffle' for event in events)


def test_purchase_crossing_reshuffle_keeps_original_agreed_cost():
    e = Engine(Scenario(supplier_reshuffle_days=1), 7)
    from vending.suppliers import build_quotes

    next_quotes = build_quotes(list(e.products.values()), e.seed, e.config, epoch=1)
    key = next(key for key, quote in e.quotes.items()
               if next_quotes[key].minimum != quote.minimum)
    quote = e.quotes[key]
    e.advance(1440 - e.config.durations['make_offer'])
    response = e.execute('make_offer', dict(
        supplier_id=quote.supplier_id, product_id=quote.product_id,
        quantity=2, unit_price_cents=quote.minimum,
    ))
    assert response['result']['outcome'] == 'accepted'
    assert response['result']['total_cents'] == 2 * quote.minimum
    assert e.inventory()[quote.product_id]['acquisition_cost_cents'] == 2 * quote.minimum
    assert e.quotes[key].minimum != quote.minimum
    assert dict(type='supplier_reshuffle', day=2) in response['events']
