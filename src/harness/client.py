"""HTTP-only access; retries preserve the same action idempotency key."""
import time
import uuid
import httpx

class ServiceError(Exception):
    def __init__(self, status, error):
        self.status, self.error = status, error
        super().__init__(f"HTTP {status}: {error.get('code', 'service_error')}")

class Client:
    def __init__(self, url, timeout=30, transport=None, clock=time.monotonic):
        self.http = httpx.Client(base_url=url, timeout=timeout, transport=transport)
        self.timeout, self.clock = timeout, clock

    def request(self, method, path, *, payload=None, key=None, deadline=None, retry=True):
        for attempt in range(3 if retry else 1):
            remaining = self.timeout if deadline is None else min(self.timeout, deadline - self.clock())
            if remaining <= 0:
                raise TimeoutError('runner deadline')
            try:
                response = self.http.request(method, path, json=payload,
                                             headers={'Idempotency-Key': key} if key else {}, timeout=remaining)
                if response.status_code in (502, 503, 504) and attempt < 2 and retry:
                    continue
                if response.is_error:
                    try:
                        error = response.json().get('error', {})
                    except ValueError:
                        error = {'code': 'service_error'}
                    raise ServiceError(response.status_code, error)
                return None if response.status_code == 204 else response.json()
            except httpx.TransportError:
                if not retry or attempt == 2:
                    raise

    def create(self, options, deadline=None):
        # Creation has no idempotency contract: don't create orphan duplicates.
        return self.request('POST', '/env', payload=options, deadline=deadline, retry=False)['env_id']

    def action(self, env_id, action, payload, deadline=None):
        return self.request('POST', f'/env/{env_id}/{action}', payload=payload,
                            key=uuid.uuid4().hex, deadline=deadline)

    def status(self, env_id, deadline=None):
        return self.request('GET', f'/env/{env_id}/status', deadline=deadline)

    def result(self, env_id, deadline=None):
        return self.request('GET', f'/env/{env_id}/result', deadline=deadline)

    def delete(self, env_id, deadline=None):
        return self.request('DELETE', f'/env/{env_id}', deadline=deadline)

    def close(self):
        self.http.close()
