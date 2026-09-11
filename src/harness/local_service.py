"""Own a temporary local service process for a single HTTP-only episode."""
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import httpx

@contextmanager
def local_service(environments_dir, artifact_dir):
    directory = Path(artifact_dir).resolve() / 'service'
    directory.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop('VENDING_SCENARIO', None)
    env['VENDING_ENVIRONMENTS_DIR'] = str(Path(environments_dir).resolve())
    env['VENDING_ARTIFACT_DIR'] = str(directory)
    log_path = directory / f'server-{uuid.uuid4().hex}.log'
    # Pass a bound socket to avoid free-port races, and bind loopback only.
    with socket.socket() as sock, log_path.open('w') as log:
        sock.bind(('127.0.0.1', 0))
        sock.listen(128)
        url = f'http://127.0.0.1:{sock.getsockname()[1]}'
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'vending.api:app',
                                    '--fd', str(sock.fileno()), '--no-access-log'],
                                   pass_fds=(sock.fileno(),), env=env, stdout=log, stderr=log)
        try:
            started = time.monotonic()
            with httpx.Client(base_url=url, timeout=.5, trust_env=False) as client:
                while True:
                    if process.poll() is not None or time.monotonic() - started > 15:
                        raise RuntimeError(f'local service failed to start; see {log_path}')
                    try:
                        if client.get('/openapi.json').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.05)
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
