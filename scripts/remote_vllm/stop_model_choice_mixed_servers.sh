#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

LOG_DIR="${LOG_DIR:-artifacts/model_choice_m4_phase_b/server}"

for tier in small medium; do
  pid_path="${LOG_DIR}/${tier}.pid"
  if [[ ! -f "${pid_path}" ]]; then
    echo "No ${tier} mixed-server PID file found."
    continue
  fi
  pid="$(cat "${pid_path}")"
  if kill -0 "${pid}" 2>/dev/null; then
    echo "Stopping ${tier} mixed-server PID ${pid}"
    kill "${pid}" || true
    for _ in $(seq 1 30); do
      if ! kill -0 "${pid}" 2>/dev/null; then
        break
      fi
      sleep 2
    done
    if kill -0 "${pid}" 2>/dev/null; then
      echo "${tier} server PID ${pid} did not exit; sending SIGKILL" >&2
      kill -9 "${pid}" || true
    fi
  else
    echo "Recorded ${tier} PID ${pid} is not running."
  fi
  rm -f "${pid_path}"
done

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
