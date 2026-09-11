"""Read existing artifacts without loading private demand logs or changing runs."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re

class RunNotFound(ValueError):
    pass

class RunStore:
    def __init__(self, directory='runs', service_directory=None):
        self.directory = Path(directory).resolve()
        self.service_directory = Path(service_directory).resolve() if service_directory else self.directory / 'service'

    def run_path(self, run_id):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', run_id):
            raise RunNotFound('Run not found')
        path = self.directory / run_id
        if path.is_symlink() or not path.is_dir() or not self.file(path, 'config.json').is_file():
            raise RunNotFound('Run not found')
        return path

    @staticmethod
    def file(path, name):
        target = path / name
        if target.is_symlink():
            raise RunNotFound('Artifact symlinks are not supported')
        return target

    def read_json(self, path, name, warnings):
        try:
            value = json.loads(self.file(path, name).read_text(), parse_constant=lambda _: None)
            if not isinstance(value, dict):
                raise ValueError('expected object')
            return value
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as exc:
            warnings.append(f'{name} is unreadable or still being written.')
            return None

    def records(self, path, name, warnings):
        try:
            with self.file(path, name).open() as stream:
                bad = 0
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line, parse_constant=lambda _: None)
                        if not isinstance(record, dict):
                            raise ValueError('expected object')
                    except ValueError:
                        bad += 1
                        continue
                    yield record
                if bad:
                    warnings.append(f'{name}: skipped {bad} incomplete or malformed records.')
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            warnings.append(f'{name} could not be read.')

    def metadata(self, path):
        warnings = []
        config = self.read_json(path, 'config.json', warnings) or {}
        summary = self.read_json(path, 'summary.json', warnings)
        terminal = (summary or {}).get('terminal') or {}
        source = 'terminal' if terminal else None
        # A stopped runner may have a trusted pre-deletion score outside its public log.
        env_id = (summary or {}).get('env_id')
        if summary and not terminal and isinstance(env_id, str) and re.fullmatch(r'env_[a-f0-9]+', env_id):
            artifact = self.read_json(self.service_directory, f'{env_id}.json', warnings)
            if artifact and isinstance(artifact.get('summary'), dict):
                terminal = artifact['summary']
                source = 'pre_deletion'
        score = terminal.get('score') or {}
        modified = self.file(path, 'config.json').stat().st_mtime
        evaluator = (summary or {}).get('evaluator') or {}
        item = dict(run_id=path.name, agent=config.get('agent', 'unknown'), model=config.get('model'),
                    environment=evaluator.get('environment_name') or config.get('environment_name') or config.get('scenario_id', 'unknown'),
                    seed=evaluator.get('seed', config.get('seed')), scenario_version=terminal.get('scenario_version'),
                    classification=(summary or {}).get('classification', 'unfinished'),
                    reason=terminal.get('termination_reason') or (summary or {}).get('reason'),
                    created_at=datetime.fromtimestamp(modified, timezone.utc).isoformat(),
                    score=score, score_source=source, simulated_minutes=terminal.get('simulated_minutes'),
                    usage=(summary or {}).get('usage') or {}, errors=(summary or {}).get('errors') or [], warnings=warnings)
        return item, config, summary, terminal

    def list_runs(self, query='', classification='', offset=0, limit=50):
        items = []
        if self.directory.is_dir():
            for path in self.directory.iterdir():
                try:
                    path = self.run_path(path.name)
                    item, *_ = self.metadata(path)
                except (RunNotFound, OSError, TypeError, AttributeError):
                    continue
                haystack = ' '.join(str(item[k]) for k in ('run_id', 'agent', 'model', 'environment', 'seed')).lower()
                if query.lower() in haystack and (not classification or item['classification'] == classification):
                    items.append(item)
        items.sort(key=lambda x: (x['created_at'], x['run_id']), reverse=True)
        return dict(runs=items[offset:offset+limit], total=len(items), offset=offset, limit=limit)

    def detail(self, run_id):
        path = self.run_path(run_id)
        item, config, summary, terminal = self.metadata(path)
        warnings = item['warnings']
        timeline, day_events, sold, action_counts, names = [], [], {}, {}, {}
        last_machine, last_inventory, last_response = None, None, None
        count = 0
        for record in self.records(path, 'actions.jsonl', warnings):
            count += 1
            action = record.get('action', 'unknown')
            action_counts[action] = action_counts.get(action, 0) + 1
            response = record.get('response') or {}
            result = response.get('result') or {}
            for product in result.get('products', []):
                names[product['product_id']] = product.get('name', product['product_id'])
            if 'slots' in result:
                last_machine = dict(slots=result['slots'], prices=result.get('prices', {}), sim_time=response.get('sim_time'))
            if 'storage' in result:
                last_inventory = dict(storage=result['storage'], sim_time=response.get('sim_time'))
            for event in response.get('events', []):
                if event.get('type') == 'sales':
                    pid = event['product_id']
                    sold[pid] = sold.get(pid, 0) + event.get('quantity', 0)
                elif event.get('type') == 'day':
                    day_events.append(event)
                    day_events = day_events[-100:]
            if 'sim_time' in response and 'metrics' in response:
                last_response = response
                clock = response['sim_time']
                point = dict(index=count, minute=(clock['day']-1)*1440+clock['minute_of_day'], **response['metrics'])
                timeline.append(point)
                if len(timeline) > 600:
                    timeline = timeline[::2]
        if last_response:
            last_point = dict(index=count, minute=(last_response['sim_time']['day']-1)*1440+last_response['sim_time']['minute_of_day'], **last_response['metrics'])
            if not timeline or timeline[-1]['minute'] != last_point['minute']:
                timeline.append(last_point)
            if item['simulated_minutes'] is None:
                item['simulated_minutes'] = last_point['minute']
            item['last_balances'] = last_response['metrics']
        usage_records = deque(maxlen=1000)
        usage_totals = dict(calls=0, input_tokens=0, output_tokens=0)
        for record in self.records(path, 'usage.jsonl', warnings):
            usage_records.append(record)
            usage_totals['calls'] += 1
            usage_totals['input_tokens'] += record.get('input_tokens', 0)
            usage_totals['output_tokens'] += record.get('output_tokens', 0)
        if not item['usage']:
            item['usage'] = usage_totals
        try:
            memory = self.file(path, 'memory.md').read_text()
        except (OSError, ValueError):
            memory = ''
        # Explicitly return only the public summary section of a trusted service artifact.
        return dict(**item, config=config, terminal=terminal, summary=summary, timeline=timeline,
                    sales=[dict(product_id=pid, name=names.get(pid, pid), quantity=qty) for pid, qty in sorted(sold.items())],
                    day_events=day_events, action_counts=action_counts, action_total=count,
                    machine=last_machine, inventory=last_inventory, product_names=names, memory=memory,
                    usage_records=list(usage_records))

    def actions(self, run_id, action='', offset=0, limit=50):
        path = self.run_path(run_id)
        warnings, items, total = [], [], 0
        for index, record in enumerate(self.records(path, 'actions.jsonl', warnings), 1):
            if action and action != record.get('action'):
                continue
            if offset <= total < offset + limit:
                items.append(dict(index=index, **record))
            total += 1
        return dict(actions=items, total=total, offset=offset, limit=limit, warnings=warnings)
