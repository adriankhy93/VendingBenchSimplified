#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 CONFIG_JSON ENVIRONMENT_NAME [SEED|random]" >&2
  exit 2
fi

seed_flag=()
if [[ $# -eq 3 ]]; then
  if [[ "$3" == "random" ]]; then
    # Keep the generated seed inside the accepted 0..2^63-1 range.
    random_u64="$(od -An -N8 -tu8 /dev/urandom | tr -d ' ')"
    random_seed="$((random_u64 & 0x7fffffffffffffff))"
    echo "Using randomized seed: $random_seed"
    seed_flag=(--seed "$random_seed")
  else
    seed_flag=(--seed "$3")
  fi
fi

export PYTHONPATH="$project_dir/src${PYTHONPATH:+:$PYTHONPATH}"
exec "${PYTHON_BIN:-python3}" -m vending.environments generate \
  --config "$1" --name "$2" --directory "$project_dir/environments" "${seed_flag[@]}"
