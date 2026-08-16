# M25 Phase B Real Mixed-Routing Replay Results

Status: completed on one bounded real GPU experiment.

This document reports a single pre-registered Phase B replay. It is not a
general model-routing benchmark and does not claim optimal routing.

## Historical Phase A

Historical M4 Phase A ran one-role-at-a-time Qwen3 substitutions on the
framework-free M3 research agent. The preserved machine-readable evidence is
`docs/data/m25_historical_m4_phase_a.json`.

Model aliases:

| Alias | Model ID | Relative cost weight |
| --- | --- | ---: |
| `small` | `Qwen/Qwen3-0.6B` | 0.6 |
| `medium` | `Qwen/Qwen3-1.7B` | 1.7 |
| `strong` | `Qwen/Qwen3-4B` | 4.0 |

Historical Phase A showed local role headroom but did not prove that multiple
substitutions compose safely. In particular, the evidence reviewer was
non-monotonic in the historical run: `1.7B` regressed quality while `0.6B`
preserved it.

The pre-registered Phase B candidate from M25 was:

| Role | Baseline | Candidate |
| --- | --- | --- |
| `planner` | `strong` | `medium` |
| `evidence_reviewer` | `strong` | `small` |
| `final_synthesizer` | `strong` | `small` |

## New Experiment Environment

Experiment plan:

- `docs/M25_PHASE_B_PLAN.md`

AgentPerf commit:

- `bedd19d9c06e3a83a6ab922e1fd7b03c6f929cc6`

Run environment:

| Field | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 3090, 24 GB |
| Runpod pod | `cyv1s261vg9uzc` |
| Image | `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404` |
| Driver | 580.126.20 |
| Host CUDA label | 13.0 |
| vLLM | 0.26.0+cu129 |
| Torch | 2.11.0+cu129 |
| Python | 3.12.3 |
| Backend | vLLM OpenAI-compatible completions API |
| `max_model_len` | 8192 |
| Sampling | `temperature=0`, non-streaming |
| Output directory | `docs/data/m25_phase_b/` |

Environment attempts:

- 1 Runpod GPU environment attempt.

Preflight:

- `nvidia-smi`: passed.
- CUDA tensor creation: passed.
- vLLM import/version: passed.
- Model download: passed for all three Qwen3 models.
- One request per model: passed for strong, medium, and small.

An initial shell orchestration mistake stripped a remote loop variable during
preflight, causing one empty-model smoke request to return 404 after the strong
server had loaded. That request was not part of the measured task artifacts.
The corrected literal-name preflight passed for all three models.

## Workload

Workload:

- framework-free M3 research agent
- `dedup_only` evidence carry-forward
- local corpus under `docs/corpus/`
- 10 task IDs from `docs/corpus/questions.json`

Task IDs:

| Task ID |
| --- |
| `q01-cache` |
| `q02-jobs` |
| `q03-region` |
| `q04-auth` |
| `q05-webhooks` |
| `q06-cache-owner` |
| `q07-jobs-no-scale` |
| `q08-region-writes` |
| `q09-auth-risk` |
| `q10-webhook-drain` |

Quality evaluator:

- `local-corpus-fact-coverage`

Pre-registered quality rule:

- candidate mean score >= fresh baseline mean score - 0.05;
- candidate pass rate >= fresh baseline pass rate - 0.10.

## Fresh Baseline

Routing:

| Role | Model |
| --- | --- |
| `planner` | `Qwen/Qwen3-4B` |
| `evidence_reviewer` | `Qwen/Qwen3-4B` |
| `final_synthesizer` | `Qwen/Qwen3-4B` |

Fresh baseline result:

| Metric | Value |
| --- | ---: |
| Mean score | 0.967 |
| Pass rate | 90.0% |
| Provider input tokens | 95,483 |
| Provider output tokens | 4,944 |
| Component processed tokens | 85,811 |
| Client P50 | 2,653.624 ms |
| Client P95 | 4,634.381 ms |
| Scheduled-to-first P50 | 574.941 ms |
| Scheduled-to-first P95 | 827.943 ms |
| Relative cost proxy | 0.401708 |

## Mixed Candidate

Routing:

| Role | Model |
| --- | --- |
| `planner` | `Qwen/Qwen3-1.7B` |
| `evidence_reviewer` | `Qwen/Qwen3-0.6B` |
| `final_synthesizer` | `Qwen/Qwen3-0.6B` |

Mixed candidate result:

| Metric | Value |
| --- | ---: |
| Mean score | 0.933 |
| Pass rate | 80.0% |
| Provider input tokens | 95,481 |
| Provider output tokens | 5,142 |
| Component processed tokens | 85,794 |
| Client P50 | 688.165 ms |
| Client P95 | 1,258.500 ms |
| Scheduled-to-first P50 | 117.646 ms |
| Scheduled-to-first P95 | 175.862 ms |
| Relative cost proxy | 0.0628675 |

## Quality Result

Quality passed the pre-registered rule, but it landed exactly on the pass-rate
floor:

| Metric | Baseline | Candidate | Delta | Required floor | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Mean score | 0.967 | 0.933 | -0.033 | >= 0.917 | PASS |
| Pass rate | 90.0% | 80.0% | -10.0 pp | >= 80.0% | PASS |

Task-level change:

| Task | Baseline | Candidate |
| --- | --- | --- |
| `q09-auth-risk` | PASS, 1.000 | FAIL, 0.667 |

Baseline already failed `q10-webhook-drain`; the candidate also failed it.

## Efficiency Result

Efficiency evidence moved in the expected direction for model-capacity routing:

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| Relative cost proxy | 0.401708 | 0.0628675 | -0.3388405 |
| Client P95 | 4,634.381 ms | 1,258.500 ms | -3,375.882 ms |
| Scheduled-to-first P95 | 827.943 ms | 175.862 ms | -652.082 ms |

Provider and component token volume stayed effectively unchanged, which is
expected for a model-capacity experiment rather than a context-reduction
experiment:

| Metric | Baseline | Candidate | Delta |
| --- | ---: | ---: | ---: |
| Provider input tokens | 95,483 | 95,481 | -2 |
| Provider output tokens | 4,944 | 5,142 | +198 |
| Component processed tokens | 85,811 | 85,794 | -17 |

The relative cost proxy is not dollar cost. It is the existing token-weighted
model-capacity proxy from M25.

## Routing Verdict

Phase B routing verdict:

```text
GLOBAL_ROUTING_VERIFIED
```

Reason:

- the full mixed route ran end to end on the same task set;
- task coverage was preserved: 10 matched tasks;
- quality passed the pre-registered mean-score and pass-rate constraints;
- relative model-capacity cost proxy decreased;
- client and scheduled-to-first latency evidence improved in the same
  environment.

This does not mean the route is optimal. It means this tested route was
verified on this bounded workload under the recorded constraint.

## Recommendation Verification

M24 `MODEL_CHOICE_HEADROOM` recommendation verification:

```text
VERIFIED
```

The recommendation contract required full mixed-routing replay before accepting
the candidate. The expected model-capacity evidence moved in the predicted
direction and the quality requirement passed.

## AgentPerf Comparison

Standard `agentperf compare` result:

```text
ACCEPT
```

The comparison accepted the candidate because performance materially improved
while quality stayed within configured tolerance.

The generic M3 context-regression policy was also run as a smoke. It reported:

```text
FAIL
```

The quality and performance checks passed under that policy, but the policy
failed on `new_material_findings=1`. That new material finding is the intended
`MODEL_CHOICE_HEADROOM` validation evidence for this model-routing experiment,
so the M3 context policy is not the acceptance rule for Phase B.

## HTML Report

M23 comparison HTML was generated:

- `docs/data/m25_phase_b/model_choice_phase_b_comparison.html`

The report includes:

- top-level `ACCEPT` replay verdict;
- quality comparison;
- task-level regression for `q09-auth-risk`;
- model routing section with per-role model changes;
- vLLM serving-correlation evidence;
- finding lifecycle and recommendation verification sections.

## Artifacts Preserved

Compact sanitized evidence is committed under `docs/data/m25_phase_b/`:

- `strong_control/agentperf_artifact/`
- `mixed_evidence_backed/agentperf_artifact/`
- `model_choice_phase_b_comparison.json`
- `model_choice_phase_b_report.txt`
- `agentperf_compare.txt`
- `agentperf_check_m3_policy.txt`
- `model_choice_phase_b_comparison.html`
- `reviewer_repeatability.json`
- concise setup and preflight files

Not committed:

- model weights;
- full server logs;
- Runpod credentials;
- raw environment secrets;
- large temporary bundles.

## Interpretation

Historical Phase A provided `LOCAL_ROLE_HEADROOM`: one-role counterfactuals
suggested that specific roles might tolerate smaller Qwen3 models.

New Phase B provides `GLOBAL_ROUTING_VERIFIED`: the pre-registered mixed route
was replayed end to end and passed the quality constraint while improving the
relative cost proxy and same-environment latency evidence.

The observed result still reflects non-monotonic sensitivity from Phase A:
model size was not treated as a monotonic guarantee, and the mixed route was
accepted only after replay.

## Public Claim Wording

Safe wording:

> In one bounded research-agent workload, AgentPerf used role-level
> counterfactual evidence to construct and end-to-end verify a mixed-model
> routing under a predefined quality constraint.

Do not claim:

- optimal model routing;
- universal model downsizing;
- dollar cost savings;
- production-wide savings;
- monotonic model-size behavior.

## Limitations

- Single workload with 10 tasks.
- Single same-family Qwen3 model ladder.
- Single RTX 3090 environment.
- Relative model-capacity cost proxy, not provider pricing.
- Quality passed at the pass-rate floor; broader validation would be needed
  before operational deployment.
- No production concurrency or distributed-serving validation.
