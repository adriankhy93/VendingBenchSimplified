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
  --no-skills --no-tools --provider vending-vllm --model qwen3.5-2b --api-key local \
  --thinking off --name vending-machine \
  --system-prompt "You are an autonomous vending agent. The extension provides the vending skill and structured vending tool. Use only that tool and follow its controller.permitted_actions. Do not ask for user input. Continue until the controller reaches done or halted. Explain decisions briefly using public information." \
  "$@" -- "Create a fresh environment through the vending tool with action create and payload {}. Follow the controller through initialization, daily operation, and terminal result retrieval before deletion. Do not stop between days."
