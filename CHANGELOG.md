# Changelog

## Unreleased

### Added

- Added standalone visual replay comparison reports with
  `agentperf compare --format html --output comparison.html`.
- Added policy-aware HTML output for `agentperf check --format html`, reusing
  existing regression-policy verdicts and checks.
- Added `agentperf demo`, a source-tree-independent deterministic onboarding
  command that creates baseline/candidate artifacts, an HTML report, a
  comparison verdict, and a regression policy without API keys, GPU, or model
  downloads.
- Added package-first getting-started documentation and a PyPI release
  checklist for future package-index publication.
- Added a copyable GitHub Actions regression-check example and CI integration
  guide.
- Added an optional LangGraph integration and deterministic local LangGraph
  example using the existing AgentPerf run/LLM/tool instrumentation model.
- Added a wheel-based M22 distribution smoke script that validates CLI startup,
  demo, doctor, report, compare, and check outside the source checkout.
- Added deterministic M21 scale fixture generation and a reproducible
  benchmark harness for instrumentation overhead, artifact growth, analysis,
  doctor, HTML report, compare, and check scaling.
- Added compact M21 benchmark result data and an engineering note documenting
  tested local operating ranges and limitations.

### Improved

- `agentperf demo` now also writes a local `comparison.html` replay-verification
  report alongside its baseline profiler report.
- Improved README first-run onboarding so users can see the future package
  install path, immediate demo command, BYOA path, and optional LangGraph path
  without reading implementation docs first.
- Reduced framework-free tracing overhead by avoiding repeated full-run
  reconstruction during default LLM/tool ID assignment.
- Made `agentperf doctor` use correlation-only completeness assessment instead
  of running full detectors.
- Reduced common-prefix analysis cost with sorted-prefix and trie-based
  computations while preserving detector semantics.

## v0.4.0

### Added

- Added framework-free Bring Your Own Agent instrumentation with public
  `ExperimentSession`, `trace_run`, `trace_llm`, and context-manager
  `trace_tool` usage for custom Python agents.
- Added `agentperf doctor` integration-readiness diagnostics with separate
  agent-level and cross-layer readiness semantics.
- Added instrumentation completeness reporting for task outcomes, LLM timing,
  provider usage, component attribution, request IDs, tool calls, and serving
  correlations.
- Added a deterministic framework-free BYOA example and a deterministic
  tool-heavy validation workload.
- Added machine-readable M20 finding-review data and a local aggregation script
  for heterogeneous workload validation.

### Improved

- Improved report credibility by labeling ambiguous metric provenance across
  agent trace, provider usage, component attribution, serving backend, and
  derived metrics.
- Improved materiality explanations so threshold gates and conservative LOW /
  OBSERVATION classifications are explicit.
- Improved finding presentation with deterministic investigation chains that
  group related evidence without claiming causality.
- Improved framework-free experiment ergonomics and error handling for failed
  LLM/tool calls while preserving user exceptions.
- Corrected artifact comparison task-coverage reporting for one-run artifacts
  that contain multiple task results.
- Improved docs for first-run inspection, BYOA instrumentation, readiness
  checks, and finding interpretation.

### Validation

- Validated BYOA instrumentation on a deterministic local support-agent
  workflow with quality-preserving replay.
- Validated finding interpretation across three heterogeneous local workloads:
  mini-SWE-agent's existing coding loop, OpenAI Agents SDK support triage, and
  a framework-free deterministic tool-heavy workload.
- Reviewed representative findings as actionable, valid non-actionable, or
  expected structural behavior. This review set is small and manually
  classified; it is not a detector-accuracy benchmark.

### Compatibility

- Existing raw trace, artifact, `compare`, `check`, `suite`, `report`, vLLM,
  and SGLang workflows remain supported.
- Artifact schema version remains `1`; AgentPerf package version,
  artifact-schema version, benchmark-suite schema version, and regression-policy
  schema version remain intentionally separate.
- Optional integrations remain optional; importing AgentPerf does not require
  vLLM, SGLang, OpenAI Agents SDK, or mini-SWE-agent.

## v0.3.0

### Added

- Added replay verification for baseline/candidate runs with quality-aware
  ACCEPT / REJECT / INCONCLUSIVE verdicts and finding lifecycle tracking.
- Added standardized `ExperimentArtifact` bundles and `ExperimentSession` so
  task quality, environment metadata, findings, and summaries can be emitted by
  default.
- Added regression policies, `agentperf check`, stable CI exit codes, JSON
  output, and GitHub Step Summary-friendly Markdown.
- Added benchmark suites with explicit reviewed baselines, suite validation,
  suite checks, multi-suite checks, and baseline proposal reports.
- Added component-aware token regression policies over system, history,
  tool-result, retrieved-context, tool-schema, and total component-attributed
  processing.
- Added a standalone local HTML profiler report for artifacts and raw traces.
- Added SGLang serving-backend ingestion/correlation with backend-specific
  telemetry provenance.

### Improved

- Improved CI report hierarchy so quality regressions, task coverage, largest
  token/latency changes, and material finding changes are easier to triage.
- Improved duplication materiality semantics so cross-run shared scaffold is not
  treated as removable within-run context waste.
- Improved token accounting documentation and reporting for provider usage
  versus AgentPerf component attribution.
- Improved serving-backend capability reporting so missing telemetry remains
  explicit rather than being interpreted as zero.

### Compatibility

- Raw trace `analyze` and `compare` workflows remain supported.
- Artifact schema version remains `1`; AgentPerf package version,
  artifact-schema version, suite version, and regression-policy schema version
  are intentionally separate.
- vLLM support and existing recorded vLLM artifacts remain valid.

## v0.2.0

- Added real vLLM ingestion and explicit request correlation.
- Added real prefix-cache diagnosis and replay validation on vLLM.
- Added component-level processed-token attribution.
- Added tool-output and context-waste profiling.
- Added quality-constrained context replay over a real multi-step research
  agent.
- Added OpenAI Agents SDK integration through public hooks/wrappers.
- Added OpenAI Agents SDK plus live vLLM cross-layer validation.
- Added mini-SWE-agent integration for real existing coding-agent profiling.
- Added run-boundary-aware duplication semantics for cross-run shared scaffold.
- Added experimental model-choice Phase A counterfactual profiling.

## v0.1.0

- Added initial normalized trace schema.
- Added synthetic trace fixtures.
- Added deterministic MVP detectors for context duplication,
  prefix-cache opportunity, and prefill bottleneck signals.
- Added terminal reporter and CLI.
- Added initial vLLM recording adapter.
