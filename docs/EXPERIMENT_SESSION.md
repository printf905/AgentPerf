# Experiment Session

M10 adds an SDK-first recording path for artifact-by-default experiments.

The goal is to remove experiment-specific JSON glue:

```text
run workload
  -> trace execution
  -> record task results
  -> record quality
  -> capture safe environment metadata
  -> generate findings
  -> finalize artifact
```

`ExperimentSession` is intentionally small. It is not a workflow engine and it
does not define a universal evaluator. Workloads keep their own task execution
and evaluation logic.

## Minimal Workflow

```python
from pathlib import Path

from agentperf import ExperimentSession, QualityResult


def run_agent(task: dict[str, str]) -> str:
    # Your agent code runs here. AgentPerf instrumentation can record LLM/tool
    # spans through the session recorder or existing framework adapters.
    return "answer"


def evaluate(task: dict[str, str], answer: str) -> QualityResult:
    return QualityResult(
        score=1.0 if answer else 0.0,
        passed=bool(answer),
        evaluator_name="rule-evaluator",
        evaluator_version="1",
    )


with ExperimentSession(
    output_path=Path("artifacts/baseline"),
    artifact_id="baseline",
    workload_id="support-triage",
    expected_task_count=len(tasks),
    framework="my-agent-framework",
    agent_name="Support Agent",
    backend="vllm",
    model="Qwen/Qwen3-0.6B",
) as experiment:
    for task in tasks:
        experiment.run_task(
            task["id"],
            task,
            run_agent,
            evaluator=evaluate,
        )
```

The output directory is a standard AgentPerf artifact bundle:

```text
artifacts/baseline/
  manifest.json
  trace.json
  tasks.json
  quality.json
  findings.json
  environment.json
  summary.json
```

Then:

```bash
agentperf inspect artifacts/baseline
agentperf analyze artifacts/baseline
agentperf compare artifacts/baseline artifacts/candidate
```

## Task Recording

Every task can record:

- `task_id`
- `execution_id`
- linked `AgentRun` IDs
- pass/fail
- quality score
- additional named quality metrics
- evaluator name/version
- input/output token totals when known
- client/end-to-end latency
- error/failure reason
- metadata

You can either use `run_task(...)` or call `record_task_result(...)` manually.
Manual recording is useful for async frameworks or existing agent loops that
already own execution.

## Quality Evaluation

AgentPerf stores quality; it does not judge quality generically.

The evaluator returns a `QualityResult`:

```python
QualityResult(
    score=0.95,
    passed=True,
    evaluator_name="local-corpus-fact-coverage",
    evaluator_version="1",
)
```

For coding agents, the score may be test pass/fail. For research agents, it may
be fact coverage. For support workflows, it may be route/policy correctness.

## Client Latency

`ExperimentSession` records task-level `client_latency_ms` when using
`run_task(...)`. Existing loops can pass the value explicitly to
`record_task_result(...)`.

This is separate from serving telemetry. It represents the workload-visible
client/end-to-end task latency when available. `agentperf compare` can use this
field to calculate client-latency P50/P95 for artifact bundles.

## Failure And Partial Runs

Task failures are recorded as task rows with:

- `passed=false`
- `status=FAILED`
- `error=<exception class and message>`

The artifact itself is marked:

- `COMPLETE` when all expected tasks were recorded and no task error exists;
- `PARTIAL` when fewer than `expected_task_count` tasks were recorded;
- `FAILED` when a task error or session exception occurred.

Comparison warns on partial artifacts and differing task coverage.

## Finalization

At finalization, the session:

1. finishes the `TraceRecorder`;
2. runs the current AgentPerf analyzer/detectors;
3. aggregates task quality into `quality.json`;
4. captures safe environment metadata;
5. writes a temporary artifact directory;
6. validates that the artifact can be loaded;
7. renames it into place.

This avoids leaving a directory that looks complete before validation succeeds.

## Environment Capture

AgentPerf automatically records safe metadata:

- AgentPerf version;
- Python version;
- platform and machine;
- git commit when available;
- creation timestamp.

Caller-supplied environment metadata can add framework, backend, model, sampling
configuration, vLLM version, GPU, and repetition count.

AgentPerf does not collect API keys, SSH keys, environment secrets, model
weights, or private shell configuration.

## Existing Examples

The following local examples now emit `agentperf_artifact/` by default:

- framework-free M3 research-agent runner;
- OpenAI Agents SDK support-triage example;
- mini-SWE-agent repository-repair example.

The mini-SWE example may require the optional dependency and its normal local
configuration directory permissions.
