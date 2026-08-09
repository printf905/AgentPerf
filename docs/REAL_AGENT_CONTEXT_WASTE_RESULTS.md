# Real Agent Context-Waste Results

This document records real execution attempts for the M3 agent harness/context-waste milestone.

## 2026-08-09 L4 Attempt

Status: blocked before workload execution.

The RTX A5000 pool was unavailable, so the approved fallback was one NVIDIA L4 under the
$0.55/hour cap.

Environment:

- Pod ID: `xabo9uz3r99iog`
- GPU: NVIDIA L4, 24 GB
- Price: $0.49/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `550.127.05`
- `nvidia-smi` CUDA compatibility label: `12.4`
- AgentPerf commit: `ff2c829`
- Branch: `feature/real-agent-context-waste`

Preflight result:

- `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`
- `vllm`: `0.26.0`
- CUDA tensor probe: passed on `NVIDIA L4`

Model download:

- Model: `Qwen/Qwen3-0.6B`
- Local path: `/workspace/models/Qwen3-0.6B`
- Files: 23
- Size: 1,519,211,941 bytes
- Download elapsed time: 9.59 seconds
- Config, tokenizer, and safetensors files were verified present after download.

vLLM startup:

```text
vllm serve /workspace/models/Qwen3-0.6B \
  --served-model-name agentperf-vllm-demo \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 12288 \
  --gpu-memory-utilization 0.80 \
  --enable-prefix-caching \
  --prefix-caching-hash-algo sha256_cbor \
  --enable-prompt-tokens-details \
  --enable-per-request-metrics
```

Failure:

- `/v1/models` did not become ready during the bounded startup window.
- `vllm_server.log` remained empty.
- `nvidia-smi` showed no model process and only 1 MiB GPU memory usage.
- The `vllm serve` process remained CPU-active but did not initialize the GPU or open port 8000.
- A separate `import vllm` diagnostic also stalled during the same window.

No real M3 baseline/optimized agent workload was run on this Pod. No token, latency,
cache, correctness, or detector result should be reported from this attempt.

Cleanup:

- Diagnostic archive copied locally to:
  `artifacts/runpod/agentperf-m3-l4-startup-failure-xabo9uz3r99iog.tgz`
- Pod deleted after diagnostics were preserved.
- `runpodctl pod list` returned `[]`.

