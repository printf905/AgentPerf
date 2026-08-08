#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000/v1}"
MODEL="${MODEL:-agentperf-vllm-demo}"
OUT_DIR="${OUT_DIR:-artifacts/real_vllm/smoke}"
REQUEST_ID="agentperf-smoke-$(date +%s)"

mkdir -p "${OUT_DIR}"

echo "Checking model endpoint"
curl -fsS "${BASE_URL}/models" > "${OUT_DIR}/models.json"

echo "Sending one attributed request"
curl -fsS "${BASE_URL}/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"${MODEL}\",
    \"messages\": [
      {\"role\": \"system\", \"content\": \"You are a concise validator.\"},
      {\"role\": \"user\", \"content\": \"Return JSON with ok=true.\"}
    ],
    \"max_tokens\": 16,
    \"temperature\": 0,
    \"request_id\": \"${REQUEST_ID}\",
    \"return_token_ids\": true,
    \"return_prompt_text\": true
  }" > "${OUT_DIR}/chat_completion.json"

OUT_DIR="${OUT_DIR}" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["OUT_DIR"]) / "chat_completion.json"
data = json.loads(path.read_text())
usage = data.get("usage") or {}
metrics = data.get("metrics") or {}
required = {
    "response.id": data.get("id"),
    "usage.prompt_tokens": usage.get("prompt_tokens"),
    "usage.completion_tokens": usage.get("completion_tokens"),
    "prompt_token_ids": data.get("prompt_token_ids"),
    "choices[0].token_ids": (data.get("choices") or [{}])[0].get("token_ids"),
    "metrics.queue_time_ms": metrics.get("queue_time_ms"),
    "metrics.time_to_first_token_ms": metrics.get("time_to_first_token_ms"),
    "metrics.generation_time_ms": metrics.get("generation_time_ms"),
    "metrics.mean_itl_ms": metrics.get("mean_itl_ms"),
}
missing = [name for name, value in required.items() if value is None]
if missing:
    raise SystemExit(f"Missing critical telemetry fields: {missing}")
print("Per-request telemetry smoke test passed")
PY

METRICS_URL="${BASE_URL%/v1}/metrics"
if curl -fsS "${METRICS_URL}" > "${OUT_DIR}/prometheus_metrics.txt"; then
  grep -E "vllm:(prefix_cache|kv_cache|request_|time_to_first_token)" \
    "${OUT_DIR}/prometheus_metrics.txt" > "${OUT_DIR}/prometheus_relevant_metrics.txt" || true
else
  echo "Prometheus /metrics endpoint unavailable" > "${OUT_DIR}/prometheus_relevant_metrics.txt"
fi

echo "Smoke artifacts written to ${OUT_DIR}"
