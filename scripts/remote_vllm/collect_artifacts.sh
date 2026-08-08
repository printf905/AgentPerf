#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_DIR="${ARTIFACT_DIR:-artifacts/real_vllm}"
PACKAGE="${PACKAGE:-artifacts/agentperf-real-vllm-artifacts.tgz}"

if [ ! -d "${ARTIFACT_DIR}" ]; then
  echo "Artifact directory not found: ${ARTIFACT_DIR}" >&2
  exit 1
fi

mkdir -p "$(dirname "${PACKAGE}")"
tar \
  --exclude='*.safetensors' \
  --exclude='*.bin' \
  --exclude='*.pt' \
  --exclude='*.pth' \
  --exclude='models' \
  --exclude='weights' \
  -czf "${PACKAGE}" \
  "${ARTIFACT_DIR}"

echo "Packaged artifacts: ${PACKAGE}"
