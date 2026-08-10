#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

MODEL_ROOT="${MODEL_ROOT:-/workspace/models}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
LOG_DIR="${LOG_DIR:-artifacts/model_choice_m4_phase_b/server}"
SMALL_PORT="${SMALL_PORT:-18001}"
MEDIUM_PORT="${MEDIUM_PORT:-18002}"
SMALL_GPU_MEMORY_UTILIZATION="${SMALL_GPU_MEMORY_UTILIZATION:-0.28}"
MEDIUM_GPU_MEMORY_UTILIZATION="${MEDIUM_GPU_MEMORY_UTILIZATION:-0.48}"
mkdir -p "${LOG_DIR}"

start_server() {
  local tier="$1"
  local model_path="$2"
  local served_name="$3"
  local port="$4"
  local gpu_memory_utilization="$5"
  local log_path="${LOG_DIR}/${tier}.log"
  local pid_path="${LOG_DIR}/${tier}.pid"

  if [[ ! -f "${model_path}/config.json" ]]; then
    echo "Missing ${tier} model at ${model_path}; download it before starting." >&2
    exit 2
  fi
  if [[ -f "${pid_path}" ]] && kill -0 "$(cat "${pid_path}")" 2>/dev/null; then
    echo "${tier} server is already running: PID $(cat "${pid_path}")" >&2
    exit 3
  fi

  echo "Starting ${tier}: ${model_path} on port ${port} as ${served_name}"
  echo "GPU memory utilization: ${gpu_memory_utilization}"
  nohup vllm serve "${model_path}" \
    --served-model-name "${served_name}" \
    --host 0.0.0.0 \
    --port "${port}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${gpu_memory_utilization}" \
    --enable-prefix-caching \
    --prefix-caching-hash-algo sha256_cbor \
    --enable-prompt-tokens-details \
    --enable-per-request-metrics \
    >"${log_path}" 2>&1 &
  echo "$!" >"${pid_path}"

  for attempt in $(seq 1 90); do
    if curl -sf "http://localhost:${port}/v1/models" >/dev/null; then
      echo "${tier} ready on port ${port}"
      return
    fi
    if ! kill -0 "$(cat "${pid_path}")" 2>/dev/null; then
      echo "${tier} server exited before readiness" >&2
      tail -n 160 "${log_path}" >&2 || true
      exit 1
    fi
    sleep 10
  done

  echo "${tier} did not become ready on port ${port}" >&2
  tail -n 160 "${log_path}" >&2 || true
  exit 1
}

start_server \
  small \
  "${MODEL_ROOT}/Qwen3-0.6B" \
  agentperf-qwen3-0.6b \
  "${SMALL_PORT}" \
  "${SMALL_GPU_MEMORY_UTILIZATION}"

start_server \
  medium \
  "${MODEL_ROOT}/Qwen3-1.7B" \
  agentperf-qwen3-1.7b \
  "${MEDIUM_PORT}" \
  "${MEDIUM_GPU_MEMORY_UTILIZATION}"

nvidia-smi || true

cat <<EOF
Endpoints:
  small=http://localhost:${SMALL_PORT}/v1,agentperf-qwen3-0.6b
  medium=http://localhost:${MEDIUM_PORT}/v1,agentperf-qwen3-1.7b
EOF
