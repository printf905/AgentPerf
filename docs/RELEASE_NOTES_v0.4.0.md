# AgentPerf v0.4.0

AgentPerf v0.4.0 is about **Bring Your Own Agent + Trustworthy Diagnosis**.

The release makes AgentPerf easier to apply to custom Python agents without a
framework-specific adapter, and it makes reports clearer about what findings
prove, what is structural, and whether the available instrumentation is strong
enough for a conclusion.

## Bring Your Own Agent

You can now instrument a framework-free Python agent with the public
`ExperimentSession`, `trace_run`, `trace_llm`, and `trace_tool` APIs:

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool

with ExperimentSession(output_path=Path("runs/raw"), workload_id="support-agent") as exp:
    with trace_run(task_id="ticket-001"):
        with trace_llm(
            model="my-model",
            components={"system": system_prompt, "user": user_prompt},
        ) as call:
            response = invoke_model(...)
            call.record_response(
                output=response.text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                request_id=response.request_id,
            )

        with trace_tool("lookup_policy") as tool:
            policy = lookup_policy(...)
            tool.record_output(policy)

    exp.record_task_result(task_id="ticket-001", passed=True, quality_score=1.0)
```

This is explicit framework-free instrumentation, not zero-code or universal
automatic instrumentation.

## Know When Instrumentation Is Sufficient

`agentperf doctor` checks whether an artifact has enough captured evidence for
profiling:

- tasks and task outcomes;
- LLM and tool call structure;
- LLM timing;
- provider token usage;
- component attribution;
- stable request IDs;
- exact serving correlations when serving telemetry exists.

Agent-level readiness and cross-layer readiness are separate. A hosted API or
local fake-model workload can be:

```text
Agent-level profiling: READY
Cross-layer profiling: NOT_APPLICABLE
```

That is valid. vLLM or SGLang telemetry is useful for cross-layer analysis, but
it is not required for core agent-level profiling.

## More Trustworthy Findings

Reports now make metric source and materiality clearer:

- agent trace tokens, provider usage, component attribution, and serving tokens
  are labeled as different accounting domains;
- materiality gates show which thresholds were exceeded and which were not;
- investigation chains group related findings without claiming causality;
- missing evidence remains unavailable rather than being treated as zero or as
  negative evidence.

The guiding semantics remain:

```text
dominant != material
repeated != removable
headroom != actionable
missing evidence != negative evidence
structural repetition != optimization target
performance improvement != acceptable if quality regresses
```

## Validation Across Heterogeneous Workloads

AgentPerf v0.4.0 was validated across three small heterogeneous local workload
classes:

- mini-SWE-agent's existing coding loop on bounded local repository-repair
  tasks;
- OpenAI Agents SDK support triage;
- a deterministic framework-free tool-heavy workload.

Representative reviewed findings included:

- an actionable `TOOL_OUTPUT_BLOAT` case whose quality-preserving replay removed
  the finding;
- a valid but non-actionable `CONTEXT_DUPLICATION` observation;
- expected structural `CROSS_RUN_SHARED_SCAFFOLD` behavior where no unsafe
  context-removal recommendation was made.

The M20 review labels are human validation classifications of representative
detector outputs. They are not automatic detector labels and not a universal
detector-accuracy benchmark.

## Existing Workflow Remains

The v0.3 workflow remains intact:

```text
ExperimentSession
-> self-contained artifact
-> analyze/report
-> compare
-> check
-> benchmark suite
-> CI PASS / FAIL / INCONCLUSIVE
```

Existing raw traces, artifacts, `compare`, `check`, `suite`, local HTML reports,
vLLM ingestion, and SGLang ingestion remain supported. Artifact schema version
remains `1`.

## Real Quantitative Validation

M3 remains AgentPerf's primary public quantitative validation example.

In the controlled M3 research-agent workload:

| Metric | RAW_FULL | DEDUP_ONLY |
| --- | ---: | ---: |
| Input processing | 132,756 | 95,479 |
| Tool-result processing | 112,287 | 78,566 |
| Scheduled-to-first P95 | 312.180 ms | 176.534 ms |
| Mean quality | 0.933 | 0.908 |
| Pass rate | 80% | 70% |

The predefined quality tolerance passed and the replay verdict was `ACCEPT`.
This is one controlled workload result, not a universal performance claim.

## Serving Backend Support

AgentPerf supports serving correlation for vLLM and SGLang, with telemetry
availability depending on backend capabilities and recording path.

SGLang support was validated with exact propagated request-ID correlation on a
real OpenAI Agents SDK to SGLang run. Ordinary SGLang OpenAI-compatible
responses do not generally expose every per-request timing stage, such as
queue latency, server-stage TTFT, or generation/decode latency.

AgentPerf's cross-layer scope is:

```text
agent execution
-> LLM calls
-> prompt/component attribution
-> serving request correlation
-> backend telemetry where available
```

It does not provide CUDA kernel tracing, GPU hardware counters, or kernel-level
attribution.

## Limitations

- Framework-free instrumentation still requires explicit integration points in
  user code.
- The M20 finding review set is small and manually classified.
- AgentPerf does not claim universal detector accuracy or universal support for
  every agent runtime.
- Serving telemetry differs by backend.
- Some component attribution may be approximate depending on instrumentation.
- mini-SWE-agent validation used bounded local repository-repair tasks, not
  SWE-bench.
- M4 mixed-routing end-to-end validation remains incomplete.
