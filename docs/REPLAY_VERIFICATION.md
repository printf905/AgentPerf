# Replay Verification

AgentPerf's product loop is:

```text
TRACE -> PROFILE -> DIAGNOSE -> RECOMMEND -> REPLAY -> VERIFY
```

Before M8, replay verification existed mostly in experiment-specific scripts and
manually written result tables. M8 adds a generic comparison command:

```bash
agentperf analyze before.json
agentperf analyze after.json

agentperf compare before.json after.json \
  --quality-tolerance 0.05 \
  --pass-rate-tolerance 0.10
```

## Why Comparison Matters

An optimization is not accepted just because tokens or latency decrease.
AgentPerf also checks whether task quality remains within a configured
tolerance. This keeps the profiler aligned with the M3 lesson: aggressive
context reduction can look good on performance metrics while harming task
correctness.

## Example

GPU-free synthetic replay fixture:

```bash
agentperf compare \
  examples/traces/replay_baseline.json \
  examples/traces/replay_candidate.json \
  --quality-tolerance 0.05 \
  --pass-rate-tolerance 0.10
```

JSON output:

```bash
agentperf compare \
  examples/traces/replay_baseline.json \
  examples/traces/replay_candidate.json \
  --quality-tolerance 0.05 \
  --format json \
  --output comparison.json
```

Optional CI-style guard:

```bash
agentperf compare before.json after.json \
  --quality-tolerance 0.05 \
  --fail-on-quality-regression
```

By default, `compare` does not fail shell scripts for non-accepted verdicts. The
`--fail-on-quality-regression` flag returns a nonzero exit code only when the
candidate violates the configured quality constraint.

## What Is Compared

M8 compares:

- total input and output tokens;
- component-level processed tokens;
- context-growth behavior;
- tool, queue, scheduled-to-first, generation, and client latency where present;
- cached tokens, cache misses, and cache ratio where serving telemetry exists;
- task-level quality and pass rate where metadata exists;
- finding lifecycle.

## Finding Lifecycle

Replay comparison closes the loop between a finding and its validation plan:

```text
baseline finding: TOOL_OUTPUT_BLOAT
expected evidence: tool-result processed tokens decrease
candidate evidence: lower tool-result processing
quality: within tolerance
verdict: ACCEPT
```

When evidence is missing, AgentPerf says so. It does not infer quality or cache
behavior from unrelated signals.

## Limitations

- The comparator is only as reliable as task matching metadata. Multi-task
  workloads should include stable `task_id` or `workload_item_id` values.
- Existing real M3 normalized traces do not embed task-quality metadata, so
  their raw trace-to-trace comparison is performance-informative but acceptance
  is quality-inconclusive.
- P95 values over tiny samples are descriptive, not statistically robust.
- Cache comparison requires real serving telemetry.
- The comparator does not search for globally optimal configurations.
