# AgentPerf Product Completeness Audit

Audit date: 2026-08-16

Starting main commit: `258e0e3a299d7d440aefed2632e5e7c23f74ef21`

Package version: `0.4.0`

Latest stable tag: `v0.4.0`

Collected test baseline before hardening: `225 tests`

## Scope

This audit evaluates the current local/offline profiler product contract:

```text
CAPTURE -> PROFILE -> DIAGNOSE -> RECOMMEND -> REPLAY -> VERIFY -> REGRESSION GUARD
```

It does not propose a release, bump the package version, publish to PyPI, add a
new detector, add a new framework/backend, or start a hosted product.

## Completeness Matrix

| Capability | Status | Evidence | Remaining gap | Severity |
|---|---|---|---|---|
| Framework-free BYOA | COMPLETE | Public `ExperimentSession`, `trace_run`, `trace_llm`, and `trace_tool` APIs; M19 smoke; doctor READY path. | Requires explicit instrumentation points. | NONE |
| ExperimentSession | COMPLETE | Finalizes portable artifacts with task results, quality, environment, findings, and routing summary. | No incremental flush or crash recovery for long-running processes. | P1 |
| `trace_run` | COMPLETE | Records run/task boundaries and nested spans. Async context propagation is now covered by regression tests. | No first-class branch/fan-in schema. | P2 |
| `trace_llm` | COMPLETE | Captures components, usage, request IDs, role/model metadata, timings, and failures. | User must provide exact provider usage/request IDs when needed. | NONE |
| `trace_tool` | COMPLETE | Context manager and decorator paths capture tool input/output metadata, timing, and failures. | Tool output redaction is a rendering concern; raw artifacts preserve captured values. | NONE |
| OpenAI Agents SDK | COMPLETE | Adapter and local tests preserve SDK span conversion and request correlation hooks. | Deep fidelity depends on SDK-exported or wrapped events. | NONE |
| LangGraph | COMPLETE | Optional integration records graph/task boundaries and supports explicit node-level LLM/tool traces. | Automatic deep capture of arbitrary graph internals is intentionally not claimed. | NONE |
| mini-SWE | COMPLETE | M20 validation covers an existing coding-agent loop and structural finding interpretation. | Not a SWE-bench claim. | NONE |
| Component attribution | COMPLETE | Component domains are separated from provider usage; attribution confidence is explicit. | Approximate local tokenization may differ from provider usage by design. | NONE |
| Context growth | COMPLETE | Context growth and carry-forward are reported in terminal, single-run HTML, and comparison HTML. | Very large local HTML remains bounded by M21 tested range. | P2 |
| Cacheability | COMPLETE | vLLM/SGLang cache evidence is provenance-labeled; recommendations and replay verification exist. | Backend telemetry differs. | NONE |
| Tool-output carry-forward | COMPLETE | `TOOL_OUTPUT_BLOAT` diagnoses, recommends, replays, and verifies expected metric movement. | Quality guard remains required before accepting changes. | NONE |
| Model-capacity routing | COMPLETE | M25 Phase B verified a pre-registered mixed routing end to end against fresh same-environment baseline. | Evidence is one bounded workload, not optimal or universal routing. | NONE |
| vLLM | COMPLETE | vLLM fixture path, cache semantics, and first-token provenance are preserved. | No GPU kernel tracing. | NONE |
| SGLang | COMPLETE | SGLang fixture path preserves exact request IDs and available cache evidence. | Ordinary OpenAI-compatible telemetry is less rich than vLLM. | NONE |
| Recommendation contracts | COMPLETE | M24 structured contracts cover current finding families and distinguish recommendation verification from replay verdict. | No auto-fix or LLM-generated advice by design. | NONE |
| `compare` | COMPLETE | Existing comparison engine owns task matching, deltas, lifecycle, quality, and verdict semantics. | Ambiguous task matching remains conservative. | NONE |
| `check` | COMPLETE | Offline policy gate returns PASS/FAIL/INCONCLUSIVE with documented exit codes. | Users must maintain reviewed baselines and policies. | NONE |
| `suite` | COMPLETE | Filesystem-first benchmark suite validation and checking work locally. | Not a hosted registry. | NONE |
| `doctor` | COMPLETE | READY/PARTIAL/NOT_APPLICABLE semantics prevent optional serving telemetry from blocking agent-level profiling. | Advanced optional analyses may be not applicable. | NONE |
| Single-run HTML | COMPLETE | Standalone local HTML with inline assets and redaction defaults. | Large traces are a local-file UX limit, not a correctness issue. | P2 |
| Comparison HTML | COMPLETE | M23 visual replay report shows verdict, quality, token deltas, lifecycle, policy, serving, and routing evidence. | Not a semantic trace-alignment engine. | NONE |
| Demo | COMPLETE | `agentperf demo` runs without network/API/GPU and produces artifacts, reports, compare, and check output. | PyPI publication is still pending. | P1 |

## Special Gap Audits

### Async and Concurrency

Status: USABLE_LIMITATION

AgentPerf now preserves task-local span parentage across `asyncio.gather`,
concurrent tool/LLM calls, branch exceptions, cancellation, and context
propagation across `await` boundaries.

Remaining limitation: the schema does not model parallel branch identity,
fan-out/fan-in edges, or concurrent causal alignment as first-class concepts.
That is not required for the current local profiler contract, but it is a real
P2 limitation for highly parallel agents.

### Multi-Agent

Status: USABLE_LIMITATION

Multiple agents can be represented with separate runs or metadata, and roles can
be represented with `semantic_role`. There is no first-class `agent_id`,
handoff, or cross-agent context entity. This is not currently required to close
the core optimization axes.

### Long-Running and Production Capture

Status: MATERIAL_GAP

AgentPerf is fundamentally an offline/local artifact profiler. `ExperimentSession`
finalizes atomically at session end, but it does not incrementally flush spans,
recover interrupted sessions, coordinate multiple writer processes, or support a
production daemon capture protocol.

This is the strongest remaining functional gap for broad production capture.

### Scale

Status: USABLE_LIMITATION

M21 characterized local scale up to 5,000 LLM calls. This hardening pass reran
the smaller 10/100/500/1,000-call grid and found no obvious superlinear behavior
at that range. AgentPerf should not claim production-scale or distributed
ingestion performance.

### Instrumentation Ergonomics

Status: USABLE_LIMITATION

AgentPerf intentionally requires explicit instrumentation for prompt components,
provider usage, request IDs, task quality, and role/model metadata. That
explicitness preserves provenance, but it remains manual glue for users.

### Distribution

Status: MATERIAL_GAP

Wheel/sdist builds and clean local wheel installs work, but the public PyPI
project is not published. As of this audit, the PyPI JSON endpoint for
`agentperf` returns `404`.

This is now a larger blocker to adoption than another feature.

### Failure Modes

Status: COMPLETE

Existing and new tests cover failures in LLM/tool spans, failed tasks, partial
artifacts, failed artifacts, missing quality, malformed artifacts, malformed
policies, task mismatches, and environment mismatches. Missing evidence remains
unavailable/inconclusive rather than becoming zero, PASS, or successful
verification.

### Security and Privacy

Status: USABLE_LIMITATION

HTML renderers redact prompt/tool payloads by default, escape HTML, and now
redact broader secret-like metadata keys and values. Raw artifacts preserve what
the user records; AgentPerf does not encrypt artifacts.

## Original Optimization Axes

| Axis | Closure status | Evidence |
|---|---|---|
| Cacheability | CLOSED | Cache findings, provenance, recommendation contracts, compatible replay verification. |
| Context/harness | CLOSED | Context attribution, TOOL_OUTPUT_BLOAT, M3 replay, demo replay, recommendation verification. |
| Model capacity | CLOSED | M25 Phase B: local headroom -> pre-registered mixed routing -> fresh same-environment replay -> quality-aware verification. |

## Out Of Scope For Core Completeness

- Hosted dashboard
- Cloud artifact registry
- Third serving backend
- Additional random framework adapters
- Automatic code rewriting
- LLM-generated recommendation engine
- Universal evaluator
- GPU kernel tracing
- Distributed scheduling
- Historical SaaS analytics

These may be future product choices, but current evidence does not make them
core-completeness blockers.

## Top Product Gaps

1. P1: PyPI publication and release-owner setup remain incomplete.
2. P1: Long-running production capture lacks incremental flush, crash recovery,
   and multi-process write coordination.
3. P2: Parallel branch/fan-in and first-class multi-agent semantics are not
   modeled beyond spans/runs/metadata.

No P0 gap was found.

## Conclusion

AgentPerf core functionality now appears complete for a local/offline profiler:
users can capture traces, profile them, diagnose findings, receive structured
recommendations, replay candidates, verify quality/performance, render HTML, and
guard regressions in CI.

The next highest-value work should be distribution/PyPI readiness and adoption
validation, not more feature development.
