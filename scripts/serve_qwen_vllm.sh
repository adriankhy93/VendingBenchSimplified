#!/usr/bin/env bash
set -euo pipefail

model_path="${QWEN_MODEL_PATH:-/storage/models/Qwen3.5-2B}"
# model_path="${QWEN_MODEL_PATH:-/storage/models/Qwen3.6-27B/}"

cache_dir="${VENDING_MODEL_CACHE:-/tmp/vending-vllm-cache}"
mkdir -p "$cache_dir"
export CUDA_VISIBLE_DEVICES="${VLLM_GPU:-1}"
export VLLM_CACHE_ROOT="$cache_dir/vllm"
export TRITON_CACHE_DIR="$cache_dir/triton"
export TORCHINDUCTOR_CACHE_DIR="$cache_dir/inductor"
export TORCH_EXTENSIONS_DIR="$cache_dir/torch_extensions"
export HF_HUB_CACHE="$cache_dir/huggingface"
export HF_HUB_OFFLINE=1
exec "${VLLM_BIN:-vllm}" serve "$model_path" \
  --served-model-name qwen3.5-2b \
  --host 127.0.0.1 --port "${VLLM_PORT:-8001}" \
  --tensor-parallel-size "${VLLM_TENSOR_PARALLEL_SIZE:-1}" --language-model-only \
  --max-model-len "${VLLM_MAX_MODEL_LEN:-262144}" --max-num-seqs 1 \
  --gpu-memory-utilization "${VLLM_GPU_MEMORY_UTILIZATION:-0.6}" \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 --generation-config vllm \
  --enforce-eager --seed 0 "$@"
