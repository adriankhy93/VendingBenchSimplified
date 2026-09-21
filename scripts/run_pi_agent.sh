#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_dir/configs/model.env"
model_name="${VLLM_MODEL_NAME:-$model_name}"
export VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-262144}"
: "${model_name:?Set model_name in configs/model.env}"
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
export PI_CODING_AGENT_DIR="${PI_CODING_AGENT_DIR:-$project_dir/.pi/agent}"
mkdir -p "$PI_CODING_AGENT_DIR"
for filename in models.json settings.json; do
  if [[ ! -f "$PI_CODING_AGENT_DIR/$filename" ]]; then
    cp "$project_dir/.pi/agent/$filename" "$PI_CODING_AGENT_DIR/$filename"
  fi
done
export PI_CODING_AGENT_SESSION_DIR="$project_dir/runs/pi-sessions"
# Keep Pi's provider registry in sync while preserving its sampling settings.
"$node_bin/node" - "$PI_CODING_AGENT_DIR/models.json" "$model_name" <<'JS'
const fs = require("node:fs");
const [path, modelName] = process.argv.slice(2);
const config = JSON.parse(fs.readFileSync(path, "utf8"));
const provider = config.providers["vending-vllm"];
provider.baseUrl = process.env.VLLM_API_URL || "http://127.0.0.1:8001/v1";
const model = provider.models[0];
if (process.env.VLLM_MAX_MODEL_LEN) {
  const contextWindow = Number(process.env.VLLM_MAX_MODEL_LEN);
  if (!Number.isSafeInteger(contextWindow) || contextWindow <= 0) {
    throw new Error("VLLM_MAX_MODEL_LEN must be a positive integer");
  }
  model.contextWindow = contextWindow;
}
model.id = modelName;
model.name = `${modelName} through local vLLM`;
const updated = JSON.stringify(config, null, 2) + "\n";
if (fs.readFileSync(path, "utf8") !== updated) {
  const temporary = `${path}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, updated);
  fs.renameSync(temporary, path);
}
JS

export PI_OFFLINE=1
export PI_TELEMETRY=0
api_url="${VENDING_API_URL:-http://127.0.0.1:8000}"
export VENDING_API_URL="$api_url"
workspace="${VENDING_AGENT_WORKSPACE:-$project_dir/.pi/workspace}"
mkdir -p "$workspace" "$PI_CODING_AGENT_SESSION_DIR"
cd -- "$workspace"

exec "$pi_bin" --approve --no-context-files --no-extensions -e "$project_dir/.pi/extensions/vending-extension.js" --no-prompt-templates \
  --no-skills --no-builtin-tools --tools vending --provider vending-vllm --model "$model_name" --api-key local \
  --thinking off --name vending-machine \
  --system-prompt "You are an autonomous vending agent. The extension provides the vending skill and structured vending tool. Use only that tool and follow its controller.permitted_actions. Do not ask for user input. Continue until the controller reaches done or halted. Explain decisions briefly using public information." \
  "$@" -- "Create a fresh environment through the vending tool with action create and payload {}. Follow the controller through initialization, daily operation, and terminal result retrieval before deletion. Do not stop between days."
