# Serving Backends

AgentPerf normalizes serving evidence so agent-layer spans can be analyzed with
backend telemetry. The goal is not to make every backend look identical. The
goal is to preserve what each backend actually exposes and make missing fields
explicit.

## Capability Matrix

| Capability | vLLM | SGLang |
| --- | --- | --- |
| Backend label | `vllm` | `sglang` |
| OpenAI-compatible response ingestion | yes | yes |
| Exact AgentPerf request correlation | yes, with propagated request IDs | yes, validated in M17 with propagated request IDs |
| Timestamp fuzzy matching | no | no |
| Input/output token usage | yes, from response usage/token IDs | yes, from response usage/token IDs when available |
| Prompt/generated token IDs | yes, when recorded with `return_token_ids=true` | yes, when explicitly recorded by the caller |
| Client TTFT | yes, when recorded | yes, from client streaming timestamps when recorded |
| Server queue latency | yes, from per-request metrics when recorded | unavailable in ordinary OpenAI-compatible responses; available only if explicit per-request trace/export is captured |
| Scheduled-to-first-token path | yes, recorded as `prefill_path_latency_ms` proxy | no equivalent ordinary response field |
| Pure prefill kernel latency | unavailable | unavailable |
| Generation/decode latency | yes, from per-request metrics or derived ITL | direct when recorded, otherwise derived from client E2E minus client TTFT |
| Per-request cached prompt tokens | yes, from `usage.prompt_tokens_details.cached_tokens` | yes, when `usage.prompt_tokens_details.cached_tokens` is exposed, for example with `--enable-cache-report` |
| Aggregate cache signal | backend metrics when collected | Prometheus metrics such as `sglang:cache_hit_rate` when collected |
| HTML report support | yes | yes |
| Real end-to-end validation | M2/M3/M4/M6 | M17 |

## Normalization Rules

- `ServingRequest.backend` records the concrete backend.
- Generic fields such as request ID, model, token counts, client TTFT, and
  output latency are filled only when the source has compatible semantics.
- Backend-specific metrics remain in `ServingRequest.metadata` with provenance.
- Missing evidence remains missing. AgentPerf does not convert missing cache
  telemetry into zero cache hits.
- Cross-layer correlation uses explicit IDs only.

## vLLM Notes

vLLM recordings can expose per-request queue time, scheduled-to-first-token,
generation timing, token IDs, and cached prompt tokens. AgentPerf labels
scheduled-to-first-token as prefill-path evidence, not pure GPU prefill kernel
time.

Detailed vLLM semantics are documented in:

- [REAL_TELEMETRY_MAPPING.md](REAL_TELEMETRY_MAPPING.md)
- [VLLM_PREFIX_CACHE_SEMANTICS.md](VLLM_PREFIX_CACHE_SEMANTICS.md)

## SGLang Notes

SGLang public telemetry includes OpenAI-compatible response usage, optional
client streaming timings, aggregate Prometheus metrics, and OpenTelemetry
request tracing when configured. Ordinary OpenAI-compatible responses do not
provide a vLLM-equivalent per-request cached-token counter or scheduled-to-first
stage.

M17 validated the SGLang path on an OpenAI Agents SDK support-triage workload:
5 tasks, 10 LLM calls, 9 tool calls, 10 SGLang serving requests, and 10/10 exact
request correlations. The run did not expose per-request queue, server-stage
first-token, or generation latency, so those fields remain unavailable in the
artifact.

Detailed SGLang semantics are documented in:

- [SGLANG_TELEMETRY.md](SGLANG_TELEMETRY.md)

## Comparing Backends

AgentPerf can analyze artifacts from different serving backends, but M17 is not
a vLLM-versus-SGLang benchmark. Latency comparisons are only meaningful when
hardware, model, configuration, workload, and measurement semantics are
compatible.
