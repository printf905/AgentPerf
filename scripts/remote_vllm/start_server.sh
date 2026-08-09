#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-0.6B}"
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-agentperf-vllm-demo}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-12288}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.80}"
LOG_DIR="${LOG_DIR:-artifacts/real_vllm/server}"

mkdir -p "${LOG_DIR}"
source .venv/bin/activate

echo "Starting vLLM server"
echo "Model: ${MODEL}"
echo "Served model name: ${SERVED_MODEL_NAME}"
echo "Logs: ${LOG_DIR}/vllm_server.log"

exec vllm serve "${MODEL}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --enable-prefix-caching \
  --prefix-caching-hash-algo sha256_cbor \
  --enable-prompt-tokens-details \
  --enable-per-request-metrics \
  2>&1 | tee "${LOG_DIR}/vllm_server.log"
