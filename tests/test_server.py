import json

import pytest
from fastapi.testclient import TestClient

from vending.server import app_from_config, load_server_config


def test_server_accepts_direct_scenario_and_environment_config(tmp_path):
    direct = tmp_path / "scenario.json"
    direct.write_text(json.dumps({"scenario_id": "smoke-v1", "runtime_seconds": 10, "max_days": 1}))
    scenario, seed = load_server_config(direct)
    assert scenario.runtime_seconds == 10 and seed is None

    environment = tmp_path / "environment.json"
    environment.write_text(json.dumps({"seed": 42, "scenario": json.loads(direct.read_text())}))
    with TestClient(app_from_config(environment, artifact_dir=tmp_path / "artifacts")) as client:
        created = client.post("/env", json={})
        assert created.status_code == 201
        entry = client.app.state.registry.lookup(created.json()["env_id"])
        assert entry.seed == 42
        assert client.get(f"/env/{created.json()['env_id']}/status").json() == {"state": "running"}


def test_server_accepts_repository_environment_configuration():
    scenario, seed = load_server_config("configs/environment.json")
    assert scenario.scenario_id == "benchmark-v1"
    assert seed == 0


def test_server_accepts_one_hour_environment_configuration():
    scenario, seed = load_server_config("configs/environment-1h.json")
    assert scenario.runtime_seconds == 3600
    assert seed == 0


@pytest.mark.parametrize("value", ["[]", "{", '{"unknown": true}'])
def test_server_rejects_invalid_configuration(tmp_path, value):
    path = tmp_path / "bad.json"
    path.write_text(value)
    with pytest.raises(ValueError):
        load_server_config(path)
