"""Launch the vending REST API from a scenario or environment configuration."""
import argparse
import json
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from .api import create_app
from .config import Scenario
from .environments import EnvironmentConfig, SavedEnvironment
from .registry import Registry


def load_server_config(path):
    """Return a server-default scenario and optional deterministic default seed.

    A direct Scenario JSON is convenient for service configuration. Generator and
    saved environment files wrap the scenario in ``scenario`` and retain their seed,
    which becomes the seed for POST /env with an empty body.
    """
    raw = Path(path).read_text()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("configuration must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("configuration must be a JSON object")
    try:
        if "scenario" not in data:
            return Scenario.model_validate(data), None
        config = (SavedEnvironment if "format_version" in data else EnvironmentConfig).model_validate(data)
        return config.scenario, config.seed
    except ValidationError as exc:
        raise ValueError("configuration is not a valid vending scenario") from exc


def app_from_config(path, *, artifact_dir="runs/service", environments_dir="environments"):
    scenario, default_seed = load_server_config(path)
    return create_app(Registry(scenario, default_seed=default_seed, artifact_dir=artifact_dir,
                               environments_dir=environments_dir))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="Scenario JSON or {seed, scenario} environment JSON")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--artifact-dir", default="runs/service")
    parser.add_argument("--environments-dir", default="environments")
    args = parser.parse_args()
    try:
        app = app_from_config(args.config, artifact_dir=args.artifact_dir,
                              environments_dir=args.environments_dir)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Invalid configuration: {exc}\n")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
