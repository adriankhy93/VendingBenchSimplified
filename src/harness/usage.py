"""Attribute each provider call exactly once, on its simulated decision day."""
from copy import deepcopy


def zero_tokens():
    return dict(input_tokens=0, output_tokens=0, total_tokens=0, estimated=False)

class TokenLedger:
    def __init__(self):
        self.sim_time = dict(day=1, minute_of_day=0)
        self.call = None
        self.pending = False
        self.days = {}

    def day(self, day):
        return self.days.setdefault(day, dict(day=day, **zero_tokens(), model_calls=0,
                                             estimated_input_tokens=0, estimated_output_tokens=0))

    def provider(self, call, input_tokens, output_tokens, *, estimated=False, **metadata):
        if any(type(n) is not int or n < 0 for n in (input_tokens, output_tokens)):
            raise ValueError('provider usage must be nonnegative integer tokens')
        if self.pending:
            raise RuntimeError('previous provider usage has not been attributed')
        self.call = dict(call=call, input_tokens=input_tokens, output_tokens=output_tokens,
                         total_tokens=input_tokens+output_tokens, estimated=estimated,
                         sim_time=deepcopy(self.sim_time), **metadata)
        self.pending = True
        day = self.day(self.sim_time['day'])
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            day[key] += self.call[key]
        day['model_calls'] += 1
        day['estimated'] |= estimated
        if estimated:
            day['estimated_input_tokens'] += input_tokens
            day['estimated_output_tokens'] += output_tokens
        return deepcopy(self.call)

    def action(self, response):
        start = deepcopy(self.sim_time)
        self.day(start['day'])
        usage = zero_tokens() | dict(model_call=self.call['call'] if self.call else None,
                                      attribution='shared_call' if self.call else 'no_model')
        if self.pending:
            usage.update({k:self.call[k] for k in zero_tokens()})
            usage['attribution'] = 'provider_call'
            self.pending = False
        for event in response.get('events', []):
            if event.get('type') == 'day':
                self.day(event['day'])
        if response.get('sim_time'):
            self.sim_time = deepcopy(response['sim_time'])
        return dict(start_sim_time=start, token_usage=usage)

    def by_day(self):
        return [deepcopy(self.days[day]) for day in sorted(self.days)]
