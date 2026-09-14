#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 1 ]]; then
  echo "Usage: bash start_env.sh CONFIG_JSON" >&2
  exit 2
fi
config_path="$1"
if [[ ! -f "$config_path" ]]; then
  echo "Configuration file not found: $config_path" >&2
  exit 2
fi

export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$project_dir"
exec "${PYTHON_BIN:-python3}" -m vending.server "$config_path" \
  --host "${VENDING_HOST:-127.0.0.1}" \
  --port "${VENDING_PORT:-8000}" \
  --artifact-dir "${VENDING_ARTIFACT_DIR:-runs/service}" \
  --environments-dir "${VENDING_ENVIRONMENTS_DIR:-environments}"
