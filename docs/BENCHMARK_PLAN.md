# Benchmark Plan

This document defines future evaluation. It does not report benchmark results.

## Detection Quality

Measure detector behavior against labeled traces:

- precision;
- recall;
- false positive rate;
- false negative rate;
- boundary behavior around documented thresholds;
- robustness when serving telemetry is missing or uncorrelated.

Initial labels can be synthetic. Real labels require manually reviewed production or benchmark traces.

## Runtime Overhead

For future instrumentation:

- application instrumentation overhead;
- server instrumentation overhead;
- trace export overhead;
- storage volume;
- local analysis runtime;
- memory use during analysis.

The MVP only measures local analysis runtime on JSON files.

## Optimization Usefulness

For each recommendation, validate by replaying or rerunning the workload and comparing:

- input token count;
- output token count;
- TTFT P50/P95;
- backend first-token path or server-stage prefill timing where explicitly
  exposed;
- decode/generation latency where explicitly exposed;
- prefix-cache hit rate;
- throughput;
- end-to-end task latency;
- cost.

## Safety and Correctness

Any optimization suggested by AgentPerf can degrade task quality. Validation must include:

- task success rate or human-reviewed quality;
- regression tests for output correctness;
- quality >= baseline - tolerance when optimizing cost/latency.

## Future Model-Choice Optimization

Model-choice optimization is explicitly out of scope for the MVP.

A future profiler could evaluate objectives such as:

```text
minimize cost/latency
subject to quality >= baseline - tolerance
```

Example future output:

```text
Planner       70B -> keep
SearchQuery   70B -> candidate 8B
Writer        70B -> keep
```

This requires replay/evaluation infrastructure and real quality metrics.

## GPU Requirements

No GPU is required for the MVP synthetic-trace analyzer.

Real vLLM/SGLang ingestion and backend-supported replay experiments require
access to at least one GPU server running the target inference backend.
