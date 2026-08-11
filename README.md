# AgentPerf

AgentPerf is a cross-layer profiler for agentic LLM workloads: it connects what
an agent did with what the inference server measured, then turns that evidence
into optimization experiments a developer can replay.

Current release target: `v0.2.0`, "Real-Validated Cross-Layer Agent Profiling".

Agent observability tools show LLM calls, tool calls, prompts, tokens, latency,
and outputs. Inference engines such as vLLM expose serving facts such as request
timing, scheduled-to-first-token latency, prefix-cache reuse, and generated
token timing. AgentPerf correlates these layers so an engineer can ask:

- Which tokens are being processed repeatedly?
- Are repeated tokens actually reusable by prefix caching?
- Is first-token latency material, or just dominant relative to an idle queue?
- Which agent role appears to need a stronger model, and which does not?
- What change should I replay to verify the diagnosis?

The intended loop is:

```text
TRACE -> PROFILE -> DIAGNOSE -> RECOMMEND -> REPLAY -> VERIFY
```

AgentPerf is not a Langfuse clone, a scheduler replacement, an automatic
optimizer, or an LLM that reads traces and invents advice. Findings are produced
from telemetry, derived metrics, deterministic detectors, and replay evidence.

## Real Validation Results

These are small controlled engineering validations, not general benchmark
claims. The primary quantitative optimization result is the M3 real-agent
context-waste replay. M2 is treated as a serving-mechanism validation: it
proves AgentPerf can detect repeated context that fails to form a reusable
prefix, recommend a layout change, and verify the behavior against real vLLM.

### Prefix Cacheability

Environment: vLLM `0.26.0+cu129`, `Qwen/Qwen3-0.6B`, NVIDIA RTX A5000.

The M2 workload kept the same model, serving configuration, sampling settings,
and semantic content while changing only prompt layout:

```text
baseline:  dynamic_context + stable_context
optimized: stable_context + dynamic_context
```

AgentPerf found `CONTEXT_DUPLICATION`, `PREFIX_CACHE_OPPORTUNITY`, and
`MATERIAL_PREFILL_BOTTLENECK` on the baseline. After reorganizing stable context
into a reusable prefix, `PREFIX_CACHE_OPPORTUNITY` disappeared and the material
prefill-path bottleneck downgraded.

The exact request-level measurements remain in the reproducibility docs rather
than being used as a headline result. Details:
[docs/REAL_VLLM_RESULTS.md](docs/REAL_VLLM_RESULTS.md) and
[docs/VLLM_PREFIX_CACHE_SEMANTICS.md](docs/VLLM_PREFIX_CACHE_SEMANTICS.md).

### Real-Agent Context Waste

Environment: vLLM `0.26.0+cu129`, `Qwen/Qwen3-0.6B`, NVIDIA RTX 3090.

The workload is a framework-free multi-step research agent:

```text
planner LLM -> local search -> evidence-review LLM -> local search -> final synthesis LLM
```

Evaluation used 10 deterministic local-corpus research tasks. AgentPerf first
identified raw tool-result reinjection as the dominant processed-token source.
An aggressive compact representation reduced tokens much more, but hurt
quality. The accepted strategy, `DEDUP_ONLY`, removed duplicate retrieved
passage carry-forward while preserving unique raw evidence.

Quality constraint:

```text
mean score >= baseline - 0.05
pass rate  >= baseline - 0.10
```

| Metric | RAW_FULL | DEDUP_ONLY |
| --- | ---: | ---: |
| Mean quality | 0.933 | 0.908 |
| Pass rate | 80% | 70% |
| Input tokens | 132,756 | 95,479 |
| Tool-result processed tokens | 112,287 | 78,566 |
| Scheduled->first P95 | 312.18 ms | 176.53 ms |
| Client latency P95 | 1607.11 ms | 1247.62 ms |

This is the current quality-constrained context-waste story: 28.1% fewer
processed input tokens, 30.0% fewer processed tool-result tokens, 43.5% lower
scheduled-to-first P95, and 22.4% lower client-latency P95 while staying within
the declared quality tolerance.

Details:
[docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md](docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md).

### Model-Choice Profiling

Status: Phase A validated, Phase B pending.

Environment: vLLM `0.26.0+cu129`, Qwen3 model ladder, NVIDIA RTX 3090.

Strong baseline:

```text
Planner 4B / Reviewer 4B / Synthesizer 4B
mean quality = 0.967
pass rate    = 90%
```

Role-sensitivity replay:

| Role change | Mean quality | Pass rate | Status |
| --- | ---: | ---: | --- |
| Planner -> 1.7B | 0.967 | 90% | quality preserving |
| Planner -> 0.6B | 0.933 | 80% | within tolerance |
| Reviewer -> 1.7B | 0.900 | 70% | quality violation |
| Reviewer -> 0.6B | 0.967 | 90% | noisy, do not generalize |
| Synthesizer -> 1.7B | 0.967 | 90% | quality preserving |
| Synthesizer -> 0.6B | 0.967 | 90% | quality preserving |

AgentPerf emitted replay-backed `MODEL_CHOICE_HEADROOM` findings for Phase A
counterfactuals. The proposed mixed route
`Planner=1.7B, Reviewer=0.6B, Synthesizer=0.6B` has not been validated end to
end. Do not report mixed-routing quality, latency, or cost improvement from the
current repository.

Details: [docs/MODEL_CHOICE_PROFILING.md](docs/MODEL_CHOICE_PROFILING.md) and
[docs/MODEL_CHOICE_RESULTS.md](docs/MODEL_CHOICE_RESULTS.md).

### External Agent Integration

Status: first external-framework adapter implemented; no material issue found
on the initial local workload.

AgentPerf now includes an optional OpenAI Agents SDK integration. The M5
workload uses the SDK's real `Agent`, `Runner`, and `function_tool` loop with a
deterministic local support-triage tool and scripted model, so it can run
without OpenAI API credentials, GPU access, or live search APIs.

Observed local M5 run:

| Metric | Value |
| --- | ---: |
| Tasks | 10 |
| LLM calls | 20 |
| Tool calls | 10 |
| Correlated serving requests | 0 |
| Input tokens | 1,604 |
| Mean score | 1.000 |
| Pass rate | 100% |

AgentPerf captured prompt components, tool-result provenance, token
attribution, and context growth. It emitted `CONTEXT_DUPLICATION` as a repeated
context observation, but the absolute token volume was small and there was no
serving telemetry, so no material optimization/replay claim is made for this
external-agent workload.

Details:
[docs/EXTERNAL_AGENT_SELECTION.md](docs/EXTERNAL_AGENT_SELECTION.md),
[docs/INSTRUMENTATION.md](docs/INSTRUMENTATION.md),
[docs/EXTERNAL_AGENT_BENCHMARK.md](docs/EXTERNAL_AGENT_BENCHMARK.md), and
[docs/GENERALIZATION_REVIEW.md](docs/GENERALIZATION_REVIEW.md).

### External Agent + vLLM Cross-Layer Trace

Status: real cross-layer validation completed; no material issue found.

M6 routed the OpenAI Agents SDK support-triage agent through a live vLLM
OpenAI-compatible endpoint and joined SDK LLM calls to vLLM serving requests by
explicit request ID. The final run used vLLM `0.26.0+cu129`,
`Qwen/Qwen3-4B`, and one RTX 3090.

Small Qwen3 models correlated correctly but did not naturally execute the SDK
tool lifecycle under `tool_choice=auto`. The successful run used a narrow
first-turn `lookup_policy` tool-choice control so the existing support-triage
agent exercised its intended tool path; no tool output or workload pathology
was added.

| Metric | Value |
| --- | ---: |
| Tasks | 5 |
| LLM calls | 10 |
| Tool calls | 5 |
| vLLM serving requests | 10 |
| Explicit correlation success | 100% |
| Input tokens | 2,955 |
| Output tokens | 770 |
| Scheduled->first P95 | 36.26 ms |
| Mean score | 0.700 |
| Pass rate | 60% |

The only finding was low-severity `PREFILL_PATH_DOMINANCE`; AgentPerf did not
emit a material actionable warning.

Details:
[docs/EXTERNAL_AGENT_VLLM_VALIDATION.md](docs/EXTERNAL_AGENT_VLLM_VALIDATION.md).

### Real Existing Agent Profile

M7 adds a second external target: upstream `mini-swe-agent` `DefaultAgent`.
AgentPerf wrapped the public model and local-environment boundaries and profiled
five small repository-repair tasks without changing the agent loop. The run
captured 30 LLM calls and 30 bash actions with 100% task pass rate. It surfaced
context duplication from repeated default prompt scaffolding, but that was not
accepted as a replay-worthy optimization because it was mostly a batch-level
artifact and no serving telemetry was present.

Details:
[docs/REAL_WORLD_AGENT_SELECTION.md](docs/REAL_WORLD_AGENT_SELECTION.md),
[docs/REAL_WORLD_AGENT_BENCHMARK.md](docs/REAL_WORLD_AGENT_BENCHMARK.md), and
[docs/REAL_WORLD_GENERALIZATION_RESULTS.md](docs/REAL_WORLD_GENERALIZATION_RESULTS.md).

## Why This Is Cross-Layer

```text
AGENT / HARNESS LAYER

Real agent
  +-- planner LLM
  +-- tool call
  +-- evidence-review LLM
  +-- tool call
  +-- final synthesis LLM
              |
              v
SERVING LAYER

vLLM serving request
  queue / scheduled->first / generation / ITL / prefix-cache tokens
              |
              v
AGENTPERF

normalized trace
  -> explicit request correlation
  -> token, latency, cache, role, and quality metrics
  -> deterministic detectors and replay-backed analyses
  -> evidence-backed findings
  -> validation plan or replay result
```

AgentPerf only correlates requests when identifiers prove the relationship. It
does not silently join agent calls to serving requests by timestamp proximity.

## Three Classes Of Waste

AgentPerf currently explores three performance questions.

| Class | Question | Current status |
| --- | --- | --- |
| Cacheability waste | The tokens repeat, but why are they not reused by prefix caching? | Real end-to-end validated |
| Context / harness waste | Why are these tokens being processed repeatedly in the first place? | Real end-to-end validated |
| Model-capacity waste | Which semantic roles can use smaller models under replayed quality constraints? | Phase A counterfactual validated; mixed replay pending |

## Implemented Capabilities

| Capability | Status |
| --- | --- |
| Normalized agent trace schema | Implemented |
| Explicit request correlation | Real validated with vLLM |
| vLLM ingestion adapter | Real validated |
| Context duplication detection | Real validated |
| Prefix-cache diagnosis | Real replay validated |
| Prefill materiality calibration | Real calibrated |
| Token component attribution | Real validated |
| Tool-output bloat detection | Real replay validated |
| Quality-constrained context optimization | Real replay validated |
| Model role attribution | Real validated |
| Model-choice counterfactual profiling | Phase A validated |
| End-to-end mixed model routing | Pending |
| Public instrumentation API | Implemented |
| OpenAI Agents SDK adapter | Agent-layer validated |
| External OpenAI Agents SDK + vLLM correlation | Real validated |
| mini-SWE-agent adapter | Agent-layer validated |
| Real existing agent profile | Agent-layer validated; no accepted material optimization |
| External-agent material finding | Not accepted yet |
| SGLang ingestion | Planned |
| Web dashboard | Not implemented |

## Detector Semantics

AgentPerf separates technical headroom from operational materiality.

- `CACHEABILITY_HEADROOM`: there is cacheable structure, but the measured
  latency or uncached-token volume does not justify a strong action.
- `MATERIAL_PREFIX_CACHE_OPPORTUNITY`: repeated stable prefix structure,
  low actual cache reuse, and material first-token/uncached-token evidence
  support a replayable prompt-layout experiment.
- `PREFILL_PATH_DOMINANCE`: the first-token path dominates the latency
  breakdown.
- `MATERIAL_PREFILL_BOTTLENECK`: the first-token path is both dominant and
  operationally large enough to prioritize.
- `CROSS_RUN_SHARED_SCAFFOLD`: repeated prompt scaffold appears across
  independent execution scopes. This is not a context-removal warning; it may
  be relevant to static/prefix caching only when backend telemetry supports
  that interpretation.

The design principle is simple: dominant does not necessarily mean important.
AgentPerf should avoid warning users about technically real headroom that is not
material in the observed run.

M7 added a second materiality rule: repetition across independent tasks is not
the same as redundant context within one task.

Example finding shape:

```text
Finding:       MATERIAL_PREFIX_CACHE_OPPORTUNITY
Evidence:      shared prefix ratio, actual cached-token ratio,
               scheduled->first P95, uncached input tokens
Affected:      LLM call IDs and serving request IDs
Recommendation:evaluate reorganizing stable context into a consistent prefix
Validation:    replay and compare cache reuse, scheduled->first, latency,
               processed tokens, and task quality
```

The pipeline is:

```text
telemetry -> derived metrics -> deterministic/replay-backed evidence -> recommendation
```

not:

```text
trace -> LLM -> generic advice
```

## Quick Start

AgentPerf does not require a GPU for local inspection, tests, synthetic traces,
or recorded telemetry fixtures.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Analyze a synthetic trace:

```bash
agentperf analyze examples/traces/multi_problem_agent.json
```

Analyze a recorded vLLM-shaped fixture:

```bash
agentperf analyze-vllm-recording \
  examples/recorded_telemetry/vllm_openai_response_fixture.json \
  --show-provenance
```

Compare a baseline trace with a replay candidate:

```bash
agentperf compare \
  examples/traces/replay_baseline.json \
  examples/traces/replay_candidate.json \
  --quality-tolerance 0.05 \
  --pass-rate-tolerance 0.10
```

Inspect and compare self-contained experiment artifacts:

```bash
agentperf inspect examples/artifacts/m3_raw_full
agentperf compare examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only
```

Generate a standalone local profiler report:

```bash
agentperf report examples/artifacts/m3_dedup_only --output agentperf-report.html
```

A trace tells AgentPerf what happened. An artifact bundle also records task
quality, findings, environment metadata, and summary data, which lets replay
verification reach an acceptance verdict without experiment-specific scripts.
Provider usage tells you how many tokens the model/backend reported; AgentPerf
component attribution tells you which parts of the agent context caused prompt
processing. Those numbers can differ. See
[docs/TOKEN_ACCOUNTING.md](docs/TOKEN_ACCOUNTING.md).

Use AgentPerf as a regression guard:

```bash
agentperf check \
  examples/artifacts/m3_raw_full \
  examples/artifacts/m3_dedup_only \
  --policy examples/policies/m3-context-regression.yaml
```

`agentperf check` is intended for CI: it applies explicit quality, performance,
finding, and task-coverage thresholds and returns stable PASS / FAIL /
INCONCLUSIVE exit codes. See [docs/CI_REGRESSION.md](docs/CI_REGRESSION.md).

The human-readable output starts with a reviewer-oriented summary:

```text
Result: PASS
Quality: mean_score 0.933 -> 0.908, within policy
Biggest improvements: component.tool_result.processed_tokens -30.0%
Biggest regressions: none above configured thresholds
```

See [docs/CI_REPORTING.md](docs/CI_REPORTING.md).

Team benchmark suites:

```bash
agentperf suite validate examples/benchmark_suites/m3_context
agentperf suite check examples/benchmark_suites/m3_context examples/artifacts/m3_dedup_only
agentperf suite propose-baseline examples/benchmark_suites/m3_context runs/candidate
```

A suite pins the accepted baseline artifact and regression policy explicitly.
Baseline updates are reviewable proposals, not automatic overwrites. See
[docs/BENCHMARK_SUITES.md](docs/BENCHMARK_SUITES.md) and
[docs/BASELINE_MANAGEMENT.md](docs/BASELINE_MANAGEMENT.md).

The repository also includes one offline dogfooding suite:

```bash
agentperf suite validate benchmarks/openai-agents-support-triage
agentperf suite check \
  benchmarks/openai-agents-support-triage \
  examples/dogfooding/openai_agents_support_triage_compact
```

That suite exercises the artifact -> policy -> suite-check workflow without
API keys, GPU access, or network storage. See
[docs/DOGFOODING_WORKFLOW.md](docs/DOGFOODING_WORKFLOW.md).

SDK-first experiment recording:

```python
from pathlib import Path

from agentperf import ExperimentSession

with ExperimentSession(output_path=Path("runs/baseline"), workload_id="my-workload") as exp:
    # run your agent and record task results
    exp.record_task_result(task_id="task-1", passed=True, quality_score=1.0)
```

Run the optional OpenAI Agents SDK integration example:

```bash
pip install -e ".[dev,openai-agents]"
python examples/external_agents/openai_agents_support_triage.py \
  --output-dir /tmp/agentperf_m5_openai_agents
```

Run all local checks:

```bash
pytest
ruff check .
mypy agentperf tests scripts
```

## Synthetic Example

```bash
agentperf analyze examples/traces/multi_problem_agent.json
```

Shortened output:

```text
============================================================
AgentPerf Report
============================================================
Data: synthetic trace fixture, not benchmark results

Run
------------------------------------------------------------
Run ID                             synthetic-multi-problem
LLM calls                          3
Tool calls                         1
Input tokens                       270
Output tokens                      455
Correlated serving requests        3

Findings
------------------------------------------------------------

[LOW] CONTEXT_DUPLICATION
Multiple LLM calls contain exact repeated prompt components.

[LOW] CACHEABILITY_HEADROOM
Correlated requests contain cacheable structure and low cache reuse, but the
observed TTFT and uncached-token volume are not yet material.
```

This fixture is synthetic. It is not benchmark evidence.

## Reproducing Real Experiments

The real results require a live vLLM server on a compatible NVIDIA GPU. They are
not required for basic use of the CLI.

Important controls used in the documented runs:

| Result | Backend / model | GPU | Workload | Repetitions / tasks | Quality evaluator |
| --- | --- | --- | --- | --- | --- |
| Prefix cacheability | vLLM 0.26.0+cu129 / Qwen3-0.6B | RTX A5000 | controlled prompt-layout replay | 3 warmups, 10 measured repetitions per config | output recorded, not quality-scored |
| Context waste | vLLM 0.26.0+cu129 / Qwen3-0.6B | RTX 3090 | local-corpus research agent | 10 deterministic tasks | rule-based fact/pass scorer |
| Model choice Phase A | vLLM 0.26.0+cu129 / Qwen3 0.6B, 1.7B, 4B | RTX 3090 | one-role-at-a-time replay | 10 deterministic tasks | same rule-based scorer |
| External SDK + vLLM correlation | vLLM 0.26.0+cu129 / Qwen3-4B | RTX 3090 | OpenAI Agents SDK support triage | 5 deterministic tasks | rule-based route/policy scorer |
| Real existing agent profile | no serving backend | none | mini-SWE-agent local repo repair | 5 bounded tasks | pytest pass/fail |

Runbooks and mappings:

- [docs/REAL_VLLM_RUNBOOK.md](docs/REAL_VLLM_RUNBOOK.md)
- [docs/REAL_TELEMETRY_MAPPING.md](docs/REAL_TELEMETRY_MAPPING.md)
- [docs/VLLM_RUNPOD_CONTAINER.md](docs/VLLM_RUNPOD_CONTAINER.md)
- [docs/DETECTOR_CALIBRATION.md](docs/DETECTOR_CALIBRATION.md)

Data types are intentionally distinguished:

- synthetic fixtures: hand-built examples for tests and CLI demos;
- recorded fixtures: small vLLM-shaped response examples for parser coverage;
- real measured experiments: documented Runpod/vLLM runs with artifacts and
  cleanup notes.

## Documentation Index

Start here:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): system architecture.
- [docs/TRACE_SCHEMA.md](docs/TRACE_SCHEMA.md): normalized trace schema.
- [docs/DUPLICATION_SEMANTICS.md](docs/DUPLICATION_SEMANTICS.md):
  run-boundary-aware context duplication semantics.
- [docs/ARTIFACT_FORMAT.md](docs/ARTIFACT_FORMAT.md): portable experiment
  artifact bundle format.
- [docs/HTML_REPORT.md](docs/HTML_REPORT.md): standalone offline profiler
  report.
- [docs/EXPERIMENT_SESSION.md](docs/EXPERIMENT_SESSION.md): artifact-by-default
  experiment recording API.
- [docs/REPLAY_COMPARISON.md](docs/REPLAY_COMPARISON.md): generic baseline vs
  replay comparison contract.
- [docs/REPLAY_VERIFICATION.md](docs/REPLAY_VERIFICATION.md): user-facing
  replay verification workflow.
- [docs/TOKEN_ACCOUNTING.md](docs/TOKEN_ACCOUNTING.md): provider usage vs
  AgentPerf component-attributed token semantics.
- [docs/CI_REGRESSION.md](docs/CI_REGRESSION.md): offline regression checks
  for CI.
- [docs/CI_REPORTING.md](docs/CI_REPORTING.md): reviewer-oriented terminal
  and Markdown summaries.
- [docs/BENCHMARK_SUITES.md](docs/BENCHMARK_SUITES.md): filesystem-first
  benchmark suite manifests.
- [docs/BASELINE_MANAGEMENT.md](docs/BASELINE_MANAGEMENT.md): reviewed
  baseline workflow.
- [docs/DOGFOODING_WORKFLOW.md](docs/DOGFOODING_WORKFLOW.md): M13 end-to-end
  workflow dogfooding.
- [docs/LANDSCAPE.md](docs/LANDSCAPE.md): competitive and novelty review.
- [docs/REAL_TELEMETRY_MAPPING.md](docs/REAL_TELEMETRY_MAPPING.md): vLLM field
  mapping and measurement quality.
- [docs/REAL_VLLM_RESULTS.md](docs/REAL_VLLM_RESULTS.md): M2 real vLLM results.
- [docs/VLLM_PREFIX_CACHE_SEMANTICS.md](docs/VLLM_PREFIX_CACHE_SEMANTICS.md):
  request-by-request vLLM cache behavior.
- [docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md](docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md):
  M3 real-agent context-waste results.
- [docs/MODEL_CHOICE_PROFILING.md](docs/MODEL_CHOICE_PROFILING.md): M4 design.
- [docs/MODEL_CHOICE_RESULTS.md](docs/MODEL_CHOICE_RESULTS.md): M4 Phase A
  results and Phase B blocked attempts.
- [docs/EXTERNAL_AGENT_SELECTION.md](docs/EXTERNAL_AGENT_SELECTION.md): M5
  external framework selection.
- [docs/INSTRUMENTATION.md](docs/INSTRUMENTATION.md): public recorder and
  OpenAI Agents SDK adapter.
- [docs/EXTERNAL_AGENT_BENCHMARK.md](docs/EXTERNAL_AGENT_BENCHMARK.md): M5
  external-agent workload and observed local result.
- [docs/GENERALIZATION_REVIEW.md](docs/GENERALIZATION_REVIEW.md): what
  generalized unchanged and what did not.
- [docs/EXTERNAL_AGENT_VLLM_VALIDATION.md](docs/EXTERNAL_AGENT_VLLM_VALIDATION.md):
  M6 external OpenAI Agents SDK plus live vLLM cross-layer validation.
- [docs/REAL_WORLD_AGENT_SELECTION.md](docs/REAL_WORLD_AGENT_SELECTION.md):
  M7 real-world agent selection.
- [docs/REAL_WORLD_AGENT_BENCHMARK.md](docs/REAL_WORLD_AGENT_BENCHMARK.md):
  mini-SWE-agent benchmark and running instructions.
- [docs/REAL_WORLD_GENERALIZATION_RESULTS.md](docs/REAL_WORLD_GENERALIZATION_RESULTS.md):
  M7 observed profile and generalization review.
- [docs/RELEASE_NOTES_v0.2.0.md](docs/RELEASE_NOTES_v0.2.0.md): v0.2.0
  release notes and claim boundaries.
- [CHANGELOG.md](CHANGELOG.md): release history.
- [docs/PRODUCT.md](docs/PRODUCT.md) and
  [docs/BENCHMARK_PLAN.md](docs/BENCHMARK_PLAN.md): product contract and future
  evaluation plan.

## Competitive Positioning

AgentPerf should be judged as a profiler, not as a runtime scheduler.

- ThunderAgent focuses on runtime and scheduling optimization for agent
  workflows. AgentPerf focuses on developer-facing diagnosis, evidence, and
  replay validation. ThunderAgent could become a backend or baseline rather
  than only a competitor.
- Langfuse, Phoenix/OpenInference, Opik, TraceRoot, OpenLIT, OpenLLMetry, and
  Helicone are strong observability/evaluation systems. AgentPerf does not try
  to replace their dashboards. Its niche is cross-layer performance analysis:
  agent prompt structure plus serving telemetry.
- vLLM and SGLang expose the serving telemetry that a profiler can consume.
  AgentPerf does not claim to invent that telemetry.

See [docs/LANDSCAPE.md](docs/LANDSCAPE.md) for the detailed review.

## Limitations

- Workloads are small and controlled.
- vLLM is the only serving backend with real validation so far.
- SGLang ingestion is not implemented.
- Model coverage is limited to one Qwen3 ladder in the documented runs.
- The local-corpus quality evaluator is deterministic but task-specific.
- M4 mixed-routing replay is not complete; Phase A role sensitivity is not an
  end-to-end routing result.
- The experiments are not statistically powered benchmarks.
- The external OpenAI Agents SDK plus vLLM run required a first-turn
  tool-choice compatibility control for Qwen3 tool calling; smaller Qwen3
  models did not naturally trigger SDK tool calls under `auto`.
- The mini-SWE-agent M7 run used bounded local repository-repair tasks and no
  GPU/vLLM serving telemetry; it is not a SWE-bench result or optimization win.
- The initial external-agent workload did not expose a material optimization
  target.
- AgentPerf does not perform production-scale distributed trace ingestion.
- No dashboard, hosted service, database, or scheduler integration is included.
- `scheduled->first` is a measured/request-level first-token path metric. It is
  not claimed to be pure GPU prefill kernel time.

## Not Claimed

AgentPerf does not claim:

- automatic optimization;
- optimal KV-cache sizing;
- scheduler superiority;
- production readiness;
- benchmark-proven general speedups;
- that repeated content is always waste;
- that smaller models are generally better for a role;
- that the proposed M4 mixed-routing candidate is validated.

## License

MIT License. See [LICENSE](LICENSE).
