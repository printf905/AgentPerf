#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

MODEL_ROOT="${MODEL_ROOT:-/workspace/models}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.25}"
LOG_DIR="${LOG_DIR:-artifacts/model_choice_m4/server}"
mkdir -p "${LOG_DIR}"

declare -A MODELS=(
  [small]="Qwen/Qwen3-0.6B"
  [medium]="Qwen/Qwen3-1.7B"
  [strong]="Qwen/Qwen3-4B"
)

declare -A LOCAL_PATHS=(
  [small]="${MODEL_ROOT}/Qwen3-0.6B"
  [medium]="${MODEL_ROOT}/Qwen3-1.7B"
  [strong]="${MODEL_ROOT}/Qwen3-4B"
)

declare -A PORTS=(
  [small]="8001"
  [medium]="8002"
  [strong]="8003"
)

declare -A SERVED_NAMES=(
  [small]="agentperf-qwen3-0.6b"
  [medium]="agentperf-qwen3-1.7b"
  [strong]="agentperf-qwen3-4b"
)

for tier in small medium strong; do
  model_path="${LOCAL_PATHS[$tier]}"
  if [[ ! -f "${model_path}/config.json" ]]; then
    echo "Missing ${tier} model at ${model_path}; download it before starting servers." >&2
    exit 2
  fi
done

for tier in small medium strong; do
  port="${PORTS[$tier]}"
  served="${SERVED_NAMES[$tier]}"
  model_path="${LOCAL_PATHS[$tier]}"
  log_path="${LOG_DIR}/${tier}.log"
  echo "Starting ${tier}: ${model_path} on port ${port} as ${served}"
  nohup vllm serve "${model_path}" \
    --served-model-name "${served}" \
    --host 0.0.0.0 \
    --port "${port}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --enable-prefix-caching \
    --prefix-caching-hash-algo sha256_cbor \
    --enable-prompt-tokens-details \
    --enable-per-request-metrics \
    >"${log_path}" 2>&1 &
  echo "$!" >"${LOG_DIR}/${tier}.pid"
done

for tier in small medium strong; do
  port="${PORTS[$tier]}"
  for attempt in $(seq 1 60); do
    if curl -sf "http://localhost:${port}/v1/models" >/dev/null; then
      echo "${tier} ready on port ${port}"
      break
    fi
    if [[ "${attempt}" == "60" ]]; then
      echo "${tier} did not become ready on port ${port}" >&2
      tail -n 120 "${LOG_DIR}/${tier}.log" >&2 || true
      exit 1
    fi
    sleep 10
  done
done

cat <<EOF
Endpoints:
  small=http://localhost:8001/v1,agentperf-qwen3-0.6b
  medium=http://localhost:8002/v1,agentperf-qwen3-1.7b
  strong=http://localhost:8003/v1,agentperf-qwen3-4b
EOF
