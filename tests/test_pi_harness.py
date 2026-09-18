"""Behavioral tests for the controller, installed extension, and real REST service."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
from vending.api import create_app
from vending.config import Scenario
from vending.registry import Registry
from viewer.store import RunStore

ROOT = Path(__file__).resolve().parents[1]


def node():
    local = ROOT / '.tools/node-v22.19.0-linux-x64/bin/node'
    executable = str(local) if local.is_file() else shutil.which('node')
    if not executable:
        pytest.skip('Install Node with scripts/install_pi.sh to run controller tests')
    return executable


def test_controller_behavior():
    result = subprocess.run([node(), '--test', 'tests/vending-controller.test.mjs'],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_installed_pi_extension():
    if not (ROOT / '.tools/pi/node_modules/@earendil-works/pi-coding-agent').is_dir():
        pytest.skip('Install Pi with scripts/install_pi.sh to test the extension runtime')
    result = subprocess.run([node(), '--test', 'tests/vending-extension.test.mjs'],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@contextmanager
def service(tmp_path, scenario):
    registry = Registry(scenario, artifact_dir=tmp_path / 'service', default_seed=7)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(create_app(registry), log_level='error'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(500):
                if server.started:
                    break
                time.sleep(.01)
            assert server.started
            yield f'http://127.0.0.1:{sock.getsockname()[1]}'
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive()


@pytest.mark.parametrize('mode', ['reshuffle', 'deadline'])
def test_controller_against_service_and_viewer(tmp_path, mode):
    scenario = (Scenario(scenario_id='smoke-v1', max_days=31, runtime_seconds=60)
                if mode == 'reshuffle' else Scenario(runtime_seconds=1))
    sessions = tmp_path / 'pi-sessions'
    sessions.mkdir()
    trace = sessions / 'integration.jsonl'
    with service(tmp_path, scenario) as url:
        result = subprocess.run([node(), 'tests/run_vending_controller.mjs', url, mode, str(trace)],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['result']['state'] == 'ended'
    if mode == 'reshuffle':
        assert report['day'] == 32
        assert report['refreshes'] == 1
        assert report['result']['termination_reason'] == 'smoke_day_cap'
    else:
        assert report['result']['termination_reason'] == 'real_deadline'
    store = RunStore(tmp_path)
    detail = store.detail('pi-integration')
    assert detail['score'] == report['result']['score']
    assert detail['action_total'] == report['result']['committed_action_count']
    assert detail['classification'] == 'completed'
    assert detail['summary'] == report['result']
    assert store.list_runs()['runs'][0]['classification'] == 'completed'
    records = [json.loads(line) for line in trace.read_text().splitlines()]
    calls = [r['message']['content'][0]['arguments']['action'] for r in records
             if r['message']['role'] == 'assistant']
    assert calls[-2:] == ['result', 'delete']
    if mode == 'reshuffle':
        assert detail['daily_activity'] and detail['inventory'] and detail['machine']
        assert detail['live_score'] == detail['score']
