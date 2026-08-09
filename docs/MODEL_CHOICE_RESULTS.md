# M4 Model-Choice Results

Status: Phase A completed on a real RTX 3090 using sequential model loading.

M4 Phase A now has real vLLM replay evidence for the all-strong baseline and
one-role-at-a-time counterfactuals. Phase B has not been run. Do not claim an
end-to-end mixed-routing result until a reviewed mixed candidate is replayed.

## 2026-08-09 RTX 3090 Sequential Phase A

Environment:

- Pod ID: `31ndf0f6dejut0`
- GPU: NVIDIA GeForce RTX 3090, 24 GB
- Price: $0.50/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Data center: `EU-CZ-1`
- Driver: `580.126.20`
- `nvidia-smi` CUDA compatibility label: `13.0`
- Backend: vLLM `0.26.0+cu129`
- `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`
- Execution strategy: sequential one model at a time
- Agent harness: framework-free M3 research agent with `dedup_only` evidence
  carry-forward
- Tasks: 10 deterministic local-corpus research tasks

Preflight:

- CUDA tensor probe: passed on `NVIDIA GeForce RTX 3090`
- Bounded `import vllm`: passed, `0.26.0`
- vLLM version check: passed

Sequential loading behavior:

1. Qwen3-4B ran the all-strong baseline and stopped.
2. GPU memory returned to 1 MiB before Qwen3-1.7B started.
3. Qwen3-1.7B ran medium candidate role calls and stopped.
4. GPU memory returned to 1 MiB before Qwen3-0.6B started.
5. Qwen3-0.6B ran small candidate role calls and stopped.
6. Qwen3-4B restarted for downstream strong continuations.

Strong baseline:

- Mean rule score: 0.967
- Pass rate: 90%
- LLM calls: 30
- Tool calls: 20
- Input tokens: 95,481
- Output tokens: 4,872
- TTFT P95: 816.5 ms
- Client latency P95: 4,660.6 ms
- Relative model-cost score: 0.401

Quality constraint:

- Mean score must be at least baseline - 0.05: 0.917
- Pass rate must be at least baseline - 0.10: 80%

Role-sensitivity matrix:

| Role | Candidate | Mean score | Pass rate | Quality delta | Pass delta | Client P95 delta | Relative cost delta | Quality-preserving |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Planner | 1.7B | 0.967 | 90% | +0.000 | +0pp | -256.8 ms | -0.006 | yes |
| Evidence reviewer | 1.7B | 0.900 | 70% | -0.067 | -20pp | +107.3 ms | -0.104 | no |
| Final synthesizer | 1.7B | 0.967 | 90% | +0.000 | +0pp | -2,006.5 ms | -0.121 | yes |
| Planner | 0.6B | 0.933 | 80% | -0.033 | -10pp | +99.1 ms | -0.007 | yes |
| Evidence reviewer | 0.6B | 0.967 | 90% | +0.000 | +0pp | +226.1 ms | -0.153 | yes |
| Final synthesizer | 0.6B | 0.967 | 90% | +0.000 | +0pp | -2,006.5 ms | -0.179 | yes |

Pareto result:

- `synthesizer_small` was the only non-dominated one-role configuration in this
  Phase A matrix.
- `reviewer_medium` violated both quality constraints.
- `strong_all`, `planner_medium`, `synthesizer_medium`, `planner_small`, and
  `reviewer_small` were dominated in the one-role table.

MODEL_CHOICE_HEADROOM findings were emitted for:

- planner -> 1.7B
- final_synthesizer -> 1.7B
- planner -> 0.6B
- evidence_reviewer -> 0.6B
- final_synthesizer -> 0.6B

Role sensitivity interpretation:

- `final_synthesizer` appears least sensitive in this workload; both smaller
  candidates preserved quality and materially lowered measured synthesizer
  latency.
- `planner` is moderately sensitive; 0.6B remained within the configured
  tolerance but landed exactly on the pass-rate floor.
- `evidence_reviewer` is not monotonic in this run: 1.7B violated quality while
  0.6B preserved it. Treat this as a noisy replay signal that requires Phase B
  confirmation before turning into a product claim.

Proposed mixed-routing candidate for review:

| Role | Candidate |
| --- | --- |
| Planner | Qwen3-1.7B |
| Evidence reviewer | Qwen3-0.6B |
| Final synthesizer | Qwen3-0.6B |

Rationale: this avoids the planner 0.6B pass-rate floor and the reviewer 1.7B
quality violation while using measured quality-preserving candidates for the
other roles. This is only a proposed Phase B candidate; it is not a measured
mixed-routing result.

Phase B justification:

- Phase B is justified as a bounded follow-up because Phase A found replay-based
  role headroom under the configured quality constraints.
- Phase B must replay the full mixed agent before claiming end-to-end quality,
  latency, or cost improvement.

Estimated Phase B memory plan:

- The proposed mixed candidate needs Qwen3-1.7B and Qwen3-0.6B only if served
  concurrently.
- A 24GB GPU may be sufficient for those two models, but Phase B should still
  explicitly allocate `gpu_memory_utilization` per instance and verify memory
  release/usage.
- Do not run Qwen3-4B concurrently unless the Phase B design explicitly needs a
  strong-control server; use sequential strong baseline replay if possible.

Artifacts:

- Compact result bundle copied locally to:
  `artifacts/runpod/agentperf-m4-phase-a-3090-sequential-31ndf0f6dejut0.tgz`
- The bundle includes the comparison JSON, model-choice report, per-config text
  reports, setup/preflight diagnostics, and server logs. It intentionally does
  not include model weights or full raw/normalized traces.

Cleanup:

- The vLLM server was stopped and GPU memory returned to 1 MiB.
- Pod was deleted after artifacts were copied locally.
- `runpodctl pod list` returned `[]`.

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

## Next Step

Do not continue with more runtime-environment experiments for Phase A. The
sequential RTX 3090 run completed the required role-sensitivity matrix.

The next step is a reviewed Phase B mixed-routing replay using the proposed
candidate above, or a revised candidate if review rejects the noisy
`evidence_reviewer` signal. Phase B must produce real end-to-end mixed-agent
quality and latency measurements before any model-routing improvement is
claimed.
