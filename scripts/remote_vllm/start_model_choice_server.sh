#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

TIER="${1:-${MODEL_TIER:-strong}}"
MODEL_ROOT="${MODEL_ROOT:-/workspace/models}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
PORT="${PORT:-18000}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
LOG_DIR="${LOG_DIR:-artifacts/model_choice_m4/server}"
mkdir -p "${LOG_DIR}"

case "${TIER}" in
  small)
    MODEL_PATH="${MODEL_ROOT}/Qwen3-0.6B"
    SERVED_NAME="agentperf-qwen3-0.6b"
    ;;
  medium)
    MODEL_PATH="${MODEL_ROOT}/Qwen3-1.7B"
    SERVED_NAME="agentperf-qwen3-1.7b"
    ;;
  strong)
    MODEL_PATH="${MODEL_ROOT}/Qwen3-4B"
    SERVED_NAME="agentperf-qwen3-4b"
    ;;
  *)
    echo "Usage: $0 {small|medium|strong}" >&2
    exit 2
    ;;
esac

if [[ ! -f "${MODEL_PATH}/config.json" ]]; then
  echo "Missing ${TIER} model at ${MODEL_PATH}; download it before starting vLLM." >&2
  exit 2
fi

if [[ -f "${LOG_DIR}/active.pid" ]] && kill -0 "$(cat "${LOG_DIR}/active.pid")" 2>/dev/null; then
  echo "A model-choice vLLM server is already running: PID $(cat "${LOG_DIR}/active.pid")" >&2
  exit 3
fi

LOG_PATH="${LOG_DIR}/${TIER}.log"
echo "Starting ${TIER}: ${MODEL_PATH} on port ${PORT} as ${SERVED_NAME}"
echo "MAX_MODEL_LEN=${MAX_MODEL_LEN}"
echo "GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION}"
nohup vllm serve "${MODEL_PATH}" \
  --served-model-name "${SERVED_NAME}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --enable-prefix-caching \
  --prefix-caching-hash-algo sha256_cbor \
  --enable-prompt-tokens-details \
  --enable-per-request-metrics \
  >"${LOG_PATH}" 2>&1 &

PID="$!"
echo "${PID}" >"${LOG_DIR}/active.pid"
echo "${TIER}" >"${LOG_DIR}/active.tier"

for attempt in $(seq 1 90); do
  if curl -sf "http://localhost:${PORT}/v1/models" >/dev/null; then
    echo "${TIER} ready on port ${PORT}"
    cat <<EOF
Endpoint:
  ${TIER}=http://localhost:${PORT}/v1,${SERVED_NAME}
EOF
    exit 0
  fi
  if ! kill -0 "${PID}" 2>/dev/null; then
    echo "${TIER} server exited before readiness" >&2
    tail -n 160 "${LOG_PATH}" >&2 || true
    exit 1
  fi
  sleep 10
done

echo "${TIER} did not become ready on port ${PORT}" >&2
tail -n 160 "${LOG_PATH}" >&2 || true
exit 1
