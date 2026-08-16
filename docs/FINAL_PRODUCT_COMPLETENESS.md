# AgentPerf Final Product Completeness

Audit date: 2026-08-16

Authoritative main commit: `ad5e6f727e72942d302c5837a4b469a2e3b80fa7`

Latest stable release: `v0.4.0`

Current package version: `0.4.0`

Artifact schema version: `1`

## Scope

This audit evaluates AgentPerf as a local/offline profiler for agent
performance work. It does not authorize a release, bump the package version, or
publish to PyPI.

AgentPerf's intended product loop is:

```text
CAPTURE -> PROFILE -> DIAGNOSE -> RECOMMEND -> REPLAY -> VERIFY -> REGRESSION GUARD
```

## Completeness Matrix

| Area | Status | Evidence | Remaining limitation |
|---|---|---|---|
| Capture | COMPLETE | Framework-free BYOA APIs, OpenAI Agents SDK, LangGraph, async/concurrent tracing, long-running checkpoints, multi-agent/branch/handoff metadata. | Explicit instrumentation is still required for prompt components, quality, request IDs, roles, and handoffs. |
| Profile | COMPLETE | Single-run terminal and standalone HTML reports show tasks, spans, components, serving evidence, context growth, checkpoints, and agent/branch attribution. | Very large local HTML files remain a local-file UX limit; no hosted dashboard. |
| Diagnose | COMPLETE | Deterministic findings preserve provenance, materiality gates, cacheability semantics, context/carry-forward evidence, serving correlation, and model-capacity evidence. | Backend-dependent telemetry remains partial when the backend does not expose a metric. |
| Recommend | COMPLETE | Structured recommendation contracts describe objective, intervention classes, expected metric movement, risks, applicability, and verification requirements. | No automatic code rewriting and no LLM-generated advice. |
| Replay | COMPLETE | `agentperf compare` reuses authoritative task matching, quality comparison, metric deltas, finding lifecycle, and routing comparison. | It is not a graph edit-distance or arbitrary semantic trace-alignment engine. |
| Verify | COMPLETE | Quality-aware ACCEPT / REJECT / INCONCLUSIVE verdicts, recommendation verification, and model-routing verification are preserved in JSON, terminal, and HTML outputs. | Acceptance depends on workload-specific quality evidence and policies supplied by the user. |
| Regression Guard | COMPLETE | `agentperf check`, benchmark suites, reviewed baselines, GitHub Actions example, and CI docs support offline filesystem-first regression gates. | No AgentPerf-hosted baseline registry or remote artifact service. |
| Distribution | COMPLETE_WITH_LIMITATIONS | Wheel/sdist build, `twine check`, clean wheel install, source-tree-independent `agentperf demo`, and PyPI Trusted Publishing workflow are prepared. | PyPI publication and release-owner setup have not happened. |

## Closed Optimization Axes

| Axis | Status | Evidence |
|---|---|---|
| Cacheability | CLOSED | vLLM/SGLang cache evidence, provenance labels, cacheability findings, structured recommendations, replay/check support. |
| Context / harness | CLOSED | Component attribution, context growth, TOOL_OUTPUT_BLOAT, M3 quality-constrained replay, comparison HTML, recommendation verification. |
| Model capacity | CLOSED | Historical local role counterfactuals plus M25 Phase B same-environment mixed-routing replay. The tested route was `GLOBAL_ROUTING_VERIFIED` under predefined tolerance. |

## Public Claim Boundaries

- M3 remains the primary scoped quantitative public optimization example.
- M2 is prefix-cache mechanism validation, not a general speedup claim.
- M20 is heterogeneous workload validation, not detector-accuracy benchmarking.
- `agentperf demo` is an onboarding demonstration, not a benchmark.
- M25 Phase B validates one tested mixed routing, not optimal routing,
  universal downsizing, or commercial cost savings.
- M26 multi-agent support is explicit local/offline profiling metadata and
  visualization, not distributed tracing, orchestration, or automatic DAG
  reconstruction.
- Long-running capture preserves evidence up to the latest completed
  checkpoint. It is not a zero-data-loss or SIGKILL-final-flush guarantee.

## Remaining Gaps

P0: none known.

P1: PyPI release-owner configuration and first package-index publication remain
open. This blocks the canonical public onboarding command from working:

```bash
pip install agentperf
agentperf demo
```

P2: adoption and real-user validation. Most current validation is local,
deterministic, and maintainer-run.

Out of scope for core completeness:

- hosted dashboard;
- cloud artifact registry;
- third serving backend;
- additional framework adapters;
- automatic code rewriting;
- LLM-generated recommendation engine;
- universal evaluator;
- GPU kernel tracing;
- distributed scheduling;
- historical SaaS analytics.

## Decision

AgentPerf should stop feature development for the intended local/offline
profiler scope and move to distribution, release, and adoption validation.

