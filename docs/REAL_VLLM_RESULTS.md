# Real vLLM Validation Results

Status: two live Runpod/vLLM executions completed on 2026-08-09 UTC.

These are small-sample engineering validation results, not benchmark claims.
They should be used to calibrate AgentPerf's telemetry assumptions and next
experiment design.

## Run 2: Prefix-Cache Diagnosis, Recommendation, Replay

This run used the cache-semantics ground truth from
`docs/VLLM_PREFIX_CACHE_SEMANTICS.md` to build a controlled AgentPerf workload
with a real cacheability contrast.

### Environment

- Pod ID: `9gbncdleolts6f`
- GPU: NVIDIA RTX A5000, 24 GB VRAM
- Runpod price: `$0.27/hr`
- Runpod image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `580.159.04`
- `nvidia-smi` CUDA label: `13.0`
- Installed torch: `2.11.0+cu129`
- Torch CUDA runtime: `12.9`
- Installed vLLM: `0.26.0+cu129`
- Model: `Qwen/Qwen3-0.6B`, downloaded to `/workspace/models/Qwen3-0.6B`
- vLLM max model length: `12288`
- vLLM flags included `--enable-prefix-caching`,
  `--enable-prompt-tokens-details`, and `--enable-per-request-metrics`.
- AgentPerf commit: `df8d00557ff9000f27fc389186ea68a2cda561ab`

The CUDA preflight succeeded:

```text
2.11.0+cu129 12.9
NVIDIA RTX A5000
tensor([1.], device='cuda:0')
```

### Protocol

- Stable context target: about 8K tokens
- Stable context observed by vLLM tokenizer: 7,840 prompt tokens
- Warmups: 3 repetitions per configuration
- Measured repetitions: 10 per configuration
- Measured requests: 30 per configuration
- Baseline layout: `dynamic_request + stable_context`
- Optimized layout: `stable_context + dynamic_request`
- Sampling: `temperature=0`, `max_tokens=8`

The logical workload and server configuration were held constant. The only
application-level change was prompt/context ordering.

### Results

| Metric | Baseline dynamic prefix | Optimized stable prefix |
| --- | ---: | ---: |
| Measured requests | 30 | 30 |
| Input tokens | 237,095 | 237,057 |
| Output tokens | 240 | 240 |
| Cached-token ratio | 0.40% | 99.57% |
| Cached tokens | 960 | 236,048 |
| Cache miss tokens | 236,135 | 1,009 |
| Queue latency P50 | 0.038 ms | 0.038 ms |
| Queue latency P95 | 0.048 ms | 0.041 ms |
| Scheduled-to-first-token P50 | 238.63 ms | 30.69 ms |
| Scheduled-to-first-token P95 | 241.73 ms | 32.61 ms |
| Generation latency P50 | 32.63 ms | 33.71 ms |
| Generation latency P95 | 35.40 ms | 36.63 ms |
| TPOT / ITL P50 | 4.66 ms | 4.82 ms |
| TPOT / ITL P95 | 5.06 ms | 5.23 ms |
| Client-observed latency P50 | 342.32 ms | 135.04 ms |
| Client-observed latency P95 | 348.97 ms | 141.55 ms |

### AgentPerf Findings

Baseline findings:

- `CONTEXT_DUPLICATION`
- `PREFIX_CACHE_OPPORTUNITY`
- `MATERIAL_PREFILL_BOTTLENECK`

The prefix-cache recommendation was:

```text
Evaluate whether stable instructions, tool schemas, and other shared context
can be organized into a consistent cacheable prefix.
```

Optimized findings:

- `CONTEXT_DUPLICATION`
- `PREFILL_PATH_DOMINANCE`

`PREFIX_CACHE_OPPORTUNITY` disappeared after moving the stable context to the
front of the prompt. `MATERIAL_PREFILL_BOTTLENECK` downgraded to low-severity
`PREFILL_PATH_DOMINANCE` because cached-token ratio rose to 99.57%, P95 uncached
input fell to 50 tokens, and scheduled-to-first-token P95 fell to 32.61 ms.

### Interpretation

This is AgentPerf's first complete real diagnosis/replay story:

```text
real dynamic-prefix workload
  -> repeated stable content but 0.40% cache reuse
  -> PREFIX_CACHE_OPPORTUNITY
  -> move stable context into a consistent prefix
  -> 99.57% cache reuse and much lower scheduled-to-first-token latency
```

The result validates the core cross-layer thesis for this controlled workload:
agent-level prompt structure plus real vLLM serving telemetry explains a
performance pathology that neither layer alone makes as actionable.

It is not a general benchmark. The run used one model, one GPU type, one server
configuration, and a small synthetic agent-like workload.

### Quality Notes

The runner records outputs but does not grade task quality. With
`max_tokens=8`, both configurations produced short runbook-related completions
rather than well-formed JSON. The optimized run did not fail or return empty
responses, but this experiment should not be used as task-quality evidence.

### Artifact Location

The compressed artifact bundle was copied off the Pod before cleanup:

```text
artifacts/runpod/agentperf-real-prefix-story-a5000-20260809.tgz
```

The bundle contains setup logs, smoke-test artifacts, vLLM startup logs, raw
vLLM recordings, normalized AgentPerf traces, terminal reports, and
`comparison.json`.

## Run 1: First Live vLLM Ingestion Attempt

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
- historical `PREFILL_BOTTLENECK` label

Optimized findings:

- `CONTEXT_DUPLICATION`
- historical `PREFILL_BOTTLENECK` label

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

A follow-up serving-only cache-semantics probe isolated the missing contrast and
is documented in `docs/VLLM_PREFIX_CACHE_SEMANTICS.md`.

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

- the historical `PREFILL_BOTTLENECK` label fired even though absolute
  scheduled-to-first-token latency was low, around 15-17 ms. This led to the
  current split between `PREFILL_PATH_DOMINANCE` and
  `MATERIAL_PREFILL_BOTTLENECK`.
- The baseline workload's "dynamic before stable context" layout did not produce
  low vLLM cached-token ratio. Either the workload failed to defeat exact cache
  reuse, or vLLM's `cached_tokens` semantics are broader than the initial
  prefix-only intuition.
- The next real experiment should first construct a minimal request pair that
  proves how vLLM `cached_tokens` changes when the first cache block differs.
