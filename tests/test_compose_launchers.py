"""Check environment startup without a Docker daemon or model installation."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def launcher(tmp_path):
    shutil.copyfile(ROOT / 'start.sh', tmp_path / 'start.sh')
    executable = tmp_path / 'docker'
    executable.write_text('''#!/usr/bin/env python3
import json, os, sys
if '--wait-timeout' in sys.argv:
    sys.exit('unknown flag: --wait-timeout')
with open(os.environ['CAPTURE'], 'a') as stream:
    stream.write(json.dumps({'args': sys.argv[1:], 'mode': os.getenv('VENDING_CONFIG'),
                             'api_port': os.getenv('VENDING_API_PORT'),
                             'dashboard_port': os.getenv('VENDING_DASHBOARD_PORT')}) + '\\n')
''')
    executable.chmod(0o755)
    capture = tmp_path / 'calls.jsonl'
    env = os.environ | {'PATH': f"{tmp_path}:{os.environ['PATH']}", 'CAPTURE': str(capture)}
    env.pop('VENDING_API_PORT', None)
    return tmp_path, capture, env


@pytest.mark.parametrize('mode, config', [('train', 'environment.json'),
                                          ('test', 'environment-eval.json')])
def test_start_without_models_uses_explicit_ports(launcher, mode, config):
    root, capture, env = launcher
    result = subprocess.run(['bash', str(root / 'start.sh'), mode, '9000', '9999'], cwd='/',
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    call, = [json.loads(line) for line in capture.read_text().splitlines()]
    assert call['mode'] == config
    assert call['args'][-2:] == ['environment', 'dashboard']
    assert '--env-file' not in call['args']
    assert '--wait' in call['args'] and '--build' in call['args']
    assert call['api_port'] == '9000'
    assert call['dashboard_port'] == '9999'
    assert 'Dashboard: http://localhost:9999' in result.stdout
    assert 'Environment API: http://localhost:9000' in result.stdout
    assert (root / 'runs/service').is_dir()


@pytest.mark.parametrize('args', [[], ['train'], ['test'], ['invalid', '9999'],
                                  ['train', '9999'], ['train', '8000', '9999', 'extra'], ['llm', '8001', '9999']])
def test_rejects_unsupported_commands(launcher, args):
    root, capture, env = launcher
    result = subprocess.run(['bash', str(root / 'start.sh'), *args], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'Usage:' in result.stderr
    assert not capture.exists()


@pytest.mark.parametrize('ports', [('0', '9999'), ('9000', '65536'), ('-1', '9999'),
                                   ('9000', 'abc'), ('8000', '8000'), ('99999999999', '9999')])
def test_invalid_ports_fail_before_docker(launcher, ports):
    root, capture, env = launcher
    result = subprocess.run(['bash', str(root / 'start.sh'), 'train', *ports], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert 'port' in result.stderr
    assert not capture.exists()


def test_explicit_ports_override_environment_variables(launcher):
    root, capture, env = launcher
    result = subprocess.run(['bash', str(root / 'start.sh'), 'train', '9000', '9999'],
                            env=env | {'VENDING_API_PORT': '7000', 'VENDING_DASHBOARD_PORT': '7070'},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    call, = [json.loads(line) for line in capture.read_text().splitlines()]
    assert call['api_port'] == '9000'
    assert call['dashboard_port'] == '9999'
