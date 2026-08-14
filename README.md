# AgentPerf

AgentPerf is a cross-layer performance profiler for AI agents. It attributes
agent context and token cost, correlates agent LLM calls with serving telemetry
when available, diagnoses performance waste, and verifies changes through
replay and CI regression checks.

Generic tracing answers "what happened?" AgentPerf is built to answer the next
questions:

- where did the token and latency budget go?
- which prompt components were processed repeatedly?
- did serving telemetry show cache or first-token evidence?
- did the proposed change actually help without breaking task quality?

The core loop is:

```text
TRACE -> PROFILE -> DIAGNOSE -> RECOMMEND -> REPLAY -> VERIFY
```

AgentPerf is not a hosted dashboard, an automatic optimizer, a scheduler, or an
LLM-based trace summarizer. Findings come from normalized telemetry,
component-level accounting, deterministic detectors, and replay evidence.

## What You Can Do

- Analyze normalized agent traces and self-contained experiment artifacts.
- Bring your own Python agent with framework-free `ExperimentSession`,
  `trace_run`, `trace_llm`, and `trace_tool` instrumentation.
- Check whether an integration captured enough evidence with `agentperf doctor`.
- Attribute processed tokens to system, user, history, tool schema, tool
  result, retrieved/file context, and other components.
- Compare baseline and candidate runs with quality-aware ACCEPT / REJECT /
  INCONCLUSIVE verdicts.
- Run offline CI regression checks with explicit quality, performance, finding,
  and task-coverage policies.
- Manage benchmark suites with reviewed baseline artifacts.
- Generate a standalone local HTML profiler report.
- Correlate agent LLM requests with vLLM or SGLang serving requests when stable
  request IDs are captured.

## Quick Start

AgentPerf does not require a GPU for local inspection, tests, synthetic traces,
recorded telemetry fixtures, artifact comparison, regression checks, benchmark
suites, or HTML reports.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Analyze a provided local artifact:

```bash
agentperf analyze examples/artifacts/m3_dedup_only
```

For a guided first run that explains trace inspection, metric provenance,
finding materiality, HTML reports, replay comparison, and CI checks, see
[docs/FIRST_RUN.md](docs/FIRST_RUN.md).

If you already have a Python agent, start with
[docs/BRING_YOUR_OWN_AGENT.md](docs/BRING_YOUR_OWN_AGENT.md). It shows the
minimal `ExperimentSession` / `trace_llm` / `trace_tool` path and how to run
`agentperf doctor` to check capture completeness.

Compare two self-contained artifacts:

```bash
agentperf compare examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only
```

Run an offline regression check:

```bash
agentperf check \
  examples/artifacts/m3_raw_full \
  examples/artifacts/m3_dedup_only \
  --policy examples/policies/m3-context-regression.yaml
```

Generate a standalone profiler report:

```bash
agentperf report examples/artifacts/m3_dedup_only --output agentperf-report.html
```

Use a benchmark suite with an explicit reviewed baseline:

```bash
agentperf suite validate examples/benchmark_suites/m3_context
agentperf suite check examples/benchmark_suites/m3_context examples/artifacts/m3_dedup_only
```

Record future experiments with `ExperimentSession`:

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool

with ExperimentSession(output_path=Path("runs/baseline"), workload_id="my-workload") as exp:
    with trace_run(task_id="task-1"):
        with trace_llm(
            model="my-model",
            components={"system": system_prompt, "user": user_prompt},
        ) as call:
            response = invoke_model(...)
            call.record_response(
                output=response.text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                request_id=response.request_id,
            )

        with trace_tool("lookup_policy") as tool:
            policy = lookup_policy(...)
            tool.record_output(policy)

    exp.record_task_result(task_id="task-1", passed=True, quality_score=1.0)
```

A trace tells AgentPerf what happened. An artifact bundle also records task
quality, findings, environment metadata, and summary data, which lets replay
verification and CI checks work without experiment-specific JSON glue.

## Local HTML Profiler

```bash
agentperf report examples/artifacts/m17_sglang_support_triage --output report.html
```

The HTML report is a single self-contained local file. It shows workload
identity, task/run structure, LLM and tool steps, context growth, component token
attribution, findings and provenance, serving telemetry when present, and exact
agent-to-serving request correlation when available. It works offline and does
not embed large raw prompts or tool outputs by default.

## Why It Is Cross-Layer

```text
agent execution
  -> LLM call
  -> prompt/component attribution
  -> serving request correlation
  -> backend telemetry where exposed
```

AgentPerf only correlates requests when identifiers prove the relationship. It
does not silently join agent calls to serving requests by timestamp proximity.

This is not GPU kernel tracing. AgentPerf does not provide CUDA kernel
attribution, hardware counters, or pure GPU prefill kernel timing.

## Token Accounting

AgentPerf keeps two token accounting systems separate:

- **Model-provider usage**: prompt and completion tokens reported by the model
  provider or serving backend.
- **AgentPerf component attribution**: AgentPerf's accounting of which agent
  context components caused prompt processing.

These can differ. In the M13/M14 dogfooding run, provider input tokens were
unchanged:

```text
1,604 -> 1,604
```

but AgentPerf component attribution showed lower system-context processing:

```text
680 -> 520
```

with quality unchanged at `1.000 -> 1.000`. That example is evidence that
component-level attribution can expose agent-context changes that aggregate
provider usage alone may miss. It is not a latency-improvement claim.

See [docs/TOKEN_ACCOUNTING.md](docs/TOKEN_ACCOUNTING.md).

## Real Validation

These are small controlled engineering validations, not general benchmark
claims. The primary public quantitative optimization example is the M3
research-agent context-waste replay.

### Quality-Constrained Context Waste

In the controlled M3 research-agent workload, AgentPerf identified repeated
tool-result carry-forward as the dominant processed-token source. The accepted
`DEDUP_ONLY` replay reduced duplicate retrieved-passage carry-forward while
keeping quality within the declared tolerance.

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
| Scheduled-to-first P95 | 312.180 ms | 176.534 ms |
| Historical client P95 | 1607.11 ms | 1247.62 ms |

The replay verdict is `ACCEPT`: processed input tokens fell by 28.1%,
tool-result processing fell by 30.0%, scheduled-to-first P95 fell by 43.5%, and
the preserved historical client P95 fell by about 22.4%, while quality stayed
inside the predefined tolerance.

Details:
[docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md](docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md).

### Prefix-Cache Mechanism Validation

AgentPerf validated prefix-cache diagnosis and replay against real vLLM,
including detection of repeated context that failed to form a reusable prefix.
The controlled M2 workload changed prompt layout while keeping model, serving
configuration, sampling settings, and semantic content fixed.

This is treated as serving mechanism/correctness validation. Exact M2
request-level numbers remain in detailed reproducibility docs, not as release
headline or marketing claims:
[docs/REAL_VLLM_RESULTS.md](docs/REAL_VLLM_RESULTS.md) and
[docs/VLLM_PREFIX_CACHE_SEMANTICS.md](docs/VLLM_PREFIX_CACHE_SEMANTICS.md).

### External Agents And Serving Correlation

- OpenAI Agents SDK: validated through public instrumentation boundaries.
- OpenAI Agents SDK + vLLM: 10/10 exact request correlations in the real M6
  vLLM run using propagated request IDs.
- OpenAI Agents SDK + SGLang: 10/10 exact request correlations in the real M17
  workload using propagated request IDs.
- mini-SWE-agent: validated on a bounded local repository-repair coding loop.
  This was not SWE-bench validation and not an optimization win.

The external-agent validations demonstrate integration and profiling
generalization. They should not be read as broad benchmark results.

The M20 generalization review extends this across three local workload classes
and classifies findings as actionable, valid-but-non-actionable, expected
structural behavior, insufficient evidence, or false positive:
[docs/M20_REAL_WORLD_GENERALIZATION.md](docs/M20_REAL_WORLD_GENERALIZATION.md).

### Model-Choice Profiling

M4 Phase A validated role-level counterfactual replay for planner, reviewer,
and synthesizer roles across Qwen3 0.6B, 1.7B, and 4B. It found role-specific
model-capacity headroom. M4 Phase B mixed-routing end-to-end replay is still
pending, so no mixed-routing quality, latency, or cost improvement is claimed.

Details:
[docs/MODEL_CHOICE_PROFILING.md](docs/MODEL_CHOICE_PROFILING.md) and
[docs/MODEL_CHOICE_RESULTS.md](docs/MODEL_CHOICE_RESULTS.md).

## Supported Integrations

### Agent / Framework Inputs

- Framework-free AgentPerf instrumentation.
- OpenAI Agents SDK integration through public wrappers/hooks.
- mini-SWE-agent profiling through public model/environment boundaries.

### Serving Backends

AgentPerf supports cross-layer ingestion and correlation for vLLM and SGLang,
but available serving metrics depend on what each backend exposes and what the
caller records.

| Backend | Validated scope |
| --- | --- |
| vLLM | request IDs, token usage, token IDs when recorded, queue timing, scheduled-to-first-token path evidence, generation timing, cached prompt tokens |
| SGLang | request IDs, token usage, client streaming timings when recorded, cached prompt tokens when cache reporting is enabled, aggregate/backend provenance |

SGLang ordinary OpenAI-compatible responses in M17 did not expose per-request
queue latency, server-stage first-token timing, or generation/decode latency.
Those fields remain unavailable rather than being inferred.

See [docs/SERVING_BACKENDS.md](docs/SERVING_BACKENDS.md) and
[docs/SGLANG_TELEMETRY.md](docs/SGLANG_TELEMETRY.md).

## Detector Semantics

AgentPerf separates technical headroom from operational materiality.

- dominant does not necessarily mean material;
- repeated does not necessarily mean removable;
- headroom does not necessarily mean actionable;
- missing evidence does not mean negative evidence.

For backend-dependent diagnostics, detectors either run with supported evidence,
degrade to weaker evidence, or skip with explicit missing-evidence semantics.

Important examples:

- `CROSS_RUN_SHARED_SCAFFOLD` is not a context-removal warning. Repetition
  across independent tasks may be relevant to static/prefix caching only when
  backend evidence supports that interpretation.
- vLLM scheduled-to-first-token is stored as first-token path evidence. It is
  not pure GPU prefill kernel latency.

## CI And Team Workflow

AgentPerf's artifact/check/suite workflow is filesystem-first and offline.

```text
ExperimentSession
  -> self-contained artifact
  -> agentperf compare
  -> RegressionPolicy
  -> agentperf check
  -> BenchmarkSuite
  -> explicit reviewed baseline
  -> agentperf suite check
  -> PASS / FAIL / INCONCLUSIVE
```

Useful docs:

- [docs/ARTIFACT_FORMAT.md](docs/ARTIFACT_FORMAT.md)
- [docs/EXPERIMENT_SESSION.md](docs/EXPERIMENT_SESSION.md)
- [docs/REPLAY_COMPARISON.md](docs/REPLAY_COMPARISON.md)
- [docs/REPLAY_VERIFICATION.md](docs/REPLAY_VERIFICATION.md)
- [docs/CI_REGRESSION.md](docs/CI_REGRESSION.md)
- [docs/CI_REPORTING.md](docs/CI_REPORTING.md)
- [docs/BENCHMARK_SUITES.md](docs/BENCHMARK_SUITES.md)
- [docs/BASELINE_MANAGEMENT.md](docs/BASELINE_MANAGEMENT.md)

## Documentation Index

Core concepts:

- [docs/FIRST_RUN.md](docs/FIRST_RUN.md): guided local first-user workflow.
- [docs/BRING_YOUR_OWN_AGENT.md](docs/BRING_YOUR_OWN_AGENT.md): instrument an
  existing framework-free Python agent.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): architecture.
- [docs/TRACE_SCHEMA.md](docs/TRACE_SCHEMA.md): normalized trace schema.
- [docs/TOKEN_ACCOUNTING.md](docs/TOKEN_ACCOUNTING.md): provider usage vs
  component-attributed token semantics.
- [docs/DUPLICATION_SEMANTICS.md](docs/DUPLICATION_SEMANTICS.md):
  run-boundary-aware duplication semantics.
- [docs/HTML_REPORT.md](docs/HTML_REPORT.md): standalone offline profiler
  report.
- [docs/M18_PROFILER_CREDIBILITY.md](docs/M18_PROFILER_CREDIBILITY.md):
  metric provenance, materiality gates, and investigation chains.
- [docs/M19_BRING_YOUR_OWN_AGENT.md](docs/M19_BRING_YOUR_OWN_AGENT.md):
  instrumentation completeness, readiness checks, and BYOA dogfooding.

Validation and backend evidence:

- [docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md](docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md):
  M3 research-agent context-waste replay.
- [docs/REAL_VLLM_RESULTS.md](docs/REAL_VLLM_RESULTS.md): M2 detailed vLLM
  prefix-cache mechanism validation.
- [docs/VLLM_PREFIX_CACHE_SEMANTICS.md](docs/VLLM_PREFIX_CACHE_SEMANTICS.md):
  request-by-request vLLM cache behavior.
- [docs/REAL_TELEMETRY_MAPPING.md](docs/REAL_TELEMETRY_MAPPING.md): vLLM field
  mapping.
- [docs/SERVING_BACKENDS.md](docs/SERVING_BACKENDS.md): serving backend matrix.
- [docs/SGLANG_TELEMETRY.md](docs/SGLANG_TELEMETRY.md): SGLang telemetry mapping.
- [docs/EXTERNAL_AGENT_VLLM_VALIDATION.md](docs/EXTERNAL_AGENT_VLLM_VALIDATION.md):
  OpenAI Agents SDK plus vLLM validation.
- [docs/REAL_WORLD_GENERALIZATION_RESULTS.md](docs/REAL_WORLD_GENERALIZATION_RESULTS.md):
  mini-SWE-agent profiling result.
- [docs/M20_REAL_WORLD_GENERALIZATION.md](docs/M20_REAL_WORLD_GENERALIZATION.md):
  heterogeneous workload review and finding-usefulness taxonomy.
- [docs/DOGFOODING_WORKFLOW.md](docs/DOGFOODING_WORKFLOW.md): end-to-end
  workflow dogfooding.

Release and positioning:

- [CHANGELOG.md](CHANGELOG.md): release history.
- [docs/RELEASE_NOTES_v0.4.0.md](docs/RELEASE_NOTES_v0.4.0.md): v0.4.0 release
  notes.
- [docs/RELEASE_NOTES_v0.3.0.md](docs/RELEASE_NOTES_v0.3.0.md): v0.3.0 release
  notes.
- [docs/PROJECT_STORY.md](docs/PROJECT_STORY.md): conservative project and
  interview framing.
- [docs/LANDSCAPE.md](docs/LANDSCAPE.md): competitive and novelty review.

## Limitations

- Workloads are small and controlled; they are not statistically powered
  benchmarks.
- AgentPerf does not claim universal support for every agent framework, model,
  or OpenAI-compatible serving backend.
- vLLM and SGLang both have real cross-layer validation, but their telemetry
  surfaces are not feature-equivalent.
- Serving metrics are only as complete as the backend and recording path expose.
- M4 mixed-routing replay is not complete.
- The local-corpus and support-triage quality evaluators are deterministic but
  task-specific.
- mini-SWE-agent validation used bounded local repository-repair tasks, not
  SWE-bench.
- AgentPerf does not perform production-scale distributed trace ingestion.
- No dashboard, hosted service, database, remote artifact registry, scheduler,
  or GPU orchestration is included.

## Not Claimed

AgentPerf does not claim:

- automatic optimization;
- production readiness;
- benchmark-proven general speedups;
- SGLang/vLLM performance superiority in either direction;
- pure GPU prefill kernel tracing;
- that repeated content is always removable waste;
- that every detector works identically on every backend;
- that the proposed M4 mixed-routing candidate is validated.

## License

MIT License. See [LICENSE](LICENSE).
