# AgentPerf v0.2.0 Release Notes

Target release: `v0.2.0`, "Real-Validated Cross-Layer Agent Profiling".

These notes summarize what has been implemented and validated so far. They do
not claim production readiness or broad benchmark generality.

## Highlights

- Normalized agent traces for runs, steps, LLM calls, tool calls, prompt
  components, token usage, timings, and provenance.
- Real vLLM ingestion and explicit request correlation.
- Prefix-cache diagnosis and replay validated against real vLLM as a
  mechanism/correctness result.
- Component-level processed-token attribution.
- Deterministic, materiality-aware findings for context duplication,
  prefix-cache opportunities, prefill-path bottlenecks, tool-output bloat, and
  replay-backed model-choice headroom.
- External agent integrations for OpenAI Agents SDK and mini-SWE-agent.
- Run-boundary-aware duplication semantics so repeated scaffold across
  independent tasks is not treated as removable within-run context waste.

## Real Validation

### Prefix Cacheability

Environment: vLLM `0.26.0+cu129`, `Qwen/Qwen3-0.6B`, NVIDIA RTX A5000.

M2 is treated as a mechanism/correctness validation. Only the prompt layout
changed:

```text
baseline:  dynamic_context + stable_context
optimized: stable_context + dynamic_context
```

AgentPerf detected repeated context that failed to form a reusable prefix,
recommended stable-prefix reorganization, and replay verified the serving
behavior against real vLLM. Exact request-level measurements are kept in
`docs/REAL_VLLM_RESULTS.md` and `docs/VLLM_PREFIX_CACHE_SEMANTICS.md` for
reproducibility rather than used as release headline numbers.

### Real-Agent Context Waste

Environment: vLLM `0.26.0+cu129`, `Qwen/Qwen3-0.6B`, NVIDIA RTX 3090.

The workload was a framework-free multi-step research agent over 10
deterministic local-corpus tasks. AgentPerf identified raw tool-result
reinjection as the dominant processed-token source. After an aggressive
compaction strategy proved too lossy, `DEDUP_ONLY` was selected under this
predeclared quality constraint:

```text
mean score >= baseline - 0.05
pass rate  >= baseline - 0.10
```

| Metric | RAW_FULL | DEDUP_ONLY |
| --- | ---: | ---: |
| Mean quality | 0.933 | 0.908 |
| Pass rate | 80% | 70% |
| Input tokens | 132,756 | 95,479 |
| Tool-result processed tokens | 112,287 | 78,566 |
| Scheduled->first P95 | 312.18 ms | 176.53 ms |
| Client latency P95 | 1607.11 ms | 1247.62 ms |

The selected strategy reduced processed input tokens by 28.1% and processed
tool-result tokens by 30.0% while staying within the declared tolerance.

## External-Agent Integrations

- OpenAI Agents SDK instrumentation uses public hooks/wrappers and does not
  patch framework internals.
- M6 validated OpenAI Agents SDK plus live vLLM cross-layer correlation on 5
  deterministic support-triage tasks: 10 LLM calls, 5 tool calls, 10 vLLM
  serving requests, and 10/10 exact request correlation by propagated request
  IDs.
- M7 profiled upstream mini-SWE-agent `DefaultAgent` on 5 bounded local
  repository-repair tasks. The natural coding loop was preserved and produced
  30 LLM calls, 30 bash/environment calls, and 5/5 task success. This was an
  agent-layer profiling/generalization result, not a SWE-bench result and not
  an optimization win.

## Cross-Layer Correlation

AgentPerf correlates agent LLM calls with serving requests only when explicit
identifiers prove the relationship. It does not join requests by timestamp
proximity. Current real serving validation is vLLM-only.

## Detector And Materiality Improvements

- `MATERIAL_PREFIX_CACHE_OPPORTUNITY` requires both cacheability structure and
  material serving evidence.
- `CACHEABILITY_HEADROOM` preserves non-actionable cacheability observations.
- `MATERIAL_PREFILL_BOTTLENECK` is separated from
  `PREFILL_PATH_DOMINANCE`; dominant does not necessarily mean operationally
  important.
- `CROSS_RUN_SHARED_SCAFFOLD` separates repeated static scaffold across
  independent runs from within-run context duplication. Repetition is not
  automatically removable waste.

## Experimental Capabilities

M4 Phase A model-choice profiling is validated as offline counterfactual
analysis. It tested Qwen3 0.6B, 1.7B, and 4B for planner, reviewer, and
synthesizer roles and emitted replay-backed `MODEL_CHOICE_HEADROOM` findings.

M4 Phase B mixed-routing end-to-end replay is pending. The repository does not
claim mixed-routing quality, latency, or cost improvements.

## Known Limitations

- vLLM is the only serving backend with real validation.
- SGLang ingestion is not implemented.
- Workloads are small, controlled, and not statistically powered benchmarks.
- Quality evaluators are task-specific.
- `scheduled->first` is a measured request-level first-token path metric, not
  pure GPU prefill kernel time.
- mini-SWE-agent profiling used bounded local repair tasks, not SWE-bench.
- No dashboard, hosted service, database, scheduler integration, or production
  trace storage is included.
