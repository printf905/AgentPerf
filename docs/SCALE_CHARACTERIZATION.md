# AgentPerf Scale Characterization

Audit date: 2026-08-16

Commit measured: `258e0e3a299d7d440aefed2632e5e7c23f74ef21`

AgentPerf version: `0.4.0`

Environment:

- OS: macOS 14.4.1
- Architecture: arm64
- Python: 3.14.6 for this local smoke
- Measurement method: existing `scripts/m21_scale_benchmark.py`
- Warmups: 1
- Repetitions: 2
- Memory: Python `tracemalloc` peak allocations during measured callable

These measurements are local engineering characterization only. They are not a
production-scale claim, SLA, or distributed-ingestion validation.

## Current Smoke Grid

The hardening pass reran deterministic synthetic fixtures at 10, 100, 500, and
1,000 LLM calls. Each fixture used task-grouped spans, component attribution,
tool calls, quality results, and portable artifact bundles.

| LLM calls | Tasks | Artifact bytes | Analyze median | Doctor median | Single-run HTML median | HTML bytes | Peak alloc, analyze |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1 | 61,054 | 11.5 ms | 2.2 ms | 19.4 ms | 49,686 | 0.35 MB |
| 100 | 10 | 590,597 | 112.0 ms | 10.4 ms | 167.6 ms | 249,441 | 3.30 MB |
| 500 | 50 | 2,972,438 | 564.5 ms | 47.3 ms | 912.6 ms | 1,147,259 | 16.45 MB |
| 1,000 | 100 | 5,951,952 | 1,191.5 ms | 96.3 ms | 1,791.0 ms | 2,269,675 | 32.90 MB |

## Compare and Check

The same benchmark measured baseline/candidate comparison pairs.

| Candidate scale | Tasks | LLM calls per side | Artifact bytes per baseline | Compare median | Check median | Peak alloc |
|---:|---:|---:|---:|---:|---:|---:|
| Small | 1 | 5 | 32,728 | 15.2 ms | 15.2 ms | 0.26 MB |
| Medium | 10 | 50 | 306,541 | 114.3 ms | 114.7 ms | 2.35 MB |
| Large | 100 | 500 | 3,081,796 | 1,159.7 ms | 1,159.3 ms | 23.35 MB |

## Comparison HTML

The existing M21 harness does not time comparison HTML directly, so this audit
measured one deterministic 1,000-call baseline/candidate pair separately.

| LLM calls per side | Tasks | Comparison HTML time | HTML bytes | Peak alloc |
|---:|---:|---:|---:|---:|
| 1,000 | 100 | 2,595.8 ms | 226,883 | 14.95 MB |

## Prior M21 Operating Range

M21 remains the broader scale characterization source. It validated local
engineering behavior up to:

- 500 tasks
- 5,000 LLM calls
- 1,000 tool calls
- approximately 18.6 MB component text
- 30.1 MB artifact size
- 8.47 seconds median analyze latency
- 844 ms median doctor latency

HTML report generation in M21 was characterized through 1,000 calls, not 5,000.
Comparison/check were characterized through 100 tasks and 500 calls per side.

## Interpretation

At the 10 to 1,000 call smoke range, artifact size, analyze latency, doctor
latency, report latency, and memory all grew roughly with recorded event and
payload volume. No new obvious O(n^2) behavior was observed in this smoke.

The dominant local costs remain:

- artifact JSON load/parse;
- component token attribution;
- detector analysis over recorded calls/components;
- standalone HTML generation proportional to rendered evidence.

## Limits

Not tested here:

- millions of spans;
- concurrent production ingestion;
- multiple writer processes;
- distributed trace collection;
- browser UX for very large HTML reports;
- GPU kernel or hardware-counter profiling.

Large trace behavior should be described as a tested local engineering range,
not a maximum supported production scale.
