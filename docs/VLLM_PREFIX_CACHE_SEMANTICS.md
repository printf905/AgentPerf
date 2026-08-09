# vLLM Prefix Cache Semantics

Status: completed on a live Runpod vLLM server on 2026-08-09 UTC.

This was a serving-behavior experiment, not an AgentPerf detector run. The goal
was to establish how vLLM `cached_tokens` behaves before designing another
baseline/optimized AgentPerf replay experiment.

## Environment

- Pod ID: `y51f2ej7iecj6i`
- GPU: NVIDIA RTX A5000, 24 GB VRAM
- Runpod image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `580.159.04`
- `nvidia-smi` CUDA label: `13.0`
- torch: `2.11.0+cu129`
- torch CUDA runtime: `12.9`
- vLLM: `0.26.0+cu129`
- Model: `Qwen/Qwen3-0.6B`
- vLLM max model length: `12288`
- Prefix caching: enabled
- Prompt-token details: enabled
- Per-request metrics: enabled
- API path: `/v1/completions`
- Generation: `max_tokens=8`, `temperature=0`

The CUDA preflight passed:

```text
2.11.0+cu129 12.9
NVIDIA RTX A5000
tensor([1.], device='cuda:0')
```

## Cases

Each case was run for stable-section targets of 1K, 4K, and 8K tokens. No
warmups were used; first-request behavior is preserved. Stable and dynamic text
was made unique per case and size to avoid cross-case cache pollution.

- A `IDENTICAL_REQUESTS`: `S + A`, `S + A`, `S + A`
- B `DYNAMIC_PREFIX`: `A1 + S`, `A2 + S`, `A3 + S`
- C `STABLE_PREFIX`: `S + A1`, `S + A2`, `S + A3`
- D `STABLE_PREFIX_DYNAMIC_SUFFIX`: `S + B + A1`, `S + B + A2`, `S + B + A3`

## Request-By-Request Results

### 1K Stable Target

| Case | Req | Prompt Tokens | Cached Tokens | Cached Ratio | Scheduled->First | Generation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A identical | 1 | 1,187 | 0 | 0.00% | 58.060 ms | 27.136 ms |
| A identical | 2 | 1,187 | 1,184 | 99.75% | 24.130 ms | 24.138 ms |
| A identical | 3 | 1,187 | 1,184 | 99.75% | 20.888 ms | 25.867 ms |
| B dynamic prefix | 1 | 1,144 | 0 | 0.00% | 38.135 ms | 27.327 ms |
| B dynamic prefix | 2 | 1,145 | 0 | 0.00% | 38.237 ms | 20.872 ms |
| B dynamic prefix | 3 | 1,138 | 0 | 0.00% | 32.112 ms | 20.435 ms |
| C stable prefix | 1 | 1,157 | 0 | 0.00% | 32.246 ms | 24.571 ms |
| C stable prefix | 2 | 1,156 | 1,024 | 88.58% | 20.975 ms | 23.733 ms |
| C stable prefix | 3 | 1,156 | 1,024 | 88.58% | 18.442 ms | 23.535 ms |
| D stable prefix + suffix | 1 | 1,698 | 0 | 0.00% | 35.057 ms | 29.444 ms |
| D stable prefix + suffix | 2 | 1,699 | 1,568 | 92.29% | 22.672 ms | 26.353 ms |
| D stable prefix + suffix | 3 | 1,694 | 1,568 | 92.56% | 8.769 ms | 20.397 ms |

### 4K Stable Target

| Case | Req | Prompt Tokens | Cached Tokens | Cached Ratio | Scheduled->First | Generation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A identical | 1 | 4,226 | 0 | 0.00% | 100.147 ms | 30.470 ms |
| A identical | 2 | 4,226 | 4,224 | 99.95% | 24.936 ms | 30.264 ms |
| A identical | 3 | 4,226 | 4,224 | 99.95% | 24.562 ms | 30.361 ms |
| B dynamic prefix | 1 | 4,224 | 0 | 0.00% | 102.409 ms | 30.631 ms |
| B dynamic prefix | 2 | 4,224 | 0 | 0.00% | 100.811 ms | 27.713 ms |
| B dynamic prefix | 3 | 4,220 | 0 | 0.00% | 97.537 ms | 28.665 ms |
| C stable prefix | 1 | 4,212 | 0 | 0.00% | 100.736 ms | 27.769 ms |
| C stable prefix | 2 | 4,217 | 4,080 | 96.75% | 24.752 ms | 29.870 ms |
| C stable prefix | 3 | 4,214 | 4,080 | 96.82% | 25.015 ms | 32.611 ms |
| D stable prefix + suffix | 1 | 4,743 | 0 | 0.00% | 122.625 ms | 29.479 ms |
| D stable prefix + suffix | 2 | 4,744 | 4,608 | 97.13% | 25.006 ms | 31.388 ms |
| D stable prefix + suffix | 3 | 4,741 | 4,608 | 97.19% | 24.604 ms | 32.323 ms |

### 8K Stable Target

| Case | Req | Prompt Tokens | Cached Tokens | Cached Ratio | Scheduled->First | Generation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A identical | 1 | 8,319 | 0 | 0.00% | 255.876 ms | 30.463 ms |
| A identical | 2 | 8,319 | 8,304 | 99.82% | 31.534 ms | 31.786 ms |
| A identical | 3 | 8,319 | 8,304 | 99.82% | 24.467 ms | 33.591 ms |
| B dynamic prefix | 1 | 8,318 | 0 | 0.00% | 255.107 ms | 37.675 ms |
| B dynamic prefix | 2 | 8,323 | 0 | 0.00% | 257.451 ms | 37.233 ms |
| B dynamic prefix | 3 | 8,315 | 0 | 0.00% | 256.227 ms | 38.028 ms |
| C stable prefix | 1 | 8,317 | 0 | 0.00% | 259.319 ms | 37.659 ms |
| C stable prefix | 2 | 8,318 | 8,176 | 98.29% | 30.111 ms | 37.410 ms |
| C stable prefix | 3 | 8,313 | 8,176 | 98.35% | 29.916 ms | 37.203 ms |
| D stable prefix + suffix | 1 | 8,845 | 0 | 0.00% | 285.714 ms | 38.203 ms |
| D stable prefix + suffix | 2 | 8,845 | 8,704 | 98.41% | 30.505 ms | 36.464 ms |
| D stable prefix + suffix | 3 | 8,845 | 8,704 | 98.41% | 30.352 ms | 34.069 ms |

## Answers

1. Dynamic content before stable content destroyed reuse as expected.
   In case B, requests 2 and 3 reported `0` cached tokens at all three tested
   stable sizes. vLLM did not reuse the stable suffix when the exact prefix
   differed.

2. Stable prefix reuse was reported as full-block cached tokens.
   In cases A, C, and D, requests 2 and 3 cached nearly all reusable prefix
   tokens. For 8K stable-prefix cases, vLLM reported 8,176 to 8,704 cached
   tokens depending on whether the additional stable `B` section was present.

3. Block granularity matters.
   Prometheus reported `block_size="16"`, and all nonzero `cached_tokens` values
   were multiples of 16. vLLM appears to count only full reusable cache blocks,
   not arbitrary token prefixes.

4. `cached_tokens` behaves consistently with AgentPerf's current assumption.
   It is a per-request prompt-token cache-hit count for reusable prefix blocks,
   not a measure of repeated content anywhere in the prompt. Stable suffixes
   after dynamic prefixes are not counted as cached.

5. Scheduled-to-first-token responded strongly to cache reuse at this size.
   At 8K tokens, uncached first requests and dynamic-prefix requests were around
   255-286 ms scheduled-to-first-token. Cached stable-prefix requests were around
   24-32 ms. Generation time did not show the same pattern because the experiment
   generated only 8 tokens and primarily tests prefill/cache behavior.

## Implication For The Next AgentPerf Workload

The previous real AgentPerf workload failed because it did not create a true
dynamic-prefix cache miss. A new baseline should place genuinely unique
per-request content at the very beginning of the serialized prompt, before the
large stable section. The optimized version should move the stable section to
the beginning while keeping task semantics otherwise equivalent.

The next workload should verify the raw vLLM `cached_tokens` contrast before
running AgentPerf detectors:

- baseline dynamic-prefix target: near-zero cached-token ratio after first
  request;
- optimized stable-prefix target: high cached-token ratio on requests 2+;
- same model, server flags, prompt content, output limit, and request count.

## PREFILL_BOTTLENECK Calibration Note

The earlier real AgentPerf run emitted `PREFILL_BOTTLENECK` even though
scheduled-to-first-token P95 was only about 16 ms. This happened because the
detector currently measures dominance: queue time was near zero, and vLLM's
scheduled-to-first-token proxy accounted for effectively all TTFT-side serving
latency. That is not the same as a meaningful user-facing bottleneck.

This cache-semantics probe shows why the distinction matters. With 8K uncached
prompts, scheduled-to-first-token was about 255-286 ms; with stable-prefix cache
reuse, it dropped to about 24-32 ms. That is a materially useful prefill-path
signal. A 16 ms prefill-path-dominant request may be technically dominated by
prefill but not operationally important.

Proposed calibration changes, not yet implemented:

- include an absolute scheduled-to-first-token or prefill-path threshold before
  reporting high severity;
- distinguish "dominant component" from "material bottleneck";
- lower severity when prefill-path fraction is high but absolute TTFT is small;
- keep `time_to_first_token_ms` labeled as `prefill_path_proxy`, not pure GPU
  prefill kernel time.

## Artifacts

The final artifact bundle was copied off the Pod before cleanup:

```text
artifacts/runpod/agentperf-vllm-cache-semantics-final-a5000-20260809.tgz
```

The bundle includes vLLM startup logs, setup preflight files, Prometheus metrics,
the raw JSON result file, and the generated markdown report.
