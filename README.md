# AgentPerf

Agent observability tells developers what an agent did.

Inference telemetry tells developers what the model server did.

AgentPerf correlates the two to diagnose agent performance inefficiencies with
evidence-backed findings.

This repository is an honest **v0.1 MVP**. It includes a normalized trace model,
explicit request correlation, deterministic detectors, a terminal CLI, synthetic
fixtures, a narrow vLLM recording adapter, and one small real vLLM validation
story. It does **not** claim general benchmark results or production readiness.

## Current Status

### Implemented

- Normalized trace parser for agent runs, steps, LLM calls, tool calls, and
  serving requests.
- Explicit-ID cross-layer correlation.
- Terminal CLI:
  - `agentperf analyze <trace.json>`
  - `agentperf analyze-vllm-recording <recording.json>`
- Deterministic detectors:
  - `CONTEXT_DUPLICATION`
  - `PREFIX_CACHE_OPPORTUNITY`
  - `PREFILL_PATH_DOMINANCE`
  - `MATERIAL_PREFILL_BOTTLENECK`
- Finding provenance for LLM calls, request IDs, serving request IDs, raw
  metrics, derived metrics, and approximation notes.
- Exact/approximate tokenization mode labels.
- vLLM OpenAI-compatible response adapter.
- Repeatable vLLM demo runner for an already running vLLM server:
  `scripts/run_vllm_real_demo.py`.

### Validated With Fixtures

- Synthetic AgentPerf traces in `examples/traces/`.
- A vLLM-shaped recorded telemetry schema fixture in
  `examples/recorded_telemetry/vllm_openai_response_fixture.json`.
- Parser, correlator, detectors, vLLM adapter, CLI, reporter, tokenization mode,
  unit conversion, missing telemetry handling, and provenance tests.
- Current local validation: `pytest`, `ruff`, and `mypy` pass.

The fixture data is for development and tests. It is not benchmark evidence.

### Live vLLM Validation

Completed on one Runpod NVIDIA RTX A5000 using vLLM `0.26.0+cu129` and
`Qwen/Qwen3-0.6B`:

- explicit request correlation from AgentPerf client request ID to vLLM
  response/serving telemetry;
- real per-request `cached_tokens`, queue timing, scheduled-to-first-token,
  generation timing, and ITL ingestion;
- controlled baseline `dynamic_request + stable_context` with low cache reuse;
- replayed optimization `stable_context + dynamic_request` with high cache
  reuse and lower scheduled-to-first-token latency.

These are small-sample validation results, not benchmark claims. See
[docs/REAL_VLLM_RESULTS.md](docs/REAL_VLLM_RESULTS.md).

### Planned

- Tokenizer and detector-threshold calibration from real traces.
- Harness/context waste analysis.
- Additional backend ingestion only after the vLLM path is proven.
- Model-choice counterfactual profiling later, under replay and quality
  constraints.

## Not Claimed

AgentPerf is not:

- a production-ready observability platform;
- a scheduler replacement;
- an automatic optimizer;
- a system for computing optimal KV-cache size;
- a claim of benchmark-proven speedups;
- a Langfuse, Phoenix, or ThunderAgent replacement.

Recommendations are deterministic experiments to evaluate, not guaranteed
performance fixes.

## Architecture

```text
Agent trace JSON or vLLM recording
  -> backend adapter when needed
  -> normalized AgentRun
  -> TraceCorrelator
  -> token / latency / cache metrics
  -> deterministic detectors
  -> Finding objects
  -> terminal report
```

Normalized shape:

```text
AgentRun
  AgentStep
    LLMCall
      ServingRequest
        queue
        prefill
        decode
        prefix/KV cache fields
    ToolCall
```

Correlation is explicit-ID only:

- `LLMCall.serving_request_id == ServingRequest.serving_request_id`
- `LLMCall.llm_request_id == ServingRequest.llm_request_id`

Timestamp, model-name, and prompt-length heuristics are intentionally avoided in
v0.1.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
agentperf analyze examples/traces/multi_problem_agent.json
```

Analyze the vLLM-shaped recording fixture:

```bash
agentperf analyze-vllm-recording \
  examples/recorded_telemetry/vllm_openai_response_fixture.json \
  --show-provenance
```

Run all local checks:

```bash
pytest
ruff check .
mypy agentperf tests scripts
```

## Synthetic Example

Command:

```bash
agentperf analyze examples/traces/multi_problem_agent.json
```

Shortened output:

```text
============================================================
AgentPerf Report
============================================================
Data: synthetic trace fixture, not benchmark results

Run
------------------------------------------------------------
Run ID                             synthetic-multi-problem
LLM calls                          3
Tool calls                         1
Input tokens                       270
Output tokens                      455
Correlated serving requests        3

Findings
------------------------------------------------------------

[HIGH] PREFIX_CACHE_OPPORTUNITY

Correlated requests contain substantial repeated stable content, but serving
telemetry reports low actual prefix-cache reuse while the prefill path
contributes materially to TTFT.
```

This is a synthetic fixture, not a production benchmark.

## vLLM Live Demo Runner

The runner requires an already running vLLM OpenAI-compatible server:

```bash
python scripts/run_vllm_real_demo.py \
  --base-url http://localhost:8000/v1 \
  --model <served-model-name> \
  --warmups 1 \
  --repetitions 3
```

The server must expose the telemetry needed by AgentPerf. In particular, the
v0.1 mapping expects per-request metrics and prompt-token details where
available. See [docs/REAL_TELEMETRY_MAPPING.md](docs/REAL_TELEMETRY_MAPPING.md).

The runner has been validated against one live vLLM/A5000 setup. The raw
artifact bundle is gitignored because it contains repeated prompt text; summary
results are documented in `docs/REAL_VLLM_RESULTS.md`.

## Documentation

- [docs/LANDSCAPE.md](docs/LANDSCAPE.md)
- [docs/PRODUCT.md](docs/PRODUCT.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/TRACE_SCHEMA.md](docs/TRACE_SCHEMA.md)
- [docs/BENCHMARK_PLAN.md](docs/BENCHMARK_PLAN.md)
- [docs/BACKEND_SELECTION.md](docs/BACKEND_SELECTION.md)
- [docs/REAL_TELEMETRY_MAPPING.md](docs/REAL_TELEMETRY_MAPPING.md)
- [docs/REAL_VLLM_RUNBOOK.md](docs/REAL_VLLM_RUNBOOK.md)
- [docs/DETECTOR_CALIBRATION.md](docs/DETECTOR_CALIBRATION.md)

## Roadmap

- M1: synthetic vertical slice. Done.
- M2: real vLLM execution and replay validation. Done for one controlled A5000
  workload.
- M3: tokenizer and threshold calibration from real traces.
- M4: harness/context waste analysis.
- M5: model-choice counterfactual profiling.

No fake dates are assigned.

## License

MIT License. See [LICENSE](LICENSE).
