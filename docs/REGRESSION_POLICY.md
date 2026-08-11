# AgentPerf Regression Policy

AgentPerf regression checks compare a baseline artifact with a candidate
artifact using an explicit policy file. The policy decides which deltas are
large enough to fail CI.

The policy separates three concepts.

## Quality Regression

Quality is the hard guard. A candidate that reduces tokens or latency but
violates the configured quality tolerance fails.

```yaml
quality:
  mean_score:
    max_drop: 0.05
  pass_rate:
    max_drop: 0.10
```

Supported quality metrics:

- `mean_score`
- `pass_rate`

These are higher-is-better metrics. `max_drop` is an absolute allowed drop, not
a percent. For pass rate, `0.10` means 10 percentage points.

## Performance Regression

Performance thresholds are opt-in. AgentPerf does not fail CI on small metric
movement unless the policy asks it to.

```yaml
performance:
  provider.input_tokens:
    max_increase_percent: 15
  component.tool_result.processed_tokens:
    max_increase_percent: 15
    min_attribution_coverage: 0.90
    require_attribution_confidence: APPROXIMATE
  client_latency_p95:
    max_increase_percent: 20
```

Supported lower-is-better metrics:

- `provider.input_tokens`
- `provider.output_tokens`
- `component.total.processed_tokens`
- `component.system.processed_tokens`
- `component.user.processed_tokens`
- `component.history.processed_tokens`
- `component.tool_schema.processed_tokens`
- `component.tool_result.processed_tokens`
- `component.retrieved_context.processed_tokens`
- `component.other.processed_tokens`
- `client_latency_p50`
- `client_latency_p95`
- `scheduled_to_first_p50`
- `scheduled_to_first_p95`

Backward-compatible aliases remain valid:

- `input_tokens`
- `output_tokens`
- `tool_result_tokens`
- `provider_input_tokens`
- `provider_output_tokens`
- `component_total_processed_tokens`
- `component_system_tokens`
- `component_user_tokens`
- `component_history_tokens`
- `component_tool_schema_tokens`
- `component_tool_result_tokens`
- `component_retrieved_context_tokens`
- `component_other_tokens`

Policy reports include an `accounting_source` field for performance checks so
reviewers can distinguish provider usage from AgentPerf component attribution.
Unknown performance metric names fail policy parsing instead of being silently
ignored.

Each metric supports:

- `max_increase_percent`
- `max_increase_absolute`

If both are supplied, both must pass.

Component-attributed token metrics also support:

- `min_attribution_coverage`
- `require_attribution_confidence`: `APPROXIMATE` or `STRUCTURED`

If these requirements are configured and the comparison lacks sufficiently
classified component attribution, the check is `INCONCLUSIVE`. `STRUCTURED` is
stricter than `APPROXIMATE`.

See [TOKEN_ACCOUNTING.md](TOKEN_ACCOUNTING.md) for provider/component accounting
semantics, coverage, and attribution confidence.

## Finding Regression

Finding checks use AgentPerf finding lifecycle data. They are materiality-aware:
LOW observations such as `CROSS_RUN_SHARED_SCAFFOLD` do not fail a material
finding policy.

```yaml
findings:
  fail_on_new_material_findings: true
  fail_on_regressed_material_findings: true
```

Material findings are those marked with `materiality: MATERIAL` or equivalent
actionable evidence. Findings explicitly marked `OBSERVATION`, `HEADROOM`, or
`CACHEABILITY_HEADROOM` are not treated as material failures.

## Task Coverage

Task coverage prevents a candidate from looking faster because it silently ran
fewer tasks.

```yaml
task_coverage:
  require_same_tasks: true
  minimum_task_coverage: 0.90
  allow_partial: false
```

`PARTIAL` or `FAILED` artifacts do not pass by default.

## Versioning

Use:

```yaml
schema_version: 1
```

Unknown policy schema versions fail clearly rather than being interpreted
silently.
