# Real vLLM Validation Runbook

This runbook reproduces AgentPerf M2 on a fresh Linux machine with one supported
NVIDIA GPU. It does not require H100-scale hardware.

The goal is empirical validation, not a benchmark leaderboard:

1. run a controlled agent-like workload against real vLLM;
2. capture real per-request telemetry;
3. run AgentPerf on the baseline;
4. apply only prompt/context reorganization;
5. replay the same workload;
6. compare real measured behavior.

## Hardware And Software

Recommended minimum:

- Linux x86_64 host;
- one NVIDIA GPU supported by current vLLM and PyTorch;
- CUDA-capable driver visible through `nvidia-smi`;
- Python 3.11 or 3.12;
- enough VRAM for `Qwen/Qwen3-0.6B` with an 8K context.

Default model:

- `Qwen/Qwen3-0.6B`

Reasoning:

- small enough for modest single-GPU machines;
- supports chat-style prompting;
- long enough context for observable stable-prefix behavior;
- cheap to run for repeated measurements.

If this model is unavailable in the execution environment, choose another small
chat model that fits comfortably on one GPU and supports the required context.
Record the substitution in `artifacts/real_vllm/environment.json`.

## Clone And Setup

```bash
git clone <agentperf-repo-url>
cd AgentPerf
git switch feature/vllm-real-validation
bash scripts/remote_vllm/setup.sh
```

The setup script installs AgentPerf in editable mode plus vLLM, OpenAI client
support, and Requests.

## Start vLLM

Terminal 1:

```bash
MODEL=Qwen/Qwen3-0.6B \
SERVED_MODEL_NAME=agentperf-vllm-demo \
MAX_MODEL_LEN=8192 \
bash scripts/remote_vllm/start_server.sh
```

Important server flags used by the script:

- `--enable-prefix-caching`
- `--prefix-caching-hash-algo sha256_cbor`
- `--enable-prompt-tokens-details`
- `--enable-per-request-metrics`

Do not change scheduler, batching, model, or GPU allocation between baseline
and optimized runs.

## Smoke Test Required Telemetry

Terminal 2:

```bash
BASE_URL=http://localhost:8000/v1 \
MODEL=agentperf-vllm-demo \
bash scripts/remote_vllm/smoke_test.sh
```

The smoke test fails if the response lacks critical fields:

- response ID;
- prompt/completion token counts;
- prompt token IDs;
- generated token IDs;
- `queue_time_ms`;
- `time_to_first_token_ms`;
- `generation_time_ms`;
- `mean_itl_ms`.

It also captures `/metrics` into `artifacts/real_vllm/smoke/` for aggregate
inspection. Prometheus metrics are workload/server-level context, not
per-request evidence.

## Run The Experiment

```bash
BASE_URL=http://localhost:8000/v1 \
MODEL=agentperf-vllm-demo \
WARMUPS=3 \
REPETITIONS=10 \
OUTPUT_DIR=artifacts/real_vllm \
bash scripts/remote_vllm/run_experiment.sh
```

Protocol:

- 3 warmup repetitions per configuration;
- 10 measured repetitions per configuration;
- 3 controlled tasks per repetition;
- baseline and optimized use the same model, sampling parameters, output limit,
  and logical task content.

Sampling configuration:

- `temperature=0`;
- `max_tokens=64`;
- `stream=false`;
- `return_token_ids=true`;
- `return_prompt_text=true`;
- `n=1`.

## Workload Design

The runner uses a small agent-like incident-analysis workload:

- stable system instructions;
- stable runbook/reference content;
- dynamic incident request;
- compact JSON output request.

Baseline configuration:

- stable policy appears first;
- dynamic request-specific content appears before a large stable runbook section;
- this represents a plausible harness/context-layout mistake that weakens exact
  reusable-prefix structure.

Optimized configuration:

- stable policy and stable runbook are combined into one consistent prefix;
- dynamic request-specific content comes after the stable prefix;
- task semantics are unchanged.

## Artifact Layout

Expected output:

```text
artifacts/real_vllm/
  environment.json
  comparison.json
  smoke/
    chat_completion.json
    models.json
    prometheus_metrics.txt
    prometheus_relevant_metrics.txt
  baseline/
    raw/
      recording.json
    normalized/
      trace.json
    report.txt
  optimized/
    raw/
      recording.json
    normalized/
      trace.json
    report.txt
```

Raw recordings contain vLLM responses. Normalized traces contain AgentPerf's
schema. Reports include finding provenance.

## Package Artifacts

```bash
ARTIFACT_DIR=artifacts/real_vllm \
PACKAGE=artifacts/agentperf-real-vllm-artifacts.tgz \
bash scripts/remote_vllm/collect_artifacts.sh
```

Before committing any artifact, inspect size and contents. Do not commit model
weights, logs with secrets, or large generated files. A small sanitized recorded
real telemetry fixture may be committed only if it is clearly labeled as real
telemetry and includes enough environment metadata.

## Analysis Expectations

The strongest expected story is:

```text
baseline:
  high repeated stable context
  low cached-token ratio
  high scheduled-to-first-token / prefill-path latency
    -> PREFIX_CACHE_OPPORTUNITY

optimized:
  stable context moved into consistent prefix
  cached-token ratio increases
  scheduled-to-first-token decreases
  finding severity decreases or disappears
```

Do not force that result. If vLLM telemetry or real measurements contradict the
detector assumptions, update `docs/DETECTOR_CALIBRATION.md` and report the
failure mode.

## Metrics To Compare

At minimum compare baseline vs optimized:

- input tokens;
- output tokens;
- cached-token ratio;
- queue latency P50/P95;
- scheduled-to-first-token P50/P95;
- generation latency P50/P95;
- TPOT / ITL P50/P95;
- client-observed total request latency P50/P95;
- task output correctness by manual review.

Do not claim statistical significance from this small run.
