#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
VLLM_VERSION="${VLLM_VERSION:-0.26.0}"
VLLM_CUDA_VERSION="${VLLM_CUDA_VERSION:-129}"
VLLM_IMPORT_TIMEOUT_SECONDS="${VLLM_IMPORT_TIMEOUT_SECONDS:-60}"
CPU_ARCH="${CPU_ARCH:-$(uname -m)}"
SETUP_ARTIFACT_DIR="${SETUP_ARTIFACT_DIR:-artifacts/real_vllm/setup}"
VLLM_WHEEL_URL="${VLLM_WHEEL_URL:-https://github.com/vllm-project/vllm/releases/download/v${VLLM_VERSION}/vllm-${VLLM_VERSION}+cu${VLLM_CUDA_VERSION}-cp38-abi3-manylinux_2_28_${CPU_ARCH}.whl}"
PYTORCH_INDEX_URL="${PYTORCH_INDEX_URL:-https://download.pytorch.org/whl/cu${VLLM_CUDA_VERSION}}"

cuda_tag_to_display() {
  local tag="$1"
  echo "${tag:0:${#tag}-1}.${tag: -1}"
}

driver_version_to_major() {
  local version="$1"
  echo "${version%%.*}"
}

mkdir -p "${SETUP_ARTIFACT_DIR}"

echo "Recording host GPU and Python environment in ${SETUP_ARTIFACT_DIR}"

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi | tee "${SETUP_ARTIFACT_DIR}/nvidia-smi.txt"
else
  echo "nvidia-smi is not available. Use a Linux host with a supported NVIDIA GPU." >&2
  exit 1
fi

DRIVER_VERSION="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1 | tr -d ' ')"
HOST_CUDA_VERSION="$(sed -n 's/.*CUDA Version: \([0-9.]*\).*/\1/p' "${SETUP_ARTIFACT_DIR}/nvidia-smi.txt" | head -n 1)"
TARGET_CUDA_VERSION="$(cuda_tag_to_display "${VLLM_CUDA_VERSION}")"
TARGET_CUDA_MAJOR="${TARGET_CUDA_VERSION%%.*}"
DRIVER_MAJOR="$(driver_version_to_major "${DRIVER_VERSION}")"
DRIVER_COMPATIBILITY_STATUS="unknown"

{
  echo "python_bin=${PYTHON_BIN}"
  "${PYTHON_BIN}" --version
  echo "driver_version=${DRIVER_VERSION}"
  echo "host_reported_cuda=${HOST_CUDA_VERSION:-unknown}"
  echo "target_vllm_version=${VLLM_VERSION}"
  echo "target_vllm_cuda=${TARGET_CUDA_VERSION}"
  echo "vllm_wheel_url=${VLLM_WHEEL_URL}"
  echo "pytorch_index_url=${PYTORCH_INDEX_URL}"
} | tee "${SETUP_ARTIFACT_DIR}/environment_preinstall.txt"

if [[ -z "${HOST_CUDA_VERSION}" ]]; then
  echo "Could not determine host CUDA compatibility from nvidia-smi; refusing to install vLLM." >&2
  exit 2
fi

if [[ "${TARGET_CUDA_MAJOR}" == "12" ]]; then
  if [[ "${DRIVER_MAJOR}" -lt 525 ]]; then
    cat >&2 <<EOF
Environment mismatch detected before installation.

NVIDIA driver ${DRIVER_VERSION} is below the documented minimum driver branch
for CUDA 12.x minor-version compatibility. The configured official vLLM
${VLLM_VERSION} wheel targets CUDA ${TARGET_CUDA_VERSION}.

Do not continue to model download or vLLM startup on this host. Use a node with
an NVIDIA driver branch >= 525 for CUDA 12.x, or revise VLLM_VERSION /
VLLM_CUDA_VERSION only after verifying an official compatible vLLM wheel exists.
EOF
    exit 42
  elif [[ "${DRIVER_MAJOR}" -lt 580 ]]; then
    DRIVER_COMPATIBILITY_STATUS="cuda_12_minor_version_compatibility"
  else
    DRIVER_COMPATIBILITY_STATUS="newer_driver_backward_compatibility"
  fi
elif [[ "${TARGET_CUDA_MAJOR}" == "13" ]]; then
  if [[ "${DRIVER_MAJOR}" -lt 580 ]]; then
    cat >&2 <<EOF
Environment mismatch detected before installation.

NVIDIA driver ${DRIVER_VERSION} is below the documented minimum driver branch
for CUDA 13.x. The configured official vLLM ${VLLM_VERSION} wheel targets CUDA
${TARGET_CUDA_VERSION}.

Do not continue to model download or vLLM startup on this host. Use a node with
an NVIDIA driver branch >= 580 for CUDA 13.x, or select a CUDA 12.x vLLM wheel.
EOF
    exit 42
  fi
  DRIVER_COMPATIBILITY_STATUS="cuda_13_supported_driver"
else
  cat >&2 <<EOF
Unsupported CUDA target detected before installation.

The setup script only has explicit preflight rules for CUDA 12.x and CUDA 13.x
vLLM wheels. The configured wheel target is CUDA ${TARGET_CUDA_VERSION}.

Add an explicit compatibility rule before using this CUDA target.
EOF
  exit 42
fi

echo "driver_compatibility_status=${DRIVER_COMPATIBILITY_STATUS}" | tee "${SETUP_ARTIFACT_DIR}/driver-compatibility.txt"
echo "nvidia_smi_cuda_label=${HOST_CUDA_VERSION}" | tee -a "${SETUP_ARTIFACT_DIR}/driver-compatibility.txt"
echo "selected_wheel_cuda=${TARGET_CUDA_VERSION}" | tee -a "${SETUP_ARTIFACT_DIR}/driver-compatibility.txt"

if ! command -v uv >/dev/null 2>&1; then
  "${PYTHON_BIN}" -m pip install --user --upgrade uv
  export PATH="${HOME}/.local/bin:${PATH}"
fi

uv --version | tee "${SETUP_ARTIFACT_DIR}/uv-version.txt"
uv venv .venv --python "${PYTHON_BIN}"
source .venv/bin/activate

uv pip install -e ".[dev]"
uv pip install openai requests
uv pip install "${VLLM_WHEEL_URL}" \
  --extra-index-url "${PYTORCH_INDEX_URL}" \
  --torch-backend="cu${VLLM_CUDA_VERSION}"

python -c "import torch; print(torch.__version__, torch.version.cuda)" | tee "${SETUP_ARTIFACT_DIR}/torch-version.txt"

VLLM_IMPORT_STDOUT="${SETUP_ARTIFACT_DIR}/vllm-import-stdout.txt"
VLLM_IMPORT_STDERR="${SETUP_ARTIFACT_DIR}/vllm-import-stderr.txt"
set +e
timeout "${VLLM_IMPORT_TIMEOUT_SECONDS}" python -c "import vllm; print(vllm.__version__)" \
  >"${VLLM_IMPORT_STDOUT}" 2>"${VLLM_IMPORT_STDERR}"
VLLM_IMPORT_STATUS="$?"
set -e
if [[ "${VLLM_IMPORT_STATUS}" -ne 0 ]]; then
  {
    echo "vllm_import_status=${VLLM_IMPORT_STATUS}"
    echo "vllm_import_timeout_seconds=${VLLM_IMPORT_TIMEOUT_SECONDS}"
    echo "vllm_import_command=python -c \"import vllm; print(vllm.__version__)\""
  } | tee "${SETUP_ARTIFACT_DIR}/vllm-import-diagnostics.txt"
  ps -ef --forest >"${SETUP_ARTIFACT_DIR}/vllm-import-ps.txt" 2>&1 || true
  nvidia-smi >"${SETUP_ARTIFACT_DIR}/vllm-import-nvidia-smi.txt" 2>&1 || true
  cat "${VLLM_IMPORT_STDOUT}"
  cat "${VLLM_IMPORT_STDERR}" >&2
  echo "vLLM import probe failed or timed out before model download. Stop this Pod and preserve ${SETUP_ARTIFACT_DIR}." >&2
  exit 43
fi
cat "${VLLM_IMPORT_STDOUT}" | tee "${SETUP_ARTIFACT_DIR}/vllm-version.txt"
cat "${VLLM_IMPORT_STDERR}" >&2
nvidia-smi | tee "${SETUP_ARTIFACT_DIR}/nvidia-smi-postinstall.txt"

SETUP_ARTIFACT_DIR="${SETUP_ARTIFACT_DIR}" EXPECTED_VLLM_VERSION="${VLLM_VERSION}" EXPECTED_TORCH_CUDA="${TARGET_CUDA_VERSION}" python - <<'PY' 2>&1 | tee "${SETUP_ARTIFACT_DIR}/cuda-probe.txt"
import os
import sys
from pathlib import Path

import torch

setup_artifact_dir = Path(os.environ["SETUP_ARTIFACT_DIR"])
expected_vllm = os.environ["EXPECTED_VLLM_VERSION"]
expected_cuda = os.environ["EXPECTED_TORCH_CUDA"]

if torch.version.cuda != expected_cuda:
    raise SystemExit(f"Unexpected torch CUDA runtime: {torch.version.cuda} != {expected_cuda}")
if not torch.cuda.is_available():
    raise SystemExit("torch.cuda.is_available() is false")

with (setup_artifact_dir / "vllm-version.txt").open(encoding="utf-8") as version_file:
    actual_vllm = version_file.read().strip()
if actual_vllm != expected_vllm:
    raise SystemExit(f"Unexpected vLLM version: {actual_vllm} != {expected_vllm}")

print(torch.cuda.get_device_name(0))
x = torch.ones(1, device="cuda")
print(x)
sys.stdout.flush()
PY

echo "Setup complete. Activate with: source .venv/bin/activate"
