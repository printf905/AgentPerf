# M18 Profiler Credibility Engineering Note

M18 focuses on making existing AgentPerf output trustworthy and understandable
for first-time users. It does not add a new backend, framework, detector family,
dashboard, storage system, or optimization axis.

## Dogfooding Observation

Manual post-release usage of:

```bash
agentperf analyze examples/traces/multi_problem_agent.json
```

surfaced a confusing report shape.

Agent-level values were internally intuitive:

```text
Context growth: 80 / 91 / 99
Run input tokens: 270
Cacheability average input tokens: 90
```

But a serving finding also reported:

```text
p95 input tokens: 596
p95 uncached input tokens: 497
```

The values were not wrong, but they came from a different telemetry layer. The
old report did not make that obvious.

The same output showed:

```text
TTFT P95: 1037 ms
TTFT threshold: 100 ms
uncached prompt threshold: 1000 tokens
finding severity: LOW
```

The detector intentionally required both high TTFT and high serving uncached
prompt volume, but the prose did not clearly explain which gate failed.

## Metric Provenance Audit

For `examples/traces/multi_problem_agent.json`:

| Metric | Source field | Values | Aggregation | Result |
| --- | --- | --- | --- | ---: |
| Agent trace input tokens | LLM prompt components | 80 / 91 / 99 | sum | 270 |
| Cacheability average input tokens | correlated LLM prompt components | 80 / 91 / 99 | mean | 90 |
| Serving request input tokens | `ServingRequest.input_tokens` | 520 / 560 / 600 | P95 | 596 |
| Serving cached prompt tokens | `prefix_cache_hit_tokens` | 80 / 90 / 100 | sum | 270 |
| Serving uncached prompt tokens | `prefix_cache_miss_tokens` | 440 / 470 / 500 | P95 | 497 |
| TTFT | `ServingRequest.ttft_ms` | 980 / 1010 / 1040 ms | P95 | 1037 ms |

AgentPerf's percentile implementation sorts the sample and linearly
interpolates:

```text
rank = (n - 1) * p
```

For three values, P95 uses rank `1.9`:

```text
[520, 560, 600] -> 560 * 0.1 + 600 * 0.9 = 596
[440, 470, 500] -> 470 * 0.1 + 500 * 0.9 = 497
[980, 1010, 1040] -> 1010 * 0.1 + 1040 * 0.9 = 1037
```

## Classification Of The Original Issue

| Suspicious item | Classification | Resolution |
| --- | --- | --- |
| Agent trace tokens 80-99 beside serving P95 596 | Reporting ambiguity | Added metric provenance and source-layer labels. |
| `TTFT > threshold` while finding is LOW | Reporting ambiguity | Added materiality gates and explicit reason. |
| `prefill_path_latency_ms` raw provenance duplicated selected true prefill values | Semantic provenance bug fixed before M18 | Raw provenance now preserves actual fields plus selected prefill-or-path latency. |
| Synthetic fixture has agent/serving token mismatch | Intentional test construction | Kept fixture; labels now explain layer differences. |

No detector threshold was changed.

## Final Metric Semantics

Terminal reports now distinguish:

- `Agent trace input tokens`
- `component processed tokens`
- `serving request input p95 tokens`
- `serving uncached prompt p95 tokens`
- `serving ttft p95 ms`

The new `Metric Provenance` section records:

- metric name;
- value;
- unit;
- source layer;
- source field;
- aggregation;
- semantic meaning;
- availability.

Source layers currently include:

- `agent_trace`
- `provider_usage`
- `agentperf_component_attribution`
- `serving_backend`
- `client_streaming`
- `derived`

## Materiality Decision Semantics

`PREFILL_PATH_DOMINANCE` remains LOW for the synthetic trace because the detector
requires:

```text
TTFT P95 >= 100 ms
AND
serving uncached prompt P95 >= 1000 tokens
```

Observed:

```text
TTFT gate: 1037 ms >= 100 ms -> EXCEEDED
Serving uncached prompt-volume gate: 497 tokens >= 1000 tokens -> NOT_EXCEEDED
Overall: OBSERVATION
```

This preserves the existing principle:

```text
dominant != material
```

The report now states that high latency is present, but current evidence does
not establish material context-driven prefill cost under the configured rule.

## Investigation Chain Design

M18 adds a deterministic grouping layer for related findings. It does not
replace individual findings and does not use an LLM.

The first supported investigation is:

```text
Repeated static context and cacheability
```

It groups:

- `CONTEXT_DUPLICATION`
- `CACHEABILITY_HEADROOM` or `MATERIAL_PREFIX_CACHE_OPPORTUNITY`
- `PREFILL_PATH_DOMINANCE` or `MATERIAL_PREFILL_BOTTLENECK`

The investigation separates:

- facts directly observed;
- interpretation;
- evidence strength;
- assessment;
- recommended replay experiment.

It deliberately says that related findings are not causal proof.

## Improved Textual Example

The improved report includes:

```text
Metric Provenance
------------------------------------------------------------
agent trace step input tokens      [80, 91, 99] tokens  agent_trace
serving request input p95 tokens   596.0 tokens  serving_backend
serving uncached prompt p95 tokens 497.0 tokens  serving_backend

Investigations
------------------------------------------------------------
Repeated static context and cacheability
...
Assessment:
  Cacheability and prefill-path headroom are observed, but a context-driven
  operational bottleneck is not proven under current materiality rules.

Materiality evaluation:
TTFT gate                          observed=1037.0 ms; threshold=100.0 ms; result=EXCEEDED
Serving uncached prompt-volume gate observed=497 tokens; threshold=1000 tokens; result=NOT_EXCEEDED
```

## HTML Report Changes

The local HTML report now includes:

- `Metric Provenance`;
- `Investigations`;
- materiality-gate details inside finding cards.

The HTML report continues to redact raw prompt/tool payloads by default and does
not add a dashboard or external frontend dependency.

## Validation Commands

Dogfooding commands:

```bash
agentperf analyze examples/traces/multi_problem_agent.json
agentperf report examples/artifacts/m3_raw_full --output /tmp/agentperf-m18-raw.html
agentperf compare examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only
agentperf check examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only \
  --policy examples/policies/m3-context-regression.yaml
```

Quality gates:

```bash
pytest
ruff check .
mypy agentperf tests scripts
git diff --check
```

## Limitations And Remaining Work

- Investigation grouping is intentionally small and explicit. It currently
  covers the repeated-context/cacheability/prefill-path chain.
- The terminal report favors clarity over compactness; very large evidence
  sections may still be verbose.
- Metric provenance is not a full observability schema. It records the metrics
  most likely to be confused in current AgentPerf reports.
- Synthetic fixtures remain synthetic. They are useful for detector semantics,
  not public benchmark claims.
