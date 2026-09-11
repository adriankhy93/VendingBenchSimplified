#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 2 ]]; then
  echo "Usage: $0 CONFIG_JSON ENVIRONMENT_NAME" >&2
  exit 2
fi
export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON_BIN:-python3}" -m vending.environments generate \
  --config "$1" --name "$2" --directory "$project_dir/environments"
