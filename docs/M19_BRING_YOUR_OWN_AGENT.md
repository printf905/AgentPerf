# M19 Bring Your Own Agent Engineering Note

M19 focuses on low-friction instrumentation and integration completeness for
users who already have a Python agent. It does not add a new framework, serving
backend, detector family, dashboard, or remote storage.

## Existing Instrumentation Audit

Before M19, AgentPerf already had:

- `TraceRecorder`: public-ish recorder that can create normalized `AgentRun`,
  `LLMCall`, and `ToolCall` records.
- `trace_run`: standalone run context that created a recorder.
- `trace_tool`: decorator-only helper for tools inside a current recorder.
- `ExperimentSession`: artifact-by-default session that records task results,
  quality, environment metadata, findings, and summaries.
- OpenAI Agents SDK `AgentPerfModelWrapper` and `OpenAIAgentsTraceProcessor`.
- request-ID propagation paths for vLLM/SGLang experiments.

Gaps:

- framework-free users still had to call `recorder.record_llm_call(...)`
  directly;
- `trace_tool` was not usable as a context manager;
- `trace_run(...)` inside an `ExperimentSession` could accidentally create a
  disconnected recorder instead of scoping a task within the active session;
- there was no public `trace_llm(...)` context manager;
- there was no integration completeness/readiness check;
- reports did not say whether conclusions were based on complete or partial
  capture.

## Public API Chosen

M19 promotes a small framework-free surface:

```python
from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool
```

`trace_run(...)` remains backward compatible for standalone runs. When a current
`ExperimentSession` recorder exists, `trace_run(task_id=...)` creates a scoped
step in that recorder instead of creating a detached trace.

`trace_llm(...)` records a model call on context exit. The user can attach
provider usage and request IDs with `record_response(...)`.

`trace_tool(...)` now supports both:

```python
@trace_tool("lookup")
def lookup(...): ...
```

and:

```python
with trace_tool("lookup") as tool:
    result = lookup(...)
    tool.record_output(result)
```

## Rejected Alternatives

- A general telemetry event API: too broad for an agent profiler.
- A new workflow engine: `ExperimentSession` already owns artifacts and quality.
- Automatic monkey-patching of user model clients: too fragile and surprising.
- New schema version: M19 adds capture/readiness logic without changing artifact
  schema v1.

## Completeness Model

The new completeness model computes:

- task rows and task outcomes;
- runs, LLM calls, tool calls;
- LLM calls with timing;
- LLM calls with provider usage;
- LLM calls with component attribution;
- LLM calls with stable request IDs;
- serving requests;
- eligible and exact serving correlations.

Coverage distinguishes observed, eligible, covered, ratio, and status.

Readiness states:

- `READY`
- `PARTIAL`
- `NOT_READY`
- `NOT_APPLICABLE`

Agent-level profiling readiness and cross-layer readiness are separate. A local
or hosted model run can be agent-ready while cross-layer profiling is not
applicable.

## Doctor Behavior

`agentperf doctor <artifact-or-trace>` loads the input, computes completeness,
and exits:

- `0`: artifact/trace is valid and not agent-level `NOT_READY`;
- `1`: invalid input or not profile-ready.

Dogfooding excerpt:

```text
AgentPerf Integration Check
============================================================

Tasks
------------------------------------------------------------
OK tasks observed                     3 / 3
OK tasks with outcomes                3 / 3
OK tasks with quality                 3 / 3

Agent tracing
------------------------------------------------------------
runs observed                        1
LLM calls observed                   9
OK LLM calls with timing              9 / 9
OK LLM calls with component attribution 9 / 9

Readiness
------------------------------------------------------------
Agent-level profiling                READY
Cross-layer profiling                NOT_APPLICABLE
```

## Framework-Free Example

`examples/bring_your_own_agent/run.py` is a deterministic local support-policy
agent. It records three tasks, planner/reviewer/final LLM calls, policy lookup
tools, quality outcomes, and two variants:

- `raw`: carries large policy-tool output downstream;
- `optimized`: carries compact policy context downstream.

Dogfooding commands:

```bash
python examples/bring_your_own_agent/run.py --variant raw --output-root /tmp/agentperf-byoa-runs
python examples/bring_your_own_agent/run.py --variant optimized --output-root /tmp/agentperf-byoa-runs
agentperf doctor /tmp/agentperf-byoa-runs/raw
agentperf report /tmp/agentperf-byoa-runs/raw --output /tmp/agentperf-byoa-raw.html
agentperf compare /tmp/agentperf-byoa-runs/raw /tmp/agentperf-byoa-runs/optimized
```

Observed baseline excerpt:

```text
[HIGH] TOOL_OUTPUT_BLOAT
raw tool output tokens             864
downstream reinjections            2
cumulative downstream processed tokens 1728
```

Replay result:

```text
verdict: ACCEPT
quality: 1.0 -> 1.0
tool_result processed tokens: 4212 -> 68
finding lifecycle: TOOL_OUTPUT_BLOAT RESOLVED
```

This is an instrumentation example, not a public performance benchmark.

## OpenAI Agents SDK Onboarding

M19 adds `agentperf.integrations.openai_agents.instrument(...)`, which returns:

- a `TraceRecorder`;
- an `OpenAIAgentsTraceProcessor`;
- an `AgentPerfModelWrapper`.

It uses public SDK wrapper/trace-processor boundaries and keeps request-ID
propagation explicit.

## Error Handling

`trace_llm` and context-manager `trace_tool` record `status=FAILED`, timing, and
error text before propagating the original exception. AgentPerf does not swallow
agent failures.

`ExperimentSession.record_task_result(...)` now rejects duplicate
`task_id`/`execution_id` rows because duplicate task rows corrupt comparison and
readiness denominators.

## Compatibility

- Artifact schema remains v1.
- Raw trace analyze/compare still works.
- Existing decorator-style `trace_tool` remains supported.
- M18 metric provenance/materiality/investigation output remains intact.
- vLLM and SGLang correlation paths are unchanged.
- M3 compare/check/suite conclusions remain unchanged.

## Remaining Limitations

- The framework-free API is sync-first.
- AgentPerf cannot prove that every user model call was wrapped; `doctor`
  reports captured evidence only.
- Cross-layer readiness depends on explicit serving telemetry and stable request
  IDs.
- OpenAI Agents SDK streaming calls remain weaker than non-streaming calls unless
  the model/backend exposes enough response metadata.
