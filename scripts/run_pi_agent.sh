#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
pi_bin="${PI_BIN:-$project_dir/.tools/pi/node_modules/.bin/pi}"
node_bin="$project_dir/.tools/node-v22.19.0-linux-x64/bin"

if [[ ! -x "$pi_bin" ]]; then
  echo "Pi is not installed. See README.md: Pi vending agent." >&2
  exit 2
fi
if [[ ! -x "$node_bin/node" ]]; then
  echo "Local Node runtime is missing: $node_bin/node" >&2
  exit 2
fi

export PATH="$node_bin:$PATH"
export PI_CODING_AGENT_DIR="$project_dir/.pi/agent"
export PI_CODING_AGENT_SESSION_DIR="$project_dir/runs/pi-sessions"
export PI_OFFLINE=1
export PI_TELEMETRY=0
api_url="${VENDING_API_URL:-http://127.0.0.1:8000}"
export VENDING_API_URL="$api_url"
workspace="$project_dir/.pi/workspace"
mkdir -p "$workspace" "$PI_CODING_AGENT_SESSION_DIR"
cd -- "$workspace"

exec "$pi_bin" --approve --no-context-files --no-extensions -e "$project_dir/.pi/extensions/vending-guard.js" --no-prompt-templates \
  --no-skills --skill "$project_dir/.pi/skills/vending-machine" \
  --tools read,bash --provider vending-vllm --model qwen3.5-2b --api-key local \
  --thinking off --name vending-machine \
  --system-prompt "You are an autonomous HTTP API agent. Read the vending-machine skill before acting. The API base URL for this run is $api_url. Use only the skill's documented HTTP workflow. Never inspect files outside the agent workspace. Do not ask the user questions or wait for further instructions: choose actions from public API results and continue independently until the environment ends or becomes unavailable. Keep the full env_id returned by POST /env, including its env_ prefix, and call observe as POST /env/{env_id}/observe with an empty JSON body {}. Never send product_id or unit_price_cents to observe; those belong to set_price and make_offer." \
  "$@" -- "The server is already running at $api_url. Create a fresh environment with POST $api_url/env; do not use ENV_ID literally. Immediately call observe as POST $api_url/env/{env_id}/observe with an empty JSON body {} and the returned env_... id, then operate the environment only through the documented API. Choose a profitable strategy from public information, keep taking actions without requesting user input until the environment ends or becomes unavailable, then delete the environment."
