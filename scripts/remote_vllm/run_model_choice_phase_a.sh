#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

MODEL_ROOT="${MODEL_ROOT:-/workspace/models}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/model_choice_m4}"
PORT="${PORT:-18000}"
BASE_URL="http://localhost:${PORT}/v1"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
TIMEOUT="${TIMEOUT:-180}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.90}"

source .venv/bin/activate
mkdir -p "${MODEL_ROOT}" "${OUTPUT_DIR}/downloads"

download_model() {
  local repo_id="$1"
  local local_dir="$2"
  if [[ -f "${local_dir}/config.json" ]]; then
    echo "Model already present: ${local_dir}"
    return
  fi
  echo "Downloading ${repo_id} to ${local_dir}"
  REPO_ID="${repo_id}" LOCAL_DIR="${local_dir}" python - <<'PY'
import os
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id=os.environ["REPO_ID"],
    local_dir=os.environ["LOCAL_DIR"],
    local_dir_use_symlinks=False,
)
PY
}

download_model "Qwen/Qwen3-4B" "${MODEL_ROOT}/Qwen3-4B"
download_model "Qwen/Qwen3-1.7B" "${MODEL_ROOT}/Qwen3-1.7B"
download_model "Qwen/Qwen3-0.6B" "${MODEL_ROOT}/Qwen3-0.6B"

run_stage() {
  local tier="$1"
  shift
  PORT="${PORT}" MAX_MODEL_LEN="${MAX_MODEL_LEN}" GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION}" \
    scripts/remote_vllm/start_model_choice_server.sh "${tier}"
  set +e
  "$@"
  local status="$?"
  set -e
  scripts/remote_vllm/stop_model_choice_server.sh
  if [[ "${status}" -ne 0 ]]; then
    echo "Stage failed with status ${status}: $*" >&2
    exit "${status}"
  fi
}

run_stage strong \
  python scripts/run_model_choice_phase_a.py \
    --stage strong-baseline \
    --tier strong \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-4b \
    --output-dir "${OUTPUT_DIR}" \
    --timeout "${TIMEOUT}"

run_stage medium \
  python scripts/run_model_choice_phase_a.py \
    --stage candidate-tier \
    --tier medium \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-1.7b \
    --output-dir "${OUTPUT_DIR}" \
    --timeout "${TIMEOUT}"

run_stage small \
  python scripts/run_model_choice_phase_a.py \
    --stage candidate-tier \
    --tier small \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-0.6b \
    --output-dir "${OUTPUT_DIR}" \
    --timeout "${TIMEOUT}"

run_stage strong \
  python scripts/run_model_choice_phase_a.py \
    --stage strong-continuations \
    --tier strong \
    --base-url "${BASE_URL}" \
    --served-model agentperf-qwen3-4b \
    --output-dir "${OUTPUT_DIR}" \
    --timeout "${TIMEOUT}"

python scripts/run_model_choice_phase_a.py \
  --stage assemble \
  --output-dir "${OUTPUT_DIR}"

agentperf analyze-model-choice \
  "${OUTPUT_DIR}/model_choice_comparison.json" \
  --show-provenance | tee "${OUTPUT_DIR}/model_choice_report.stdout.txt"

echo "M4 Phase A artifacts written to ${OUTPUT_DIR}"
