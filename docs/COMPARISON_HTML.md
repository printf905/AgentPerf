# Visual Replay Comparison

AgentPerf can render baseline-vs-candidate replay verification as one local
standalone HTML file:

```bash
agentperf compare baseline/ candidate/ \
  --format html \
  --output comparison.html
```

The HTML report is a presentation layer over the existing `agentperf compare`
engine. It does not recompute verdicts, task matching, quality gates,
materiality, finding lifecycle, or regression-policy semantics.

## What The Report Shows

The top of the report shows the replay verdict and reason:

```text
ACCEPT
REJECT QUALITY REGRESSION
REGRESSION
NO MATERIAL CHANGE
INCONCLUSIVE
```

Quality failures visually dominate token or latency improvements. If quality
evidence is unavailable, the report states that performance improvement cannot
be fully accepted.

## Token Accounting

The report keeps token domains separate:

- **Model / provider usage**: input and output tokens reported by the model or
  serving layer.
- **Agent context attribution**: AgentPerf's component-level accounting for
  processed context such as `SYSTEM`, `USER`, `HISTORY`, `TOOL_SCHEMA`,
  `TOOL_RESULT`, `RETRIEVED_CONTEXT`, and `OTHER`.

These values are not expected to always match. They can describe different
telemetry layers.

## Finding Lifecycle

Finding changes are shown using the existing comparison lifecycle:

```text
RESOLVED
IMPROVED
PERSISTENT
REGRESSED
NEW
```

The report prioritizes material new/regressed/resolved findings while still
showing lower-severity structural observations. Drill-down rows show baseline
evidence, candidate evidence, scope, materiality, and severity where recorded.

## Quality And Task Coverage

The quality view shows mean score, pass rate, configured tolerances, task-level
quality changes, and whether the quality gate passed.

The task-matching view shows matched tasks, unmatched baseline tasks, unmatched
candidate tasks, and coverage. If task sets differ, the report makes that
inconclusive coverage risk visible instead of making a partial replay look like
a clean speedup.

## Context Growth And Tool Output

For matched task/run pairs, the report shows step-level context growth where
available.

Tool-output carry-forward is shown as:

- tool-result unique content from tool outputs;
- cumulative downstream processing from repeated prompt-component processing;
- number of reinjected LLM calls.

This distinction explains why repeated downstream processing can drop even when
the underlying tool result still exists.

## Serving Telemetry

If serving telemetry is present, the report shows exact agent LLM call to
serving-request correlation by request ID. If serving evidence is absent, it is
shown as unavailable. Agent-only artifacts remain valid.

Latency labels preserve AgentPerf semantics. In particular,
`scheduled-to-first` is not pure GPU prefill kernel latency.

Cache comparison is shown only when compatible cache telemetry exists. Backend
telemetry differences are not silently normalized.

## Regression Policy HTML

Policy checks can also be rendered into the same visual comparison format:

```bash
agentperf check baseline/ candidate/ \
  --policy agentperf-regression.yaml \
  --format html \
  --output check.html
```

The policy section shows each check, allowed threshold, actual value, and
PASS/FAIL/INCONCLUSIVE result.

## Security

The comparison HTML embeds bounded comparison and policy data. It does not embed
raw prompts, full tool payloads, credentials, or secret-like metadata. IDs,
metrics, safe environment metadata, and provenance are HTML-escaped.

## Limitations

- The report is standalone local HTML, not a hosted dashboard.
- Task/run side-by-side alignment is intentionally simple and uses existing
  task matching. It does not attempt a full semantic trace diff.
- Missing evidence remains unavailable, not zero.
- Hardware/backend differences are surfaced rather than normalized away.
- Manual interpretation is still required for whether a technically valid
  finding is worth optimizing.
