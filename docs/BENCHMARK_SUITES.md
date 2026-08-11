# Benchmark Suites

An AgentPerf benchmark suite is a small filesystem manifest that connects:

- a stable suite identity;
- an explicit accepted baseline artifact;
- a regression policy;
- task-set metadata;
- optional environment compatibility rules.

It does not execute workloads and does not manage remote storage.

## Layout

```text
benchmarks/
  research-agent/
    suite.yaml
    baseline/
    policy.yaml
```

The baseline can also be referenced elsewhere in the repository using a
relative path. It is never inferred from "latest artifact in this directory."

## `suite.yaml`

```yaml
schema_version: 1
suite_id: research-agent
suite_version: 1
description: Local research-agent quality/performance suite.
agent: framework-free-research-agent
framework: none
task_set:
  id: local-corpus-v1
  fingerprint: optional-sha256-of-sorted-task-ids
baseline_artifact: baseline
regression_policy: policy.yaml
expected_task_count: 10
quality_metrics:
  mean_score: true
  pass_rate: true
environment:
  latency_requires_compatible: true
  allow_environment_mismatch: false
metadata:
  owner: agent-team
```

## Versioning

`suite_version` is the version of the benchmark contract: task set, evaluator,
and baseline expectations.

It is separate from:

- AgentPerf package version;
- AgentPerf artifact schema version;
- regression policy schema version.

If tasks or evaluator semantics intentionally change, update the suite version
and review the baseline change explicitly.

## Baseline Identity

The suite points to one accepted baseline artifact:

```yaml
baseline_artifact: baseline
```

Validation records baseline metadata such as:

- artifact ID;
- AgentPerf version;
- created timestamp;
- task count.

This makes baseline drift visible during review.

## Task-Set Fingerprint

When task rows are available in the artifact, AgentPerf computes:

```text
sha256(sorted task IDs joined by newline)
```

This detects accidental task-set changes without hashing task contents that may
contain private data.

Historical aggregate-only artifacts can omit the fingerprint. Future M10+
artifacts should include task rows so suites can check task identity more
strictly.

## Environment Compatibility

Latency comparisons are hardware/backend-sensitive. If a suite policy checks
latency and the baseline/candidate artifacts clearly differ on backend, model,
or GPU metadata, `agentperf suite check` reports an environment compatibility
check.

By default, mismatched latency environments are `INCONCLUSIVE`, not `PASS`.

Use separate suite IDs for materially different environments such as:

- local CPU/agent-only;
- vLLM GPU;
- a different serving backend.

AgentPerf does not normalize arbitrary hardware performance.

## Commands

Validate a suite:

```bash
agentperf suite validate benchmarks/research-agent/
```

Check a candidate:

```bash
agentperf suite check benchmarks/research-agent/ candidate-artifact/
```

Check many suites:

```bash
agentperf suite check-all benchmarks/ candidate-artifacts/
```

Create a reviewable baseline update report:

```bash
agentperf suite propose-baseline benchmarks/research-agent/ candidate-artifact/
```

The proposal command does not overwrite any baseline.
