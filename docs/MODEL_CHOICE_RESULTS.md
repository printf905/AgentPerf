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
- avoid concurrent three-server residency on a 24GB GPU;
- use the sequential Phase A runner, which loads only one model at a time and
  regenerates downstream strong continuations from checkpointed role state;
- ask for approval for a larger single GPU only after Phase A identifies a mixed
  routing candidate that requires simultaneous serving.

## Sequential Phase A Plan

Status: implemented locally; not yet executed on a live GPU after the blocked
concurrent-server attempt.

Scripts:

- `scripts/run_model_choice_phase_a.py`
- `scripts/remote_vllm/start_model_choice_server.sh`
- `scripts/remote_vllm/stop_model_choice_server.sh`
- `scripts/remote_vllm/run_model_choice_phase_a.sh`

Execution order:

1. Load Qwen3-4B only and run `strong_all`.
2. Stop Qwen3-4B and release GPU memory.
3. Load Qwen3-1.7B only and run medium candidate role calls.
4. Stop Qwen3-1.7B.
5. Load Qwen3-0.6B only and run small candidate role calls.
6. Stop Qwen3-0.6B.
7. Reload Qwen3-4B only and regenerate downstream strong continuations for
   planner/reviewer counterfactuals.
8. Assemble the Phase A role-sensitivity matrix.

Counterfactual semantics:

- Unchanged strong-role records are reused from the all-strong baseline.
- Candidate-role calls are regenerated with the candidate model.
- Downstream strong calls are regenerated when upstream planner or reviewer
  output changes.
- Deterministic local retrieval/tool results are held fixed.
- Mixed routing is not run until Phase A evidence justifies a candidate.

Artifacts:

- Diagnostic bundle copied locally to:
  `artifacts/runpod/agentperf-m4-3090-startup-failure-v8rw1kjzdsdl6s.tgz`

Cleanup:

- Pod was deleted after diagnostics were preserved and pushed.
- `runpodctl pod list` returned `[]`.

## 2026-08-09 A5000 Sequential Phase A Attempt

Status: blocked by the bounded vLLM import preflight before model download.

Environment:

- Pod ID: `5u2mgbnrsyt23n`
- GPU: NVIDIA RTX A5000, 24 GB
- Price: $0.27/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Data center: `CA-MTL-1`
- Driver: `580.159.04`
- `nvidia-smi` CUDA compatibility label: `13.0`
- AgentPerf commit: `ff1ccd0`
- Intended backend: vLLM `0.26.0+cu129`
- Installed `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`

Preflight:

- CUDA driver compatibility check: passed.
- vLLM wheel installation: completed.
- Torch version probe: passed, `2.11.0+cu129 12.9`.
- Bounded `import vllm`: failed by timeout.

Exact hard-gate failure:

```text
vllm_import_status=124
vllm_import_timeout_seconds=60
vllm_import_command=python -c "import vllm; print(vllm.__version__)"
vLLM import probe failed or timed out before model download.
```

The setup script stopped before model download and before vLLM server startup,
as intended. The GPU showed no running processes during the import timeout
diagnostic snapshot.

Artifacts:

- Diagnostic bundle copied locally to:
  `artifacts/runpod/agentperf-m4-phase-a-a5000-vllm-import-timeout-5u2mgbnrsyt23n.tgz`

Cleanup:

- Pod was deleted after diagnostics were copied locally.
- `runpodctl pod list` returned `[]`.

## Next Infrastructure Path

Do not keep retrying random PyTorch-template Pods for M4 Phase A until the vLLM
runtime import issue is isolated.

The next reproducible path should use the official vLLM OpenAI-compatible image
instead of installing vLLM into the Runpod PyTorch template at runtime.

Official sources checked:

- vLLM Docker documentation says the official deployment image is
  `vllm/vllm-openai` and shows running it with NVIDIA GPUs and OpenAI-compatible
  serving.
- Docker Hub currently lists pinned vLLM `0.26.0` CUDA 12.9 image tags,
  including `vllm/vllm-openai:v0.26.0-cu129-ubuntu2404` and
  `vllm/vllm-openai:v0.26.0-x86_64-cu129-ubuntu2404`.

Before another GPU rental, prepare a Runpod template or direct Pod command based
on one of those pinned images, mount `/workspace`, and run the existing
sequential Phase A script inside that container. Do not create a 48GB Phase B Pod
until Phase A produces a real role-sensitivity matrix.
