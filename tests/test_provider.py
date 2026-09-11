from types import SimpleNamespace
import pytest
pytest.importorskip('anthropic')
from harness.provider import AnthropicAdapter

def test_adapter_native_pairs_and_usage():
    captured = {}
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type='tool_use',name='end_day',input={})],
                               usage=SimpleNamespace(input_tokens=10,output_tokens=3,cache_read_input_tokens=2))
    adapter = AnthropicAdapter('explicit-test-model', SimpleNamespace(messages=SimpleNamespace(create=create)))
    messages = [dict(role='system',content='instructions'), dict(role='user',content='initial'),
                dict(role='assistant',content='{"action":"end_day","payload":{}}'), dict(role='user',content='{"state":"running"}')]
    result = adapter.decide(messages, [{'name':'end_day','input_schema':{'type':'object'}}], 100, 5)
    assert result.input_tokens == 12 and result.output_tokens == 3
    assert captured['messages'][1]['content'][0]['type'] == 'tool_use'
    assert captured['messages'][2]['content'][0]['type'] == 'tool_result'
    assert captured['timeout'] == 5 and captured['max_tokens'] == 100
