# M25 Phase B Real Mixed-Routing Replay Plan

Status: pre-registered before any new Phase B GPU run.

This plan fixes the experiment before observing new mixed-routing results. Do
not change the task set, routing, quality thresholds, or stopping rule after
seeing Phase B outputs.

## Goal

Run one bounded real model-routing experiment to test whether the historical
M4/M25 local role-headroom evidence composes into a full end-to-end mixed
routing.

This is an empirical validation run, not a model search. A quality-regressing
candidate is a valid result.

## Historical Source of Truth

Primary machine-readable evidence:

- `docs/data/m25_historical_m4_phase_a.json`

Supporting documents and scripts:

- `docs/M25_MODEL_CAPACITY_REPLAY.md`
- `docs/MODEL_CHOICE_RESULTS.md`
- `docs/MODEL_CHOICE_PROFILING.md`
- `scripts/run_model_choice_phase_b.py`
- `scripts/remote_vllm/run_model_choice_phase_b.sh`

The older `docs/MODEL_CHOICE_PROFILING.md` mixed-candidate table contains a
stale placeholder route. The current M25 source of truth is the migrated JSON,
the M25 model-capacity document, the Phase B runner, and the regression tests.
Those all define the Phase B candidate as planner=medium,
evidence_reviewer=small, final_synthesizer=small.

## Workload

Workload:

- framework-free M3 research agent
- carry strategy: `dedup_only`
- local deterministic corpus: `docs/corpus/`
- questions file: `docs/corpus/questions.json`
- agent architecture: planner LLM -> local search -> evidence reviewer LLM ->
  local search -> final synthesizer LLM

Task IDs:

| Index | Task ID |
| ---: | --- |
| 1 | `q01-cache` |
| 2 | `q02-jobs` |
| 3 | `q03-region` |
| 4 | `q04-auth` |
| 5 | `q05-webhooks` |
| 6 | `q06-cache-owner` |
| 7 | `q07-jobs-no-scale` |
| 8 | `q08-region-writes` |
| 9 | `q09-auth-risk` |
| 10 | `q10-webhook-drain` |

No tasks may be added, removed, or replaced after the run starts.

## Roles

Role IDs are workload-defined and match the existing M4/M25 scripts:

- `planner`
- `evidence_reviewer`
- `final_synthesizer`

## Model Ladder

| Alias | Model ID | Relative cost weight |
| --- | --- | ---: |
| `small` | `Qwen/Qwen3-0.6B` | 0.6 |
| `medium` | `Qwen/Qwen3-1.7B` | 1.7 |
| `strong` | `Qwen/Qwen3-4B` | 4.0 |

The relative cost value is a token-weighted model-capacity proxy. It is not
dollar cost.

## Baseline Routing

Fresh same-environment baseline:

| Role | Alias | Model ID |
| --- | --- | --- |
| `planner` | `strong` | `Qwen/Qwen3-4B` |
| `evidence_reviewer` | `strong` | `Qwen/Qwen3-4B` |
| `final_synthesizer` | `strong` | `Qwen/Qwen3-4B` |

Configuration name: `strong_control`.

## Candidate Routing

Pre-registered mixed candidate:

| Role | Alias | Model ID |
| --- | --- | --- |
| `planner` | `medium` | `Qwen/Qwen3-1.7B` |
| `evidence_reviewer` | `small` | `Qwen/Qwen3-0.6B` |
| `final_synthesizer` | `small` | `Qwen/Qwen3-0.6B` |

Configuration name: `mixed_evidence_backed`.

Do not alter this routing after observing task failures or quality movement.

## Backend and Runtime

Backend:

- vLLM OpenAI-compatible completions API

Preferred runtime path:

- existing AgentPerf remote scripts in `scripts/remote_vllm/`
- `scripts/remote_vllm/setup.sh`
- `scripts/remote_vllm/run_model_choice_phase_b.sh`

Target vLLM configuration:

- `VLLM_VERSION=0.26.0`
- `VLLM_CUDA_VERSION=129`
- `MAX_MODEL_LEN=8192`
- prefix caching enabled
- prompt token details enabled
- per-request metrics enabled

Request settings are fixed by `call_vllm`:

- completions endpoint: `/v1/completions`
- `temperature=0`
- `stream=false`
- `return_token_ids=true`
- `return_prompt_text=true`
- `stop=["<|im_end|>"]`

Maximum generated tokens:

- planner: 64
- evidence reviewer: 160 in normal full-agent execution; 160 for reviewer
  repeat candidates because Phase B uses `FINAL_MAX_TOKENS // 2`
- final synthesizer: 320

## Hardware Target

Primary target:

- one NVIDIA RTX 3090 24GB-class GPU, matching historical M4 Phase A when
  available.

Acceptable fallback:

- one single-GPU resource with at least equivalent VRAM and compatible NVIDIA
  driver/CUDA support, if an RTX 3090 resource cannot start reliably.

The GPU is used for bounded empirical validation, not throughput benchmarking.

## Model Loading Strategy

Strong-control stages run the strong model alone.

Reviewer-repeat stages run one model at a time:

1. strong model for `strong_control`;
2. medium model for `reviewer_medium` repeats;
3. small model for `reviewer_small` repeats;
4. strong model for downstream strong continuations.

The mixed end-to-end stage starts only the medium and small models:

- medium server on port `18002`;
- small server on port `18001`.

The strong model is not run concurrently with the mixed candidate. If the
medium+small pair cannot fit concurrently, the run stops as infrastructure
failure unless a sequential equivalent can preserve the exact same candidate
routing semantics without changing prompts, tasks, or evaluation.

## Preflight

Every potentially hanging step must use the timeouts built into the scripts or
an explicit shell timeout.

Required preflight before measured replay:

1. `nvidia-smi`
2. Python version
3. CUDA tensor creation through PyTorch
4. vLLM import/version
5. model download presence or download completion
6. server startup health check through `/v1/models`
7. one request per served model
8. one complete role path if practical before full run

If the environment fails before running both baseline and candidate, classify
the attempt as infrastructure failure, not model failure.

## Run Order

Use `scripts/remote_vllm/run_model_choice_phase_b.sh` unless a preflight-only
failure requires equivalent manual staging.

The intended stage order is:

1. `strong-control`
2. `reviewer-candidates --tier medium`
3. `reviewer-candidates --tier small`
4. `reviewer-continuations`
5. `mixed-end-to-end`
6. `assemble`
7. `agentperf analyze-model-choice`
8. `agentperf compare` on `strong_control/agentperf_artifact` and
   `mixed_evidence_backed/agentperf_artifact`
9. `agentperf check` with the existing applicable policy, if present
10. `agentperf compare --format html` for the same artifact pair

Baseline and candidate must be produced on the same GPU resource, same commit,
same corpus, same script configuration, and same evaluator.

## Warmup Policy

Server health and one small request per served model are warmup/preflight and
are not task results.

The 10 task executions in `strong_control` and `mixed_evidence_backed` are the
measured workload. Do not remove warmup requests from task artifacts because
they should not be written into task artifacts in the first place.

## Reviewer Repeatability

The Phase B runner repeats reviewer-only candidates before the full mixed run:

- `REVIEWER_REPEAT_COUNT=3`

These repeats are diagnostic context for the historically noisy
`evidence_reviewer` signal. They are not a substitute for full mixed-routing
verification.

## Quality Evaluator

Evaluator:

- `local-corpus-fact-coverage`

The evaluator checks required facts and required document IDs from
`docs/corpus/questions.json` in the final answer. A task passes only when all
required facts and document IDs are present.

## Pre-Registered Quality Constraint

Use the historical M4/M25 quality constraint:

- candidate mean score must be at least fresh baseline mean score - 0.05;
- candidate pass rate must be at least fresh baseline pass rate - 0.10.

The mixed routing is not successful unless quality passes these thresholds.
Do not replace the fresh baseline with the historical Phase A baseline for
acceptance.

## Efficiency Metrics

Primary efficiency metric:

- `model.relative_cost_proxy`

Supporting metrics when available:

- provider input tokens;
- provider output tokens;
- component processed tokens;
- client latency P50/P95;
- TTFT P50/P95 from vLLM telemetry.

Latency is same-environment evidence only. Do not compare new latency numbers
against historical Phase A latency.

## Routing Verdict

Assign exactly one Phase B routing verdict:

- `GLOBAL_ROUTING_VERIFIED`: quality passes, task coverage is preserved, and
  relative cost proxy or available latency improves materially.
- `REJECTED_QUALITY_REGRESSION`: efficiency improves but quality violates the
  pre-registered constraint.
- `NO_MATERIAL_BENEFIT`: quality passes but no meaningful efficiency benefit is
  observed.
- `INCONCLUSIVE`: task coverage, quality, environment, or artifact evidence is
  incomplete or incompatible.

Do not use `INCONCLUSIVE` to hide a quality failure.

## Retry Policy

Maximum GPU environment attempts:

- one primary attempt;
- one fallback attempt only if the first fails before producing both baseline
  and candidate artifacts because of infrastructure startup or provisioning.

Within a valid environment, do not rerun only failed model tasks. If a server or
script fails mid-condition for infrastructure reasons, rerun the entire affected
condition under the same configuration and keep the failed attempt documented
separately.

Model/task failures are not infrastructure failures and must remain in the
measured result.

## Stopping Rule

Stop after one valid fresh `strong_control` versus one valid fresh
`mixed_evidence_backed` comparison.

If the candidate fails quality, stop and report
`REJECTED_QUALITY_REGRESSION`.

If the candidate passes quality and efficiency improves, stop and report
`GLOBAL_ROUTING_VERIFIED`.

If quality passes but efficiency does not materially improve, stop and report
`NO_MATERIAL_BENEFIT`.

Do not search for another candidate without a separate approved milestone.

## Artifacts to Preserve

Preserve compact sanitized artifacts:

- `strong_control/agentperf_artifact`
- `mixed_evidence_backed/agentperf_artifact`
- `model_choice_phase_b_comparison.json`
- `model_choice_phase_b_report.txt`
- comparison HTML
- concise preflight metadata

Do not commit:

- model weights;
- full server logs;
- credentials;
- raw environment secrets;
- large temporary bundles.

## Resource Cleanup

After the run, stop all vLLM servers and delete the GPU resource immediately.
Verify no GPU resources remain through provider tooling.

Record:

- GPU type;
- runtime/container;
- approximate wall-clock experiment duration;
- environment attempt count;
- cleanup verification.

## Public Claim Policy

This is not a general model-routing benchmark.

Safe successful wording:

> In one bounded research-agent workload, AgentPerf used role-level
> counterfactual evidence to construct and end-to-end verify a mixed-model
> routing under a predefined quality constraint.

Safe rejected wording:

> Role-level substitutions that appeared individually safe did not compose
> safely under end-to-end replay, and AgentPerf rejected the mixed routing on
> quality.

Do not claim optimal routing, universal model downsizing, production cost
savings, monotonic model-size behavior, or dollar savings.
