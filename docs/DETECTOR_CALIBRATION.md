# Detector Calibration Review

Status: synthetic validation complete; real AgentPerf/vLLM executions,
a focused vLLM prefix-cache semantics probe, and one real agent
context-waste validation have completed on Runpod NVIDIA A5000/RTX 3090 hosts.
See `docs/REAL_VLLM_RESULTS.md`, `docs/VLLM_PREFIX_CACHE_SEMANTICS.md`, and
`docs/REAL_AGENT_CONTEXT_WASTE_RESULTS.md`.

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

Real vLLM assumptions that held:

- prompt components remain available only because the client runner records
  them before sending the request;
- vLLM can provide exact token counts and token IDs, but it does not preserve
  AgentPerf prompt component boundaries in the backend response;
- component-level duplication analysis remains an agent/client responsibility.

Real vLLM observations:

- `CONTEXT_DUPLICATION` fired for both baseline and optimized real traces;
- repeated-context ratios were above 92% in both traces;
- this was expected because both workload variants intentionally reused large
  stable runbook content.

External-agent observation:

- the OpenAI Agents SDK support-triage workload repeated short system/tool
  scaffolding across 20 LLM calls;
- the run processed only 1,604 total input tokens and had no serving telemetry;
- AgentPerf now emits this as low-severity `materiality=OBSERVATION` rather
  than treating ratio alone as a material optimization warning.

Remaining real-trace checks:

- whether chat-template serialization changes common-prefix estimates enough to
  require comparing token IDs rather than client-side component text;
- whether exact prompt token IDs should become the default duplication basis
  when available.

False-positive risks:

- large stable system prompts may be necessary policy, safety, or task context;
- multiple calls may repeat content because each call is semantically
  independent;
- approximate tokenization on synthetic fixtures can overstate repeated tokens.
- high repeated-token ratio can be misleading when the absolute token volume is
  small.

False-negative risks:

- semantically duplicate but textually changed context will not be detected;
- repeated content after chat-template role markers may not appear as a common
  prefix at the component-text level;
- exact backend token IDs are unavailable if `return_token_ids` is disabled.

## CACHEABILITY_HEADROOM And MATERIAL_PREFIX_CACHE_OPPORTUNITY

Synthetic assumptions that held:

- agent calls can share a large theoretical prefix;
- serving telemetry can show low actual cached-token ratio;
- high TTFT/prefill-path proxy strengthens the evidence;
- healthy large-context traces with high cache reuse should not fire.

Real vLLM assumptions that held:

- `usage.prompt_tokens_details.cached_tokens` is the per-request cache hit token
  signal when prompt-token details are enabled;
- the runner's client request ID and vLLM response ID provide explicit
  correlation;
- vLLM `time_to_first_token_ms` is scheduled-to-first-token. AgentPerf maps it
  to `prefill_path_latency_ms`, not pure `prefill_latency_ms`;
- true request-level prefill kernel time remains unavailable in the OpenAI
  response.

Real vLLM observations:

- the smoke test and experiment confirmed that vLLM `0.26.0+cu129` exposes
  `usage.prompt_tokens_details.cached_tokens` when prompt-token details are
  enabled;
- the first live AgentPerf workload had high cache reuse in both baseline and
  optimized variants, so `PREFIX_CACHE_OPPORTUNITY` correctly did not fire;
- the second live AgentPerf workload used the proven `dynamic_request +
  stable_context` baseline and showed poor prefix-cache reuse;
- after reordering only the prompt layout to `stable_context +
  dynamic_request`, prefix-cache reuse became high;
- `PREFIX_CACHE_OPPORTUNITY` fired only for the baseline and disappeared after
  replay.
- the first M3 real-agent attempt showed a calibration problem: the compact
  harness still emitted an actionable prefix-cache warning even though TTFT P95
  was only 18.8 ms;
- the quality-constrained M3 run now reports compact low-latency strategies as
  `CACHEABILITY_HEADROOM` rather than `MATERIAL_PREFIX_CACHE_OPPORTUNITY`;
- `MATERIAL_PREFIX_CACHE_OPPORTUNITY` still fires for `RAW_FULL` and
  `DEDUP_ONLY`, where cache reuse is poor and TTFT P95 remains 176-312 ms.

Focused prefix-cache semantics observations:

- identical repeated prompts cached nearly all prompt tokens on requests 2+;
- prompts with genuinely dynamic content before a large stable suffix reported
  `0` cached tokens on requests 2+;
- prompts with a large stable prefix before dynamic suffixes reported high
  cached-token ratios on requests 2+;
- Prometheus reported `block_size="16"`, and all nonzero cached-token counts
  were multiples of 16;
- vLLM `cached_tokens` behaves like reusable prefix-block hits, not repeated
  content anywhere in the prompt.

Assumptions invalidated or weakened:

- AgentPerf's original prefix detector was too narrow because it required a
  large existing common prefix. Real vLLM semantics showed that the pathology can
  be large repeated stable content that is not currently a prefix;
- placing dynamic content before stable content only defeats cache reuse when
  the serialized prompt actually starts with sufficiently unique dynamic text;
- client-side component ordering must be preserved in normalized traces. The
  real demo now writes prompt components as ordered lists.

Remaining real-trace checks:

- whether chat-template or message ordering makes the theoretical common prefix
  differ from the backend-token prefix;
- whether exact backend token IDs should replace approximate component-token
  estimates for the repeated-non-prefix evidence path.

False-positive risks:

- low cache reuse may be caused by server policy, cache eviction pressure,
  batching, or prefix-caching disabled rather than bad prompt organization;
- stable prefixes may be too small relative to cache block size to matter;
- the detector may overemphasize prefix reuse when output quality or prompt
  clarity depends on current ordering.

False-negative risks:

- prefix-cache problems may exist even when cached-token details are unavailable;
- per-request cached token counts may hide server-wide KV pressure;
- a workload with cache opportunity but low scheduled-to-first-token latency may
  not pass the current prefill-path-strength evidence threshold.

Implemented calibration change:

- `MATERIAL_PREFIX_CACHE_OPPORTUNITY` requires poor actual cache reuse plus
  materiality evidence: P95 scheduled-to-first-token at or above 100 ms and P95
  uncached input at or above 1,000 tokens;
- when repeated stable content or theoretical cacheability exists but the
  serving impact is small, AgentPerf reports `CACHEABILITY_HEADROOM` with low
  severity;
- this is based on the M2 dynamic-prefix result, where stable-prefix reordering
  materially improved serving behavior, and the M3 compact traces, where TTFT
  P95 around 20-27 ms should not produce a high/actionable cache warning.

## PREFILL_PATH_DOMINANCE And MATERIAL_PREFILL_BOTTLENECK

Synthetic assumptions that held:

- request-level latency can be decomposed into queue, prefill-path, and decode;
- high input length plus high prefill fraction is more useful than reporting
  "prefill is slow";
- the detector should cross-link conceptually with duplication and prefix-cache
  evidence.

Real vLLM assumptions that held:

- vLLM per-request `time_to_first_token_ms` is used only as
  `prefill_path_latency_ms`, a scheduled-to-first-token proxy;
- queue time is separate when per-request metrics are enabled;
- generation time or mean inter-token latency provides decode evidence.

Real vLLM observations:

- in the first live AgentPerf run, the old `PREFILL_BOTTLENECK` label fired even
  though scheduled-to-first-token P95 was only about 16 ms;
- in the second live run, the dynamic-prefix baseline had material
  scheduled-to-first-token latency and high uncached input volume;
- after stable-prefix replay, scheduled-to-first-token latency and uncached
  input volume were no longer material;
- the detector now distinguishes low-severity `PREFILL_PATH_DOMINANCE` from
  `MATERIAL_PREFILL_BOTTLENECK`.

Focused prefix-cache semantics observations:

- 8K uncached prompts had scheduled-to-first-token around 255-286 ms;
- 8K stable-prefix cached prompts had scheduled-to-first-token around 24-32 ms;
- this confirms that scheduled-to-first-token can respond strongly to cache
  reuse at the tested model/context size;
- the earlier 16 ms finding was dominance, not necessarily a material
  bottleneck.

Assumptions invalidated or weakened:

- prefill-path fraction alone is not enough to make a useful real-world
  bottleneck claim;
- absolute TTFT and uncached prompt volume must be part of the materiality
  evidence before calling this detector a bottleneck.

Implemented calibration change:

- `MATERIAL_PREFILL_BOTTLENECK` requires relative prefill-path dominance plus
  P95 scheduled-to-first-token at or above 100 ms and P95 uncached input at or
  above 1,000 tokens;
- otherwise, high relative prefill-path fraction is reported as
  `PREFILL_PATH_DOMINANCE` with lower severity;
- these thresholds are early empirical defaults based on the 16 ms false
  positive and the 8K uncached/prefix-cached contrast. They are not production
  cutoffs.

Remaining real-trace checks:

- whether output length variation distorts the decode comparison.

False-positive risks:

- `time_to_first_token_ms` is not pure prefill and includes work through first
  output token;
- cold-start, model-load, or warmup artifacts may look like prefill bottlenecks;
- server queueing may be hidden if the backend reports scheduled-to-first-token
  TTFT rather than client-observed TTFT.

False-negative risks:

- if vLLM omits per-request metrics, the detector will not fire;
- short prompts with poor cache behavior may be missed because input length is
  below threshold;
- server-level prefill saturation may not appear in one request's normalized
  telemetry.

## M2 Execution Package And First Result

The M2 runbook and scripts define the first real validation protocol:

- `docs/REAL_VLLM_RUNBOOK.md`;
- `scripts/remote_vllm/setup.sh`;
- `scripts/remote_vllm/start_server.sh`;
- `scripts/remote_vllm/smoke_test.sh`;
- `scripts/remote_vllm/run_experiment.sh`;
- `scripts/remote_vllm/collect_artifacts.sh`.

The smoke test must pass before running the experiment. If any critical vLLM
field is absent, AgentPerf should not fabricate it.

The first live run completed on 2026-08-09 UTC. It validated real vLLM
ingestion, explicit request correlation, and detector execution on real
telemetry. It did not validate the intended prefix-cache-improvement story
because both baseline and optimized traces already had very high cached-token
ratios.

The second live run completed the intended story. A dynamic-prefix baseline
produced low cache reuse, `PREFIX_CACHE_OPPORTUNITY`, and
`MATERIAL_PREFILL_BOTTLENECK`. Reordering stable context to the front produced
high cache reuse, much lower scheduled-to-first-token latency, no
`PREFIX_CACHE_OPPORTUNITY`, and only low-severity `PREFILL_PATH_DOMINANCE`.

M3 real-agent validation completed a separate tool-output waste story. The
first aggressive compaction run reduced tokens and latency but harmed
correctness. A follow-up quality-constrained run found that deterministic
deduplication preserved quality within an explicit tolerance while reducing
processed input tokens by 28.1%, tool-result processed tokens by 30.0%, TTFT P95
by 43.5%, and client latency P95 by 22.4%.

## Threshold Policy

The prefill detector thresholds changed after the first real vLLM run and the
cache-semantics probe because real evidence showed that dominance alone was not
material. Prefix-cache reporting now also has a materiality split: high
actionable findings require evidence that cache miss behavior is contributing
meaningful scheduled-to-first-token or uncached-token cost, while low-latency
residual cacheability is reported as headroom.

The next threshold review should use:

- 3 warmup repetitions;
- at least 10 measured repetitions per configuration;
- unchanged tasks between baseline and improved configurations;
- a minimal vLLM cache-semantics probe that intentionally changes the first
  cache block;
- captured raw vLLM responses;
- AgentPerf reports with provenance enabled;
- output review sufficient to catch trivial task breakage.

Until then, the current detector thresholds should be considered early empirical
defaults, not validated production cutoffs.
