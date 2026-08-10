# Instrumentation

Status: M5 public instrumentation surface.

AgentPerf can now capture agent-only traces from hand-written agents and from
one external framework adapter. Serving telemetry remains optional: agent-layer
token and context analysis works without vLLM, and cross-layer cache/latency
analysis activates only when serving requests are present and explicitly
correlated.

## Public API

The core recorder lives in `agentperf.instrumentation`.

```python
from agentperf import trace_run

with trace_run("support-triage") as recorder:
    with recorder.step("planner"):
        recorder.record_llm_call(
            llm_call_id="llm-1",
            model="my-model",
            prompt_components={
                "system": "Use the policy lookup tool before answering.",
                "user": "Customer asks for a refund.",
            },
            input_tokens=21,
            output_tokens=8,
        )
        recorder.record_tool_call(
            tool_call_id="tool-1",
            name="lookup_policy",
            input={"query": "refund"},
            output="POLICY-REFUND-2026: ...",
        )

    recorder.write_json(Path("agentperf_trace.json"))
```

For simple tools, `trace_tool` can record calls when a current run exists:

```python
from agentperf import trace_tool

@trace_tool("lookup_policy")
def lookup_policy(query: str) -> str:
    return local_lookup(query)
```

The decorator preserves the wrapped function signature and docstring so agent
frameworks that inspect tools can still use the original callable metadata.

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
from agents.tracing import set_trace_processors
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.openai_agents import (
    AgentPerfModelWrapper,
    OpenAIAgentsTraceProcessor,
)

recorder = TraceRecorder(agent_run_id="support-triage")
processor = OpenAIAgentsTraceProcessor(recorder)
set_trace_processors([processor])

model = AgentPerfModelWrapper(real_sdk_model, recorder, model_name="my-model")
agent = Agent(name="Support Triage", instructions=..., tools=[lookup_policy], model=model)

with recorder.as_current():
    result = await Runner.run(agent, user_task)

recorder.write_json(Path("agentperf_trace.json"))
processor.write_export(Path("openai_agents_export.json"))
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
