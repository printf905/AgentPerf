# CI Reporting

M15 improves AgentPerf's human-readable regression output for PR review. The
goal is to let a reviewer identify the important result in seconds, while JSON
continues to expose the full machine-readable structure.

## Summary Hierarchy

Terminal and Markdown reports now lead with:

1. final result;
2. quality status;
3. task coverage;
4. biggest performance or component-token improvements;
5. biggest configured regressions;
6. provider/component accounting note when relevant;
7. finding regression summary;
8. changed tasks when quality regresses and task rows are available.

Detailed check tables remain below the summary.

## Quality First

Quality failures are promoted as `QUALITY REGRESSION` before performance
improvements. This keeps AgentPerf from visually rewarding a candidate that
reduces tokens or latency by breaking the task.

Example:

```text
Result: FAIL

Summary
------------------------------------------------------------
QUALITY REGRESSION: mean_score: 1.000 -> 0.500, -50.0%, allowed 0.05
Task coverage: 1 matched
Biggest improvements: input_tokens: 1000 -> 200, -80.0%
```

## Component Attribution Presentation

Component metrics are ranked by meaningful movement instead of being treated as
equally important in the summary. Full component details remain available in
the detailed comparison output and JSON.

For the M13 dogfooding suite, the summary surfaces the important distinction:

```text
Provider input tokens: 1604 -> 1604
component.system.processed_tokens: 680 -> 520, -23.5%
Accounting note: provider-reported usage is unchanged, but AgentPerf observed
component-level context movement.
```

The note does not claim either accounting source is wrong. Provider usage is
what the backend/client reported; component attribution is AgentPerf's view of
agent prompt/context structure.

## Findings

Finding summaries prioritize new or regressed material findings. LOW
observations such as cross-run shared scaffold do not become material failures
unless the regression policy says so through materiality-aware finding checks.

Detailed lifecycle data remains in `agentperf compare`.

## Task-Level Triage

When artifact task rows show changed task outcomes or quality scores,
regression summaries list only changed tasks. Unchanged tasks are omitted to
keep PR output compact.

## Multi-Suite Output

`agentperf suite check-all` keeps a concise suite table and adds a triage
section only when at least one suite fails or is inconclusive:

```text
Suite                              Result
------------------------------------------------------------
research-agent                     PASS
support-triage                     PASS
mini-swe-local-repair              FAIL

Overall: FAIL

Failed/Inconclusive Suites
------------------------------------------------------------
mini-swe-local-repair              pass_rate: 1.0 -> 0.8, allowed 0.1
```

## Markdown

Markdown output is intended for `$GITHUB_STEP_SUMMARY`. It uses short headings,
compact bullets, and detailed tables. It does not require a dashboard or GitHub
App.

Example:

```bash
agentperf suite check benchmarks/support-triage candidate/ \
  --format markdown \
  --output agentperf-summary.md
cat agentperf-summary.md >> "$GITHUB_STEP_SUMMARY"
```

## JSON Compatibility

JSON output is intentionally not reorganized around presentation. It still
returns stable structured fields such as:

- `status`
- `checks`
- `warnings`
- `metadata`

Presentation filtering does not affect PASS / FAIL / INCONCLUSIVE semantics.

## Limitations

- The summary is a triage layer, not statistical significance analysis.
- Task-level triage depends on task rows being present in artifacts.
- Component ranking hides tiny changes from the summary, but full details remain
  in JSON and detailed sections.
