#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -lt 1 ]]; then
  echo "Usage: $0 ENVIRONMENT_NAME_OR_CONFIG_JSON [run_pi_agent options]" >&2
  exit 2
fi
target="$1"
shift

if [[ -f "$target" ]]; then
  config_path="$target"
else
  config_path="$project_dir/environments/$target.json"
fi
if [[ ! -f "$config_path" ]]; then
  echo "Environment/config not found: $target" >&2
  exit 2
fi

log_dir="$project_dir/runs/service"
mkdir -p "$log_dir"
log_path="$log_dir/run-environment-$(date +%s).log"

cleanup() {
  if [[ -n "${server_pid:-}" ]]; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

bash "$project_dir/start_env.sh" "$config_path" >"$log_path" 2>&1 &
server_pid="$!"

for _ in $(seq 1 100); do
  if curl -fsS "${VENDING_API_URL:-http://127.0.0.1:8000}/openapi.json" >/dev/null 2>&1; then
    exec "$project_dir/scripts/run_pi_agent.sh" "$@"
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "Server failed to start; see $log_path" >&2
    exit 1
  fi
  sleep 0.1
done

echo "Timed out waiting for server start; see $log_path" >&2
exit 1
