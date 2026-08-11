# Changelog

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
