import json
import httpx
import pytest
from harness.vllm_provider import VLLMAdapter, VLLMSettings

TOOLS=[dict(name='end_day',description='Finish day',input_schema={'type':'object','properties':{}})]


def test_native_tools_history_and_measured_usage():
    captured=[]
    def handle(request):
        captured.append(json.loads(request.content))
        assert str(request.url)=='http://vllm/v1/chat/completions'
        return httpx.Response(200,json=dict(choices=[dict(message=dict(tool_calls=[dict(function=dict(name='end_day',arguments='{}'))]))],
                              usage=dict(prompt_tokens=123,completion_tokens=45,prompt_tokens_details=dict(cached_tokens=60))))
    with httpx.Client(base_url='http://vllm/v1/',transport=httpx.MockTransport(handle)) as client:
        adapter=VLLMAdapter('qwen',client=client)
        messages=[dict(role='system',content='Instructions'),dict(role='user',content='Public state'),
                  dict(role='assistant',content='{"action":"end_day","payload":{}}'),dict(role='user',content='{"state":"running"}')]
        result=adapter.decide(messages,TOOLS,512,3)
    assert result.calls==[dict(name='end_day',payload={})]
    assert result.input_tokens==123 and result.output_tokens==45
    request=captured[0]
    assert request['messages'][2]['tool_calls'][0]['function']['arguments']=='{}'
    assert request['messages'][3]['role']=='tool'
    assert request['parallel_tool_calls'] is False and request['max_tokens']==512
    assert request['chat_template_kwargs']=={'enable_thinking':False}
    assert request['tools'][0]['function']['parameters']==TOOLS[0]['input_schema']


@pytest.mark.parametrize('arguments', ['{bad', 'null', '[]'])
def test_malformed_tool_payload_preserves_token_usage(arguments):
    def handle(request):
        return httpx.Response(200,json=dict(choices=[dict(message=dict(tool_calls=[dict(function=dict(name='end_day',arguments=arguments))]))],usage=dict(prompt_tokens=10,completion_tokens=20)))
    with httpx.Client(base_url='http://vllm/',transport=httpx.MockTransport(handle)) as client:
        decision=VLLMAdapter('qwen',client=client).decide([],TOOLS,100,3)
    assert decision.input_tokens==10 and decision.output_tokens==20
    assert not isinstance(decision.calls[0]['payload'],dict)


def test_timeout_does_not_retry_inference():
    calls=[]
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout')
    with httpx.Client(base_url='http://vllm/',transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(TimeoutError):
            VLLMAdapter('qwen',client=client).decide([],TOOLS,100,3)
    assert len(calls)==1
