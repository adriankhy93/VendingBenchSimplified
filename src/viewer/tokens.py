"""Display new token records and distinguish legacy unknowns from scripted zeroes."""
SCRIPTED = {'idle', 'listed', 'negotiating'}


def action_tokens(record, config):
    if isinstance(record.get('token_usage'), dict):
        return record['token_usage']
    if config.get('agent') in SCRIPTED:
        return dict(input_tokens=0, output_tokens=0, total_tokens=0, estimated=False,
                    model_call=None, attribution='no_model')
    return dict(input_tokens=None, output_tokens=None, total_tokens=None, estimated=False,
                model_call=None, attribution='unavailable')

class DailyTokens:
    def __init__(self, config):
        self.scripted = config.get('agent') in SCRIPTED
        self.available = self.scripted or config.get('token_tracking_version') == 1
        self.days = {}
        self.unattributed = dict(input_tokens=0, output_tokens=0, total_tokens=0, model_calls=0)
        self.clock = dict(day=1, minute_of_day=0)

    def day(self, day):
        return self.days.setdefault(day, dict(day=day, input_tokens=0 if self.available else None,
            output_tokens=0 if self.available else None, total_tokens=0 if self.available else None,
            model_calls=0 if self.available else None, estimated=False,
            estimated_input_tokens=0, estimated_output_tokens=0))

    def action(self, record):
        start = record.get('start_sim_time') or self.clock
        self.day(start['day'])
        response = record.get('response') or {}
        for event in response.get('events', []):
            if event.get('type') == 'day':
                self.day(event['day'])
        self.clock = response.get('sim_time') or self.clock

    def usage(self, record):
        stamp = record.get('sim_time') or {}
        day = stamp.get('day')
        if type(day) is not int or day < 1:
            target = self.unattributed
        else:
            target = self.day(day)
        for key in ('input_tokens', 'output_tokens'):
            target[key] = (target[key] or 0) + record.get(key, 0)
        target['total_tokens'] = target['input_tokens'] + target['output_tokens']
        target['model_calls'] = (target['model_calls'] or 0) + 1
        if target is not self.unattributed and record.get('estimated'):
            target['estimated'] = True
            target['estimated_input_tokens'] += record.get('input_tokens', 0)
            target['estimated_output_tokens'] += record.get('output_tokens', 0)

    def rows(self):
        return [self.days[day] for day in sorted(self.days)]
