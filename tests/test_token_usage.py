import json
from harness.usage import TokenLedger
from harness.runner import RunConfig, run
from harness.agents import Decision
from vending.api import create_app
from vending.registry import Registry
from test_harness import Fake, LocalClient


def test_multiaction_call_is_charged_once_on_decision_day():
    ledger=TokenLedger()
    ledger.sim_time=dict(day=1,minute_of_day=1435)
    call=ledger.provider(1,101,19)
    first=ledger.action({'sim_time':dict(day=2,minute_of_day=0)})
    second=ledger.action({'sim_time':dict(day=2,minute_of_day=5)})
    assert call['sim_time']['day']==1
    assert first['token_usage']['total_tokens']==120
    assert second['token_usage']['total_tokens']==0
    assert second['token_usage']['attribution']=='shared_call'
    assert second['token_usage']['model_call']==1
    assert first['start_sim_time']['day']==1 and second['start_sim_time']['day']==2
    assert ledger.by_day()[0]['total_tokens']==120 and ledger.by_day()[1]['total_tokens']==0


def test_runner_records_actions_days_errors_and_usage(tmp_path):
    registry=Registry(artifact_dir=tmp_path/'private')
    client=LocalClient(create_app(registry))
    fake=Fake([Decision([],11,2), TimeoutError(),
               Decision([dict(name='end_day',payload={}),dict(name='get_balance',payload={})],100,20),
               Decision([dict(name='end_day',payload={})],200,30)])
    try:
        path,summary=run(RunConfig(agent='model',scenario_id='smoke-v1',max_days=2,artifact_dir=str(tmp_path)),fake,client)
    finally:
        client.close()
    assert summary['complete']
    actions=[json.loads(line) for line in (path/'actions.jsonl').read_text().splitlines()]
    usage=[json.loads(line) for line in (path/'usage.jsonl').read_text().splitlines()]
    assert actions[0]['token_usage']['total_tokens']==0
    assert sum(a['token_usage']['total_tokens'] for a in actions)==summary['usage']['total_tokens']
    assert sum(d['total_tokens'] for d in summary['usage']['tokens_by_day'])==summary['usage']['total_tokens']
    assert [u['sim_time']['day'] for u in usage]==[1,1,1,2]
    assert summary['usage']['tokens_by_day'][0]['estimated'] is True
    assert summary['usage']['tokens_by_day'][1]['total_tokens']==230
    shared=next(a for a in actions if a['action']=='get_balance')
    assert shared['token_usage']['attribution']=='shared_call'
    assert shared['token_usage']['total_tokens']==0


def test_model_usage_survives_stop_before_tool_execution(tmp_path):
    registry=Registry(artifact_dir=tmp_path/'private')
    client=LocalClient(create_app(registry))
    try:
        path,summary=run(RunConfig(agent='model',artifact_dir=str(tmp_path)),
                         Fake([Decision([dict(name='end_day',payload={})],100000,1)]),client)
    finally:
        client.close()
    assert summary['reason']=='token_budget'
    actions=[json.loads(line) for line in (path/'actions.jsonl').read_text().splitlines()]
    assert actions[-1]['action']=='provider_no_action'
    assert actions[-1]['token_usage']['total_tokens']==100001
    assert summary['usage']['tokens_by_day'][0]['total_tokens']==100001
