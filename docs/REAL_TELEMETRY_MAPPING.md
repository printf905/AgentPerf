# Real Telemetry Mapping: vLLM

Selected backend: vLLM OpenAI-compatible server.

Review date: 2026-08-08.

Primary sources:

- vLLM per-request metrics docs:
  https://docs.vllm.ai/en/latest/features/per_request_metrics/
- vLLM production metrics docs:
  https://docs.vllm.ai/en/latest/usage/metrics/
- vLLM OpenAI chat protocol source:
  https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/protocol.py
- vLLM per-request timing source:
  https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/generate/base/serving.py
- vLLM prompt token details source:
  https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/serving.py
- vLLM CPU / Apple Silicon installation docs:
  https://docs.vllm.ai/en/latest/getting_started/installation/cpu/?device=apple
- vLLM automatic prefix caching docs:
  https://docs.vllm.ai/en/latest/design/prefix_caching/
- vLLM serve CLI docs:
  https://docs.vllm.ai/en/latest/cli/serve/

This document is the contract for real telemetry ingestion. Missing backend
metrics must remain missing. Synthetic or schema-fixture values must never be
presented as real measurements.

## Current vLLM Capabilities Verified

| Capability | vLLM source | Classification | AgentPerf handling |
| --- | --- | --- | --- |
| Explicit request ID | `ChatCompletionRequest.request_id` is used throughout inference and returned in responses. | DIRECT | Store client ID as `llm_request_id`; store response `id` as `serving_request_id`. |
| Prompt token count | `usage.prompt_tokens`. | DIRECT | `input_tokens`. |
| Completion token count | `usage.completion_tokens`. | DIRECT | `output_tokens`. |
| Prompt token IDs | `prompt_token_ids` when `return_token_ids=true`. | DIRECT when enabled | `prompt_token_ids`, `tokenization_mode=EXACT`. |
| Generated token IDs | `choices[*].token_ids` when `return_token_ids=true`. | DIRECT when enabled | `output_token_ids`. |
| Queue timing | `metrics.queue_time_ms`. Source computes scheduled minus queued timestamps. | DIRECT when per-request metrics are enabled | `queue_latency_ms`. |
| Scheduled-to-first-token timing | `metrics.time_to_first_token_ms`. Source computes first token timestamp minus scheduled timestamp. | DIRECT measurement, PROXY for prefill path | `ttft_ms` and `prefill_path_latency_ms`; not `prefill_latency_ms`. |
| Pure prefill kernel time | Not exposed per request in OpenAI response. | UNAVAILABLE | `prefill_latency_ms=None` for vLLM adapter records. |
| Generation timing | `metrics.generation_time_ms`. Source computes last token minus first token and says it excludes queue and prefill/TTFT. | DIRECT when enabled | `decode_latency_ms`. |
| TPOT / ITL | `metrics.mean_itl_ms`. Source divides decode interval by generated-token intervals. | DIRECT when enabled | `tpot_ms`. |
| Cached prompt tokens | `usage.prompt_tokens_details.cached_tokens` when prompt token details are enabled. | DIRECT when enabled | `prefix_cache_hit_tokens`. |
| Cache-created prompt tokens | `usage.prompt_tokens_details.created_cache_tokens` when available. | DIRECT when enabled | Kept in raw response today; not normalized yet. |
| Prefix cache enablement | Cache config has `enable_prefix_caching`; CLI supports prefix-cache flags. | DIRECT config | Recorded in environment/server flags. |
| Prometheus prefix cache metrics | `/metrics` exposes server/workload aggregate prefix-cache metrics. | DIRECT aggregate | Collected separately; not attributed to a single request. |
| Prometheus KV usage | `/metrics` exposes server/workload aggregate KV cache usage. | DIRECT aggregate | Collected separately; not mapped to request-level KV fields. |
| Request-level KV capacity/evictions | Not exposed through OpenAI per-request response. | UNAVAILABLE | Request-level KV fields remain `None`. |

## Normalized Field Mapping

| AgentPerf field | Backend source | Raw field | Unit | Classification | Derivation / notes | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `trace_id` | AgentPerf runner | `traceparent` header recorded by runner | string | DIRECT client-side | Client-generated and recorded. | vLLM does not necessarily echo it. |
| `span_id` | Client / OTel export | recording field | string | UNAVAILABLE by default | Not used for M2. | Real OTel ingestion is not implemented. |
| `parent_span_id` | Client / OTel export | recording field | string | UNAVAILABLE by default | Not used for M2. | Real OTel ingestion is not implemented. |
| `agent_run_id` | AgentPerf runner | recording `agent_run_id` | string | DIRECT client-side | Not backend telemetry. | None. |
| `agent_step_id` | AgentPerf runner | record `agent_step_id` | string | DIRECT client-side | Not backend telemetry. | None. |
| `llm_call_id` | AgentPerf runner | record `llm_call_id` | string | DIRECT client-side | Not backend telemetry. | None. |
| `llm_request_id` | vLLM request body | `request_id` / recorded `client_request_id` | string | DIRECT | Explicit request propagation. | Must be sent by client. |
| `serving_request_id` | vLLM response | response `id` | string | DIRECT | Backend returned ID. | vLLM may prefix or normalize request IDs. |
| `model` | vLLM request/response | `model` | string | DIRECT | Runner records served model. | Per-response model should be preferred for future routing. |
| `prompt_components` | AgentPerf runner | record `prompt_components` | text | DIRECT client-side | Preserves logical prompt sections. | Backend only sees rendered prompt. |
| `input_tokens` | vLLM usage | `usage.prompt_tokens` | tokens | DIRECT | Exact for backend tokenizer. | Requires usage in response. |
| `output_tokens` | vLLM usage | `usage.completion_tokens` | tokens | DIRECT | Exact for backend tokenizer. | Requires usage in response. |
| `prompt_token_ids` | vLLM response | `prompt_token_ids` | token IDs | DIRECT when enabled | Requires `return_token_ids=true`. | Optional. |
| `output_token_ids` | vLLM response | `choices[*].token_ids` | token IDs | DIRECT when enabled | Concatenated across choices. | M2 uses `n=1`; multi-choice attribution is out of scope. |
| `tokenization_mode` | Adapter | token ID presence | enum | DERIVED label | `EXACT` when prompt token IDs exist. | Token counts may be exact even when IDs are omitted. |
| `queue_latency_ms` | vLLM per-request metrics | `metrics.queue_time_ms` | ms | DIRECT | Queue wait before scheduled processing. | Requires `--enable-per-request-metrics`. |
| `ttft_ms` | vLLM per-request metrics | `metrics.time_to_first_token_ms` | ms | DIRECT | Scheduled-to-first-token timing. | Not client-observed arrival-to-first-token. |
| `prefill_latency_ms` | None in OpenAI response | none | ms | UNAVAILABLE | vLLM adapter leaves this `None`. | Do not infer pure prefill kernel time. |
| `prefill_path_latency_ms` | vLLM per-request metrics | `metrics.time_to_first_token_ms` | ms | PROXY | Scheduled-to-first-token proxy for the prefill path. | Includes more than pure prefill and excludes queue. |
| `decode_latency_ms` | vLLM per-request metrics | `metrics.generation_time_ms` | ms | DIRECT when present | Decode interval from first to last token. | If missing, adapter can derive from ITL and output count. |
| `tpot_ms` | vLLM per-request metrics | `metrics.mean_itl_ms` | ms/token | DIRECT when present | Mean inter-token latency. | Null for single-token responses. |
| `prefix_cache_hit_tokens` | vLLM usage details | `usage.prompt_tokens_details.cached_tokens` | tokens | DIRECT when enabled | Cached prompt token count. | Requires `--enable-prompt-tokens-details`. |
| `prefix_cache_miss_tokens` | AgentPerf adapter | `input_tokens - cached_tokens` | tokens | DERIVED | `max(input_tokens - cached_tokens, 0)`. | Only valid when both fields are present. |
| `kv_cache_used_tokens` | Prometheus aggregate only | no per-request field | tokens | UNAVAILABLE per request | Not mapped. | Server-level KV usage must not be attributed to one request. |
| `kv_cache_capacity_tokens` | Server config / Prometheus aggregate | no per-request field | tokens | UNAVAILABLE per request | Not mapped. | Do not infer per-request capacity. |
| `kv_cache_evictions` | Internal/server aggregate only | no per-request field | count | UNAVAILABLE per request | Not mapped. | Per-request eviction sequence unavailable. |

## Prometheus Metrics Policy

vLLM's `/metrics` endpoint is useful for workload-level context, including
request histograms, prefix-cache counters, and KV-cache gauges. Those metrics are
not per-request evidence unless vLLM explicitly exposes request labels or a
trace relationship. AgentPerf M2 may collect them as aggregate artifacts, but
detectors continue to use normalized request-level fields.

## Local Execution Assessment

The current development host is Apple Silicon without CUDA. Official vLLM docs
state that Apple Silicon support is experimental, requires source build, and has
no prebuilt Apple Silicon CPU wheels. That path is not a reliable way to validate
CUDA vLLM prefix-cache/per-request telemetry parity. M2 therefore uses the remote
single-NVIDIA-GPU runbook instead of forcing local emulation.

## Fixture Policy

`examples/recorded_telemetry/vllm_openai_response_fixture.json` is a schema
fixture, not a real backend capture. It is labeled with:

- `fixture_kind`;
- `real_backend_capture: false`;
- a note that it is not benchmark evidence.

Only artifacts produced by a real vLLM server run should be discussed as real
telemetry.
