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
| 10 | 0.032 MB | 1.9 ms | 4.5 ms | 9.0 ms | 7.7 ms | 15.4 ms | 0.033 MB | 0.026 MB | 0.2 MB |
| 100 | 0.250 MB | 9.3 ms | 33.5 ms | 63.5 ms | 98.9 ms | 102.4 ms | 0.173 MB | 0.042 MB | 1.2 MB |
| 500 | 1.225 MB | 36.1 ms | 157.1 ms | 290.3 ms | 987.3 ms | 488.1 ms | 0.802 MB | 0.110 MB | 5.7 MB |
| 1,000 | 2.443 MB | 77.5 ms | 329.3 ms | 560.6 ms | 4,515.8 ms | 1,059.8 ms | 1.589 MB | 0.196 MB | 11.3 MB |
| 5,000 | 12.230 MB | 416.8 ms | 1,931.1 ms | 3,528.9 ms | 96,044.9 ms | 4,941.1 ms | 7.941 MB | 0.904 MB | 57.2 MB |

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
| 5,000 | 42,906.6 ms | 10.727 MB | 64 | 618.1 ms | 1,175.7 ms | 1,266.0 ms | 101.5 ms | 177.4 ms | 99.4 ms | 43.4 MB |
| 10,000 | 170,169.0 ms | 21.472 MB | 128 | 1,248.1 ms | 2,523.6 ms | 3,432.4 ms | 230.3 ms | 463.5 ms | 340.5 ms | 84.2 MB |

## Findings

- Load, analyze, compare, doctor, and comparison HTML remained usable through
  the 5,000-call local fixture.
- Single-run HTML generation is the clearest local scalability limitation in
  this audit: 5,000 calls took roughly 96 seconds on the audited host.
- Checkpointing is reliable but currently writes a full recoverable artifact.
  High-frequency checkpoints at 10,000 spans are expensive and should be tuned
  by users with larger intervals for long-running local capture.

## Classification

No P0/P1 reliability issue was found. The 5,000-call single-run HTML cost and
high-frequency full-artifact checkpoint cost are P2 scalability limitations for
large local captures.
