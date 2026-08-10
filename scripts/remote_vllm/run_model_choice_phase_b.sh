#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

MODEL_ROOT="${MODEL_ROOT:-/workspace/models}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/model_choice_m4_phase_b}"
PORT="${PORT:-18000}"
BASE_URL="http://localhost:${PORT}/v1"
SMALL_PORT="${SMALL_PORT:-18001}"
MEDIUM_PORT="${MEDIUM_PORT:-18002}"
SMALL_BASE_URL="http://localhost:${SMALL_PORT}/v1"
MEDIUM_BASE_URL="http://localhost:${MEDIUM_PORT}/v1"
TIMEOUT="${TIMEOUT:-180}"
REVIEWER_REPEAT_COUNT="${REVIEWER_REPEAT_COUNT:-3}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi
mkdir -p "${MODEL_ROOT}" "${OUTPUT_DIR}/downloads"

download_model() {
  local repo_id="$1"
  local local_dir="$2"
  if [[ -f "${local_dir}/config.json" ]]; then
    echo "Model already present: ${local_dir}"
    return
  fi
  echo "Downloading ${repo_id} to ${local_dir}"
  REPO_ID="${repo_id}" LOCAL_DIR="${local_dir}" "${PYTHON_BIN}" - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id=os.environ["REPO_ID"],
    local_dir=os.environ["LOCAL_DIR"],
)
PY
}

run_single_stage() {
  local tier="$1"
  shift
  PORT="${PORT}" MAX_MODEL_LEN="${MAX_MODEL_LEN}" GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION}" \
    LOG_DIR="${OUTPUT_DIR}/server" scripts/remote_vllm/start_model_choice_server.sh "${tier}"
  set +e
  "$@"
  local status="$?"
  set -e
  LOG_DIR="${OUTPUT_DIR}/server" scripts/remote_vllm/stop_model_choice_server.sh
  if [[ "${status}" -ne 0 ]]; then
    echo "Stage failed with status ${status}: $*" >&2
    exit "${status}"
  fi
}

download_model "Qwen/Qwen3-4B" "${MODEL_ROOT}/Qwen3-4B"
download_model "Qwen/Qwen3-1.7B" "${MODEL_ROOT}/Qwen3-1.7B"
download_model "Qwen/Qwen3-0.6B" "${MODEL_ROOT}/Qwen3-0.6B"

run_single_stage strong \
  "${PYTHON_BIN}" scripts/run_model_choice_phase_b.py \
    --stage strong-control \
    --tier strong \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-4b \
    --output-dir "${OUTPUT_DIR}" \
    --timeout "${TIMEOUT}"

run_single_stage medium \
  "${PYTHON_BIN}" scripts/run_model_choice_phase_b.py \
    --stage reviewer-candidates \
    --tier medium \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-1.7b \
    --output-dir "${OUTPUT_DIR}" \
    --repeat-count "${REVIEWER_REPEAT_COUNT}" \
    --timeout "${TIMEOUT}"

run_single_stage small \
  "${PYTHON_BIN}" scripts/run_model_choice_phase_b.py \
    --stage reviewer-candidates \
    --tier small \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-0.6b \
    --output-dir "${OUTPUT_DIR}" \
    --repeat-count "${REVIEWER_REPEAT_COUNT}" \
    --timeout "${TIMEOUT}"

run_single_stage strong \
  "${PYTHON_BIN}" scripts/run_model_choice_phase_b.py \
    --stage reviewer-continuations \
    --tier strong \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-4b \
    --output-dir "${OUTPUT_DIR}" \
    --repeat-count "${REVIEWER_REPEAT_COUNT}" \
    --timeout "${TIMEOUT}"

LOG_DIR="${OUTPUT_DIR}/server" \
SMALL_PORT="${SMALL_PORT}" \
MEDIUM_PORT="${MEDIUM_PORT}" \
MAX_MODEL_LEN="${MAX_MODEL_LEN}" \
scripts/remote_vllm/start_model_choice_mixed_servers.sh
set +e
"${PYTHON_BIN}" scripts/run_model_choice_phase_b.py \
  --stage mixed-end-to-end \
  --small-base-url "${SMALL_BASE_URL}" \
  --medium-base-url "${MEDIUM_BASE_URL}" \
  --small-served-model agentperf-qwen3-0.6b \
  --medium-served-model agentperf-qwen3-1.7b \
  --output-dir "${OUTPUT_DIR}" \
  --timeout "${TIMEOUT}"
mixed_status="$?"
set -e
LOG_DIR="${OUTPUT_DIR}/server" scripts/remote_vllm/stop_model_choice_mixed_servers.sh
if [[ "${mixed_status}" -ne 0 ]]; then
  echo "Mixed end-to-end replay failed with status ${mixed_status}" >&2
  exit "${mixed_status}"
fi

"${PYTHON_BIN}" scripts/run_model_choice_phase_b.py \
  --stage assemble \
  --output-dir "${OUTPUT_DIR}"

agentperf analyze-model-choice \
  "${OUTPUT_DIR}/model_choice_phase_b_comparison.json" \
  --show-provenance | tee "${OUTPUT_DIR}/model_choice_phase_b_report.stdout.txt"

echo "M4 Phase B artifacts written to ${OUTPUT_DIR}"
