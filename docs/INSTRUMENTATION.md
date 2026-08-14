# Instrumentation

Status: M19 public instrumentation surface.

AgentPerf can now capture agent-only traces from hand-written agents and from
one external framework adapter. Serving telemetry remains optional: agent-layer
token and context analysis works without vLLM, and cross-layer cache/latency
analysis activates only when serving requests are present and explicitly
correlated.

## Public API

For a framework-free Python agent, prefer the context-manager API:

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool

with ExperimentSession(output_path=Path("runs/raw"), workload_id="support-triage") as exp:
    with trace_run(task_id="ticket-001"):
        with trace_llm(
            model="my-model",
            components={
                "system": "Use the policy lookup tool before answering.",
                "user": "Customer asks for a refund.",
            },
        ) as call:
            response = invoke_model(...)
            call.record_response(
                output=response.text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                request_id=response.request_id,
            )

        with trace_tool("lookup_policy", input={"query": "refund"}) as tool:
            policy = lookup_policy("refund")
            tool.record_output(policy)

    exp.record_task_result(task_id="ticket-001", passed=True, quality_score=1.0)
```

`TraceRecorder` remains available for adapters and lower-level integrations.
For simple tools, `trace_tool` can also record calls as a decorator when a
current run exists:

```python
from agentperf import trace_tool

@trace_tool("lookup_policy")
def lookup_policy(query: str) -> str:
    return local_lookup(query)
```

The decorator preserves the wrapped function signature and docstring so agent
frameworks that inspect tools can still use the original callable metadata.

After recording an artifact, run:

```bash
agentperf doctor runs/raw
```

`doctor` reports agent-level readiness separately from cross-layer readiness.
Serving correlation is `NOT_APPLICABLE` when no serving telemetry is recorded,
not a failure.

## Concepts Captured

| Concept | Required | Notes |
| --- | --- | --- |
| `AgentRun` | yes | One logical agent execution or workload batch. |
| `AgentStep` | optional | A named phase such as planner, tool, reviewer, or final answer. |
| `LLMCall` | optional | Captures prompt components, token counts, model, request IDs, and timing. |
| `ToolCall` | optional | Captures tool name, input/output, IDs, timing, and provenance metadata. |
| `PromptComponent` | optional | Component labels such as `system`, `user`, `history`, `tool_schema`, `tool_result`, `retrieved_context`, or `other`. |
| `ServingRequest` | optional | Added by backend ingestion adapters, currently vLLM. |
| `semantic_role` | optional | Used by model-choice profiling when roles are meaningful. |

Unknown fields should be left unset rather than fabricated. AgentPerf detectors
are expected to degrade gracefully when serving telemetry or exact tokenization
is unavailable.

## OpenAI Agents SDK Adapter

The M5 adapter lives in `agentperf.integrations.openai_agents`.

It uses two mechanisms:

1. `OpenAIAgentsTraceProcessor` consumes the SDK's public tracing callbacks and
   preserves exported framework spans.
2. `AgentPerfModelWrapper` wraps a real SDK `Model` so AgentPerf can see the
   model input before the SDK sends it. This is needed for prompt-component
   attribution because exported response spans do not always contain the full
   prompt.

Minimal integration shape:

```python
from agentperf.integrations.openai_agents import instrument

instrumentation = instrument(
    real_sdk_model,
    model_name="my-model",
    request_id_factory=lambda llm_call_id: f"agentperf-{llm_call_id}",
)

agent = Agent(
    name="Support Triage",
    instructions=...,
    tools=[lookup_policy],
    model=instrumentation.model,
)

with instrumentation.recorder.as_current():
    result = await Runner.run(agent, user_task)

instrumentation.processor.write_export(Path("openai_agents_export.json"))
```

The adapter does not patch OpenAI Agents SDK internals.

## OpenTelemetry Alignment

AgentPerf's trace model intentionally uses familiar span concepts:

- `trace_id`
- `span_id`
- `parent_span_id`
- span start/end timestamps
- model/provider/backend attributes
- request IDs
- tool call spans

For M5, the mapping is pragmatic rather than a full OpenTelemetry exporter:

| Framework event/span | AgentPerf representation |
| --- | --- |
| SDK trace start/end | `AgentRun.metadata.external_traces` |
| SDK generation/response span | `LLMCall` |
| SDK function span | `ToolCall` when enabled |
| SDK model input items | `PromptComponent` |
| SDK function-call output input item | `PromptComponent(name="tool_result")` with `source_tool_call_ids` |

Future OTel ingestion should use the same normalized representation rather than
adding detector-specific framework fields.

## Known Limits

- The OpenAI Agents SDK adapter currently records non-streaming model calls.
  Streaming calls are passed through but not individually token-attributed.
- The adapter records approximate token counts unless the underlying model or
  serving backend provides exact usage.
- Serving request correlation is optional and not exercised by the local M5
  example.
- Framework-specific span exports vary; missing prompt text or usage should be
  reported as unavailable, not inferred.
