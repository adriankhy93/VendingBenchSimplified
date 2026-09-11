import json
import pytest
from harness.context import Context
from harness.runner import RunConfig, run, tools_for
from harness.agents import Decision
from vending.api import create_app
from vending.registry import Registry
from test_harness import LocalClient, Fake


def test_memory_is_on_demand_and_confined(tmp_path):
    ctx = Context('guide', tmp_path/'memory.md', memory_limit=100)
    ctx.memory_action('write_memory_file', {'name':'products.md', 'content':'secret shortlist'})
    assert ctx.memory_action('list_memory', {}) == {'files':['products.md']}
    assert 'secret shortlist' not in json.dumps(ctx.messages({}))
    assert ctx.memory_action('read_memory', {'name':'products.md'})['content'] == 'secret shortlist'
    for name in ('../escape.md', '/tmp/escape.md', 'nested/file.md'):
        with pytest.raises(ValueError):
            ctx.memory_action('write_memory_file', {'name':name, 'content':'bad'})
    outside = tmp_path/'outside.md';outside.write_text('outside')
    (tmp_path/'memory'/'link.md').symlink_to(outside)
    with pytest.raises(ValueError):
        ctx.memory_action('read_memory', {'name':'link.md'})
    with pytest.raises(ValueError):
        ctx.memory_action('write_memory_file', {'name':'large.md', 'content':'x'*101})


def test_compact_context_retains_public_state_without_quote_matrix(tmp_path):
    ctx = Context('guide', tmp_path/'memory.md', recent_pairs=1)
    observation = {'result': {'products':[{'id':'p01'}], 'quotes':[{'large':'quote matrix'}],
                             'storage':{'p01':{'quantity':10}}, 'rules':{'slot_capacity':10}},
                   'sim_time':{'day':1,'minute_of_day':5}}
    ctx.append('observe', {}, observation)
    ctx.append('get_balance', {}, {'result':{'cash_cents':100}})
    messages = json.dumps(ctx.messages({}))
    assert 'quote matrix' not in messages
    assert ctx.state['storage']['value']['p01']['quantity'] == 10
    assert 'quotes' in observation['result']  # logging input was not mutated


def test_loop_blocks_without_time_cost_and_recovers_after_price(tmp_path):
    registry = Registry(artifact_dir=tmp_path/'private')
    client = LocalClient(create_app(registry))
    stock = {'name':'stock_items', 'payload':{'product_id':'p01','slot_id':'r1s1','quantity':1}}
    decisions = [Decision([stock]) for _ in range(4)]
    decisions += [Decision([{'name':'set_price','payload':{'product_id':'p01','unit_price_cents':150}}]),
                  Decision([stock]), Decision([{'name':'end_day','payload':{}}])]
    directory, summary = run(RunConfig(agent='model', scenario_id='smoke-v1', max_days=1,
                                       artifact_dir=str(tmp_path), token_budget=1000000), Fake(decisions), client)
    actions = [json.loads(x) for x in (directory/'actions.jsonl').read_text().splitlines()]
    assert summary['complete']
    assert actions[4]['response']['error']['code'] == 'loop_blocked'
    assert 'action_id' not in actions[4]['response']
    assert 'action_id' in actions[6]['response']  # price changed state, retry reached engine
    assert 'harness.md' in json.loads((directory/'config.json').read_text())['file_hashes']
    client.close()


def test_memory_tools_available_with_action_descriptions():
    tools = {t['name']:t for t in tools_for(RunConfig(enable_memory=True))}
    assert {'read_memory','write_memory_file','list_memory'} <= tools.keys()
    assert 'price_required' in tools['stock_items']['description']


@pytest.mark.parametrize('outcome', ['rejected', 'no_reply', 'insufficient_funds', 'counteroffer'])
def test_business_refusals_all_trigger_recovery(tmp_path, outcome):
    ctx = Context('guide', tmp_path/'memory.md')
    payload = {'supplier_id':'s01','product_id':'p01','quantity':100,'unit_price_cents':100}
    for _ in range(3):
        ctx.append('make_offer', payload, {'result':{'outcome':outcome}})
    assert ctx.blocked('make_offer', payload, 3)
    ctx.append('get_balance', {}, {'result':{'cash_cents':0}})
    assert ctx.blocked('make_offer', payload, 3)
