# LangGraph Integration

AgentPerf's LangGraph support is an optional integration. It adapts LangGraph
graph invocations into AgentPerf's existing run/task model and uses the same
LLM/tool instrumentation semantics as Bring Your Own Agent.

Install the optional dependency:

```bash
pip install "agentperf[langgraph]"
```

Until AgentPerf is published on PyPI, install from a local wheel or source
checkout with the `langgraph` extra.

## Minimal Shape

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_tool
from agentperf.integrations.langgraph import instrument

graph = build_graph()

with ExperimentSession(
    output_path=Path("runs/langgraph"),
    workload_id="policy-graph",
    framework="langgraph",
) as exp:
    runner = instrument(graph, experiment=exp)
    result = runner.invoke(
        {"query": "Route this refund request", "topic": "refund"},
        task_id="ticket-001",
    )
    exp.record_task_result(
        task_id="ticket-001",
        passed="refund" in result["answer"].lower(),
        quality_score=1.0,
    )
```

Inside graph nodes, use the public AgentPerf helpers to capture exact LLM and
tool spans:

```python
with trace_llm(
    model="my-model",
    components={"system": system_prompt, "user": state["query"]},
) as call:
    response = invoke_model(...)
    call.record_response(
        output=response.text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        request_id=response.request_id,
    )

with trace_tool("lookup_policy") as tool:
    policy = lookup_policy(state["topic"])
    tool.record_output(policy)
```

## What Is Captured

The integration captures:

- graph invocation as an AgentPerf run/task boundary;
- LLM calls instrumented inside graph nodes;
- tool calls instrumented inside graph nodes;
- provider usage and request IDs when node code records them;
- component attribution when node code supplies prompt components;
- task outcomes recorded through `ExperimentSession`.

It does not infer hidden model calls from private LangGraph internals. If a
graph node calls a model without `trace_llm`, AgentPerf will not fabricate that
span. `agentperf doctor` reports the resulting partial coverage.

## Readiness

Run:

```bash
agentperf doctor runs/langgraph
```

A local deterministic LangGraph workload with no serving backend can be:

```text
Agent-level profiling: READY
Cross-layer profiling: NOT_APPLICABLE
```

Cross-layer readiness only applies when serving telemetry is supplied and stable
request IDs are available.

## Local Example

The repository includes a deterministic LangGraph policy-routing example:

```bash
python examples/langgraph_agent/run.py --variant raw --output-root /tmp/agentperf-langgraph
python examples/langgraph_agent/run.py --variant optimized --output-root /tmp/agentperf-langgraph

agentperf doctor /tmp/agentperf-langgraph/raw
agentperf report /tmp/agentperf-langgraph/raw --output /tmp/agentperf-langgraph/report.html
agentperf compare /tmp/agentperf-langgraph/raw /tmp/agentperf-langgraph/optimized
```

The example uses a local fake model and deterministic tools. It requires no API
key, GPU, model download, or serving backend.
