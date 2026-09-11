import json
from fastapi.testclient import TestClient
import pytest
from viewer.api import create_app
from viewer.store import RunStore


def write_run(root, name='run-a', complete=True):
    path=root/name
    path.mkdir(parents=True)
    (path/'config.json').write_text(json.dumps(dict(agent='negotiating',seed=42,scenario_id='smoke-v1')))
    records=[dict(action='observe',payload={},response=dict(sim_time=dict(day=1,minute_of_day=5),
        result=dict(products=[dict(product_id='p01',name='Water')],slots=[],storage={}),
        metrics=dict(cash_cents=50000,machine_cash_cents=0,fee_debt_cents=0,units_sold=0),events=[])),
        dict(action='end_day',payload={},response=dict(sim_time=dict(day=2,minute_of_day=0),result={},
        metrics=dict(cash_cents=49800,machine_cash_cents=500,fee_debt_cents=0,units_sold=5),
        events=[dict(type='sales',product_id='p01',quantity=5)]))]
    (path/'actions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    (path/'memory.md').write_text('<script>window.bad=true</script>')
    if complete:
        (path/'summary.json').write_text(json.dumps(dict(classification='completed',complete=True,env_id='env_abc',
            terminal=dict(score=dict(score_cents=50300),simulated_minutes=1440,termination_reason='smoke_day_cap'),usage=dict(calls=1))))
    return path


def test_api_lists_runs_filters_and_pages(tmp_path):
    write_run(tmp_path)
    write_run(tmp_path,'run-b',False)
    (tmp_path/'service').mkdir()
    (tmp_path/'suite.json').write_text('{}')
    with TestClient(create_app(tmp_path)) as c:
        data=c.get('/api/runs?limit=1').json()
        assert data['total']==2 and len(data['runs'])==1
        assert c.get('/api/runs?classification=completed').json()['total']==1
        assert c.get('/api/runs?q=42').json()['total']==2
        assert c.get('/api/runs?q=nothing').json()['total']==0
        assert c.get('/api/runs?limit=1000').status_code==422
        assert c.get('/api/runs/missing').status_code==404
        assert c.post('/api/runs/run-a').status_code==405


def test_details_chart_sales_and_action_pagination(tmp_path):
    write_run(tmp_path)
    with TestClient(create_app(tmp_path)) as c:
        d=c.get('/api/runs/run-a').json()
        assert d['score']['score_cents']==50300 and d['score_source']=='terminal'
        assert d['timeline'][-1]['minute']==1440
        assert d['sales']==[dict(product_id='p01',name='Water',quantity=5)]
        assert d['action_total']==2 and d['memory'].startswith('<script>')
        assert c.get('/api/runs/run-a/actions?offset=1&limit=1').json()['actions'][0]['index']==2
        assert c.get('/api/runs/run-a/actions?action=observe').json()['total']==1
        assert c.get('/').status_code==200
        assert 'Run explorer' in c.get('/').text
        assert c.get('/assets/app.js').headers['content-type'].startswith('text/javascript')
        assert c.get('/assets/secrets').status_code==404
        assert "script-src 'self'" in c.get('/').headers['content-security-policy']


def test_partial_logs_and_missing_summary_are_unfinished(tmp_path):
    path=write_run(tmp_path,complete=False)
    with (path/'actions.jsonl').open('a') as f:
        f.write('{"action":')
    (path/'summary.json').write_text('{')
    d=RunStore(tmp_path).detail('run-a')
    assert d['classification']=='unfinished' and d['score']=={}
    assert d['action_total']==2 and d['simulated_minutes']==1440
    assert len(d['warnings'])==2


def test_truncated_score_uses_only_trusted_summary(tmp_path):
    path=write_run(tmp_path,complete=False)
    (path/'summary.json').write_text(json.dumps(dict(classification='budget_truncated',env_id='env_abc',reason='max_calls')))
    (tmp_path/'service').mkdir()
    (tmp_path/'service'/'env_abc.json').write_text(json.dumps(dict(summary=dict(score=dict(score_cents=49800),complete=False),evaluator=dict(secret='hidden'))))
    d=RunStore(tmp_path).detail('run-a')
    assert d['classification']=='budget_truncated' and d['score_source']=='pre_deletion'
    assert d['score']['score_cents']==49800 and 'hidden' not in json.dumps(d)


def test_symlinks_and_traversal_do_not_expose_files(tmp_path):
    root=tmp_path/'runs';root.mkdir()
    outside=write_run(tmp_path,'outside')
    (root/'link').symlink_to(outside,target_is_directory=True)
    safe=write_run(root,'safe')
    (safe/'memory.md').unlink()
    (safe/'memory.md').symlink_to(outside/'memory.md')
    with TestClient(create_app(root)) as c:
        assert c.get('/api/runs/link').status_code==404
        assert c.get('/api/runs/..%2Foutside').status_code==404
        assert c.get('/api/runs/safe').json()['memory']==''
        assert c.get('/api/runs').json()['total']==1


def test_empty_run_directory(tmp_path):
    with TestClient(create_app(tmp_path/'missing')) as c:
        assert c.get('/api/runs').json()['runs']==[]


def test_daily_tokens_and_action_attribution(tmp_path):
    path=write_run(tmp_path,complete=False)
    config=json.loads((path/'config.json').read_text())|dict(agent='model',token_tracking_version=1)
    (path/'config.json').write_text(json.dumps(config))
    records=[json.loads(s) for s in (path/'actions.jsonl').read_text().splitlines()]
    records[0]['token_usage']=dict(input_tokens=100,output_tokens=20,total_tokens=120,estimated=False,model_call=1,attribution='provider_call')
    records[0]['start_sim_time']=dict(day=1,minute_of_day=0)
    records[1]['token_usage']=dict(input_tokens=0,output_tokens=0,total_tokens=0,estimated=False,model_call=1,attribution='shared_call')
    records[1]['start_sim_time']=dict(day=1,minute_of_day=5)
    (path/'actions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    # An inference timeout on day two has usage even without a completed business day.
    usage=[dict(call=1,input_tokens=100,output_tokens=20,sim_time=dict(day=1,minute_of_day=0)),
           dict(call=2,input_tokens=200,output_tokens=30,estimated=True,sim_time=dict(day=2,minute_of_day=0))]
    (path/'usage.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in usage))
    with TestClient(create_app(tmp_path)) as c:
        d=c.get('/api/runs/run-a').json()
        assert [row['total_tokens'] for row in d['tokens_by_day']]==[120,230]
        assert d['tokens_by_day'][1]['estimated'] is True
        assert d['tokens_by_day'][1]['estimated_input_tokens']==200
        assert d['usage']['input_tokens']==300
        actions=c.get('/api/runs/run-a/actions').json()['actions']
        assert actions[0]['token_usage']['total_tokens']==120
        assert actions[1]['token_usage']['attribution']=='shared_call'
        assert 'Tokens by simulated day' in c.get('/').text


def test_legacy_scripted_zeroes_and_unknown_model_usage(tmp_path):
    path=write_run(tmp_path,complete=False)
    store=RunStore(tmp_path)
    assert store.actions('run-a')['actions'][0]['token_usage']['total_tokens']==0
    assert store.detail('run-a')['tokens_by_day'][0]['total_tokens']==0
    config=json.loads((path/'config.json').read_text())|dict(agent='model')
    (path/'config.json').write_text(json.dumps(config))
    (path/'usage.jsonl').write_text(json.dumps(dict(call=1,input_tokens=100,output_tokens=5))+'\n')
    assert store.actions('run-a')['actions'][0]['token_usage']['total_tokens'] is None
    detail=store.detail('run-a')
    assert detail['tokens_by_day'][0]['total_tokens'] is None
    assert detail['unattributed_tokens']['total_tokens']==105
    assert detail['unattributed_tokens']['model_calls']==1
    assert detail['token_tracking_available'] is False
