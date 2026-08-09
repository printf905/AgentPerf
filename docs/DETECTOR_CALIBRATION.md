# Detector Calibration Review

Status: synthetic validation complete; one real AgentPerf/vLLM execution and
one focused vLLM prefix-cache semantics probe completed on Runpod NVIDIA RTX
A5000 hosts. See `docs/REAL_VLLM_RESULTS.md` and
`docs/VLLM_PREFIX_CACHE_SEMANTICS.md`.

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

False-negative risks:

- semantically duplicate but textually changed context will not be detected;
- repeated content after chat-template role markers may not appear as a common
  prefix at the component-text level;
- exact backend token IDs are unavailable if `return_token_ids` is disabled.

## PREFIX_CACHE_OPPORTUNITY

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
- baseline cached-token ratio was 99.75%;
- optimized cached-token ratio was 99.40%;
- `PREFIX_CACHE_OPPORTUNITY` did not fire for either trace, which was correct
  for the observed telemetry;
- the baseline workload did not produce the intended low-cache-reuse condition.

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

- placing dynamic content before later stable content was not sufficient to
  defeat vLLM cache reuse in this controlled workload;
- the next experiment should not assume that client-side component ordering maps
  cleanly to low `cached_tokens`;
- the earlier workload's baseline did not put sufficiently unique dynamic
  content at the very beginning of the serialized prompt.

Remaining real-trace checks:

- whether chat-template or message ordering makes the theoretical common prefix
  differ from the backend-token prefix;
- whether a revised AgentPerf workload using the proven dynamic-prefix pattern
  triggers `PREFIX_CACHE_OPPORTUNITY` and then disappears after stable-prefix
  reorganization.

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

## PREFILL_BOTTLENECK

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

- `PREFILL_BOTTLENECK` fired for both baseline and optimized traces;
- scheduled-to-first-token P95 was low in absolute terms: 16.56 ms baseline and
  16.23 ms optimized;
- prefill-path proxy fraction was 100% because vLLM exposes
  scheduled-to-first-token as the prefill-path proxy and queue time was near
  zero;
- the current detector may overstate severity when prefill-path fraction is high
  but absolute TTFT is small.

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
- absolute TTFT or TTFT impact should be part of the calibration review before
  calling this detector high severity on real data.

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

## Threshold Policy

No threshold changes were made from the first real vLLM run. A single small
workload is not enough to tune detector thresholds, and tuning solely to make
the expected `PREFIX_CACHE_OPPORTUNITY` finding fire would be wrong.

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
