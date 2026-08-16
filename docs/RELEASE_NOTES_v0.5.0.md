# AgentPerf v0.5.0

AgentPerf v0.5.0 is prepared around one product loop:

```text
CAPTURE -> PROFILE -> DIAGNOSE -> RECOMMEND -> CHANGE -> REPLAY -> VERIFY -> REGRESSION GUARD
```

This release is intended for a coordinated GitHub Release and first PyPI
publication. Do not treat the PyPI install command as available until the
package owner completes publication.

## Try It Locally

After PyPI publication:

```bash
pip install agentperf
agentperf demo
```

Before PyPI publication, install from the GitHub source package or a reviewed
local wheel.

`agentperf demo` runs entirely locally. It creates baseline and candidate
artifacts, generates a profiler report and comparison report, surfaces a
deterministic finding, verifies task quality, and runs the same compare/check
workflow a user would run on their own agent. The demo is an onboarding example,
not a benchmark.

## Bring Your Own Agent

Framework-free instrumentation remains the base path:

```python
from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool
```

Use `ExperimentSession` with `trace_run`, `trace_llm`, and `trace_tool` to
record task/run boundaries, prompt components, provider usage, request IDs,
tool calls, task quality, model roles, agent IDs, branch IDs, and handoffs when
those dimensions matter.

## Profile Real Execution Structures

v0.5.0 adds stronger local/offline capture for realistic agents:

- async and concurrent tracing with task-local parentage;
- long-running checkpoint and recovery as explicit `PARTIAL` artifacts;
- explicit multi-agent, branch, handoff, fan-out, and fan-in metadata;
- per-agent and per-branch attribution in terminal and HTML reporting;
- optional LangGraph integration;
- OpenAI Agents SDK, mini-SWE-agent, vLLM, and SGLang compatibility paths.

This is not distributed tracing or production orchestration. AgentPerf observes
local evidence that the user records.

## Diagnose And Verify

Findings now include structured recommendation contracts:

- objective;
- possible intervention classes;
- expected metric movement;
- quality risk;
- applicability;
- replay verification requirements.

Replay verification remains quality-aware. Performance improvements are not
accepted when task quality violates the configured tolerance.

`agentperf compare --format html --output comparison.html` produces a
standalone before/after report showing verdict, quality, token/component deltas,
finding lifecycle, policy checks, serving evidence, recommendation
verification, and model-routing evidence when present.

## Model-Capacity Replay

AgentPerf now separates:

- `LOCAL_ROLE_HEADROOM`: one role/model substitution preserved quality while
  other roles stayed fixed;
- candidate routing: a proposed multi-role routing that still needs replay;
- `GLOBAL_ROUTING_VERIFIED`: the full mixed routing was replayed end to end and
  satisfied quality and efficiency evidence requirements.

Historical one-role-at-a-time counterfactual replay identified local
model-choice headroom. AgentPerf then tested one pre-registered mixed routing
against a fresh same-environment all-strong baseline.

The candidate remained within predefined quality tolerance and improved a
relative model-capacity cost proxy, so that tested routing was marked
`GLOBAL_ROUTING_VERIFIED`.

Actual bounded evidence:

| Metric | Baseline | Candidate |
|---|---:|---:|
| Mean quality | 0.967 | 0.933 |
| Pass rate | 90% | 80% |
| Verdict | baseline | within predefined tolerance |

The candidate sits exactly at the allowed pass-rate floor. This is not optimal
routing, production cost savings, universal downsizing, or evidence of
monotonic model-size behavior.

## Serving

vLLM and SGLang support remain available through recorded request IDs and
backend telemetry where exposed.

Important caveats:

- vLLM and SGLang telemetry surfaces are not feature-equivalent.
- Missing serving telemetry remains unavailable rather than inferred.
- `scheduled-to-first` is first-token path evidence, not pure GPU prefill
  kernel timing.
- AgentPerf does not perform GPU kernel tracing.

## Validation

The primary scoped quantitative result remains the controlled M3 research-agent
workload:

| Metric | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Input processing | 132,756 | 95,479 | -28.1% |
| Tool-result processing | 112,287 | 78,566 | -30.0% |
| Scheduled-to-first P95 | 312.180 ms | 176.534 ms | -43.5% |
| Mean quality | 0.933 | 0.908 | -0.025 |
| Pass rate | 80% | 70% | -10pp |

The predefined quality tolerance passed and AgentPerf's replay verdict was
`ACCEPT`.

This is one controlled workload. It should not be generalized as "AgentPerf
reduces tokens by 28%."

## Compatibility

- Artifact schema version remains `1`.
- Benchmark-suite schema version remains `1`.
- Regression-policy schema version remains `1`.
- Existing raw trace analysis, artifact bundles, BYOA, OpenAI Agents SDK,
  LangGraph, vLLM, SGLang, `compare`, `check`, `suite`, `doctor`, and HTML
  reports remain compatible.

## Limitations

AgentPerf v0.5.0 remains intentionally local/offline:

- no hosted dashboard;
- no remote artifact registry;
- no distributed ingestion;
- no production orchestration;
- no graph edit-distance alignment engine;
- no GPU kernel tracing;
- no automatic code rewriting;
- no LLM-generated recommendations;
- no universal detector-accuracy claim;
- no universal model-routing claim.

The demo's large token reductions, M2 cache numbers, M20 tool-heavy reduction,
M25 relative cost-proxy improvement, and synthetic scale timings are preserved
in scoped technical docs only. They are not release headlines or general
performance claims.

