#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ "${AGENTPERF_ALLOW_CONCURRENT_MODEL_CHOICE:-0}" != "1" ]]; then
  cat >&2 <<'EOF'
This legacy script starts all M4 model-choice servers concurrently.
Do not use it for 24GB Phase A role-sensitivity profiling.

Use scripts/remote_vllm/run_model_choice_phase_a.sh instead, which loads one
model at a time. To intentionally run concurrent servers on a larger GPU, set:

  AGENTPERF_ALLOW_CONCURRENT_MODEL_CHOICE=1
EOF
  exit 2
fi

MODEL_ROOT="${MODEL_ROOT:-/workspace/models}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
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
  [small]="${SMALL_PORT:-18001}"
  [medium]="${MEDIUM_PORT:-18002}"
  [strong]="${STRONG_PORT:-18003}"
)

declare -A SERVED_NAMES=(
  [small]="agentperf-qwen3-0.6b"
  [medium]="agentperf-qwen3-1.7b"
  [strong]="agentperf-qwen3-4b"
)

declare -A GPU_MEMORY_FRACTIONS=(
  [small]="${SMALL_GPU_MEMORY_UTILIZATION:-0.16}"
  [medium]="${MEDIUM_GPU_MEMORY_UTILIZATION:-0.26}"
  [strong]="${STRONG_GPU_MEMORY_UTILIZATION:-0.44}"
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
  gpu_memory_utilization="${GPU_MEMORY_FRACTIONS[$tier]}"
  log_path="${LOG_DIR}/${tier}.log"
  echo "Starting ${tier}: ${model_path} on port ${port} as ${served}"
  echo "GPU memory utilization: ${gpu_memory_utilization}"
  nohup vllm serve "${model_path}" \
    --served-model-name "${served}" \
    --host 0.0.0.0 \
    --port "${port}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${gpu_memory_utilization}" \
    --enable-prefix-caching \
    --prefix-caching-hash-algo sha256_cbor \
    --enable-prompt-tokens-details \
    --enable-per-request-metrics \
    >"${log_path}" 2>&1 &
  echo "$!" >"${LOG_DIR}/${tier}.pid"

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
  small=http://localhost:${PORTS[small]}/v1,agentperf-qwen3-0.6b
  medium=http://localhost:${PORTS[medium]}/v1,agentperf-qwen3-1.7b
  strong=http://localhost:${PORTS[strong]}/v1,agentperf-qwen3-4b
EOF
