#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 ENVIRONMENT_NAME [--agent idle|listed|negotiating|model] [runner options]" >&2
  exit 2
fi
environment_name="$1"
shift
export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
cd -- "$project_dir"
exec "${PYTHON_BIN:-python3}" -m harness.runner --local \
  --environment "$environment_name" --environments-dir "$project_dir/environments" "$@"
