"""Bounded public context, deterministic summaries, and isolated Markdown memory."""
import json
from pathlib import Path

class Context:
    def __init__(self, instructions, memory_path, recent_pairs=20, memory_limit=8000):
        self.instructions = instructions
        self.memory_path = Path(memory_path)
        self.recent_pairs, self.memory_limit = recent_pairs, memory_limit
        self.history = []
        self.notebook = {'quotes': {}, 'prices': {}, 'sales': {}}
        self.initial = None
        self.memory = ''
        self.write_memory('')

    def write_memory(self, content):
        if not isinstance(content, str) or len(content) > self.memory_limit:
            raise ValueError('memory exceeds character limit')
        self.memory = content
        self.memory_path.write_text(content)

    def append(self, action, payload, response):
        result = response.get('result', {})
        if action == 'observe' and self.initial is None:
            self.initial = result
        if action == 'make_offer' and result.get('outcome') in ('accepted', 'counteroffer'):
            key = payload['supplier_id'] + ':' + payload['product_id']
            self.notebook['quotes'][key] = result.get('unit_price_cents', payload['unit_price_cents'])
        if action == 'set_price' and 'unit_price_cents' in result:
            self.notebook['prices'][payload['product_id']] = result['unit_price_cents']
        for event in response.get('events', []):
            if event['type'] == 'sales':
                pid = event['product_id']
                self.notebook['sales'][pid] = self.notebook['sales'].get(pid, 0) + event['quantity']
        # Cap keys even if a fake/misbehaving service returns arbitrary identifiers.
        for name in self.notebook:
            self.notebook[name] = dict(list(self.notebook[name].items())[-100:])
        self.history.append(({'action': action, 'payload': payload}, response))
        self.history = self.history[-self.recent_pairs:]

    def messages(self, budget):
        messages = [dict(role='system', content=self.instructions),
                    dict(role='user', content=json.dumps(dict(initial=self.initial, notebook=self.notebook,
                                                             memory=self.memory, remaining_budget=budget)))]
        for action, response in self.history:
            messages.append(dict(role='assistant', content=json.dumps(action)))
            messages.append(dict(role='user', content=json.dumps(response)))
        return messages
