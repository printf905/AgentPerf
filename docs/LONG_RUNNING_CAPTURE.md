# Long-Running Capture

AgentPerf's default workflow is still optimized for bounded local experiments:

```python
with ExperimentSession(output_path=Path("runs/baseline")) as exp:
    ...
```

On successful exit, the session finalizes one self-contained artifact. That
path remains unchanged.

For longer-running local applications, `ExperimentSession` can also write
recoverable checkpoints before finalization:

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run

with ExperimentSession(
    output_path=Path("runs/live-capture"),
    workload_id="support-agent",
    expected_task_count=1000,
    checkpoint_interval=50,
) as exp:
    for task in tasks:
        with trace_run(task_id=task.id):
            with trace_llm(components={"user": task.prompt}) as call:
                response = agent(task.prompt)
                call.record_response(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
        exp.record_task_result(task_id=task.id, passed=True)

        # Optional manual checkpoint for important boundaries.
        exp.flush()
```

## What Checkpoints Preserve

A checkpoint stores a schema-v1 AgentPerf artifact snapshot containing evidence
recorded so far:

- completed LLM calls and tool calls;
- completed task results;
- prompt component attribution already recorded on completed calls;
- role/model routing metadata already recorded on calls;
- environment and experiment metadata;
- a manifest status of `PARTIAL` by default.

Checkpoints do not run detector analysis on every write. When you later run
`agentperf analyze`, `agentperf report`, or `agentperf doctor`, AgentPerf loads
the recovered trace evidence and performs normal offline analysis.

## Trigger Semantics

`exp.flush()` writes a checkpoint immediately.

`checkpoint_interval=N` writes a checkpoint after every `N` completed capture
events. Capture events include completed LLM calls, completed tool calls,
completed run steps, and recorded task results.

Automatic checkpointing is intentionally count-based. AgentPerf does not start
a background writer thread or local collector daemon.

## Recovery

If a process exits before finalization, the output path can be loaded directly:

```python
from agentperf import ExperimentSession

artifact = ExperimentSession.recover(Path("runs/live-capture"))
```

The standard CLIs also understand recoverable checkpoint paths:

```bash
agentperf inspect runs/live-capture
agentperf doctor runs/live-capture
agentperf analyze runs/live-capture
agentperf report runs/live-capture --output partial.html
```

Recovered checkpoint artifacts are marked `PARTIAL`, and doctor reports that
the artifact was recovered from the latest checkpoint. AgentPerf does not label
checkpointed evidence as `COMPLETE`.

## Crash Guarantees

AgentPerf's local checkpoint guarantee is:

```text
Evidence is recoverable up to the latest successfully written checkpoint.
```

This does not mean no data can ever be lost. Work completed after the latest
checkpoint may be lost if the process is killed before another checkpoint
finishes.

`SIGKILL`, machine power loss, filesystem failure, and storage corruption can
still interrupt the current write. Checkpoint writes use a versioned checkpoint
directory plus an atomic `latest.json` pointer, so an interrupted new checkpoint
does not invalidate the previous completed checkpoint.

## Exceptions And Interruptions

If user code raises inside an `ExperimentSession`, AgentPerf attempts to write
a failed checkpoint and a `FAILED` final artifact while preserving the original
exception. It does not swallow the user's exception.

`KeyboardInterrupt` follows the same rule: evidence recorded before the
interrupt is preserved where the process can still run Python cleanup handlers.

Hard process death cannot run cleanup handlers. In that case, only the latest
completed checkpoint is recoverable.

## Active Spans

Checkpoints may include an active run step when useful completed child evidence
has already been recorded. Active steps keep `ended_at` unset. AgentPerf does
not fabricate end times or present half-open spans as completed.

LLM and tool calls are only recorded after their context managers exit. A call
that is interrupted before exiting may be absent from the checkpoint rather than
misrepresented as completed.

## Memory Behavior

Checkpointing improves crash recovery, not streaming analysis. The current
session still keeps the in-memory recorder state needed for final artifact
generation. AgentPerf does not yet implement streaming detector state,
cross-process ingestion, or bounded-memory distributed trace collection.

For very long-running applications, treat checkpointing as local evidence
preservation and periodically inspect recovered partial artifacts.

## Security

Checkpoint files are local AgentPerf artifacts. They may contain the same prompt
component text, tool metadata, IDs, and usage evidence that normal artifacts
contain.

AgentPerf HTML reports redact raw prompt and tool payloads by default, but local
artifact and checkpoint files are not encrypted. Store checkpoint directories
with the same care as normal artifacts.

## Limitations

- Local filesystem only; no remote collector, database, daemon, or cloud
  registry.
- No guarantee for writes interrupted before the first checkpoint completes.
- No lossless guarantee for evidence recorded after the latest checkpoint.
- No resume-writing API in this version; recovery is read-only.
- Final expensive analysis still happens during `finalize()` or offline CLI
  analysis/reporting, not continuously during capture.
