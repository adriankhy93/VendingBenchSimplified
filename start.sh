#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -ne 3 || ( "$1" != train && "$1" != test ) ]]; then
  echo "Usage: bash start.sh train|test ENV_PORT DASHBOARD_PORT" >&2
  exit 2
fi
validate_port() {
  if [[ ! "$1" =~ ^[0-9]{1,5}$ ]] || (( 10#$1 < 1 || 10#$1 > 65535 )); then
    echo "Invalid port: $1. Use an integer from 1 to 65535." >&2
    exit 2
  fi
}
validate_port "$2"
validate_port "$3"
export VENDING_API_PORT="$((10#$2))"
export VENDING_DASHBOARD_PORT="$((10#$3))"
if [[ "$VENDING_API_PORT" == "$VENDING_DASHBOARD_PORT" ]]; then
  echo "Dashboard port must differ from the API port ($VENDING_API_PORT)." >&2
  exit 2
fi
cd -- "$project_dir"
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
export VENDING_CONFIG=environment.json
if [[ "$1" == test ]]; then
  export VENDING_CONFIG=environment-eval.json
fi
mkdir -p runs/service runs/pi-sessions

docker compose up -d --build --wait environment dashboard
echo "Ready ($1). Dashboard: http://localhost:$VENDING_DASHBOARD_PORT"
echo "Environment API: http://localhost:$VENDING_API_PORT"
