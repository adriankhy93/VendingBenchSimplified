#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_dir/configs/model.env"
model_path="${QWEN_MODEL_PATH:-$model_path}"
model_name="${VLLM_MODEL_NAME:-$model_name}"
export VLLM_MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-262144}"
: "${model_path:?Set model_path in configs/model.env}"
: "${model_name:?Set model_name in configs/model.env}"
PORT_NUMBER="${VLLM_PORT:-8001}"
VLLM_GPU="${VLLM_GPU:-1}"

cache_dir="${VENDING_MODEL_CACHE:-/tmp/vending-vllm-cache}"
mkdir -p "$cache_dir"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-$VLLM_GPU}"
export VLLM_CACHE_ROOT="$cache_dir/vllm"
export TRITON_CACHE_DIR="$cache_dir/triton"
export TORCHINDUCTOR_CACHE_DIR="$cache_dir/inductor"
export TORCH_EXTENSIONS_DIR="$cache_dir/torch_extensions"
export HF_HUB_CACHE="$cache_dir/huggingface"
export HF_HUB_OFFLINE=1
exec "${VLLM_BIN:-vllm}" serve "$model_path" \
  --served-model-name "$model_name" \
  --host "${VLLM_HOST:-127.0.0.1}" --port "$PORT_NUMBER" \
  --tensor-parallel-size "${VLLM_TENSOR_PARALLEL_SIZE:-1}" --language-model-only \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-262144}" --max-num-seqs 1 \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.8}" \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 --generation-config vllm \
  --enforce-eager --seed 0 "$@"
