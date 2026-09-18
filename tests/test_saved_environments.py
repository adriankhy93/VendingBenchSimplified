import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from vending.api import create_app
from vending.environments import EnvironmentConfig, generate, load_environment
from vending.registry import Registry
from test_environment_config import custom_scenario


def saved(tmp_path, name="custom"):
    config = EnvironmentConfig(
        seed=42,
        scenario=custom_scenario(
            scenario_id="smoke-v1", max_days=1, runtime_seconds=20
        ),
    )
    source = tmp_path / "source.json"
    source.write_text(config.model_dump_json())
    directory = tmp_path / "environments"
    generate(source, name, directory)
    return source, directory


def test_generation_is_self_contained_reproducible_and_no_overwrite(tmp_path):
    source, directory = saved(tmp_path)
    definition, digest = load_environment(directory, "custom")
    assert definition.seed == 42 and definition.scenario.products[0].id == "tea"
    assert len(definition.scenario.supplier_quotes) == 1
    other = tmp_path / "other"
    generate(source, "custom", other)
    assert load_environment(other, "custom")[1] == digest
    with pytest.raises(FileExistsError):
        generate(source, "custom", directory)
    source.unlink()
    assert load_environment(directory, "custom")[0] == definition


@pytest.mark.parametrize(
    "name", ["../escape", "a/b", "/tmp/foo", "name.json", "", ".."]
)
def test_names_cannot_escape_directory(tmp_path, name):
    with pytest.raises(ValueError):
        load_environment(tmp_path, name)


def test_selected_creation_preserves_definition_and_isolation(tmp_path):
    _, directory = saved(tmp_path)
    definition, digest = load_environment(directory, "custom")
    registry = Registry(artifact_dir=tmp_path / "private", environments_dir=directory)
    with TestClient(create_app(registry)) as client:
        options = dict(environment_name="custom", environment_sha256=digest)
        a = client.post("/env", json=options).json()["env_id"]
        b = client.post("/env", json=options).json()["env_id"]
        assert registry.lookup(a).engine.seed == 42
        assert registry.lookup(a).engine.config == definition.scenario
        assert client.post("/env", json=options | dict(seed=1)).status_code == 422
        assert (
            client.post(
                "/env", json=options | dict(environment_sha256="0" * 64)
            ).status_code
            == 409
        )
        assert (
            client.post("/env", json=dict(environment_name="missing")).status_code
            == 404
        )
        assert (
            client.post("/env", json=dict(environment_name="../custom")).status_code
            == 422
        )
        initial = client.post(f"/env/{a}/observe", json={}).json()
        assert (
            initial["result"]["cash_cents"] == 900
            and len(initial["result"]["slots"]) == 4
        )
        for secret in (
            "seed",
            "supplier_quotes",
            "minimum_cents",
            "category_weights",
            "environment_sha256",
        ):
            assert secret not in json.dumps(initial)
        client.post(f"/env/{a}/end_day", json={})
        assert (
            registry.status(a)["state"] == "ended"
            and registry.status(b)["state"] == "running"
        )


def test_resolved_quotes_and_default_seed_market_match(tmp_path):
    from vending.engine import Engine

    original = EnvironmentConfig(seed=17)
    source = tmp_path / "config.json"
    source.write_text(original.model_dump_json())
    generate(source, "default", tmp_path)
    definition, _ = load_environment(tmp_path, "default")
    assert (
        Engine(original.scenario, 17).quotes == Engine(definition.scenario, 17).quotes
    )


def test_generation_seed_override_changes_saved_seed_and_quotes(tmp_path):
    base = EnvironmentConfig(seed=1)
    source = tmp_path / "config.json"
    source.write_text(base.model_dump_json())

    generate(source, "from-config", tmp_path)
    generate(source, "overridden", tmp_path, seed=999)

    from_config, _ = load_environment(tmp_path, "from-config")
    overridden, _ = load_environment(tmp_path, "overridden")

    assert from_config.seed == 1
    assert overridden.seed == 999
    assert from_config.scenario.supplier_quotes != overridden.scenario.supplier_quotes


def test_saved_quotes_do_not_prevent_periodic_reshuffle(tmp_path):
    from vending.engine import Engine

    original = EnvironmentConfig(seed=17)
    source = tmp_path / 'config.json'
    source.write_text(original.model_dump_json())
    generate(source, 'rotating', tmp_path)
    definition, _ = load_environment(tmp_path, 'rotating')
    direct = Engine(original.scenario, 17)
    restored = Engine(definition.scenario, 17)
    initial = dict(restored.quotes)
    direct.advance(30 * 1440)
    restored.advance(30 * 1440)
    assert restored.quotes != initial
    assert restored.quotes == direct.quotes
