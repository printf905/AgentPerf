# AgentPerf v0.4.0 Release Review

Scope: release-readiness and public-claim audit for v0.4.0. This document does
not create a tag or publish a release.

## Release Story

AgentPerf v0.4.0 is framed as:

```text
Bring Your Own Agent + Trustworthy Diagnosis
```

The release makes AgentPerf easier to apply to custom Python agents through a
framework-free public instrumentation path and strengthens report credibility
through metric provenance, explicit materiality gates, readiness diagnostics,
and conservative heterogeneous-workload validation.

## Versioning

- Package version: `0.4.0`.
- Artifact schema version: `1`.
- Benchmark-suite schema version: `1`.
- Regression-policy schema version: `1`.

These versions are intentionally separate. Historical artifacts preserve their
recorded AgentPerf version metadata.

## Public Claim Checklist

| Claim | Status | Notes |
| --- | --- | --- |
| Cross-layer agent profiler | SUPPORTED WITH CAVEAT | Cross-layer means agent execution, LLM calls, prompt/component attribution, serving request correlation, and backend telemetry where exposed. It does not mean GPU kernel tracing. |
| Bring your own Python agent | SUPPORTED WITH CAVEAT | Supported for explicit framework-free Python instrumentation. It is not zero-code automatic instrumentation and not universal runtime support. |
| Framework-free instrumentation | VERIFIED | `ExperimentSession`, `trace_run`, `trace_llm`, and `trace_tool` are package-root public APIs. |
| Works with any agent | NOT CLAIMED | Too broad for current validation. |
| Supports vLLM and SGLang | SUPPORTED WITH CAVEAT | Request correlation and telemetry ingestion are supported; metric coverage depends on backend capabilities. |
| Quality-aware replay verification | VERIFIED | M3 compare/check/suite flows remain compatible. |
| CI regression guardrails | VERIFIED | Existing `check` and suite workflows are preserved. |
| Component-level token attribution | VERIFIED | Provider usage and component attribution remain separate accounting domains. |
| Doctor/readiness diagnostics | VERIFIED | Agent-level readiness is distinct from cross-layer readiness. |
| Validated across heterogeneous workloads | SUPPORTED WITH CAVEAT | Validated on three small local workload classes; not universal generalization. |
| Detector accuracy | NOT CLAIMED | M20 review labels are manual validation classifications, not automatic detector labels or accuracy rates. |

## Release Blockers

None identified during release preparation.

## SHOULD_FIX

Fixed during release preparation:

- Artifact comparison now reports task coverage from artifact task results when
  baseline and candidate artifacts contain explicit task results, including the
  one-run/multiple-task BYOA artifact shape.

No remaining SHOULD_FIX items block release.

## NICE_TO_HAVE

- A future release could add richer before/after visual inspection, but compare
  HTML is not a v0.4 blocker.
- Additional external-user studies would strengthen adoption evidence.

## POST_RELEASE

- Gather independent user feedback on BYOA instrumentation friction.
- Track repeated requests for framework adapters before adding any new one.
- Keep detector usefulness review separate from detector-accuracy claims.

## Claim Boundaries

- M3 remains the primary scoped quantitative public result.
- M2 remains mechanism/correctness validation only.
- M20's deterministic tool-heavy token reduction remains detailed validation
  evidence, not a README or release headline.
- mini-SWE-agent validation is bounded local repository-repair work, not
  SWE-bench.
- SGLang support is backend-generalization evidence, not a performance
  comparison against vLLM.

## Validation

Local release-prep validation on `release/v0.4.0-prep`:

- `pytest`: 175 passed.
- `ruff check .`: passed.
- `mypy agentperf tests scripts`: passed.
- `python -m build`: produced `agentperf-0.4.0.tar.gz` and
  `agentperf-0.4.0-py3-none-any.whl`.
- `git diff --check`: passed.
- Markdown local-link audit: passed.
- Tracked-file security scan: passed.
- Package inspection confirmed comparison, regression, experiments,
  instrumentation, completeness/readiness, suites, reporters, vLLM/SGLang
  adapters, `py.typed`, license metadata, and CLI entrypoint are included.
- Fresh Python 3.11 clone/install with `.[dev]`: passed.
- Fresh Python 3.11 test/lint/type/build/diff-check: passed.
- Fresh basic install without extras: `import agentperf` succeeds without
  OpenAI Agents SDK, vLLM, SGLang, or mini-SWE-agent installed.
- CLI smokes passed for `analyze`, `report`, `compare`, `check`,
  `suite validate`, `suite check`, and `doctor`.
- BYOA smoke produced raw/optimized artifacts, `doctor` reported agent-level
  `READY` and cross-layer `NOT_APPLICABLE`, HTML report generation succeeded,
  and compare returned `ACCEPT` with 3 matched task results.
- M3 compare/check/suite compatibility remains `ACCEPT` / `PASS` / `PASS`.
- vLLM and SGLang recorded-telemetry smokes passed.

Build/install commands required network access only for standard Python package
resolution in isolated build/fresh-install environments. No GPU, Runpod, paid
API, model service, or external serving backend was used.

## Release Decision

```text
READY FOR v0.4.0
```
