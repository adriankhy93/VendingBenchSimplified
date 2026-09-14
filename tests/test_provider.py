from types import SimpleNamespace
import pytest
pytest.importorskip('anthropic')
from harness.provider import AnthropicAdapter
from anthropic.types import Message
from harness.traces import TraceWriter, TracedAdapter
import json

def test_adapter_native_pairs_and_usage(tmp_path):
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return Message.model_validate(dict(id='msg_test', type='message', role='assistant', model='explicit-test-model',
            content=[dict(type='tool_use',id='tool_test',name='end_day',input={})], stop_reason='tool_use',
            usage=dict(input_tokens=10,output_tokens=3,cache_read_input_tokens=2)))
    adapter = AnthropicAdapter('explicit-test-model', SimpleNamespace(messages=SimpleNamespace(create=create)))
    adapter = TracedAdapter(adapter, TraceWriter(tmp_path/'llm_traces.jsonl'), 1)
    messages = [dict(role='system',content='instructions'), dict(role='user',content='initial'),
                dict(role='assistant',content='{"action":"end_day","payload":{}}'), dict(role='user',content='{"state":"running"}')]
    result = adapter.decide(messages, [{'name':'end_day','input_schema':{'type':'object'}}], 100, 5)
    assert result.input_tokens == 12 and result.output_tokens == 3
    assert captured['messages'][1]['content'][0]['type'] == 'tool_use'
    assert captured['messages'][2]['content'][0]['type'] == 'tool_result'
    assert captured['timeout'] == 5 and captured['max_tokens'] == 100

    rows = [json.loads(x) for x in (tmp_path/'llm_traces.jsonl').read_text().splitlines()]
    assert next(r for r in rows if r['event']=='provider_response')['body']['stop_reason']=='tool_use'
