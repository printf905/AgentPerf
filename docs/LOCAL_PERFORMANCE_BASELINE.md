# Local Performance Baseline

Date: 2026-08-16

Audited commit: `1efe59f`

This file records a deterministic local characterization run. It is not a
production benchmark and should not be used as hardware-independent performance
evidence.

Reproducer:

```bash
python scripts/deep_reliability_local_baseline.py
python scripts/deep_reliability_local_baseline.py --checkpoint-stress --sizes 5000 10000
```

## Artifact Operation Baseline

Synthetic fixture shape:

- one artifact run;
- component-attributed LLM calls;
- serving telemetry;
- one matching task result;
- baseline and candidate differ in tool-result carry-forward frequency.

| LLM calls | Artifact size | Load | Analyze | Compare | Single HTML | Comparison HTML | HTML size | Comparison HTML size | Peak Python allocation |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 0.032 MB | 2.9 ms | 7.1 ms | 14.2 ms | 11.9 ms | 24.5 ms | 0.033 MB | 0.026 MB | 0.2 MB |
| 100 | 0.250 MB | 12.6 ms | 46.5 ms | 88.4 ms | 72.8 ms | 149.9 ms | 0.173 MB | 0.042 MB | 1.2 MB |
| 500 | 1.225 MB | 56.6 ms | 249.5 ms | 445.0 ms | 362.9 ms | 744.1 ms | 0.802 MB | 0.110 MB | 5.7 MB |
| 1,000 | 2.443 MB | 113.8 ms | 454.2 ms | 887.4 ms | 913.6 ms | 1,703.5 ms | 1.589 MB | 0.196 MB | 11.3 MB |
| 5,000 | 12.230 MB | 575.0 ms | 2,541.6 ms | 4,796.7 ms | 5,213.3 ms | 8,317.0 ms | 7.941 MB | 0.904 MB | 57.2 MB |

## Checkpoint Capture Stress

Synthetic fixture shape:

- framework-free local capture;
- `checkpoint_interval=250`;
- one LLM call per task;
- one tool call every five tasks;
- task quality recorded for every task;
- no HTML rendering in the stress loop.

| Completed spans/tasks | Capture runtime | Final artifact size | Checkpoints | Checkpoint P50 | Checkpoint P95 | Checkpoint max | Load | Analyze | Doctor | Peak Python allocation |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5,000 | 71,740.0 ms | 10.724 MB | 64 | 1,034.5 ms | 1,921.4 ms | 2,401.7 ms | 493.8 ms | 1,112.1 ms | 532.3 ms | 43.2 MB |
| 10,000 | 279,668.8 ms | 21.466 MB | 128 | 2,195.3 ms | 3,926.6 ms | 4,613.3 ms | 1,005.4 ms | 2,384.9 ms | 1,113.2 ms | 83.7 MB |

## Findings

- Load, analyze, compare, doctor, single-run HTML, and comparison HTML remained
  usable through the 5,000-call local fixture.
- A validation-marathon renderer fix changed single-run HTML scope lookup from
  repeated linear scans to one call-scope index per report. In the profiled
  1,000-call run, single-run HTML generation dropped from roughly 8.1 seconds
  to roughly 1.3 seconds; in the 5,000-call baseline it measured 5.2 seconds.
- Checkpointing is reliable but currently writes a full recoverable artifact.
  High-frequency checkpoints at 10,000 spans are expensive and should be tuned
  by users with larger intervals for long-running local capture.

## Classification

No P0/P1 reliability issue was found. High-frequency full-artifact checkpoint
cost remains a P2 scalability limitation for large local captures.
