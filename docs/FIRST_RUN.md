# First Run: Inspect, Report, Compare, Check

This path is for a first-time user who wants useful AgentPerf output without a
GPU, API key, model download, serving backend, or knowledge of AgentPerf
internals.

It uses committed local fixtures and artifacts.

## 1. Inspect One Trace

```bash
agentperf analyze examples/traces/multi_problem_agent.json
```

This input is a synthetic trace fixture, not a benchmark result. It is useful
because it contains related agent-context, cacheability, and serving-timing
signals in one small file.

Look for:

- `Agent trace input tokens`: input represented in the normalized agent trace;
- `Context Growth`: per-LLM prompt growth, here `80`, `91`, `99`;
- `Metric Provenance`: where each potentially confusing number came from;
- `Investigations`: grouped evidence across related findings;
- `Materiality evaluation`: which gates were exceeded and which were not.

The trace intentionally demonstrates why different token metrics can coexist:

| Metric | Source | Value |
| --- | --- | ---: |
| Agent trace step input tokens | normalized LLM prompt components | 80 / 91 / 99 |
| Agent trace total input tokens | sum over LLM calls | 270 |
| Cacheability average input tokens | mean over correlated LLM prompts | 90 |
| Serving request input P95 tokens | serving request telemetry | 596 |
| Serving uncached prompt P95 tokens | serving cache-miss telemetry | 497 |

These are not the same accounting source. AgentPerf now labels them separately
instead of relying on a generic "input tokens" label.

The same trace also shows conservative materiality:

```text
TTFT gate: exceeded
Serving uncached prompt-volume gate: not exceeded
Overall: OBSERVATION / HEADROOM
```

High TTFT is present, but AgentPerf does not label this as a proven
context-driven operational bottleneck unless the configured serving
uncached-token gate is also exceeded.

## 2. View The Local Profiler Report

```bash
agentperf report \
  examples/artifacts/m3_raw_full \
  --output agentperf-report.html
```

Open `agentperf-report.html` locally. The HTML report is standalone and
offline.

Use it to inspect:

- execution timeline;
- prompt component attribution;
- context growth;
- tool-output carry-forward;
- findings and provenance;
- serving telemetry where recorded.

## 3. Compare An Optimization Replay

```bash
agentperf compare \
  examples/artifacts/m3_raw_full \
  examples/artifacts/m3_dedup_only
```

This compares two preserved M3 controlled research-agent artifacts.

The story is:

```text
inspect
-> identify repeated tool-result processing
-> change agent context behavior
-> replay the same workload
-> observe lower processing/latency
-> verify quality remains within tolerance
-> ACCEPT
```

This is one controlled workload, not a universal performance claim.

## 4. Enforce A Regression Policy

```bash
agentperf check \
  examples/artifacts/m3_raw_full \
  examples/artifacts/m3_dedup_only \
  --policy examples/policies/m3-context-regression.yaml
```

This applies an explicit quality/performance policy. A candidate with lower
tokens but unacceptable quality should fail.

## What You Should Understand After This

- A trace tells AgentPerf what happened.
- An artifact also stores task quality, findings, environment metadata, and
  summary data.
- Agent trace tokens, provider usage tokens, component-attributed tokens, and
  serving tokens can differ.
- Findings are deterministic conclusions from evidence and thresholds.
- Investigations group related evidence without claiming causality.
- Replay verification checks whether a change helped without breaking quality.

## Next

- Add AgentPerf to your own agent:
  [BRING_YOUR_OWN_AGENT.md](BRING_YOUR_OWN_AGENT.md)
- Understand token semantics:
  [TOKEN_ACCOUNTING.md](TOKEN_ACCOUNTING.md)
- Understand HTML report sections:
  [HTML_REPORT.md](HTML_REPORT.md)
