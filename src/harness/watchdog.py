"""Bound provider wall time and poll environment status during slow inference."""
from queue import Queue, Empty
from threading import Thread
import time

class EnvironmentStopped(Exception):
    def __init__(self, state):
        self.state = state


def decide(adapter, messages, schemas, max_output_tokens, timeout, poll, clock=time.monotonic):
    mailbox = Queue(maxsize=1)
    def work():
        try:
            mailbox.put((True, adapter.decide(messages, schemas, max_output_tokens, timeout)))
        except Exception as exc:
            mailbox.put((False, exc))
    # A timed-out inference thread has no environment handle or tool execution rights.
    Thread(target=work, daemon=True).start()
    deadline = clock() + timeout
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError('provider wall timeout')
        try:
            ok, value = mailbox.get(timeout=min(1., remaining))
        except Empty:
            state = poll()
            if state != 'running':
                raise EnvironmentStopped(state)
            continue
        if ok:
            return value
        raise value
