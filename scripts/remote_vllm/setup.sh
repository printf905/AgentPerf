#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi
else
  echo "nvidia-smi is not available. Use a Linux host with a supported NVIDIA GPU." >&2
  exit 1
fi

"${PYTHON_BIN}" -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
pip install vllm openai requests

echo "Setup complete. Activate with: source .venv/bin/activate"
