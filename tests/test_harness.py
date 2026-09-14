import json
import httpx
import pytest
from fastapi.testclient import TestClient
from vending.api import create_app
from vending.registry import Registry
from harness.client import Client
from harness.runner import RunConfig, run
from harness.agents import Decision
from harness.context import Context

class LocalClient(Client):
    def __init__(self, app):
        super().__init__('http://testserver')
        self.http.close()
        self.http = TestClient(app)

@pytest.mark.parametrize('agent', ['idle','listed','negotiating'])
def test_scripted_episodes(tmp_path, agent):
    registry = Registry(artifact_dir=tmp_path/'private')
    client = LocalClient(create_app(registry))
    directory, summary = run(RunConfig(agent=agent, scenario_id='smoke-v1', max_days=4, artifact_dir=str(tmp_path)), client=client)
    assert summary['complete'] and summary['reason'] == 'ended'
    assert f'--{agent}--smoke-v1--' in directory.name
    assert json.loads((directory/'config.json').read_text())['created_at']
    assert not registry.entries
    assert {p.name for p in directory.iterdir()} == {'config.json','actions.jsonl','usage.jsonl','memory.md','summary.json'}
    assert summary['usage']['input_tokens'] == 0
    client.close()

def test_transport_retry_preserves_key():
    keys = []
    def handler(request):
        keys.append(request.headers['Idempotency-Key'])
        if len(keys) < 3:
            raise httpx.ReadTimeout('ambiguous', request=request)
        return httpx.Response(200, json={'ok':True})
    client = Client('http://local', transport=httpx.MockTransport(handler))
    assert client.action('x','make_offer',{}) == {'ok':True}
    assert len(keys) == 3 and len(set(keys)) == 1
    client.close()

class Fake:
    def __init__(self, decisions):
        self.decisions = iter(decisions)
    def decide(self, *args):
        decision = next(self.decisions)
        if isinstance(decision, Exception):
            raise decision
        return decision

def test_fake_invalid_memory_and_terminal(tmp_path):
    registry = Registry(artifact_dir=tmp_path/'private')
    client = LocalClient(create_app(registry))
    fake = Fake([Decision([]), Decision([{}]), Decision([{'name':'write_memory','payload':{'content':'learned'}}]),
                 Decision([{'name':'end_day','payload':{}}, {'name':'end_day','payload':{}}], 20, 5)])
    directory, summary = run(RunConfig(agent='model', scenario_id='smoke-v1', max_days=1, enable_memory=True, artifact_dir=str(tmp_path)), fake, client)
    assert summary['complete'] and summary['usage']['calls'] == 4
    assert (directory/'memory.md').read_text() == 'learned'
    traces = [json.loads(x) for x in (directory/'llm_traces.jsonl').read_text().splitlines()]
    assert [x['call_id'] for x in traces if x['event']=='harness_request'] == [1,2,3,4]
    assert len([x for x in (directory/'actions.jsonl').read_text().splitlines() if json.loads(x)['action'] == 'end_day']) == 1
    assert not registry.entries
    client.close()

def test_budget_truncation_and_trusted_delete_artifact(tmp_path):
    registry = Registry(artifact_dir=tmp_path/'private')
    client = LocalClient(create_app(registry))
    _, summary = run(RunConfig(agent='model', token_budget=1, artifact_dir=str(tmp_path)), Fake([]), client)
    assert summary['reason'] == 'token_budget' and not summary['complete']
    trusted = json.loads((tmp_path/'private'/summary['truncated_accounting_artifact']).read_text())
    assert trusted['summary']['score']['score_cents'] == 50000
    assert not registry.entries
    client.close()

def test_provider_timeouts_stop_and_cleanup(tmp_path):
    registry = Registry(artifact_dir=tmp_path/'private')
    client = LocalClient(create_app(registry))
    _, summary = run(RunConfig(agent='model', max_invalid=2, artifact_dir=str(tmp_path)), Fake([TimeoutError(), TimeoutError()]), client)
    assert summary['reason'] == 'repeated_invalid_actions'
    assert summary['usage']['input_tokens'] > 0 and not registry.entries
    client.close()

def test_context_is_bounded_and_memory_isolated(tmp_path):
    a = Context('instructions', tmp_path/'a.md', recent_pairs=2)
    b = Context('instructions', tmp_path/'b.md', recent_pairs=2)
    a.write_memory('private to this run')
    for _ in range(5):
        a.append('wait', {}, {'events':[{'type':'sales','product_id':'p01','quantity':2}]})
    assert len(a.history) == 2 and a.notebook['sales']['p01'] == 10
    assert b.memory == ''

def test_watchdog_polls_during_model_call():
    import time
    from harness.watchdog import decide, EnvironmentStopped
    class Slow:
        def decide(self, *args):
            time.sleep(1.1)
            return Decision([])
    with pytest.raises(EnvironmentStopped):
        decide(Slow(), [], [], 10, 2, lambda:'ended')
    with pytest.raises(TimeoutError):
        decide(Slow(), [], [], 10, .01, lambda:'running')
