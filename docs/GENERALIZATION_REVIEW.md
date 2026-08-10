# Generalization Review

Status: M5 review after integrating one external agent framework.

Selected framework: OpenAI Agents SDK.

## What Transferred Unchanged

- The normalized `AgentRun` / `AgentStep` / `LLMCall` / `ToolCall` schema could
  represent the external agent without framework-specific fields in the core
  dataclasses.
- Agent-only analysis worked with no serving requests.
- Token component attribution worked from framework model input items.
- Tool-result provenance worked when `function_call_output.call_id` was present
  in downstream model input.
- Existing detector execution did not require framework-specific logic.
- The terminal report could render the external-agent trace without a dashboard.

## What Was Specific To The Original Research Agent

- M3 semantic roles such as planner, evidence reviewer, and final synthesizer
  are not naturally exposed by the small support-triage OpenAI Agents example.
- The M3 context-carry strategies do not apply directly to the selected
  external agent because it does not repeatedly carry large tool outputs.
- vLLM request correlation is not exercised by the local M5 benchmark.

## Missing Trace Fields

The M5 local run did not provide:

- serving request IDs;
- queue latency;
- scheduled-to-first-token latency;
- generation latency from a real model server;
- prefix-cache tokens;
- KV-cache telemetry;
- exact tokenizer counts.

Those fields are optional in AgentPerf and were correctly reported as
unavailable rather than inferred.

## Detectors And Analyses

Worked:

- component token attribution;
- processed-vs-unique token accounting;
- context growth table;
- `CONTEXT_DUPLICATION` as a repeated-context observation.

Irrelevant or unavailable:

- prefix-cache materiality, because no serving telemetry was present;
- prefill-path materiality, because no serving telemetry was present;
- tool-output bloat, because tool-result carry-forward was small;
- model-choice profiling, because the example does not define semantic model
  roles or counterfactual replay results.

## False Positives

The main false-positive risk is still materiality around
`CONTEXT_DUPLICATION`.

The external support-triage workload repeated system instructions across 20 LLM
calls. The detector now records this as `materiality=OBSERVATION` with low
severity because the absolute repeated-token volume is small and no serving
latency/cost evidence is present. Future calibration should continue refining
the boundary between context-duplication headroom and material context waste.

## False Negatives

The adapter currently may miss:

- prompt details from streaming model calls;
- framework events that appear only in trace exports but not model input;
- exact token IDs unless provided by the model/backend;
- tool latency when function spans are disabled to avoid duplicate tool-call
  accounting.

## Framework-Specific Logic Required

OpenAI Agents SDK integration required:

- a `Model` wrapper to observe prompt input and usage at the model boundary;
- a tracing processor to preserve SDK trace/span exports;
- mapping SDK input items into AgentPerf prompt components;
- special handling for `function_call_output` items to link tool-result prompt
  components back to tool call IDs.

No monkey-patching was required.

## Adoption Cost

The minimal integration is roughly:

- one optional dependency: `openai-agents`;
- one recorder setup block;
- one trace processor registration;
- one model wrapper;
- one `with recorder.as_current()` around agent execution;
- one artifact write step.

The example modifies no framework internals and does not require changing tool
business logic.

## Public API Review

The API appears general enough for a second adapter:

- names map to common tracing concepts;
- serving telemetry is optional;
- framework adapters remain outside core detectors;
- prompt component labels are generic rather than framework-specific.

The main API weakness is verbosity. Existing framework users must understand
both the recorder and the model wrapper. A small helper such as
`instrument_openai_agents(model, recorder)` may be useful later, but M5 does not
justify a plugin framework.

## Generalization Conclusion

AgentPerf generalized to one existing external agent framework for agent-layer
profiling. It produced a normalized trace, token attribution, context growth,
and detector output without changing the agent's intended behavior.

The observed external workload did not contain a material performance pathology.
That is a credible result: AgentPerf must be able to report a clean or
low-materiality profile instead of manufacturing an optimization story.

The biggest remaining generalization weakness is real cross-layer validation on
an external framework agent. The adapter can capture agent-layer traces today,
but a future run should combine the OpenAI Agents SDK adapter with a live
OpenAI-compatible vLLM endpoint and explicit request IDs.
