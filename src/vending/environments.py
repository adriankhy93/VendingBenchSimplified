"""Self-contained, named environment definitions; never persist running episodes."""

import argparse
import hashlib
import json
import secrets
from pathlib import Path
from typing import Literal
from pydantic import Field, model_validator
from .config import Scenario, StrictModel, PairQuote
from .suppliers import build_quotes

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"


class EnvironmentConfig(StrictModel):
    seed: int | None = Field(default=0, ge=0, le=2**63 - 1)
    scenario: Scenario = Field(default_factory=Scenario)


class SavedEnvironment(EnvironmentConfig):
    seed: int = Field(default=0, ge=0, le=2**63 - 1)
    format_version: Literal[1] = 1
    name: str = Field(pattern=NAME_PATTERN)

    @model_validator(mode="after")
    def complete_quotes(self):
        if len(self.scenario.supplier_quotes) != len(self.scenario.products) * len(
            self.scenario.suppliers
        ):
            raise ValueError(
                "saved environments must contain every resolved supplier/product quote"
            )
        return self


def environment_path(directory, name):
    import re

    if not isinstance(name, str) or not re.fullmatch(NAME_PATTERN, name):
        raise ValueError(
            "environment name must use letters, digits, hyphens, or underscores"
        )
    root = Path(directory).resolve()
    path = root / f"{name}.json"
    if path.resolve().parent != root:
        raise ValueError("environment file must be inside the environment directory")
    return path


def load_environment(directory, name):
    path = environment_path(directory, name)
    raw = path.read_bytes()
    saved = SavedEnvironment.model_validate_json(raw)
    if saved.name != name:
        raise ValueError("saved environment name does not match its filename")
    return saved, hashlib.sha256(raw).hexdigest()


def generate(config_path, name, directory="environments", seed=None):
    config = EnvironmentConfig.model_validate_json(Path(config_path).read_text())
    if seed is not None:
        config = EnvironmentConfig.model_validate(config.model_dump() | dict(seed=seed))
    path = environment_path(directory, name)
    resolved_seed = config.seed if config.seed is not None else secrets.randbits(63)
    quotes = build_quotes(config.scenario.products, resolved_seed, config.scenario)
    resolved = tuple(
        PairQuote(
            supplier_id=q.supplier_id,
            product_id=q.product_id,
            category=q.category,
            minimum_cents=q.minimum,
            listed_cents=q.listed,
        )
        for q in quotes.values()
    )
    scenario = Scenario.model_validate(
        config.scenario.model_dump() | dict(supplier_quotes=resolved)
    )
    saved = SavedEnvironment(name=name, seed=resolved_seed, scenario=scenario)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement of a reproducible experiment.
    with path.open("x") as stream:
        stream.write(saved.model_dump_json(indent=2) + "\n")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate")
    create.add_argument("--config", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--directory", default="environments")
    create.add_argument("--seed", type=int, default=None)
    listing = commands.add_parser("list")
    listing.add_argument("--directory", default="environments")
    args = parser.parse_args()
    try:
        if args.command == "generate":
            print(generate(args.config, args.name, args.directory, seed=args.seed))
        else:
            for path in sorted(Path(args.directory).glob("*.json")):
                saved, digest = load_environment(args.directory, path.stem)
                print(
                    f"{saved.name}\t{len(saved.scenario.products)} products\t{len(saved.scenario.suppliers)} suppliers\tseed={saved.seed}\t{digest[:12]}"
                )
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
