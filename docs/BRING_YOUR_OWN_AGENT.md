# Bring Your Own Agent

This guide is for a Python agent that is not built around an AgentPerf-specific
fixture. The goal is to record enough structure for AgentPerf to explain where
agent token/context/latency budget went.

## Minimal Framework-Free Integration

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool

with ExperimentSession(
    output_path=Path("runs/raw"),
    workload_id="support-agent",
    expected_task_count=1,
) as experiment:
    with trace_run(task_id="ticket-001"):
        with trace_llm(
            model="my-model",
            components={
                "system": system_prompt,
                "user": user_prompt,
                "history": "\n".join(history),
            },
        ) as call:
            response = invoke_model(...)
            call.record_response(
                output=response.text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                request_id=response.request_id,
            )

        with trace_tool("lookup_policy", input={"policy": "refund"}) as tool:
            policy = lookup_policy("refund")
            tool.record_output(policy)

    experiment.record_task_result(
        task_id="ticket-001",
        passed=True,
        quality_score=1.0,
        status="COMPLETE",
    )
```

`trace_llm` and `trace_tool` do not require raw prompt/tool payload retention
beyond the component text you choose to provide. If you cannot safely provide raw
content, provide redacted or summarized component text and leave unavailable
fields unset.

## What AgentPerf Needs

Required for a usable trace:

- task or run boundaries;
- LLM call boundaries.

Recommended:

- prompt component boundaries such as `system`, `user`, `history`,
  `tool_result`, `tool_schema`, `retrieved_context`, or `other`;
- provider input/output token usage when your model client exposes it;
- task outcomes or quality scores.

Optional:

- stable request IDs for serving correlation;
- vLLM/SGLang serving telemetry;
- tool input/output metadata or redacted output summaries;
- client TTFT / streaming timing if your model client exposes it.

Missing fields are allowed. AgentPerf reports them as unavailable or partial
instead of fabricating values.

## Check The Integration

Run:

```bash
agentperf doctor runs/raw
```

`doctor` answers:

- Did the artifact load?
- Were tasks and task outcomes recorded?
- How many LLM calls have timing?
- How many have provider usage?
- How many have component attribution?
- How many have stable request IDs?
- Are serving correlations exact, partial, or not applicable?

Agent-level readiness and cross-layer readiness are separate. A hosted-API or
local fake-model workload can be:

```text
Agent-level profiling: READY
Cross-layer profiling: NOT_APPLICABLE
```

That is valid. Cross-layer profiling only becomes applicable when serving
telemetry is recorded.

## Run The Local Example

The framework-free example uses a deterministic local fake model. It requires no
GPU, API key, or model download.

```bash
python examples/bring_your_own_agent/run.py --variant raw
python examples/bring_your_own_agent/run.py --variant optimized

agentperf doctor examples/bring_your_own_agent/runs/raw
agentperf report examples/bring_your_own_agent/runs/raw --output /tmp/agentperf-raw.html
agentperf compare \
  examples/bring_your_own_agent/runs/raw \
  examples/bring_your_own_agent/runs/optimized
```

The raw variant carries large policy-tool output into multiple downstream LLM
calls. The optimized variant carries a compact policy representation instead.
The example is a local instrumentation workflow, not a benchmark claim.

## OpenAI Agents SDK

The OpenAI Agents SDK path uses public SDK boundaries. AgentPerf provides the
validated lower-level wrapper/processor and a small helper:

```python
from agentperf.integrations.openai_agents import instrument

instrumentation = instrument(
    real_model,
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
    result = await Runner.run(agent, prompt)
```

Install `instrumentation.processor` through the OpenAI Agents SDK tracing API if
you want SDK span exports and function-span capture. Request-ID propagation
depends on the model/backend accepting a stable request identifier.

## Replay Workflow

Once a baseline and candidate artifact exist:

```bash
agentperf compare runs/raw runs/optimized
agentperf check runs/raw runs/optimized --policy agentperf-regression.yaml
```

The performance result is only accepted when quality stays within the configured
tolerance.
