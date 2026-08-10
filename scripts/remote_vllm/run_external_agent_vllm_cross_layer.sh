#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-agentperf-vllm-demo}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/m6_external_vllm}"
TASK_LIMIT="${TASK_LIMIT:-5}"
TIMEOUT="${TIMEOUT:-120}"
API_KEY="${API_KEY:-EMPTY}"

source .venv/bin/activate

python scripts/run_external_agent_vllm_cross_layer.py \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --output-dir "${OUTPUT_DIR}" \
  --task-limit "${TASK_LIMIT}" \
  --timeout "${TIMEOUT}" \
  --api-key "${API_KEY}"
