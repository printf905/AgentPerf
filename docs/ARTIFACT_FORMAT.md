# AgentPerf Artifact Format

M9 introduces a portable AgentPerf experiment artifact. A raw normalized trace
answers "what happened in this execution." An artifact bundle also records the
task outcomes, quality metrics, findings, environment, and summary metadata
needed for replay verification and reproducibility.

The format is local-filesystem first. A bundle is a directory:

```text
agentperf-run/
  manifest.json
  trace.json
  tasks.json
  quality.json
  findings.json
  environment.json
  summary.json
```

The current artifact schema version is `1`.

## Manifest

`manifest.json` is the entry point:

```json
{
  "schema_version": 1,
  "artifact_id": "m3-raw_full",
  "agentperf_version": "0.2.0",
  "created_at": "2026-08-09T06:17:10.948324+00:00",
  "workload_id": "m3-real-agent-context-waste",
  "framework": "none",
  "agent_name": "m3-framework-free-research-agent",
  "backend": "vllm",
  "model": "agentperf-vllm-demo",
  "task_count": 10,
  "serving_telemetry": true,
  "status": "COMPLETE",
  "locations": {
    "trace": "trace.json",
    "tasks": "tasks.json",
    "quality": "quality.json",
    "findings": "findings.json",
    "environment": "environment.json",
    "summary": "summary.json"
  }
}
```

All locations are relative to the artifact directory. Absolute paths or paths
that escape the bundle are rejected.

## Trace

`trace.json` contains the normalized AgentPerf trace:

- one trace object;
- a workload object with `runs: [...]`;
- or a list of trace objects.

Existing raw trace JSON inputs remain valid for `agentperf analyze` and
`agentperf compare`. The artifact format adds surrounding experiment metadata
without changing the normalized trace schema.

## Tasks

`tasks.json` standardizes per-task results:

```json
{
  "tasks": [
    {
      "task_id": "task-1",
      "execution_id": "run-1",
      "passed": true,
      "quality_score": 0.95,
      "evaluator": "rule-score-v1",
      "input_tokens": 1234,
      "output_tokens": 120,
      "duration_ms": 2500.0,
      "client_latency_ms": 2500.0,
      "status": "COMPLETE",
      "error": null,
      "agent_run_ids": ["task-1-run"],
      "metadata": {}
    }
  ]
}
```

Task rows may link to one or more `AgentRun` IDs. This is the preferred place
for task success and task quality. Historical artifacts may only have aggregate
quality metrics; AgentPerf records that limitation instead of inventing
per-task rows.

`client_latency_ms` is task/client-visible latency. It is separate from serving
metrics such as queue time or scheduled-to-first-token latency. New experiment
runners should store it when available so generic replay comparison can compute
client-latency P50/P95.

Task and artifact status values are:

- `COMPLETE`: expected work finished and was recorded;
- `PARTIAL`: fewer tasks were recorded than expected;
- `FAILED`: a task or experiment-level exception was recorded.

## Quality

`quality.json` stores generic named metrics produced by the workload evaluator:

```json
{
  "metrics": [
    {
      "name": "mean_score",
      "value": 0.9333333333333333,
      "direction": "higher_is_better",
      "aggregation": "mean",
      "tolerance": 0.05
    },
    {
      "name": "pass_rate",
      "value": 0.8,
      "direction": "higher_is_better",
      "aggregation": "rate",
      "tolerance": 0.10
    }
  ]
}
```

AgentPerf stores evaluation results; it does not define a universal evaluator.
Research tasks, support-triage tasks, coding tasks, and CI repair tasks can use
different metrics as long as the metric names and semantics are explicit.

`agentperf compare` currently understands `mean_score` and `pass_rate` for
accept/reject semantics. Other metrics are preserved for inspection and future
tools.

## Environment

`environment.json` should include reproducibility metadata such as:

- AgentPerf version and git commit when known;
- framework and framework version;
- model and backend;
- vLLM version where relevant;
- GPU and server configuration where relevant;
- sampling configuration;
- repetition count.

GPU fields are optional. Agent-only local workloads should still produce valid
artifacts. Do not store API keys, SSH keys, Runpod tokens, Hugging Face tokens,
or model weights.

## Findings

`findings.json` stores the findings generated for that run:

- finding ID;
- severity;
- materiality/scope evidence where available;
- provenance;
- recommendation;
- validation plan.

By default, `agentperf compare` recomputes findings from `trace.json` so the
current detector code is authoritative. Stored findings are useful for audit,
debugging, and reproducing what a historical run reported. If future tools need
to compare exactly the historical detector output, they should explicitly opt
into trusted stored findings.

## Summary

`summary.json` contains compact human- and machine-readable run summaries. It
may duplicate derived totals from the trace for convenience, but the normalized
trace and quality files remain authoritative for analysis and comparison.

## Versioning

Unknown newer artifact schema versions fail clearly. AgentPerf does not silently
interpret a bundle with a schema version it does not understand.

M10 adds optional task latency, task status, task error, and artifact status
fields while keeping schema version `1`. Older v1 bundles remain valid.

## Portability

Bundles are portable directories. They should avoid:

- absolute private local paths;
- credentials or environment files;
- large generated archives;
- model weights;
- machine-specific paths that are not needed for interpretation.

Copying a bundle to another directory should not change `agentperf inspect`,
`agentperf analyze`, or `agentperf compare` behavior.
