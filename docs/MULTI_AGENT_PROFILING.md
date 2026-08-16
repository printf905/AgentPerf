# Multi-Agent and Parallel Profiling

AgentPerf can record optional structure metadata for local multi-agent and
parallel executions. This is observation metadata only: AgentPerf does not
orchestrate agents, schedule branches, or infer hidden framework internals.

## Identity Model

AgentPerf keeps these identities separate:

- `task_id`: one benchmark or workload item.
- `execution_id` / run: one execution scope.
- `agent_id`: the logical actor producing actions.
- `agent_role`: the actor's responsibility in the application.
- LLM `semantic_role`: the model-capacity role used by routing analysis.
- `branch_id`: one parallel path inside an execution.

For example, an agent can have:

```python
agent_id = "researcher-2"
agent_role = "researcher"
semantic_role = "evidence_reviewer"
branch_id = "search-b"
```

The `semantic_role` remains attached to the LLM call for model-routing
analysis. The `agent_id` and `agent_role` describe who performed the work.

## Instrumentation

Framework-free instrumentation accepts optional structure labels:

```python
from agentperf import record_handoff, trace_llm, trace_run, trace_tool

with trace_run("task", task_id="task-001", agent_id="coordinator", role="coordinator"):
    record_handoff(
        from_agent_id="coordinator",
        to_agent_id="researcher",
        context_components={"user": "research question"},
        branch_id="research",
    )

    with trace_run(
        "search-a",
        agent_id="researcher",
        role="researcher",
        branch_id="search-a",
        parent_branch_id="research",
    ):
        with trace_tool("search") as tool:
            tool.record_output("bounded result metadata")
        with trace_llm(
            role="evidence_reviewer",
            components={"tool_result": "bounded result metadata"},
            model="fixture-model",
        ) as call:
            call.record_response(input_tokens=128, output_tokens=32)
```

For handoffs, AgentPerf records IDs, token counts, component types, and bounded
metadata. It does not require or preserve raw handoff payloads for the HTML
views.

## Handoffs and Cross-Agent Context

`record_handoff(...)` records an explicit transfer from one logical agent to
another. When component text or explicit token counts are supplied, reports can
show transferred context tokens and downstream provider input tokens for the
receiving agent.

These values have different meanings:

- transferred tokens: unique context passed at the handoff boundary.
- downstream input tokens: later provider input attributed to the destination
  agent.
- component processed tokens: prompt-component processing inside the receiving
  agent's LLM calls.

AgentPerf keeps these separate to avoid implying that every transferred token is
always reprocessed exactly once.

## Parallel Branches

Branches are explicit IDs scoped by optional `parent_branch_id` values. A
fan-out/fan-in shape can be represented with multiple child branches sharing the
same parent:

```text
research
  search-a
  search-b
  search-c
  research-join
```

Reports show branch-level LLM calls, tool calls, provider input tokens,
component processed tokens, elapsed duration, and summed work.

## Wall-Clock vs Work

For parallel branches, summed work is not wall-clock latency.

AgentPerf reports:

- elapsed duration: min start to max end for that branch when timestamps exist.
- summed work: recorded LLM/tool duration within the branch.
- critical path: the longest child branch elapsed duration when branch timing
  evidence is complete.

If dependency edges or timestamps are insufficient, critical path is reported as
unavailable rather than inferred.

## Findings

Existing detectors remain authoritative. Multi-agent metadata improves scope
when provenance points to a scoped call, for example:

```text
agent:researcher branch:search-b
```

Historical findings without agent or branch metadata continue to load and render
normally.

## Comparison

`agentperf compare` includes optional multi-agent metadata in comparison output.
The HTML comparison report shows:

- added and removed agents;
- added and removed branches;
- per-agent LLM/tool deltas;
- per-agent provider-token and component-token deltas;
- handoff and branch-count changes.

Matching uses stable explicit IDs. AgentPerf does not perform graph edit-distance
matching when identities change ambiguously.

## Long-Running Capture

Checkpointed and recovered artifacts preserve completed agent, branch, and
handoff metadata. Active branches are not fabricated as completed spans. A
recovered incomplete session remains an explicit `PARTIAL` artifact under the
long-running capture semantics.

## Framework Integrations

LangGraph and OpenAI Agents SDK integrations can pass agent/branch labels where
their public instrumentation paths expose them or where users add explicit
node-level AgentPerf instrumentation. M26 does not add private framework
introspection or automatic deep capture of arbitrary multi-agent graphs.

For LangGraph's wrapper, explicit labels can be supplied through invocation
metadata:

```python
runner.invoke(
    {"task_id": "task-001", "query": "..."},
    task_id="task-001",
    metadata={"agent_id": "policy-router", "agent_role": "coordinator"},
)
```

Exact node, LLM, tool, and branch attribution still requires explicit
instrumentation at the relevant graph nodes.

## Security

Agent, branch, and handoff labels are user-provided metadata. HTML reports escape
these labels and apply existing redaction behavior to metadata values. Local
artifacts and checkpoint files are not encrypted; store them according to the
sensitivity of the traced workload.

## Limitations

- Multi-agent structure is explicit metadata, not inferred orchestration.
- AgentPerf does not attribute overall task quality to individual agents unless
  the workload records such quality evidence.
- Critical-path evidence is unavailable when timestamps or dependency structure
  are incomplete.
- Comparison uses stable IDs and reports unmatched identities; it does not solve
  general graph alignment.
