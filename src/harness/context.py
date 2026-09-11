"""Bounded public context, deterministic summaries, and isolated Markdown memory."""
import json
import re
from copy import deepcopy
from pathlib import Path

class Context:
    def __init__(self, instructions, memory_path, recent_pairs=20, memory_limit=8000):
        self.instructions = instructions
        self.memory_path = Path(memory_path)
        self.recent_pairs, self.memory_limit = recent_pairs, memory_limit
        self.history = []
        self.notebook = {'quotes': {}, 'prices': {}, 'sales': {}}
        self.initial = None
        self.state = {}
        self.failures = {}
        self.recovery = None
        self.memory_dir = self.memory_path.parent / 'memory'
        self.memory = ''
        self.write_memory('')

    def write_memory(self, content):
        if not isinstance(content, str) or len(content) > self.memory_limit:
            raise ValueError('memory exceeds character limit')
        self.memory = content
        self.memory_path.write_text(content)

    def memory_file(self, name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}\.md', name):
            raise ValueError('Use a simple Markdown filename, e.g. products.md')
        path = self.memory_dir / name
        if self.memory_dir.is_symlink() or path.is_symlink():
            raise ValueError('Memory symlinks are forbidden')
        return path

    def memory_action(self, action, payload):
        if action == 'list_memory':
            if payload:
                raise ValueError('list_memory takes no fields')
            return {'files': self.memory_files()}
        expected = {'name', 'content'} if action == 'write_memory_file' else {'name'}
        if set(payload) != expected:
            raise ValueError('Invalid memory fields')
        path = self.memory_file(payload['name'])
        if action == 'write_memory_file':
            content = payload['content']
            if not isinstance(content, str) or len(content) > self.memory_limit:
                raise ValueError('Memory exceeds character limit')
            if not path.exists() and len(self.memory_files()) >= 20:
                raise ValueError('At most 20 memory files')
            self.memory_dir.mkdir(exist_ok=True)
            path.write_text(content)
            return {'outcome': 'written', 'name': path.name}
        if not path.is_file():
            raise ValueError('Memory file does not exist')
        return {'name': path.name, 'content': path.read_text()[:self.memory_limit]}

    def memory_files(self):
        return sorted(p.name for p in self.memory_dir.glob('*.md') if p.is_file() and not p.is_symlink())

    def blocked(self, action, payload, limit):
        return self.failures.get(json.dumps([action, payload], sort_keys=True), 0) >= limit

    def append(self, action, payload, response):
        result = response.get('result', {})
        signature = json.dumps([action, payload], sort_keys=True)
        if result.get('outcome') in ('rejected', 'no_reply') or response.get('error'):
            self.failures[signature] = self.failures.get(signature, 0) + 1
            self.failures = dict(list(self.failures.items())[-100:])
            self.recovery = {'action': action, 'payload': payload, 'result': result or response.get('error'),
                             'repeats': self.failures[signature],
                             'guidance': 'Do not repeat an unsuccessful call unchanged. Inspect the cause and change the plan. price_required means call set_price first.'}
        elif action in ('make_offer', 'set_price', 'stock_items', 'unstock_items', 'collect_cash', 'wait', 'end_day'):
            self.failures.clear()
            self.recovery = None
        if 'sim_time' in response:
            self.state['sim_time'] = response['sim_time']
        if 'metrics' in response:
            self.state['metrics'] = response['metrics']
        for key in ('storage', 'slots', 'prices', 'cash_cents', 'machine_cash_cents', 'fee_debt_cents'):
            if key in result:
                self.state[key] = {'value': deepcopy(result[key]), 'as_of': response.get('sim_time')}
        if action in ('make_offer', 'stock_items', 'unstock_items'):
            self.state['last_' + action] = {'payload': payload, 'result': result, 'as_of': response.get('sim_time')}

        if action == 'observe' and self.initial is None:
            self.initial = {k: deepcopy(v) for k, v in result.items() if k in ('scenario_version', 'products', 'suppliers', 'rules')}
            response = deepcopy(response)
            response['result'] = self.initial
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
                                                             memory=self.memory, memory_files=self.memory_files(), state=self.state, recovery=self.recovery, remaining_budget=budget)))]
        for action, response in self.history:
            messages.append(dict(role='assistant', content=json.dumps(action)))
            messages.append(dict(role='user', content=json.dumps(response)))
        return messages
