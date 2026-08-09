#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-agentperf-vllm-demo}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/vllm_cache_semantics}"
STABLE_TARGETS="${STABLE_TARGETS:-1024,4096,8192}"
TIMEOUT="${TIMEOUT:-180}"
MAX_TOKENS="${MAX_TOKENS:-8}"
RUN_LABEL="${RUN_LABEL:-}"

source .venv/bin/activate

python scripts/run_vllm_cache_semantics.py \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --output-dir "${OUTPUT_DIR}" \
  --stable-targets "${STABLE_TARGETS}" \
  --max-tokens "${MAX_TOKENS}" \
  ${RUN_LABEL:+--run-label "${RUN_LABEL}"} \
  --timeout "${TIMEOUT}"

echo "Cache semantics artifacts written to ${OUTPUT_DIR}"
