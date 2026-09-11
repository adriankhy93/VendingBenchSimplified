#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON_BIN:-python3}" -m viewer.api --runs-dir "$project_dir/runs" "$@"
