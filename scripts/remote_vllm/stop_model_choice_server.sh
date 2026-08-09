#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f .venv/bin/activate ]]; then
  source .venv/bin/activate
fi

LOG_DIR="${LOG_DIR:-artifacts/model_choice_m4/server}"
PID_FILE="${LOG_DIR}/active.pid"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "No active model-choice vLLM PID file found."
  nvidia-smi || true
  exit 0
fi

PID="$(cat "${PID_FILE}")"
if kill -0 "${PID}" 2>/dev/null; then
  echo "Stopping model-choice vLLM server PID ${PID}"
  kill "${PID}" || true
  for _ in $(seq 1 30); do
    if ! kill -0 "${PID}" 2>/dev/null; then
      break
    fi
    sleep 2
  done
  if kill -0 "${PID}" 2>/dev/null; then
    echo "Server PID ${PID} did not exit after SIGTERM; sending SIGKILL" >&2
    kill -9 "${PID}" || true
  fi
else
  echo "Recorded PID ${PID} is not running."
fi

rm -f "${PID_FILE}" "${LOG_DIR}/active.tier"
python - <<'PY'
import gc

try:
    import torch

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
except Exception as exc:  # noqa: BLE001
    print(f"CUDA cache cleanup probe skipped: {exc}")
gc.collect()
PY
nvidia-smi || true
