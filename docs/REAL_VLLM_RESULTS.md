# Real vLLM Validation Results

Status: one live Runpod/vLLM execution completed on 2026-08-09 UTC.

These are small-sample engineering validation results, not benchmark claims.
They should be used to calibrate AgentPerf's telemetry assumptions and next
experiment design.

## Environment

- Pod ID: `1mafvnkj7kukls`
- GPU: NVIDIA RTX A5000, 24 GB VRAM
- Runpod price: `$0.27/hr`
- Runpod image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `580.159.04`
- `nvidia-smi` CUDA label: `13.0`
- Installed torch: `2.11.0+cu129`
- Torch CUDA runtime: `12.9`
- Installed vLLM: `0.26.0+cu129`
- Model: `Qwen/Qwen3-0.6B`, downloaded to `/workspace/models/Qwen3-0.6B`
- vLLM flags included `--enable-prefix-caching`,
  `--enable-prompt-tokens-details`, and `--enable-per-request-metrics`.

The CUDA preflight succeeded:

```text
2.11.0+cu129 12.9
NVIDIA RTX A5000
tensor([1.], device='cuda:0')
```

## Protocol

- Warmups: 3 repetitions per configuration
- Measured repetitions: 10 per configuration
- Measured requests: 30 per configuration
- Baseline: `baseline_inefficient`
- Optimized: `improved_stable_prefix`
- Sampling: `temperature=0`, `max_tokens=64`

The vLLM smoke test passed and confirmed response IDs, prompt/completion token
counts, prompt token IDs, generated token IDs, per-request timing metrics, and
prompt-token cache details.

## Results

| Metric | Baseline | Optimized |
| --- | ---: | ---: |
| Measured requests | 30 | 30 |
| Input tokens | 48,120 | 47,970 |
| Output tokens | 1,920 | 1,920 |
| Cached-token ratio | 99.75% | 99.40% |
| Cached tokens | 48,000 | 47,680 |
| Cache miss tokens | 120 | 290 |
| Queue latency P50 | 0.036 ms | 0.036 ms |
| Queue latency P95 | 0.045 ms | 0.044 ms |
| Scheduled-to-first-token P50 | 15.04 ms | 14.99 ms |
| Scheduled-to-first-token P95 | 16.56 ms | 16.23 ms |
| Generation latency P50 | 191.67 ms | 192.37 ms |
| Generation latency P95 | 193.28 ms | 193.89 ms |
| TPOT / ITL P50 | 3.04 ms | 3.05 ms |
| TPOT / ITL P95 | 3.07 ms | 3.08 ms |
| Client-observed latency P50 | 231.79 ms | 232.75 ms |
| Client-observed latency P95 | 235.98 ms | 234.67 ms |

## AgentPerf Findings

Baseline findings:

- `CONTEXT_DUPLICATION`
- `PREFILL_BOTTLENECK`

Optimized findings:

- `CONTEXT_DUPLICATION`
- `PREFILL_BOTTLENECK`

`PREFIX_CACHE_OPPORTUNITY` did not fire for either configuration. This was the
correct behavior for the observed telemetry: both configurations achieved very
high cached-token ratios.

## Interpretation

The hoped-for M2 story did not hold for this workload:

```text
baseline low cache reuse -> AgentPerf prefix-cache finding -> prompt reorder -> higher cache reuse
```

Instead, vLLM reported high cache reuse for both baseline and optimized layouts.
The developer-level prefix reorganization did not materially improve serving
behavior in this run.

This result is still useful:

- the CUDA/vLLM environment is now validated;
- explicit request correlation worked for real vLLM responses;
- AgentPerf consumed real per-request vLLM telemetry without detector-specific
  backend code;
- the prefix-cache detector avoided a false positive when actual cache reuse was
  high;
- the workload design is not sufficient to demonstrate a prefix-cache failure.

## Quality Notes

The runner records model outputs but does not grade task quality. Manual spot
inspection showed Qwen returned `<think>` reasoning text and often used the full
64-token output cap instead of returning the requested compact JSON. Therefore
this run should not be used to claim task-quality preservation.

## Artifact Location

The compressed artifact bundle was copied off the Pod before cleanup:

```text
artifacts/runpod/agentperf-real-vllm-a5000-20260809.tgz
```

The bundle contains setup logs, smoke-test artifacts, raw vLLM recordings,
normalized AgentPerf traces, terminal reports, and `comparison.json`.

## Calibration Consequences

No detector thresholds were changed from this single run.

Immediate calibration concerns:

- `PREFILL_BOTTLENECK` fired even though absolute scheduled-to-first-token
  latency was low, around 15-17 ms. The detector currently weighs prefill-path
  fraction and input length more than absolute TTFT impact.
- The baseline workload's "dynamic before stable context" layout did not produce
  low vLLM cached-token ratio. Either the workload failed to defeat exact cache
  reuse, or vLLM's `cached_tokens` semantics are broader than the initial
  prefix-only intuition.
- The next real experiment should first construct a minimal request pair that
  proves how vLLM `cached_tokens` changes when the first cache block differs.
