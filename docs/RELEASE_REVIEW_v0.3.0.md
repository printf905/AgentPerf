# AgentPerf v0.3.0 Release Review

Date: 2026-08-11

Scope: release-readiness and public-claim audit for v0.3.0. This pass does not
add product features, rerun GPU experiments, create a tag, publish a package, or
modify historical v0.2.0 release state.

## Release Story

AgentPerf evolved from an early cross-layer profiler into a reusable local
agent-performance development workflow:

1. trace and profile an agent execution;
2. persist a self-contained artifact with task quality and environment metadata;
3. compare baseline and candidate artifacts;
4. verify changes under explicit quality and performance policies;
5. run suite-level CI checks against reviewed baselines;
6. inspect the execution in a standalone local HTML profiler;
7. correlate agent LLM calls with vLLM or SGLang serving telemetry where exact
   request IDs and backend evidence exist.

## Public Claim Audit

| Claim | Classification | Notes |
| --- | --- | --- |
| Cross-layer agent profiler | VERIFIED | Agent spans, LLM calls, prompt components, serving requests, and exact request joins are represented in artifacts. |
| Supports vLLM and SGLang | SUPPORTED WITH CAVEAT | Ingestion/correlation is validated for both; telemetry fields differ by backend and recording path. |
| Quality-aware replay verification | VERIFIED | `agentperf compare` and `agentperf check` consume artifacts with quality evidence and produce conservative verdicts. |
| CI regression guardrails | VERIFIED | Regression policies, exit codes, JSON, Markdown, and suite checks are implemented and tested offline. |
| Component-level token attribution | VERIFIED | Component processed-token totals, coverage, and policy checks are implemented; provider usage remains distinct. |
| Standalone local profiler report | VERIFIED | `agentperf report` generates self-contained HTML from artifacts/raw traces. |
| OpenAI Agents SDK support | VERIFIED | Validated through public instrumentation boundaries. |
| mini-SWE-agent support | SUPPORTED WITH CAVEAT | Validated on bounded local repository-repair tasks; not SWE-bench. |
| Backend-independent | SUPPORTED WITH CAVEAT | Prefer "serving-backend generalization validated on vLLM and SGLang"; do not imply arbitrary backend support. |
| M2 extreme cacheability speedup headline | CONTROLLED EXPERIMENT ONLY | Exact numbers remain only in detailed reproducibility docs. |
| M4 mixed-routing gains | NOT SUFFICIENTLY SUPPORTED | Phase B remains pending; no mixed-routing gains claimed. |

## Validation Summary

Local release-prep validation on `release/v0.3.0-prep`:

- `pytest`: 152 passed.
- `ruff check .`: passed.
- `mypy agentperf tests scripts`: passed.
- `git diff --check`: passed.
- `python -m build --no-isolation`: built
  `agentperf-0.3.0.tar.gz` and `agentperf-0.3.0-py3-none-any.whl`.
- Package metadata: name `agentperf`, version `0.3.0`, Python `>=3.11`,
  MIT SPDX license expression, `agentperf` console entry point, `py.typed`
  included.
- Optional dependency behavior: base `pip install -e .`, `import agentperf`,
  and `agentperf --help` work without vLLM, SGLang, OpenAI Agents SDK, or
  mini-SWE-agent installed.
- CLI smoke coverage: `analyze`, `compare`, `check`, `suite validate`,
  `suite check`, `report`, vLLM recorded fixture analysis, and SGLang recorded
  fixture analysis all ran on local deterministic examples.
- Link audit: local README/docs Markdown links resolve.
- Artifact-size audit: tracked curated artifacts are small JSON examples; the
  largest tracked artifact files are the M3 trace fixtures at about 1.4 MB and
  1.2 MB.
- Security/hygiene scan: no actual API keys, HF tokens, Runpod keys, SSH
  private keys, or tracked diagnostic bundles were found. The M17 artifact uses
  placeholder Runpod URLs and preserves historical `agentperf_version` metadata.
- GitHub CI coverage: local CI remains limited to offline tests, lint, type
  check, deterministic suite regression smoke, and package build.
- Fresh-clone validation: a separate temporary clone installed with
  `pip install -e ".[dev]"`, imported `agentperf` as version `0.3.0`, passed
  152 tests, lint, type check, diff-check, and package build, and passed CLI
  smoke tests for `analyze`, `compare`, `check`, `inspect`, `report`, `suite
  validate`, `suite check`, vLLM recorded fixture analysis, and SGLang recorded
  fixture analysis.

## BLOCKER

None identified.

## SHOULD FIX

- Keep README focused on the v0.3.0 product workflow rather than chronological
  milestone history.
- Keep SGLang wording explicit: cache-report cached tokens are available when
  exposed, but ordinary responses do not provide per-request queue,
  server-stage TTFT, or generation/decode latency.
- Keep all public M2 headline surfaces free of the extreme controlled numbers.

## NICE TO HAVE

- A small committed screenshot of the HTML report could help future GitHub
  presentation, but the generated HTML report itself is sufficient for this
  release.
- More backend/version fixtures would improve confidence but are not necessary
  for v0.3.0.

## POST-RELEASE

- Broader benchmark/task coverage.
- Optional richer HTML visualizations.
- Additional serving backends or deeper backend tracing paths.
- Baseline history/registry functionality.

## Release Decision

**READY FOR v0.3.0**, pending human approval to tag and publish the release.
