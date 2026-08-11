# Local HTML Profiler Report

M16 adds a standalone local HTML report for inspecting one AgentPerf execution
artifact or normalized trace.

```bash
agentperf report examples/artifacts/m3_dedup_only --output agentperf-report.html
```

The output is one self-contained HTML file with inline CSS, inline JavaScript,
and embedded report metadata. It does not require npm, a web server, a CDN, API
keys, GPU access, or remote storage.

## Supported Inputs

Preferred input:

- an `ExperimentArtifact` directory containing `manifest.json`, `trace.json`,
  task rows, quality metrics, findings, environment metadata, and summary data.

Fallback input:

- normalized raw AgentPerf trace JSON.

Raw traces may not contain task quality, persisted findings, environment
metadata, or serving telemetry. The report shows explicit "not recorded" or
"No ... recorded" states instead of treating missing optional data as an error.

## Report Sections

The report includes:

- overview: workload/run identity, status, framework, backend, model, task
  count, LLM/tool calls, provider usage, component-attributed processed tokens,
  quality if available, duration if available, and material finding count;
- task list: task status, pass/fail, quality score, token counts, latency, and
  linked AgentRun IDs;
- execution timeline: per-run LLM/tool steps, rendered in order and with
  duration bars when timing exists;
- step drill-down: IDs, model, request IDs, token counts, component attribution,
  tool metadata, and serving correlation;
- token attribution: provider usage versus AgentPerf component attribution,
  per-component processed and unique counts, coverage, and confidence;
- context growth: prompt size across LLM steps;
- tool-output carry-forward: unique tool output versus cumulative downstream
  processed contribution where provenance exists;
- findings: severity, materiality, scope, evidence, recommendation, validation
  plan, and provenance links;
- serving telemetry: queue time, scheduled-to-first, generation time, cache
  counts, and exact request correlation where recorded;
- environment: collapsible reproducibility metadata.

## Timeline Semantics

AgentPerf keeps execution boundaries explicit.

Multiple independent AgentRuns are rendered as separate run groups. The report
does not merge independent tasks into one synthetic timeline. When timestamps
or latency fields exist, the timeline uses relative bars. When timing is
missing, the report preserves execution order without inventing durations.

## Token Accounting

The report follows the M14 accounting model:

- **MODEL-PROVIDER USAGE**: input/output tokens reported by the provider,
  backend, or client instrumentation.
- **AGENTPERF COMPONENT ATTRIBUTION**: AgentPerf's attribution of prompt/context
  processing to `system`, `user`, `history`, `tool_schema`, `tool_result`,
  `retrieved_context`, and `other`.
- **UNIQUE CONTENT**: content counted once conceptually.
- **CUMULATIVE PROCESSED CONTENT**: content counted each time it is processed by
  an LLM call.

These values can differ. For example, a scripted provider may report unchanged
aggregate input tokens while AgentPerf component attribution sees a shorter
system instruction.

## Serving Correlation

When serving telemetry is present, the report shows exact LLM-call to serving
request correlation through propagated request IDs.

```text
Agent LLM call -> llm_request_id -> vLLM serving request
```

No timestamp fuzzy matching is used. Missing serving telemetry or missing
correlation is shown as missing evidence, not inferred.

Scheduled-to-first-token is labeled as serving-path timing evidence. It is not
described as pure GPU prefill kernel time.

## Findings And Provenance

Findings are ordered by materiality and severity. A finding card includes the
detector ID, severity, materiality/scope evidence where available, affected
spans, structured evidence, recommendation, validation plan, and provenance
links to LLM calls when possible.

The report preserves current AgentPerf materiality principles:

- dominant does not necessarily mean material;
- repeated does not automatically mean removable;
- headroom is not automatically an actionable bottleneck.

## Security / Redaction

The default report does not dump full raw prompts, full user messages, or full
tool outputs. It shows:

- IDs;
- token counts;
- component names;
- bounded metadata;
- hashes/identifiers where already present in the trace;
- provenance.

Metadata keys that look credential-like, such as `api_key`, `token`,
`secret`, `password`, or `private_key`, are redacted. HTML is escaped before
rendering.

Because the report is a local file generated from local trace data, users
should still treat it as potentially sensitive if their trace metadata contains
private identifiers.

## Large Trace Behavior

The report is designed for moderate local traces. Task and run groups are
collapsible, and raw payloads are not expanded by default. It is not optimized
for millions of spans.

## Limitations

- It is a static local report, not a hosted dashboard.
- It does not add new detectors or generate LLM-written explanations.
- It cannot show serving telemetry that was not recorded.
- It cannot recover task quality if the input is only a raw trace.
- It is intentionally conservative about raw content display.
