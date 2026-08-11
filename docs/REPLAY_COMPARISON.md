# Replay Comparison Contract

M8 adds a generic comparison contract for replay verification:

```text
BaselineRun
CandidateRun
    -> task matching
    -> token, latency, cache, quality, and finding deltas
    -> conservative verification verdict
```

The comparison layer is backend- and framework-independent. It operates on
normalized AgentPerf traces after each side has already been analyzed.

## Inputs

`agentperf compare` accepts either:

- one normalized AgentPerf trace JSON file per side;
- a workload object with `runs: [...]`;
- a JSON list of normalized trace objects.

Each entry may represent one `AgentRun`. For workload comparisons, AgentPerf
matches baseline and candidate tasks by stable metadata identifiers:

- `workload_item_id`
- `task_id`
- `execution_id`
- `run_id`

If both files contain exactly one run and no stable task ID, AgentPerf compares
them by file cardinality and emits a warning. If multi-run workloads do not
share stable task IDs, it reports unmatched tasks instead of silently
subtracting unrelated runs.

## Output Model

The reusable schema is `RunComparison`:

- `baseline_id`
- `candidate_id`
- `matched_tasks`
- `unmatched_baseline_tasks`
- `unmatched_candidate_tasks`
- `token_deltas`
- `context_growth_delta`
- `latency_deltas`
- `cache_deltas`
- `quality_deltas`
- `finding_changes`
- `acceptance_result`
- `warnings`
- `metadata`

The model serializes cleanly to JSON for future CI, benchmark-runner, dashboard,
or optimization-loop use.

## Token Deltas

The comparison reports:

- total input tokens;
- total output tokens;
- component-level processed tokens for system, user, history, tool schema, tool
  result, retrieved/file context, and other components where present.

This is processed-token accounting, not model-capacity cost. A model-choice
change may reduce latency or relative cost without reducing tokens.

## Context Growth

The comparison reports:

- total baseline and candidate LLM step counts;
- final-step input tokens;
- max-step input tokens;
- average growth slope in tokens per step when a run has two or more steps.

Step counts do not need to match. When step counts differ, raw counts and
normalized growth behavior are both surfaced.

## Latency Deltas

Where available, the comparison reports:

- tool latency;
- queue P50/P95;
- scheduled-to-first-token P50/P95;
- generation/decode P50/P95;
- client LLM-call latency P50/P95.

`scheduled->first` remains a measured request-level first-token path metric. It
is not pure GPU prefill kernel time. Missing telemetry is reported as
unavailable instead of inferred.

## Cache Deltas

When serving telemetry exists, the comparison reports:

- cached tokens;
- cache-miss tokens;
- cached-token ratio.

Agent-only traces still compare successfully. AgentPerf does not infer cache
misses without backend evidence.

## Quality Deltas

Quality is optional but central to acceptance. AgentPerf currently reads
task-level quality from `AgentRun.metadata`, either directly or under a
`quality` object:

```json
{
  "metadata": {
    "task_id": "task-1",
    "quality": {
      "score": 0.93,
      "passed": true
    }
  }
}
```

CLI tolerances are explicit:

```bash
agentperf compare baseline.json candidate.json \
  --quality-tolerance 0.05 \
  --pass-rate-tolerance 0.10
```

If performance improves but no quality signal exists, the verdict is
`INCONCLUSIVE` with the warning
`PERFORMANCE_IMPROVEMENT_UNVERIFIED_FOR_QUALITY`.

## Verdicts

AgentPerf emits conservative states:

- `ACCEPT`: performance materially improved and quality stayed within the
  configured tolerance.
- `REJECT_QUALITY_REGRESSION`: performance may have improved, but quality
  violated the configured tolerance.
- `NO_MATERIAL_CHANGE`: no material token or client-latency improvement was
  observed.
- `INCONCLUSIVE`: task matching, quality, or telemetry gaps prevent a strong
  conclusion.
- `REGRESSION`: the candidate is materially worse on tokens or client latency.

There is no "optimal" verdict.

## Finding Lifecycle

Findings are compared by detector ID and semantic scope, not display title.
Lifecycle states are:

- `RESOLVED`
- `IMPROVED`
- `PERSISTENT`
- `REGRESSED`
- `NEW`

For example, `TOOL_OUTPUT_BLOAT` changing from `HIGH` to `MEDIUM` is
`IMPROVED`; disappearing entirely is `RESOLVED`.

## Current Real-Artifact Note

The preserved M3 normalized real traces reconstruct token, component, cache, and
scheduled-to-first deltas. They do not currently carry task-quality metadata in
the normalized trace itself, so the generic comparator correctly reports an
`INCONCLUSIVE` acceptance verdict for those raw trace files. Future real
experiment artifacts should embed per-task quality metadata directly in
`AgentRun.metadata`.
