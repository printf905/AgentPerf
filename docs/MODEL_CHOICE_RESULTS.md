# M4 Model-Choice Results

Status: blocked before replay on the first real GPU attempt.

No model-choice quality, latency, or cost result should be reported from this
attempt. The failure happened during multi-model vLLM endpoint startup before
the baseline or counterfactual agent workload ran.

## 2026-08-09 RTX 3090 Attempt

Environment:

- Pod ID: `v8rw1kjzdsdl6s`
- GPU: NVIDIA GeForce RTX 3090, 24 GB
- Price: $0.50/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `580.159.03`
- `nvidia-smi` CUDA compatibility label: `13.0`
- AgentPerf branch: `feature/model-choice-counterfactual`
- Latest pushed commit during attempt: `a52f30a`
- Backend: vLLM `0.26.0+cu129`
- `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`

Preflight:

- Bounded `import vllm`: passed, `0.26.0`
- CUDA tensor probe: passed on `NVIDIA GeForce RTX 3090`

Model downloads:

| Model | Local path | Size | Status |
| --- | --- | ---: | --- |
| `Qwen/Qwen3-0.6B` | `/workspace/models/Qwen3-0.6B` | 1,519,211,938 bytes | complete |
| `Qwen/Qwen3-1.7B` | `/workspace/models/Qwen3-1.7B` | 4,079,453,481 bytes | complete |
| `Qwen/Qwen3-4B` | `/workspace/models/Qwen3-4B` | 8,060,930,441 bytes | complete |

Startup attempts:

1. Ports `8001`, `8002`, `8003` with uniform `gpu_memory_utilization=0.25`.
   `8001` collided with a Runpod/Ubuntu HTML service, and medium/strong failed
   with no KV-cache memory.
2. High ports `18001`, `18002`, `18003` with memory split
   small=`0.16`, medium=`0.26`, strong=`0.48`. Small and medium started.
   Strong failed because free memory was `10.7/23.56 GiB` and requested memory
   was `11.31 GiB`.
3. High ports with small=`0.16`, medium=`0.26`, strong=`0.44`. Small and medium
   started. Strong progressed farther but failed during compile/warmup with CUDA
   OOM:

```text
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB.
GPU 0 has a total capacity of 23.56 GiB of which 20.38 MiB is free.
Process ... has 5.24 GiB memory in use.
Process ... has 7.56 GiB memory in use.
Process ... has 10.71 GiB memory in use.
```

Conclusion:

- The selected Qwen3 ladder is compatible with vLLM individually.
- The three-server concurrent endpoint design did not fit on the first 24GB RTX
  3090 attempt at `max_model_len=8192`.
- M4 replay did not run, so no role sensitivity, `MODEL_CHOICE_HEADROOM`, mixed
  routing, quality delta, latency delta, or cost delta can be claimed.

Recommended next execution design:

- keep the same model ladder and agent semantics;
- avoid concurrent three-server residency on a 24GB GPU unless a smaller context
  length is validated against actual prompt lengths;
- implement or run a sequential model-loading protocol per configuration, or ask
  for approval for a larger single GPU.

Artifacts:

- Diagnostic bundle copied locally to:
  `artifacts/runpod/agentperf-m4-3090-startup-failure-v8rw1kjzdsdl6s.tgz`

Cleanup:

- Pod deletion is required after this documentation is committed and pushed.
