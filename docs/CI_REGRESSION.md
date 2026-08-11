# CI Regression Guardrails

AgentPerf can compare a stored baseline artifact with a candidate artifact and
turn the result into a CI gate.

```bash
agentperf check baseline/ candidate/ \
  --policy agentperf-regression.yaml
```

Exit codes:

- `0`: policy passed
- `1`: policy failed
- `2`: comparison, artifact, or policy error
- `3`: inconclusive because required evidence is missing

Normal `agentperf compare` behavior is unchanged. Regression exit codes are
only used by `agentperf check`.

For teams with multiple benchmarks, prefer suite-managed checks:

```bash
agentperf suite check benchmarks/research-agent/ candidate-artifact/
```

Suites pin the accepted baseline and policy explicitly. See
[BENCHMARK_SUITES.md](BENCHMARK_SUITES.md).

## Baselines

AgentPerf only needs filesystem paths. Two practical baseline patterns are:

- commit a small baseline artifact under version control;
- download or restore a reviewed baseline artifact in CI.

Baseline updates should be explicit and code-reviewed. AgentPerf never
overwrites a baseline artifact automatically.

## Policy File

Example:

```yaml
schema_version: 1
quality:
  mean_score:
    max_drop: 0.05
  pass_rate:
    max_drop: 0.10
performance:
  provider.input_tokens:
    max_increase_percent: 15
  component.tool_result.processed_tokens:
    max_increase_percent: 15
    min_attribution_coverage: 0.90
  client_latency_p95:
    max_increase_percent: 20
findings:
  fail_on_new_material_findings: true
task_coverage:
  require_same_tasks: true
  allow_partial: false
```

Performance thresholds are opt-in. Quality should usually be configured because
token or latency improvements are not acceptable when task success regresses.
Provider usage metrics and AgentPerf component-attribution metrics can be gated
separately. For example, a scripted model may report unchanged provider input
tokens while AgentPerf sees fewer `component.system.processed_tokens`.

See [REGRESSION_POLICY.md](REGRESSION_POLICY.md) for the full policy semantics.

## Output Formats

Terminal:

```bash
agentperf check baseline/ candidate/ --policy agentperf-regression.yaml
```

JSON:

```bash
agentperf check baseline/ candidate/ \
  --policy agentperf-regression.yaml \
  --format json \
  --output agentperf-check.json
```

Markdown for GitHub step summaries:

```bash
agentperf check baseline/ candidate/ \
  --policy agentperf-regression.yaml \
  --format markdown \
  --output agentperf-summary.md
```

Then append `agentperf-summary.md` to `$GITHUB_STEP_SUMMARY`.

See [CI_REPORTING.md](CI_REPORTING.md) for the reviewer-oriented summary
hierarchy and Markdown presentation details.

## Task Coverage

If a candidate runs fewer tasks than the baseline, AgentPerf reports the
coverage explicitly. Depending on policy, this is either a failure or an
inconclusive result.

This avoids accepting a faster run merely because tasks disappeared.

## Partial And Failed Artifacts

M10 artifacts have `COMPLETE`, `PARTIAL`, and `FAILED` status.

By default:

- `COMPLETE` can pass;
- `PARTIAL` is inconclusive;
- `FAILED` fails.

`allow_partial: true` can be used for exploratory checks, but it should not be
the default for release or PR gating.

## Example GitHub Actions Pattern

See [examples/ci/agentperf-regression.yml](../examples/ci/agentperf-regression.yml).

The example is intentionally offline. It does not require API keys, Runpod, GPU
access, or network storage.

## Limitations

- AgentPerf does not manage remote baseline storage.
- Statistical significance is not inferred from small task sets.
- Missing quality evidence produces an inconclusive result when quality is
  required.
- Component-specific token checks depend on prompt-component attribution. Low
  coverage should be treated cautiously.
- `scheduled_to_first` remains scheduled-to-first-token timing, not pure GPU
  prefill kernel latency.
