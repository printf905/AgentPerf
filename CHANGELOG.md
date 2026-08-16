# Changelog

## Unreleased

No unreleased changes yet.

## v0.5.0

### Added

- Added standalone visual replay comparison reports with
  `agentperf compare --format html --output comparison.html`.
- Added policy-aware HTML output for `agentperf check --format html`, reusing
  existing regression-policy verdicts and checks.
- Added `agentperf demo`, a source-tree-independent deterministic onboarding
  command that creates baseline/candidate artifacts, an HTML report, a
  comparison verdict, and a regression policy without API keys, GPU, or model
  downloads.
- Added package-first getting-started documentation, a copyable GitHub Actions
  regression-check example, and PyPI Trusted Publishing release documentation.
- Added an optional LangGraph integration and deterministic local LangGraph
  example using the existing AgentPerf run/LLM/tool instrumentation model.
- Added deterministic scale fixture generation and a reproducible benchmark
  harness for instrumentation overhead, artifact growth, analysis, doctor, HTML
  report, compare, and check scaling.
- Added structured recommendation contracts that describe objectives,
  intervention classes, expected metric movement, quality risks, applicability,
  and replay verification requirements.
- Added standalone recommendation verification output in comparison JSON,
  terminal output, and HTML reports.
- Added model-capacity replay semantics that distinguish local one-role
  headroom from full mixed-routing verification.
- Added preserved M25 Phase B evidence for one pre-registered mixed-routing
  replay, marked as bounded `GLOBAL_ROUTING_VERIFIED` evidence rather than
  optimal or universal routing.
- Added crash-recoverable long-running local capture with explicit checkpoints
  and recovered `PARTIAL` artifact semantics.
- Added optional multi-agent, branch, and handoff metadata for framework-free
  instrumentation, plus agent/branch attribution in single-run and comparison
  HTML reports.

### Improved

- Improved async/concurrent tracing correctness so concurrent LLM/tool spans,
  nested runs, cancellation, and branch failures preserve task-local parentage.
- Added a public `role=` alias for `trace_llm(..., semantic_role=...)` so
  framework-free experiments can record model-routing identity more directly.
- Preserved model-capacity role semantics separately from multi-agent identity
  so `semantic_role` routing analysis and `agent_id` attribution can coexist.
- Improved metric provenance, materiality/report semantics, and detector
  wording so missing evidence remains unavailable rather than becoming zero,
  negative evidence, or a successful verification.
- Improved HTML and comparison redaction for secret-like metadata while keeping
  raw artifact capture semantics explicit.
- `agentperf demo` now also writes a local `comparison.html` replay-verification
  report alongside its baseline profiler report.
- Improved README first-run onboarding so the package install path, demo,
  BYOA path, CI path, and advanced integrations are easier to find.
- Reduced framework-free tracing overhead by avoiding repeated full-run
  reconstruction during default LLM/tool ID assignment.
- Made `agentperf doctor` use correlation-only completeness assessment instead
  of running full detectors.
- Reduced common-prefix analysis cost with sorted-prefix and trie-based
  computations while preserving detector semantics.

### Validation

- Preserved the controlled M3 research-agent replay as the primary scoped
  quantitative optimization example: input processing `132,756 -> 95,479`
  (`-28.1%`), tool-result processing `112,287 -> 78,566` (`-30.0%`),
  scheduled-to-first P95 `312.180 ms -> 176.534 ms` (`-43.5%`), with quality
  remaining inside the predefined tolerance and replay verdict `ACCEPT`.
- Preserved heterogeneous workload validation across mini-SWE-agent,
  tool-heavy research support, and OpenAI Agents SDK support-triage workloads.
- Added measured instrumentation-overhead and local scale characterization
  through deterministic fixtures, without production-scale claims.
- Preserved one bounded real model-capacity Phase B validation where the tested
  mixed routing stayed within the predefined quality tolerance and was marked
  `GLOBAL_ROUTING_VERIFIED`.
- Expanded regression coverage for concurrency, failure modes, checkpoint
  recovery, multi-agent structure, recommendations, comparison HTML, package
  installation, vLLM, SGLang, LangGraph, and OpenAI Agents SDK paths.

### Compatibility

- Artifact schema version remains `1`.
- Benchmark-suite schema version remains `1`.
- Regression-policy schema version remains `1`.
- Existing raw trace analysis, artifact loading, BYOA instrumentation,
  OpenAI Agents SDK integration, LangGraph integration, vLLM fixtures, SGLang
  fixtures, benchmark suites, `compare`, `check`, `doctor`, and HTML reports
  remain supported.

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

- M19 BYOA smoke: generated a valid framework-free artifact with 3 tasks, 6 LLM
  calls, 3 tool calls, complete task quality, and expected doctor readiness.
- M20 heterogeneous validation: 3 workloads, 19 tasks, 62 LLM calls, 51 tool
  calls, and 3 reviewed findings across coding, tool-heavy, and OpenAI Agents
  SDK-style workloads.
- Historical M3 compare remains `ACCEPT`; M3 check remains `PASS`; M3 suite
  check remains `PASS`.
- vLLM and SGLang recorded fixtures remain supported with exact request ID
  correlation where evidence is available.

### Compatibility

- Artifact schema version remains `1`.
- Existing normalized trace JSON workflows remain supported.
- Existing compare/check/suite/report/analyze commands remain compatible.
