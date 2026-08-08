# Trace Schema

The MVP accepts JSON in a normalized AgentPerf format. Fields are optional unless marked required.

## Top Level

```json
{
  "schema_version": "0.1",
  "synthetic": true,
  "agent_run": {},
  "serving_requests": []
}
```

## AgentRun

Required:

- `agent_run_id`
- `steps`

Optional:

- `trace_id`
- `span_id`
- `parent_span_id`
- `name`
- `started_at`
- `ended_at`
- `metadata`

## AgentStep

Required:

- `agent_step_id`

Optional:

- `trace_id`
- `span_id`
- `parent_span_id`
- `started_at`
- `ended_at`
- `llm_calls`
- `tool_calls`
- `metadata`

## LLMCall

Required:

- `llm_call_id`

Optional:

- `trace_id`
- `span_id`
- `parent_span_id`
- `agent_step_id`
- `llm_request_id`
- `serving_request_id`
- `model`
- `provider`
- `backend`
- `started_at`
- `ended_at`
- `prompt`
- `input_tokens`
- `output_tokens`
- `prompt_token_ids`
- `output_token_ids`
- `tokenization_mode`
- `ttft_ms`
- `tpot_ms`
- `metadata`

The prompt may be either a mapping of component names to strings or a list of prompt components:

```json
{
  "system": "...",
  "history": "...",
  "tool_schemas": "...",
  "tool_results": "...",
  "user": "...",
  "other_context": "..."
}
```

Known prompt component names:

- `system`
- `user`
- `history`
- `tool_schemas`
- `tool_results`
- `other_context`

Unknown component names are preserved.

## ToolCall

Required:

- `tool_call_id`
- `name`

Optional:

- `trace_id`
- `span_id`
- `parent_span_id`
- `started_at`
- `ended_at`
- `latency_ms`
- `input`
- `output`
- `metadata`

## ServingRequest

Required:

- `serving_request_id`

Optional:

- `trace_id`
- `span_id`
- `parent_span_id`
- `llm_request_id`
- `model`
- `backend`
- `started_at`
- `ended_at`
- `queue_latency_ms`
- `prefill_latency_ms`
- `decode_latency_ms`
- `ttft_ms`
- `tpot_ms`
- `input_tokens`
- `output_tokens`
- `prefix_cache_hit_tokens`
- `prefix_cache_miss_tokens`
- `kv_cache_used_tokens`
- `kv_cache_capacity_tokens`
- `kv_cache_evictions`
- `tokenization_mode`
- `metadata`

## Supported Trace Modes

Agent-only trace:

- Contains `agent_run` and LLM calls.
- Serving-specific findings are skipped or reduced to agent-only evidence.

Serving-only trace:

- Contains `serving_requests`.
- Agent-level context duplication and prefix opportunity findings are skipped.

Correlated cross-layer trace:

- Contains LLM calls and serving requests with explicit matching IDs.
- All MVP detectors can run.

## Tokenization

Tokenization mode is explicit:

- `EXACT`: token IDs or backend tokenizer counts are available for the relevant
  text.
- `APPROXIMATE`: AgentPerf used its fallback regex tokenizer.
- `UNKNOWN`: the source did not declare tokenization reliability.

Synthetic fixtures may use approximate tokenization. Real vLLM recordings can
use exact token counts from `usage.prompt_tokens` and `usage.completion_tokens`;
when `return_token_ids=true`, AgentPerf also preserves `prompt_token_ids` and
`output_token_ids`.

AgentPerf must not silently mix exact and approximate token evidence. Findings
include provenance notes when token-derived metrics are approximate.

## Finding Provenance

Findings may include a `provenance` object with:

- agent span IDs;
- LLM call IDs;
- client LLM request IDs;
- backend serving request IDs;
- raw metrics used by the detector;
- derived metrics calculated by AgentPerf;
- notes about approximations or missing telemetry.

The terminal reporter can print this with `--show-provenance`.

## OpenTelemetry Alignment

The schema keeps `trace_id`, `span_id`, and `parent_span_id` fields and uses GenAI terminology where practical, such as provider, model, agent invocation, tool call, token usage, TTFT, and TPOT. It intentionally stores serving-specific fields that are not currently first-class in generic GenAI semantic conventions, such as prefill latency and prefix-cache hit/miss tokens.
