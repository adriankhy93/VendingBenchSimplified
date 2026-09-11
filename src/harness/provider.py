"""Optional Anthropic Messages adapter. Explicit model; credentials stay in the SDK.

Contract: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
"""
import json
from .agents import Decision

class AnthropicAdapter:
    def __init__(self, model, client=None):
        import anthropic
        self.sdk = anthropic
        self.client = client or anthropic.Anthropic(max_retries=0)
        self.model = model

    def decide(self, messages, tools, max_output_tokens, timeout):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        converted = []
        # Reconstruct each retained action/result pair as native tool messages.
        # Summary/error records remain ordinary text, so truncated histories stay valid.
        index = 0
        history = [m for m in messages if m['role'] != 'system']
        allowed = {t['name'] for t in tools}
        while index < len(history):
            message = history[index]
            try:
                action = json.loads(message['content']) if message['role'] == 'assistant' else {}
            except ValueError:
                action = {}
            if action.get('action') in allowed and index + 1 < len(history) and history[index + 1]['role'] == 'user':
                tool_id = f'history_{index}'
                converted.append(dict(role='assistant', content=[dict(type='tool_use', id=tool_id,
                                      name=action['action'], input=action['payload'])]))
                converted.append(dict(role='user', content=[dict(type='tool_result', tool_use_id=tool_id,
                                      content=history[index + 1]['content'])]))
                index += 2
            else:
                converted.append(message)
                index += 1
        try:
            response = self.client.messages.create(model=self.model, system=system, messages=converted,
                                                   tools=tools, tool_choice={'type':'any', 'disable_parallel_tool_use':True},
                                                   max_tokens=max_output_tokens, timeout=timeout)
        except self.sdk.APITimeoutError as exc:
            raise TimeoutError('provider timeout') from exc
        usage = response.usage
        return Decision(calls=[dict(name=block.name, payload=block.input) for block in response.content if block.type == 'tool_use'],
                        input_tokens=usage.input_tokens + (getattr(usage, 'cache_creation_input_tokens', 0) or 0)
                                     + (getattr(usage, 'cache_read_input_tokens', 0) or 0),
                        output_tokens=usage.output_tokens)
