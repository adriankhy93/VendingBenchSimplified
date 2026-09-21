"""Exercise launch commands without starting vLLM or a real agent."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('overrides', [False, True])
def test_shared_model_config_reaches_both_launchers(tmp_path, overrides):
    node = ROOT / '.tools/node-v22.19.0-linux-x64/bin/node'
    if not node.exists():
        pytest.skip('Install Node with scripts/install_pi.sh')
    for relative in ('scripts/serve_qwen_vllm.sh', 'scripts/run_pi_agent.sh',
                     '.pi/agent/models.json', '.pi/agent/settings.json'):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    node_target = tmp_path / '.tools/node-v22.19.0-linux-x64/bin/node'
    node_target.parent.mkdir(parents=True)
    node_target.symlink_to(node)
    (tmp_path / 'configs').mkdir()
    stub = tmp_path / 'capture'
    stub.write_text('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
    stub.chmod(0o755)
    env = os.environ | {'VLLM_BIN': str(stub), 'PI_BIN': str(stub),
                        'VENDING_MODEL_CACHE': str(tmp_path / 'cache')}
    for key in ('QWEN_MODEL_PATH', 'VLLM_MODEL_NAME'):
        env.pop(key, None)
    model_config = tmp_path / '.pi/agent/models.json'
    if overrides:
        env.update({
            'PI_CODING_AGENT_DIR': str(tmp_path / 'runtime-agent'),
            'VENDING_AGENT_WORKSPACE': str(tmp_path / 'runtime-workspace'),
            'VLLM_API_URL': 'http://127.0.0.1:9001/v1',
            'VLLM_HOST': '0.0.0.0',
            'VLLM_MAX_MODEL_LEN': '32768',
            'QWEN_MODEL_PATH': '/alternate-model',
        })
        model_config = tmp_path / 'runtime-agent/models.json'
    original = json.loads((tmp_path / '.pi/agent/models.json').read_text())
    original_model = original['providers']['vending-vllm']['models'][0]
    for name in ('first-model', 'second-model'):
        model_path = f'/models with spaces/{name}'
        (tmp_path / 'configs/model.env').write_text(
            f'model_path="{model_path}"\nmodel_name="{name}"\n')
        expected_name = name
        if overrides:
            expected_name = f'overrides-{name}'
            env['VLLM_MODEL_NAME'] = expected_name
        for script, flag in [('serve_qwen_vllm.sh', '--served-model-name'),
                             ('run_pi_agent.sh', '--model')]:
            result = subprocess.run(['bash', str(tmp_path / 'scripts' / script)],
                                    cwd='/', env=env, capture_output=True, text=True,
                                    timeout=10)
            assert result.returncode == 0, result.stderr
            args = json.loads(result.stdout)
            assert args[args.index(flag) + 1] == expected_name
            if script == 'serve_qwen_vllm.sh':
                assert args[:2] == ['serve', '/alternate-model' if overrides else model_path]
                assert args[args.index('--host') + 1] == ('0.0.0.0' if overrides else '127.0.0.1')
        config = json.loads(model_config.read_text())
        model = config['providers']['vending-vllm']['models'][0]
        assert model['id'] == expected_name
        assert model['samplingParams'] == original_model['samplingParams']
        assert model['contextWindow'] == (32768 if overrides else 262144)
        assert config['providers']['vending-vllm']['baseUrl'] == (
            'http://127.0.0.1:9001/v1' if overrides else 'http://127.0.0.1:8001/v1')
        if overrides:
            assert json.loads((tmp_path / '.pi/agent/models.json').read_text()) == original
