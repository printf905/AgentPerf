# AgentPerf Architecture

## Data Flow

```text
JSON trace file or vLLM recording
  -> backend adapter when needed
  -> normalized AgentRun schema
  -> TraceCorrelator
  -> derived metrics
  -> deterministic detectors
  -> Finding objects
  -> terminal report
```

## Components

- `agentperf.schema.trace`: Dataclasses for agent runs, steps, LLM calls, tool calls, serving requests, prompt components, and parsing.
- `agentperf.schema.findings`: Reusable finding model.
- `agentperf.correlation.correlator`: Associates agent-level `LLMCall` records with `ServingRequest` records only when explicit IDs match.
- `agentperf.metrics.tokens`: Approximate tokenization and repeated-prefix/content metrics.
- `agentperf.metrics.latency`: Latency summaries and percentile helpers.
- `agentperf.metrics.cache`: Prefix-cache hit ratio helpers.
- `agentperf.detectors`: Deterministic detector implementations.
- `agentperf.backends.vllm`: vLLM OpenAI-compatible response adapter. It maps
  real backend telemetry into normalized `AgentRun` data and labels unavailable
  or approximated fields.
- `agentperf.tokenization`: Exact/approximate tokenizer provider interface used
  to make token evidence reliability explicit.
- `agentperf.reporters.terminal`: Plain terminal output.
- `agentperf.cli`: `agentperf analyze <trace.json>` and
  `agentperf analyze-vllm-recording <recording.json>`.

## Correlation Policy

The MVP uses explicit identifier matching only:

- `LLMCall.serving_request_id == ServingRequest.serving_request_id`
- `LLMCall.llm_request_id == ServingRequest.llm_request_id`

If neither proves a relationship, the serving span remains unresolved. The MVP does not infer matches using timestamps, model names, or prompt lengths because those heuristics can produce misleading cross-layer findings.

## Detector Pipeline

The analyzer computes derived facts first, then detectors consume those facts:

- prompt token sequences and common-prefix lengths;
- repeated prompt content by exact component text;
- per-request serving latency fractions;
- prefix-cache hit ratios;
- aggregate run summaries.

The detector output is a `Finding` with severity, evidence, affected spans, confidence, recommendation, and validation plan.

Findings also carry optional provenance: LLM call IDs, client request IDs,
serving request IDs, raw metrics, derived metrics, and notes. The terminal
reporter prints this only when requested with `--show-provenance`.

## Real vLLM Ingestion

The first real-backend path is intentionally narrow:

```text
scripts/run_vllm_real_demo.py
  -> vLLM OpenAI-compatible /chat/completions
  -> recorded response bundle
  -> VLLMTelemetryProvider
  -> normalized AgentRun
  -> existing detectors
```

The runner sends a client `request_id` and records vLLM's returned response ID.
The normalized LLM call keeps both:

- `llm_request_id`: client-generated request ID;
- `serving_request_id`: backend response ID.

The serving request stores the same pair, so `TraceCorrelator` can associate
requests through explicit IDs. No timestamp-based matching is used.

The adapter currently supports vLLM only. There is no speculative SGLang adapter
or generic plugin layer in this milestone.

## MVP Thresholds

Thresholds are code-level configuration objects today, not CLI flags.

| Detector | Threshold | Default |
| --- | --- | --- |
| `CONTEXT_DUPLICATION` | minimum affected calls | 3 |
| `CONTEXT_DUPLICATION` | minimum repeated context tokens | 50 approximate tokens |
| `CONTEXT_DUPLICATION` | minimum repeated context ratio | 25% |
| `PREFIX_CACHE_OPPORTUNITY` | minimum affected requests | 2 |
| `PREFIX_CACHE_OPPORTUNITY` | minimum shared prefix ratio | 60% |
| `PREFIX_CACHE_OPPORTUNITY` | minimum repeated non-prefix ratio | 50% |
| `PREFIX_CACHE_OPPORTUNITY` | minimum shared prefix tokens | 50 approximate tokens |
| `PREFIX_CACHE_OPPORTUNITY` | maximum actual prefix-cache hit ratio | 35% |
| `PREFIX_CACHE_OPPORTUNITY` | minimum prefill/prefill-path fraction of TTFT | 50% |
| `PREFILL_PATH_DOMINANCE` | minimum affected requests | 2 |
| `PREFILL_PATH_DOMINANCE` | minimum prefill/prefill-path fraction of TTFT | 60% |
| `PREFILL_PATH_DOMINANCE` | minimum P95 input tokens | 100 tokens |
| `MATERIAL_PREFILL_BOTTLENECK` | minimum P95 scheduled-to-first-token | 100 ms |
| `MATERIAL_PREFILL_BOTTLENECK` | minimum P95 uncached input tokens | 1,000 tokens |

The low token thresholds are intentional for the synthetic MVP fixtures and unit tests. Real trace ingestion should revisit these defaults per workload class and model tokenizer.

## Future Ingestion

Future versions can add importers for:

- OpenTelemetry/OpenInference spans;
- SGLang request dumps and metrics;
- ThunderAgent program traces.

Those importers should normalize into the same internal schema rather than adding detector-specific formats.
