"""Native tool-call adapter for vLLM's /v1/chat/completions endpoint.

Protocol reference: https://docs.vllm.ai/en/latest/features/tool_calling/
Uses httpx directly; no hosted-provider SDK or model credentials are required.
"""
import json
from typing import Literal
import httpx
from pydantic import Field
from vending.config import StrictModel
from .agents import Decision

class VLLMSettings(StrictModel):
    base_url: str = 'http://127.0.0.1:8001/v1'
    temperature: float = Field(default=0.7, ge=0, le=2, allow_inf_nan=False)
    top_p: float = Field(default=0.8, gt=0, le=1, allow_inf_nan=False)
    top_k: int = Field(default=20, ge=-1)
    presence_penalty: float = Field(default=0., ge=-2, le=2, allow_inf_nan=False)
    generation_seed: int = Field(default=0, ge=0)
    enable_thinking: bool = False
    tool_choice: Literal['auto', 'required'] = 'auto'


def native_messages(messages, tools):
    allowed = {tool['name'] for tool in tools}
    converted = []
    index = 0
    while index < len(messages):
        message = messages[index]
        try:
            action = json.loads(message['content']) if message['role'] == 'assistant' else {}
        except (ValueError, TypeError):
            action = {}
        if (isinstance(action, dict) and action.get('action') in allowed and index+1 < len(messages)
                and messages[index+1]['role'] == 'user'):
            call_id = f'history_{index}'
            converted.append(dict(role='assistant', content=None, tool_calls=[dict(id=call_id, type='function',
                function=dict(name=action['action'], arguments=json.dumps(action['payload'])))]))
            converted.append(dict(role='tool', tool_call_id=call_id, content=messages[index+1]['content']))
            index += 2
        else:
            converted.append(message)
            index += 1
    return converted

class VLLMAdapter:
    def __init__(self, model, settings=None, client=None):
        self.model = model
        self.settings = settings or VLLMSettings()
        self.client = client or httpx.Client(base_url=self.settings.base_url.rstrip('/')+'/', trust_env=False)
        self.owns_client = client is None

    def decide(self, messages, tools, max_output_tokens, timeout):
        options = self.settings
        body = dict(model=self.model, messages=native_messages(messages, tools),
                    tools=[dict(type='function', function=dict(name=t['name'], description=t.get('description',''),
                           parameters=t['input_schema'])) for t in tools],
                    tool_choice=options.tool_choice, parallel_tool_calls=False,
                    max_tokens=max_output_tokens, temperature=options.temperature,
                    top_p=options.top_p, top_k=options.top_k, presence_penalty=options.presence_penalty,
                    seed=options.generation_seed, chat_template_kwargs=dict(enable_thinking=options.enable_thinking))
        try:
            # No automatic retry: an ambiguous inference may already have consumed tokens.
            response = self.client.post('chat/completions', json=body, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise TimeoutError('vLLM inference timeout') from exc
        response.raise_for_status()
        data = response.json()
        usage = data['usage']
        input_tokens, output_tokens = usage['prompt_tokens'], usage['completion_tokens']
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
            raise ValueError('invalid vLLM token usage')
        calls = []
        for choice in data.get('choices', [])[:1]:
            for call in choice.get('message', {}).get('tool_calls') or []:
                function = call.get('function') or {}
                payload = function.get('arguments')
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except ValueError:
                        pass  # Local schema validation will reject it, retaining token usage.
                calls.append(dict(name=function.get('name'), payload=payload))
        return Decision(calls, input_tokens, output_tokens)

    def close(self):
        if self.owns_client:
            self.client.close()
