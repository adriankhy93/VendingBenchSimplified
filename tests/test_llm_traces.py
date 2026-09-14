import json
import httpx
import pytest
from harness.traces import TraceWriter, TracedAdapter
from harness.vllm_provider import VLLMAdapter


def test_trace_preserves_actual_payload_and_unparsed_response(tmp_path):
    body = {'choices':[{'message':{'content':'visible model text', 'tool_calls':[
        {'function':{'name':'end_day','arguments':'{broken'}}]},'finish_reason':'tool_calls'}],
        'usage':{'prompt_tokens':12,'completion_tokens':9}}
    sent = []
    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=body)
    path = tmp_path/'llm_traces.jsonl'
    with httpx.Client(base_url='http://local/', headers={'Authorization':'Bearer SECRET'}, transport=httpx.MockTransport(handle)) as client:
        adapter = TracedAdapter(VLLMAdapter('qwen',client=client), TraceWriter(path), 7)
        adapter.decide([{'role':'user','content':'state'}], [], 100, 3)
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert all(r['call_id']==7 for r in rows)
    assert next(r for r in rows if r['event']=='provider_request')['body']==sent[0]
    assert next(r for r in rows if r['event']=='provider_response')['body']==body
    assert rows[-1]['decision']['calls'][0]['payload']=='{broken'
    assert 'SECRET' not in path.read_text()


def test_timeout_keeps_request_and_safe_error(tmp_path):
    def handle(request):
        raise httpx.ReadTimeout('SECRET transport details')
    path = tmp_path/'llm_traces.jsonl'
    with httpx.Client(base_url='http://local/', transport=httpx.MockTransport(handle)) as client:
        adapter = TracedAdapter(VLLMAdapter('qwen',client=client), TraceWriter(path), 1)
        with pytest.raises(TimeoutError):
            adapter.decide([], [], 100, 3)
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert any(r['event']=='provider_request' for r in rows)
    assert rows[-1]['event']=='error'
    assert not any(r['event']=='provider_response' for r in rows)
    assert 'SECRET' not in path.read_text()
