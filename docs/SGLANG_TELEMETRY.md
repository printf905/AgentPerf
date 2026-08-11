# SGLang Telemetry Mapping

This document records the SGLang telemetry surface AgentPerf relies on for M17.
It is intentionally conservative: AgentPerf only maps a value into a normalized
serving field when the source has compatible semantics.

Primary sources reviewed:

- SGLang production metrics documentation:
  https://docs.sglang.io/docs/references/production_metrics
- SGLang production request tracing documentation:
  https://docs.sglang.io/docs/references/production_request_trace
- SGLang observability documentation:
  https://docs.sglang.io/docs/advanced_features/observability
- SGLang tool parser documentation:
  https://docs.sglang.io/docs/advanced_features/tool_parser
- SGLang server arguments documentation:
  https://docs.sglang.io/docs/advanced_features/server_arguments

## Summary

SGLang exposes several useful public telemetry paths:

- OpenAI-compatible responses can provide response IDs and token usage.
- Client streaming can measure client-observed time to first token and
  end-to-end latency.
- Prometheus metrics expose aggregate server behavior when `--enable-metrics`
  is used.
- OpenTelemetry request tracing is available when `--enable-trace` and an OTLP
  endpoint are configured.

The ordinary OpenAI-compatible response path does not provide all of the same
per-request serving metrics AgentPerf can ingest from vLLM recordings.

## Field Classification

| AgentPerf concept | SGLang source | Classification | Notes |
| --- | --- | --- | --- |
| `serving_request_id` | OpenAI-compatible response `id`, or an explicitly captured request ID | DIRECTLY OBSERVED | Exact correlation requires the same stable ID to be captured on the AgentPerf LLM call and serving request. |
| `llm_request_id` | Client-side propagated request ID | DIRECTLY OBSERVED | AgentPerf does not use timestamp matching. |
| `model` | Request/response metadata | DIRECTLY OBSERVED | Stored directly when available. |
| `input_tokens` | OpenAI-compatible `usage.prompt_tokens` | DIRECTLY OBSERVED | If absent, AgentPerf may fall back to explicit token IDs in recorded fixtures. |
| `output_tokens` | OpenAI-compatible `usage.completion_tokens` | DIRECTLY OBSERVED | If absent, AgentPerf may fall back to explicit generated token IDs. |
| `ttft_ms` | Client streaming timestamp from request start to first token | DIRECTLY OBSERVED | This is client TTFT, not server prefill latency. |
| `decode_latency_ms` | Recorded generation latency or `client_e2e_latency_ms - client_ttft_ms` | DIRECTLY OBSERVED or DERIVED | Provenance records whether it was direct or derived. |
| `tpot_ms` | Recorded TPOT, or derived from decode latency and output tokens | DIRECTLY OBSERVED or DERIVED | This is client/output timing unless server tracing provides stronger evidence. |
| `queue_latency_ms` | OpenTelemetry/request trace or explicit per-request export | DIRECTLY OBSERVED when present | Aggregate queue metrics are not converted into per-request latency. |
| `prefill_latency_ms` | No ordinary OpenAI-compatible response field | UNAVAILABLE | Do not infer from TTFT. |
| `prefill_path_latency_ms` | No vLLM-equivalent scheduled-to-first field in ordinary response | UNAVAILABLE | Client TTFT remains `ttft_ms`. |
| `prefix_cache_hit_tokens` | Per-request `usage.prompt_tokens_details.cached_tokens` when SGLang is launched with `--enable-cache-report` | DIRECTLY OBSERVED when present | Otherwise unavailable. |
| aggregate cache reuse | Prometheus `sglang:cache_hit_rate` | DIRECTLY OBSERVED aggregate | Stored as backend-specific metadata, not per-request cached tokens. |
| prompt/generated token IDs | Explicit recorded fields if captured by the caller | DIRECTLY OBSERVED when present | Not guaranteed by the public response path. |

## Cache Semantics

SGLang uses RadixAttention/prefix reuse internally, and public metrics include
aggregate cache signals such as `sglang:cache_hit_rate`. AgentPerf does not
treat that aggregate metric as equivalent to vLLM per-request
`cached_tokens`.

Therefore:

- per-request cached tokens are recorded only when SGLang exposes them directly,
  such as through `usage.prompt_tokens_details` with `--enable-cache-report`;
- aggregate SGLang cache metrics are stored in `ServingRequest.metadata` as
  backend provenance;
- missing per-request cache evidence means "unavailable", not "zero cache
  hits".

## First-Token Semantics

For SGLang recordings produced through the OpenAI-compatible streaming path,
AgentPerf records first-token timing as client TTFT:

```text
request start at client -> first streamed token observed by client
```

This is not server queue time, not pure GPU prefill time, and not vLLM's
scheduled-to-first-token metric. If SGLang OpenTelemetry spans are captured in
future runs, those server-stage metrics should be stored with their own
backend-specific provenance.

## Tool-Calling Compatibility

SGLang supports OpenAI-compatible tool parsing through configured tool parsers.
The official documentation lists parser options for several model families and
notes that tool choice support depends on parser/grammar backend configuration.
M17 should treat tool-parser/model incompatibility as a workload/backend setup
issue, not an AgentPerf detector failure.

## Request Correlation

AgentPerf supports exact correlation for SGLang when a stable identifier is
captured on both sides:

```text
AgentPerf LLMCall.llm_request_id
        =
SGLang ServingRequest.llm_request_id
```

or when the agent LLM call and serving request share the same
`serving_request_id`.

If the runtime path cannot propagate or expose such an identifier, AgentPerf
must report missing correlation. It must not silently use timestamp fuzzy
matching.

## M17 Live Validation

M17 ran the existing OpenAI Agents SDK support-triage workload through a live
SGLang endpoint.

Environment:

- SGLang image: `lmsysorg/sglang:v0.5.16-cu129-runtime`.
- Model: `Qwen/Qwen3-4B`, served as `agentperf-sglang-demo`.
- GPU: NVIDIA RTX A5000 24GB on Runpod.
- Server flags included `--enable-metrics`, `--enable-cache-report`, and
  `--tool-call-parser qwen`.
- Workload: 5 deterministic support-triage tasks.

Result:

| Metric | Value |
| --- | ---: |
| Tasks | 5 |
| LLM calls | 10 |
| Tool calls | 9 |
| SGLang serving requests | 10 |
| Exact request correlation | 10 / 10 |
| Input tokens | 3,561 |
| Output tokens | 924 |
| Cached prompt tokens | 1,980 |
| Mean score | 0.700 |
| Pass rate | 60% |

AgentPerf produced a unified artifact at
`examples/artifacts/m17_sglang_support_triage`. The artifact includes normalized
agent spans, tool calls, LLM calls, SGLang serving requests, task-level quality,
environment metadata, and persisted findings.

Findings:

- No high-confidence material AgentPerf findings were emitted.
- This is acceptable for M17: the milestone validates backend generalization and
  exact cross-layer correlation, not a new optimization win.

Unavailable in this run:

- per-request queue latency;
- per-request server-stage first-token timing;
- per-request generation/decode latency.

Those fields remain unavailable in the normalized serving requests rather than
being inferred from aggregate metrics.
