#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-agentperf-vllm-demo}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts/real_vllm}"
WARMUPS="${WARMUPS:-3}"
REPETITIONS="${REPETITIONS:-10}"
TIMEOUT="${TIMEOUT:-180}"

source .venv/bin/activate

python scripts/run_vllm_real_demo.py \
  --base-url "${BASE_URL}" \
  --model "${MODEL}" \
  --output-dir "${OUTPUT_DIR}" \
  --warmups "${WARMUPS}" \
  --repetitions "${REPETITIONS}" \
  --timeout "${TIMEOUT}"

echo "Experiment artifacts written to ${OUTPUT_DIR}"
