#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:30000/v1}"
METRICS_URL="${METRICS_URL:-http://localhost:30000/metrics}"
MODEL="${MODEL:-agentperf-sglang-demo}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/m17_sglang}"
TASK_LIMIT="${TASK_LIMIT:-5}"
TIMEOUT="${TIMEOUT:-120}"
API_KEY="${API_KEY:-EMPTY}"

source .venv/bin/activate

python scripts/run_external_agent_sglang_cross_layer.py \
  --base-url "${BASE_URL}" \
  --metrics-url "${METRICS_URL}" \
  --model "${MODEL}" \
  --output-dir "${OUTPUT_DIR}" \
  --task-limit "${TASK_LIMIT}" \
  --timeout "${TIMEOUT}" \
  --api-key "${API_KEY}"
