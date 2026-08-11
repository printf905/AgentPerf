# Token Accounting

AgentPerf intentionally separates provider token usage from AgentPerf
component attribution. They answer related but different questions and should
not be assumed to match numerically.

## Provider Usage Tokens

Provider usage tokens are reported by the model provider or serving backend.
Common fields are:

- `prompt_tokens`
- `completion_tokens`
- AgentPerf comparison metric `provider.input_tokens`
- AgentPerf comparison metric `provider.output_tokens`

These values are useful for backend/provider billing-style accounting and for
comparing with model-server telemetry. They are only as complete as the
provider/backend response. Some clients or scripted test models may omit system
instructions, tool schemas, or other scaffolding from their reported usage.

Backward-compatible policy aliases:

- `input_tokens` -> `provider.input_tokens`
- `output_tokens` -> `provider.output_tokens`

## AgentPerf Component-Attributed Tokens

AgentPerf component-attributed tokens come from normalized prompt components
captured at the agent/instrumentation layer.

Supported component kinds include:

- `system`
- `user`
- `history`
- `tool_schema`
- `tool_result`
- `retrieved_context`
- `other`

Comparison and regression policies can address these metrics directly:

```yaml
performance:
  component.total.processed_tokens:
    max_increase_percent: 10
  component.system.processed_tokens:
    max_increase_percent: 5
    min_attribution_coverage: 0.80
    require_attribution_confidence: APPROXIMATE
  component.history.processed_tokens:
    max_increase_percent: 20
  component.tool_result.processed_tokens:
    max_increase_percent: 10
  component.tool_schema.processed_tokens:
    max_increase_percent: 10
  component.retrieved_context.processed_tokens:
    max_increase_percent: 10
```

Backward-compatible aliases are also accepted, for example:

- `tool_result_tokens`
- `component_tool_result_tokens`
- `component_system_tokens`
- `component_total_processed_tokens`

Component attribution answers: which parts of the agent context caused prompt
processing? This is why it can expose a prompt-scaffold change even when a
provider-style `input_tokens` field is unchanged.

## Unique Content

Unique content counts a component text once conceptually. If the same tool
result appears in five later LLM calls, the unique tool-result content may be
one block.

## Cumulative Processed Content

Cumulative processed content counts every time a component contributes to an
LLM call. If the same 1,000-token tool result is carried into five downstream
LLM calls, it contributes roughly 5,000 processed tool-result tokens.

This is the accounting used for context and harness waste. It respects task and
AgentRun boundaries; cross-run shared scaffold is not automatically treated as
removable within-run context waste.

## Coverage And Confidence

Comparison output includes component attribution coverage:

```text
(component processed tokens - OTHER tokens) / component processed tokens
```

`OTHER` means AgentPerf saw prompt content but could not classify it into a
more specific component. A low coverage ratio means component-specific policies
should be interpreted cautiously.

Attribution confidence is lightweight:

- `STRUCTURED`: prompt components came from structured instrumentation and all
  involved LLM calls reported exact tokenization mode.
- `APPROXIMATE`: AgentPerf had structured components, but token counts were
  estimated or at least one LLM call used non-exact tokenization mode.
- `UNAVAILABLE`: no component attribution was available.

AgentPerf does not claim these are probabilistic confidence scores.

Component-aware regression policies can require a minimum coverage ratio or
confidence level:

```yaml
performance:
  component.tool_result.processed_tokens:
    max_increase_percent: 10
    min_attribution_coverage: 0.90
    require_attribution_confidence: STRUCTURED
```

If the required attribution evidence is missing or too weak, the check is
`INCONCLUSIVE` rather than silently passing.

## Why M13 Needed This

The M13 dogfooding candidate shortened the OpenAI Agents SDK support-triage
system instruction. Provider-style input tokens stayed flat:

```text
1,604 -> 1,604
```

AgentPerf component attribution showed the actual prompt-scaffold change:

```text
component.total.processed_tokens: 1,320 -> 1,160
component.system.processed_tokens: 680 -> 520
```

Both facts are true. The first is provider/scripted-model usage accounting; the
second is AgentPerf's agent-layer component accounting.
