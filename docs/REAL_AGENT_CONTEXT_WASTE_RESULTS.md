# Real Agent Context-Waste Results

This document records real execution attempts for the M3 agent harness/context-waste milestone.

## 2026-08-09 L4 Attempt

Status: blocked before workload execution.

The RTX A5000 pool was unavailable, so the approved fallback was one NVIDIA L4 under the
$0.55/hour cap.

Environment:

- Pod ID: `xabo9uz3r99iog`
- GPU: NVIDIA L4, 24 GB
- Price: $0.49/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `550.127.05`
- `nvidia-smi` CUDA compatibility label: `12.4`
- AgentPerf commit: `ff2c829`
- Branch: `feature/real-agent-context-waste`

Preflight result:

- `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`
- `vllm`: `0.26.0`
- CUDA tensor probe: passed on `NVIDIA L4`

Model download:

- Model: `Qwen/Qwen3-0.6B`
- Local path: `/workspace/models/Qwen3-0.6B`
- Files: 23
- Size: 1,519,211,941 bytes
- Download elapsed time: 9.59 seconds
- Config, tokenizer, and safetensors files were verified present after download.

vLLM startup:

```text
vllm serve /workspace/models/Qwen3-0.6B \
  --served-model-name agentperf-vllm-demo \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 12288 \
  --gpu-memory-utilization 0.80 \
  --enable-prefix-caching \
  --prefix-caching-hash-algo sha256_cbor \
  --enable-prompt-tokens-details \
  --enable-per-request-metrics
```

Failure:

- `/v1/models` did not become ready during the bounded startup window.
- `vllm_server.log` remained empty.
- `nvidia-smi` showed no model process and only 1 MiB GPU memory usage.
- The `vllm serve` process remained CPU-active but did not initialize the GPU or open port 8000.
- A separate `import vllm` diagnostic also stalled during the same window.

No real M3 baseline/optimized agent workload was run on this Pod. No token, latency,
cache, correctness, or detector result should be reported from this attempt.

Cleanup:

- Diagnostic archive copied locally to:
  `artifacts/runpod/agentperf-m3-l4-startup-failure-xabo9uz3r99iog.tgz`
- Pod deleted after diagnostics were preserved.
- `runpodctl pod list` returned `[]`.

## 2026-08-09 RTX 3090 Attempt

Status: completed with a correctness regression.

This run used the approved fallback GPU after the L4 startup failure. It is a real
single-run validation of the M3 harness/context-waste workflow, not a statistically
significant benchmark.

Environment:

- Pod ID: `vvrrzawc4y6h3p`
- GPU: NVIDIA GeForce RTX 3090, 24 GB
- Price: $0.50/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `580.126.20`
- `nvidia-smi` CUDA compatibility label: `13.0`
- AgentPerf commit: `d0f997a`
- Branch: `feature/real-agent-context-waste`
- Model: `Qwen/Qwen3-0.6B`
- Served model name: `agentperf-vllm-demo`
- Backend: vLLM `0.26.0+cu129`

Preflight result:

- `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`
- Bounded `timeout 60 python -c "import vllm; print(vllm.__version__)"`: passed, `0.26.0`
- CUDA tensor probe: passed on `NVIDIA GeForce RTX 3090`

Workload:

- Agent architecture: planner LLM -> deterministic local search -> evidence review LLM ->
  deterministic local search -> final synthesis LLM
- Agent framework: none
- Questions: 10 deterministic local-corpus research questions
- LLM calls per configuration: 30
- Tool calls per configuration: 20
- Baseline harness: raw full tool-result carry-forward
- Optimized harness: compact tool-result carry-forward

Measured results:

| Metric | Baseline | Optimized | Change |
| --- | ---: | ---: | ---: |
| Rule-based pass rate | 20.0% | 10.0% | -10.0 pp |
| Mean rule-based score | 0.342 | 0.292 | -0.050 |
| Input tokens processed | 129,658 | 14,997 | -88.4% |
| Output tokens | 3,840 | 3,840 | 0.0% |
| Component processed tokens | 117,542 | 12,198 | -89.6% |
| Tool-result processed tokens | 111,387 | 5,989 | -94.6% |
| History processed tokens | 2,815 | 2,869 | +1.9% |
| Prefix-cache hit ratio | 3.2% | 34.5% | +31.3 pp |
| TTFT P50 | 112.3 ms | 11.2 ms | -90.0% |
| TTFT P95 | 291.2 ms | 18.8 ms | -93.5% |
| Prefill-path proxy total | 4.1 s | 0.4 s | -90.8% |
| Client latency P50 | 440.5 ms | 257.4 ms | -41.6% |
| Client latency P95 | 1,071.2 ms | 516.7 ms | -51.8% |

Baseline token attribution:

| Component | Processed tokens | Unique tokens | Share |
| --- | ---: | ---: | ---: |
| System | 1,200 | 40 | 1.0% |
| User | 550 | 487 | 0.5% |
| History | 2,815 | 2,815 | 2.4% |
| Tool schema | 1,590 | 53 | 1.4% |
| Tool result | 111,387 | 74,249 | 94.8% |

Optimized token attribution:

| Component | Processed tokens | Unique tokens | Share |
| --- | ---: | ---: | ---: |
| System | 1,200 | 40 | 9.8% |
| User | 550 | 487 | 4.5% |
| History | 2,869 | 2,869 | 23.5% |
| Tool schema | 1,590 | 53 | 13.0% |
| Tool result | 5,989 | 3,989 | 49.1% |

Baseline AgentPerf findings:

- `CONTEXT_DUPLICATION`
- `TOOL_OUTPUT_BLOAT`
- `PREFIX_CACHE_OPPORTUNITY`
- `MATERIAL_PREFILL_BOTTLENECK`

Optimized AgentPerf findings:

- `CONTEXT_DUPLICATION`
- `PREFIX_CACHE_OPPORTUNITY`
- `PREFILL_PATH_DOMINANCE`

Interpretation:

- AgentPerf correctly identified that raw tool-output carry-forward dominated processed
  input tokens in the baseline.
- The planned compact carry-forward intervention removed `TOOL_OUTPUT_BLOAT` and reduced
  processed input tokens by 88.4%.
- Serving behavior improved materially on this single run: TTFT P95 fell from 291.2 ms to
  18.8 ms and client latency P95 fell from 1,071.2 ms to 516.7 ms.
- The intervention was not quality-neutral. Rule-based pass rate dropped from 20.0% to
  10.0%, and mean rule-based score dropped from 0.342 to 0.292.
- Because correctness regressed, this optimization should be treated as a useful diagnosis
  and a partially successful systems intervention, not an accepted product recommendation.

Calibration notes:

- `TOOL_OUTPUT_BLOAT` behaved as intended for this workload: present in the raw baseline and
  absent after compact tool-result carry-forward.
- `MATERIAL_PREFILL_BOTTLENECK` downgraded to `PREFILL_PATH_DOMINANCE` after the token
  reduction, matching the intended materiality distinction.
- `PREFIX_CACHE_OPPORTUNITY` still fired in the optimized run despite TTFT P95 being only
  18.8 ms. This is likely a detector calibration issue: prefix-cache reuse was still not
  high in absolute terms, but the remaining latency was no longer material.
- The current optimized harness is too lossy for the local-corpus QA task. A follow-up should
  improve compact evidence selection before claiming a successful quality-preserving
  optimization.

Artifacts:

- Full result bundle copied locally to:
  `artifacts/runpod/agentperf-m3-3090-real-agent-results-vvrrzawc4y6h3p.tgz`
- The bundle includes raw vLLM recordings, normalized AgentPerf traces, terminal reports,
  setup logs, vLLM logs, smoke-test artifacts, and `comparison.json`.

Cleanup:

- Pod was deleted after artifacts were preserved.

## 2026-08-09 RTX 3090 Quality-Constrained Attempt

Status: completed with a quality-preserving deterministic compaction strategy.

This run fixed benchmark/agent issues found in the first RTX 3090 attempt and
then evaluated multiple deterministic context-carry strategies over the same
local-corpus workload. It is still a small single-run validation, not a
statistically significant benchmark.

Environment:

- Pod ID: `bkq1j1rhie1x4z`
- GPU: NVIDIA GeForce RTX 3090, 24 GB
- Price: $0.50/hour
- Image: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404`
- Driver: `580.159.03`
- `nvidia-smi` CUDA compatibility label: `13.0`
- AgentPerf commit: `1ce0b8e` for the executed workload
- Branch: `feature/real-agent-context-waste`
- Model: `Qwen/Qwen3-0.6B`
- Served model name: `agentperf-vllm-demo`
- Backend: vLLM `0.26.0+cu129`
- `torch`: `2.11.0+cu129`
- `torch.version.cuda`: `12.9`

Preflight result:

- Bounded `timeout 60 python -c "import vllm; print(vllm.__version__)"`:
  passed, `0.26.0`
- CUDA tensor probe: passed on `NVIDIA GeForce RTX 3090`
- Model download path: `/workspace/models/Qwen3-0.6B`
- Model download size: 1,519,211,936 bytes
- Model download elapsed time: 4.20 seconds
- Smoke test: passed with per-request telemetry

Root cause of weak baseline quality:

- The corpus and answer keys were solvable; all required facts were present in
  `docs/corpus`.
- The previous runner sent Qwen a raw completion prompt instead of a chat-format
  prompt, and Qwen often continued prompt sections rather than answering.
- Planner/review outputs polluted later prompts with hallucinated structure and
  fake document references.
- The final-answer output budget and answer format were too weak for the local
  QA task.
- The rule scorer was also too brittle for punctuation, hyphenation, and word
  order.

Fixes before optimizing context:

- Wrapped vLLM prompts in Qwen-style chat turns while preserving normalized
  AgentPerf prompt components for attribution.
- Constrained planner/review/final prompts to a smaller structured format.
- Increased the final answer budget to 320 tokens.
- Made rule scoring deterministic but less exact-string brittle by normalizing
  punctuation and matching significant fact terms.

Trustworthy baseline after those fixes:

- Rule-based pass rate: 80.0%
- Mean rule-based score: 0.933
- Input tokens processed: 132,756
- Tool-result processed tokens: 112,287
- TTFT P95: 312.18 ms
- Client latency P95: 1,607.11 ms

Strategies tested:

- `RAW_FULL`: carry all tool output.
- `DEDUP_ONLY`: remove repeated passage carry-forward while preserving unique
  raw evidence.
- `TOP_K_2`: carry the top two unique retrieved passages.
- `BUDGET_1200`: carry ranked unique evidence until a 1,200-token budget.
- `AGGRESSIVE_COMPACT`: carry only compact `ANSWER_FACT`/`CITATION` lines.

Quality constraint:

- Objective: minimize processed input tokens.
- Constraint: mean score must be at least baseline minus 0.05 and pass rate
  must be at least baseline minus 0.10.
- Minimum acceptable mean score: 0.883.
- Minimum acceptable pass rate: 70.0%.

Measured results:

| Strategy | Mean score | Pass rate | Input tokens | Tool-result tokens | TTFT P95 | Client P95 | Cache hit ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `RAW_FULL` | 0.933 | 80.0% | 132,756 | 112,287 | 312.18 ms | 1,607.11 ms | 3.13% |
| `DEDUP_ONLY` | 0.908 | 70.0% | 95,479 | 78,566 | 176.53 ms | 1,247.62 ms | 6.18% |
| `TOP_K_2` | 0.842 | 60.0% | 17,053 | 6,778 | 20.22 ms | 858.41 ms | 31.62% |
| `BUDGET_1200` | 0.858 | 50.0% | 21,921 | 10,569 | 26.53 ms | 912.54 ms | 24.82% |
| `AGGRESSIVE_COMPACT` | 0.708 | 40.0% | 16,370 | 5,989 | 22.82 ms | 864.22 ms | 33.92% |

Quality-constrained selection:

- `DEDUP_ONLY` was the only non-baseline strategy within the quality constraint.
- Compared with `RAW_FULL`, it reduced input tokens from 132,756 to 95,479
  (-28.1%).
- It reduced tool-result processed tokens from 112,287 to 78,566 (-30.0%).
- TTFT P95 fell from 312.18 ms to 176.53 ms (-43.5%).
- Client latency P95 fell from 1,607.11 ms to 1,247.62 ms (-22.4%).
- Mean score fell by 0.025 and pass rate fell by 10 percentage points, which is
  inside the explicit tolerance but should still be treated as a product tradeoff
  to show to users.

AgentPerf findings by strategy:

| Strategy | Findings |
| --- | --- |
| `RAW_FULL` | `CONTEXT_DUPLICATION`, `TOOL_OUTPUT_BLOAT`, `MATERIAL_PREFIX_CACHE_OPPORTUNITY`, `MATERIAL_PREFILL_BOTTLENECK` |
| `DEDUP_ONLY` | `CONTEXT_DUPLICATION`, `TOOL_OUTPUT_BLOAT`, `MATERIAL_PREFIX_CACHE_OPPORTUNITY`, `MATERIAL_PREFILL_BOTTLENECK` |
| `TOP_K_2` | `CONTEXT_DUPLICATION`, `CACHEABILITY_HEADROOM`, `PREFILL_PATH_DOMINANCE` |
| `BUDGET_1200` | `CACHEABILITY_HEADROOM`, `PREFILL_PATH_DOMINANCE` |
| `AGGRESSIVE_COMPACT` | `CONTEXT_DUPLICATION`, `CACHEABILITY_HEADROOM`, `PREFILL_PATH_DOMINANCE` |

Interpretation:

- `TOOL_OUTPUT_BLOAT` is empirically useful: raw tool-result carry-forward
  accounted for 84.6% of baseline processed input tokens.
- Aggressive compaction was too lossy in the previous attempt and remains below
  the quality constraint here.
- The acceptable intervention is much narrower: deterministic deduplication of
  repeated retrieved passages, while preserving unique raw evidence.
- The strongest result is quality-constrained token reduction: 28.1% fewer
  processed input tokens and 30.0% fewer processed tool-result tokens with
  quality inside the declared tolerance.
- More aggressive strategies produce much lower latency but fail the quality
  constraint on this model/task.

Calibration notes:

- Prefix-cache findings now distinguish `CACHEABILITY_HEADROOM` from
  `MATERIAL_PREFIX_CACHE_OPPORTUNITY`. A material finding requires low cache
  reuse plus meaningful scheduled-to-first-token and uncached-token evidence.
- The compact strategies with TTFT P95 around 20-27 ms now produce only
  `CACHEABILITY_HEADROOM`, not a high actionable prefix-cache warning.
- `MATERIAL_PREFILL_BOTTLENECK` remains appropriate for `RAW_FULL` and
  `DEDUP_ONLY`, whose TTFT P95 remained above 100 ms with high uncached input
  volume.

Artifacts:

- Full result bundle copied locally to:
  `artifacts/runpod/agentperf-m3-quality-3090-results-bkq1j1rhie1x4z.tgz`
- The bundle includes raw vLLM recordings, normalized AgentPerf traces,
  terminal reports, setup logs, vLLM logs, smoke-test artifacts, and
  `comparison.json`.

Cleanup:

- Pod deletion is required after this documentation is committed and pushed.
