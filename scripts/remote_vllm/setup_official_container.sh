#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PREFLIGHT_DIR="${PREFLIGHT_DIR:-artifacts/model_choice_m4/container_preflight}"
VLLM_IMPORT_TIMEOUT_SECONDS="${VLLM_IMPORT_TIMEOUT_SECONDS:-60}"
mkdir -p "${PREFLIGHT_DIR}"

echo "Recording official vLLM container preflight in ${PREFLIGHT_DIR}"

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi | tee "${PREFLIGHT_DIR}/nvidia-smi.txt"
else
  echo "nvidia-smi is not available. This container is not attached to a GPU." >&2
  exit 1
fi

{
  echo "python_bin=${PYTHON_BIN}"
  "${PYTHON_BIN}" --version
  command -v vllm || true
} | tee "${PREFLIGHT_DIR}/environment.txt"

VLLM_IMPORT_STDOUT="${PREFLIGHT_DIR}/vllm-import-stdout.txt"
VLLM_IMPORT_STDERR="${PREFLIGHT_DIR}/vllm-import-stderr.txt"
set +e
timeout "${VLLM_IMPORT_TIMEOUT_SECONDS}" "${PYTHON_BIN}" -c \
  "import vllm; print(vllm.__version__)" \
  >"${VLLM_IMPORT_STDOUT}" 2>"${VLLM_IMPORT_STDERR}"
VLLM_IMPORT_STATUS="$?"
set -e

if [[ "${VLLM_IMPORT_STATUS}" -ne 0 ]]; then
  {
    echo "vllm_import_status=${VLLM_IMPORT_STATUS}"
    echo "vllm_import_timeout_seconds=${VLLM_IMPORT_TIMEOUT_SECONDS}"
    echo "vllm_import_command=${PYTHON_BIN} -c 'import vllm; print(vllm.__version__)'"
  } | tee "${PREFLIGHT_DIR}/vllm-import-diagnostics.txt"
  ps -ef --forest >"${PREFLIGHT_DIR}/vllm-import-ps.txt" 2>&1 || true
  nvidia-smi >"${PREFLIGHT_DIR}/vllm-import-nvidia-smi.txt" 2>&1 || true
  cat "${VLLM_IMPORT_STDOUT}"
  cat "${VLLM_IMPORT_STDERR}" >&2
  echo "Official-container vLLM import failed or timed out before model download." >&2
  exit 43
fi

cat "${VLLM_IMPORT_STDOUT}" | tee "${PREFLIGHT_DIR}/vllm-version.txt"
cat "${VLLM_IMPORT_STDERR}" >&2

"${PYTHON_BIN}" - <<'PY' 2>&1 | tee "${PREFLIGHT_DIR}/cuda-probe.txt"
import torch

print(torch.__version__, torch.version.cuda)
assert torch.cuda.is_available()
print(torch.cuda.get_device_name(0))
print(torch.ones(1, device="cuda"))
PY

vllm --version | tee "${PREFLIGHT_DIR}/vllm-cli-version.txt"

"${PYTHON_BIN}" -m pip install -e ".[dev]" huggingface-hub

echo "Official vLLM container setup complete."
