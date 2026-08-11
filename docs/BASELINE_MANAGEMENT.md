# Baseline Management

A baseline is a reviewed AgentPerf artifact that defines the current expected
behavior for one benchmark suite.

It is not a cache of the latest run, and it should not be updated automatically
to erase regressions.

## Team Workflow

1. Store or reference a reviewed baseline artifact.
2. Store a regression policy next to the suite.
3. Generate a candidate artifact in CI or locally.
4. Run `agentperf suite check`.
5. Review the Markdown/JSON evidence.
6. If expectations intentionally change, generate a baseline proposal and
   review it like code.

## Example

```bash
agentperf suite validate benchmarks/research-agent/
agentperf suite check benchmarks/research-agent/ runs/candidate/
agentperf suite propose-baseline benchmarks/research-agent/ runs/candidate/ \
  --output baseline-proposal.md
```

## Baseline Updates

Baseline updates are explicit. `agentperf suite propose-baseline` produces a
report comparing the current baseline against the candidate. It does not modify
`suite.yaml`, copy artifacts, or overwrite the baseline path.

A new baseline represents a deliberate change in expectations:

- task set changed;
- evaluator changed;
- model/backend changed;
- a performance trade-off was accepted;
- a quality threshold was intentionally revised.

Do not use baseline replacement as a way to bypass CI.

## Task-Set Changes

Suites can record a task-set fingerprint derived from sorted stable task IDs.
If a candidate uses a different task set, the suite check reports it.

If the benchmark intentionally changes tasks, update `suite_version` and review
the new baseline.

## Environment Compatibility

Latency thresholds are meaningful only when environments are comparable. If a
baseline was recorded on one GPU/backend/model and the candidate on another,
AgentPerf warns or returns `INCONCLUSIVE` for latency-sensitive checks.

Token and quality comparisons may still be valid, but latency should not be
treated as hardware-independent.

## CI

The filesystem-only pattern is:

```bash
agentperf suite check benchmarks/research-agent/ candidate-artifact/ \
  --format markdown \
  --output agentperf-summary.md
cat agentperf-summary.md >> "$GITHUB_STEP_SUMMARY"
```

AgentPerf does not need a database, hosted registry, API key, Runpod resource,
or object-store integration for this workflow.

## Limitations

- No remote artifact registry.
- No automatic baseline approval.
- No multi-hardware baseline matrix.
- No statistical significance inference.
- Historical artifacts without task rows cannot produce strict task-set
  fingerprints.
