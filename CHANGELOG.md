# Changelog

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
