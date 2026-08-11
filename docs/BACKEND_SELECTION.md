# Backend Selection: vLLM vs SGLang

Historical note: this document records the first real-ingestion backend
selection before SGLang support existed. Current serving-backend capabilities
are summarized in [SERVING_BACKENDS.md](SERVING_BACKENDS.md).

Status: selected backend for the first real-ingestion milestone is **vLLM**.

Date of review: 2026-08-08.

Primary sources reviewed:

- vLLM metrics documentation: https://docs.vllm.ai/en/latest/usage/metrics/
- vLLM per-request metrics example: https://docs.vllm.ai/en/latest/features/per_request_metrics/
- vLLM OpenTelemetry example: https://docs.vllm.ai/en/latest/examples/observability/opentelemetry/
- vLLM OpenAI serving CLI: https://docs.vllm.ai/en/latest/cli/serve/
- vLLM automatic prefix caching example: https://docs.vllm.ai/en/latest/examples/features/automatic_prefix_caching/
- vLLM OpenAI chat protocol source: https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/chat_completion/protocol.py
- SGLang observability docs: https://docs.sglang.io/docs/advanced_features/observability
- SGLang metrics and request dump docs linked from the observability page.

## Decision

Use **vLLM** for the first real backend ingestion path.

The reason is narrow: vLLM gives the fastest credible path from a client LLM call
to backend telemetry with explicit request identity, exact token counts, TTFT/TPOT,
queue timing, prefix-cache hit token counts, and per-request timing fields. The
adapter can convert those fields into AgentPerf's normalized schema without
putting backend-specific logic inside detectors.

This is not a claim that vLLM is a better runtime than SGLang. It is only the
best fit for AgentPerf's current cross-layer profiling demo.

## Capability Comparison

| Capability needed by AgentPerf | vLLM | SGLang | Selection impact |
| --- | --- | --- | --- |
| Request ID propagation | OpenAI chat request model includes `request_id`; response ID is explicit. | Request logs/dumps and server APIs exist, but the documented OpenAI-compatible path is less direct for per-request metric correlation. | vLLM is simpler for explicit correlation. |
| OpenTelemetry/tracing | Official OpenTelemetry example and `--otlp-traces-endpoint`. | Official observability docs include tracing/logging/metrics. | Both are viable. |
| Queue timing | Per-request metrics expose queue time when enabled. Prometheus also exposes scheduler queue metrics. | Metrics expose scheduling/runtime state, but request-level mapping is less direct from public docs. | vLLM is lower friction. |
| Prefill timing | vLLM exposes `time_to_first_token_ms`, which is the closest request-level prefill proxy; pure prefill kernel time is not isolated in the OpenAI response. | SGLang exposes prefill/decode-oriented server metrics, but request-level conversion requires more backend-specific work. | vLLM is acceptable with documented approximation. |
| Decode timing | vLLM exposes generation time / inter-token latency metrics. | SGLang exposes generation metrics, but the first demo needs request-level artifacts. | vLLM is simpler. |
| TTFT / TPOT | Direct per-request fields in vLLM when enabled. | Exposed in observability stack, but per-request ingestion requires more investigation. | vLLM wins for the MVP. |
| Prefix-cache telemetry | `prompt_tokens_details.cached_tokens` can report cached prompt tokens; server metrics expose prefix cache hits/queries. | Prefix-cache metrics exist, but first-class per-request OpenAI response mapping is less documented. | vLLM gives the clearest detector input. |
| KV-cache telemetry | Server-level KV cache usage metrics exist; request-level KV capacity/eviction is unavailable. | SGLang exposes cache/runtime metrics, but request-level mapping is still not enough for AgentPerf's normalized request object. | Neither fully satisfies request-level KV analysis. |
| Ease of local integration | OpenAI-compatible HTTP client, per-request response metrics, no detector changes. Local execution still requires supported vLLM hardware/platform. | Integration likely needs request dump/replay and metrics scraping work. | vLLM selected. |
| Stability of relevant APIs | OpenAI-compatible serving API is stable enough; per-request metrics are documented as an example feature and should be treated as evolving. | Observability APIs are active and useful, but the exact cross-layer demo path is less direct. | vLLM has fewer moving pieces for the milestone. |

## What vLLM Does Not Solve

vLLM does not expose every AgentPerf field directly:

- request-level pure prefill kernel time is not directly exposed in the OpenAI response;
- request-level KV cache capacity and eviction/reuse behavior are not exposed;
- server-wide Prometheus metrics need a separate time-series correlation story;
- per-request metrics must be explicitly enabled on the server.

AgentPerf therefore records unavailable fields as unavailable and labels
approximations. It does not synthesize missing cache or prefill telemetry.

## Local Execution Status

This workspace is an Apple M2 laptop:

- platform: Darwin arm64;
- GPU: Apple M2 Metal, no CUDA GPU;
- no vLLM server was listening at `http://localhost:8000/v1/models`;
- `vllm` was not installed;
- a bounded `pip install vllm` attempt in `.venv-vllm` downloaded source
  distributions and backtracked through CPU-local package metadata instead of
  resolving to a supported wheel. The attempt was stopped before source build.

Because of that host limitation, this pass implements and tests the vLLM
ingestion path and runner but does **not** claim a completed real telemetry run.

## Direction

vLLM remains the right first backend. The next execution step is to run
`scripts/run_vllm_real_demo.py` against a real vLLM OpenAI server on a supported
GPU or CPU environment with per-request metrics and prompt-token details enabled.
