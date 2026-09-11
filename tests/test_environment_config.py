from collections import Counter
import pytest
from vending.config import Scenario, Product, Supplier, PairQuote
from vending.engine import Engine


def custom_scenario(**changes):
    defaults = dict(products=(Product(id='tea', name='Tea', reference_price_cents=300, base_demand=2., elasticity=1.5),),
                    suppliers=(Supplier(id='vendor', kind='pushy-patient'),), machine_rows=2, slots_per_row=2,
                    min_price_percent=50, max_price_percent=200, day_multipliers=(0.,), tick_minutes=1,
                    starting_cash_cents=900, daily_fee_cents=0,
                    supplier_quotes=(PairQuote(supplier_id='vendor',product_id='tea',category='winner',minimum_cents=99,listed_cents=120),))
    return Scenario(**(defaults | changes))


def test_custom_parameters_reach_engine():
    e = Engine(custom_scenario(), 1)
    assert len(e.slots) == 4 and e.bounds('tea') == (150,600)
    assert e.catalog()['suppliers'] == ['vendor']
    result = e.execute('make_offer',dict(supplier_id='vendor',product_id='tea',quantity=1,unit_price_cents=99))
    assert result['result']['outcome'] == 'accepted' and 'upsell' not in result['result']
    e.advance(1440)
    assert e.cash == 801 and sum(e.stockouts.values()) == 0
    assert e.config == Scenario.model_validate_json(e.config.model_dump_json())


@pytest.mark.parametrize('changes', [dict(tick_minutes=7), dict(min_price_percent=501),
    dict(cost_variation_min_ppm=2000000), dict(category_weights={'winner':0,'loser':0,'balanced':0}),
    dict(products=()), dict(day_multipliers=(float('nan'),))])
def test_invalid_config_rejected(changes):
    with pytest.raises(ValueError):
        Scenario(**changes)


def test_category_weights_scale_to_catalog_size():
    config = custom_scenario(supplier_quotes=(),category_weights=dict(winner=1,loser=0,balanced=0))
    assert Counter(q.category for q in Engine(config,0).quotes.values()) == {'winner':1}
