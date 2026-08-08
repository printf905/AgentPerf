# Detector Calibration Review

Status: synthetic validation complete; real vLLM execution pending.

This document records detector assumptions before threshold tuning. Thresholds
remain configurable in detector constructors and should not be changed just to
force findings on a small real demo.

## CONTEXT_DUPLICATION

Synthetic assumptions that held:

- repeated stable prompt text across LLM calls can be detected from normalized
  prompt components;
- exact common-prefix length and repeated-token ratio are useful evidence;
- repeated text is not automatically waste, so the recommendation is framed as
  an inspection and restructuring opportunity.

Real vLLM assumptions:

- prompt components remain available only because the client runner records
  them before sending the request;
- vLLM can provide exact token counts and token IDs, but it does not preserve
  AgentPerf prompt component boundaries in the backend response;
- component-level duplication analysis remains an agent/client responsibility.

Pending real-trace checks:

- whether chat-template serialization changes common-prefix estimates enough to
  require comparing token IDs rather than client-side component text;
- whether exact prompt token IDs should become the default duplication basis
  when available.

False-positive risks:

- large stable system prompts may be necessary policy, safety, or task context;
- multiple calls may repeat content because each call is semantically
  independent;
- approximate tokenization on synthetic fixtures can overstate repeated tokens.

False-negative risks:

- semantically duplicate but textually changed context will not be detected;
- repeated content after chat-template role markers may not appear as a common
  prefix at the component-text level;
- exact backend token IDs are unavailable if `return_token_ids` is disabled.

## PREFIX_CACHE_OPPORTUNITY

Synthetic assumptions that held:

- agent calls can share a large theoretical prefix;
- serving telemetry can show low actual cached-token ratio;
- high TTFT/prefill proxy strengthens the evidence;
- healthy large-context traces with high cache reuse should not fire.

Real vLLM assumptions:

- `usage.prompt_tokens_details.cached_tokens` is the per-request cache hit token
  signal when prompt-token details are enabled;
- the runner's client request ID and vLLM response ID provide explicit
  correlation;
- `time_to_first_token_ms` is the best available request-level prefill proxy,
  not pure prefill time.

Pending real-trace checks:

- whether vLLM reports cached tokens consistently for the selected model and
  server configuration;
- whether the baseline workload actually produces low cache reuse;
- whether the improved workload produces higher cached-token ratio without
  altering task semantics;
- whether chat-template or message ordering makes the theoretical common prefix
  differ from the backend-token prefix.

False-positive risks:

- low cache reuse may be caused by server policy, cache eviction pressure,
  batching, or prefix-caching disabled rather than bad prompt organization;
- stable prefixes may be too small relative to cache block size to matter;
- the detector may overemphasize prefix reuse when output quality or prompt
  clarity depends on current ordering.

False-negative risks:

- prefix-cache problems may exist even when cached-token details are unavailable;
- per-request cached token counts may hide server-wide KV pressure;
- a workload with cache opportunity but low TTFT may not pass the current
  prefill-strength evidence threshold.

## PREFILL_BOTTLENECK

Synthetic assumptions that held:

- request-level latency can be decomposed into queue, prefill, and decode;
- high input length plus high prefill fraction is more useful than reporting
  "prefill is slow";
- the detector should cross-link conceptually with duplication and prefix-cache
  evidence.

Real vLLM assumptions:

- vLLM per-request `time_to_first_token_ms` is used as a prefill proxy;
- queue time is separate when per-request metrics are enabled;
- generation time or mean inter-token latency provides decode evidence.

Pending real-trace checks:

- whether TTFT proxy values are stable enough across repeated runs to support a
  meaningful demo;
- whether queue time is low enough that prefill remains the dominant component;
- whether output length variation distorts the decode comparison.

False-positive risks:

- `time_to_first_token_ms` includes work beyond pure prefill;
- cold-start, model-load, or warmup artifacts may look like prefill bottlenecks;
- server queueing may be hidden if the backend reports scheduled-to-first-token
  TTFT rather than client-observed TTFT.

False-negative risks:

- if vLLM omits per-request metrics, the detector will not fire;
- short prompts with poor cache behavior may be missed because input length is
  below threshold;
- server-level prefill saturation may not appear in one request's normalized
  telemetry.

## Threshold Policy

No threshold changes were made from real data in this pass because a real vLLM
run could not be executed on the local Apple M2 host.

The first threshold review should use:

- at least one warmup run;
- multiple measured repetitions;
- unchanged tasks between baseline and improved configurations;
- captured raw vLLM responses;
- AgentPerf reports with provenance enabled;
- output review sufficient to catch trivial task breakage.

Until then, the current detector thresholds should be considered synthetic-MVP
defaults, not validated production cutoffs.
