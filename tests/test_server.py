import json

import pytest
from fastapi.testclient import TestClient

from vending.server import app_from_config, load_server_config


def test_server_accepts_direct_scenario_and_environment_config(tmp_path):
    direct = tmp_path / "scenario.json"
    direct.write_text(
        json.dumps({"scenario_id": "smoke-v1", "runtime_seconds": 10, "max_days": 1})
    )
    scenario, seed = load_server_config(direct)
    assert scenario.runtime_seconds == 10 and seed is None

    environment = tmp_path / "environment.json"
    environment.write_text(
        json.dumps({"seed": 42, "scenario": json.loads(direct.read_text())})
    )
    with TestClient(
        app_from_config(environment, artifact_dir=tmp_path / "artifacts")
    ) as client:
        created = client.post("/env", json={})
        assert created.status_code == 201
        entry = client.app.state.registry.lookup(created.json()["env_id"])
        assert entry.seed == 42
        assert client.get(f"/env/{created.json()['env_id']}/status").json() == {
            "state": "running"
        }


def test_server_accepts_repository_environment_configuration():
    scenario, seed = load_server_config("configs/environment.json")
    assert scenario.scenario_id == "benchmark-v1"
    assert seed == 0


def test_server_accepts_one_hour_environment_configuration(tmp_path):
    one_hour = tmp_path / "environment-1h.json"
    one_hour.write_text(
        json.dumps(
            {
                "seed": 0,
                "scenario": {"scenario_id": "benchmark-v1", "runtime_seconds": 3600},
            }
        )
    )
    scenario, seed = load_server_config(one_hour)
    assert scenario.runtime_seconds == 3600
    assert seed == 0


@pytest.mark.parametrize("value", ["[]", "{", '{"unknown": true}'])
def test_server_rejects_invalid_configuration(tmp_path, value):
    path = tmp_path / "bad.json"
    path.write_text(value)
    with pytest.raises(ValueError):
        load_server_config(path)


def test_launch_config_cuts_off_after_one_real_hour(tmp_path):
    from vending.api import create_app
    from vending.registry import Registry

    scenario, seed = load_server_config('configs/environment.json')
    assert scenario.runtime_seconds == 3600
    now = [100.0]
    registry = Registry(scenario, default_seed=seed, clock=lambda: now[0],
                        artifact_dir=tmp_path)
    with TestClient(create_app(registry)) as client:
        env_id = client.post('/env', json={}).json()['env_id']
        now[0] += 3599
        response = client.post(f'/env/{env_id}/observe', json={})
        assert response.status_code == 200
        assert response.json()['result']['rules']['runtime_seconds'] == 3600
        now[0] += 1
        # An idle environment expires without needing another agent action.
        registry.sweep()
        assert registry.lookup(env_id).engine is None
        assert client.post(f'/env/{env_id}/observe', json={}).status_code == 410
        result = client.get(f'/env/{env_id}/result').json()
        assert result['termination_reason'] == 'real_deadline'
        assert result['wall_duration_seconds'] == 3600
        assert result['committed_action_count'] == 1
        assert result['simulated_minutes'] == 5
        artifact = json.loads((tmp_path / f'{env_id}.json').read_text())
        assert artifact['summary'] == result
