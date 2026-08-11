# AgentPerf v0.3.0 Release Notes

Release title: **Reusable Agent-Performance Development Workflow**

These notes summarize the v0.3.0 release-prep state. They do not create a tag,
publish a package, or claim production readiness.

## What Changed

AgentPerf has grown from an early cross-layer profiler into a local developer
workflow for agent-performance work:

- compare baseline and candidate runs;
- preserve task quality, environment metadata, findings, and traces in portable
  artifacts;
- verify changes with quality-aware regression policies;
- manage benchmark suites with explicit reviewed baselines;
- gate component-attributed token processing, not only provider-reported usage;
- generate a standalone local HTML profiler report;
- ingest and correlate serving telemetry from both vLLM and SGLang.

## Why It Matters

Agent performance work is risky when token or latency reductions are separated
from task quality. AgentPerf v0.3.0 makes replay verification a first-class
workflow: a developer can record a baseline artifact, record a candidate
artifact, compare them, and get PASS / FAIL / INCONCLUSIVE evidence suitable for
local review or CI.

## Example Workflow

```bash
agentperf analyze examples/artifacts/m3_raw_full
agentperf compare examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only
agentperf check \
  examples/artifacts/m3_raw_full \
  examples/artifacts/m3_dedup_only \
  --policy examples/policies/m3-context-regression.yaml
agentperf report examples/artifacts/m3_dedup_only --output agentperf-report.html
```

For team workflows:

```bash
agentperf suite validate examples/benchmark_suites/m3_context
agentperf suite check examples/benchmark_suites/m3_context examples/artifacts/m3_dedup_only
```

## Real Validation

The primary quantitative optimization example remains the controlled M3
research-agent workload:

| Metric | RAW_FULL | DEDUP_ONLY |
| --- | ---: | ---: |
| Mean quality | 0.933 | 0.908 |
| Pass rate | 80% | 70% |
| Input tokens | 132,756 | 95,479 |
| Tool-result processed tokens | 112,287 | 78,566 |
| Scheduled-to-first P95 | 312.180 ms | 176.534 ms |

The preserved replay evidence reaches `ACCEPT` under the declared quality
tolerance. This is a controlled workload result, not a universal token or
latency reduction claim.

M2 prefix-cache validation remains a real vLLM mechanism/correctness result:
AgentPerf detected repeated context that failed to form a reusable prefix and
verified the layout fix through replay. Exact M2 measurements are kept in the
detailed reproducibility docs rather than used as release headline numbers.

M13/M14 dogfooding showed why component attribution matters:

| Metric | Baseline | Candidate |
| --- | ---: | ---: |
| Provider input tokens | 1,604 | 1,604 |
| AgentPerf system processed tokens | 680 | 520 |
| Quality | 1.000 | 1.000 |

Provider usage stayed flat while AgentPerf's component attribution exposed a
real system-context processing change.

## Serving Backend Support

AgentPerf supports cross-layer ingestion and correlation for vLLM and SGLang,
with backend-specific telemetry semantics preserved.

- vLLM: validated with request IDs, token usage, token IDs when recorded, queue
  timing, scheduled-to-first-token path evidence, generation timing, and cached
  prompt tokens.
- SGLang: validated in M17 with 10/10 exact AgentPerf LLM request ID joins to
  SGLang serving requests, token usage, cache-report cached-token evidence, and
  HTML visualization.

SGLang ordinary OpenAI-compatible responses in the validated run did not expose
per-request queue latency, server-stage first-token timing, or generation/decode
latency. Missing telemetry remains explicit; it is not treated as zero.

## External Agent Integrations

- OpenAI Agents SDK is integrated through public instrumentation boundaries.
- mini-SWE-agent was profiled through its existing local coding loop on bounded
  repository-repair tasks.

The mini-SWE-agent workload is not SWE-bench validation.

## Experimental Capabilities

M4 Phase A model-choice profiling is validated as role-level counterfactual
replay over planner, reviewer, and synthesizer roles. M4 Phase B mixed-routing
end-to-end replay remains pending. Do not claim mixed-routing gains from this
release.

## Upgrade And Compatibility Notes

- Package version: `0.3.0`.
- Artifact schema version remains `1`.
- Regression policy schema version remains `1`.
- Benchmark suite schema version remains `1`.
- Raw trace `agentperf analyze` and `agentperf compare` workflows remain
  supported.
- Backend/framework integrations remain optional; `import agentperf` should not
  require vLLM, SGLang, OpenAI Agents SDK, or mini-SWE-agent.

AgentPerf package version, artifact schema version, benchmark suite version, and
regression policy schema version are intentionally separate.

## Known Limitations

- Workloads are small and controlled; they are not statistically powered
  benchmarks.
- Serving telemetry differs by backend and recording path.
- Scheduled-to-first-token is not pure GPU prefill kernel latency.
- Missing evidence does not imply the corresponding metric is zero.
- Repeated context is not automatically removable waste.
- No hosted service, dashboard, remote artifact registry, GPU orchestration, or
  production-scale ingestion pipeline is included.
