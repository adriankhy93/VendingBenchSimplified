"""Per-call append-only traces, including responses that arrive after a watchdog stop."""
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timezone
import json
from threading import Lock

_active = ContextVar('llm_trace', default=None)


def emit(event, **data):
    active = _active.get()
    if active is not None:
        writer, call_id = active
        writer.write(call_id, event, **data)


class TraceWriter:
    def __init__(self, path):
        self.path = path
        self.lock = Lock()
        self.path.touch(exist_ok=False)

    def write(self, call_id, event, **data):
        record = dict(version=1, call_id=call_id, event=event,
                      timestamp=datetime.now(timezone.utc).isoformat(), **data)
        with self.lock, self.path.open('a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')


class TracedAdapter:
    def __init__(self, adapter, writer, call_id):
        self.adapter, self.writer, self.call_id = adapter, writer, call_id

    def decide(self, messages, tools, max_output_tokens, timeout):
        token = _active.set((self.writer, self.call_id))
        try:
            emit('harness_request', messages=messages, tools=tools,
                 max_output_tokens=max_output_tokens, timeout_seconds=timeout)
            result = self.adapter.decide(messages, tools, max_output_tokens, timeout)
            emit('decision', decision=asdict(result))
            return result
        except Exception as exc:
            # Exception text and transport headers can contain credentials.
            emit('error', error_type=type(exc).__name__)
            raise
        finally:
            _active.reset(token)
