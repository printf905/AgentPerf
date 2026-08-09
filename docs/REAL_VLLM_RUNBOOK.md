# Real vLLM Validation Runbook

This runbook reproduces AgentPerf M2 on a fresh Linux machine with one supported
NVIDIA GPU. It does not require H100-scale hardware.

For the first completed live execution result, see
`docs/REAL_VLLM_RESULTS.md`.

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
- NVIDIA driver branch compatible with the selected wheel's CUDA major version;
  for the pinned CUDA 12.9 vLLM `0.26.0` wheel, driver branch `>= 525` is the
  minimum CUDA 12.x minor-version compatibility requirement;
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
support, and Requests. It uses `uv` and the official vLLM release wheel instead
of an unconstrained `pip install vllm`.

Default pinned vLLM installation:

```bash
uv pip install \
  https://github.com/vllm-project/vllm/releases/download/v0.26.0/vllm-0.26.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl \
  --extra-index-url https://download.pytorch.org/whl/cu129 \
  --torch-backend=cu129
```

The script records `nvidia-smi`, driver version, host-reported CUDA
compatibility, Python version, selected vLLM wheel, PyTorch index, and installed
`torch` / `vllm` versions under `artifacts/real_vllm/setup/`.

Important CUDA terminology:

- the selected vLLM/PyTorch wheel has a CUDA runtime/toolkit target, such as
  CUDA `12.9`;
- `nvidia-smi` reports the maximum CUDA API version supported by the installed
  driver, but this label is not an exact toolkit minor-version requirement;
- NVIDIA driver version is the hard compatibility input;
- CUDA minor-version compatibility allows CUDA 12.x applications to run on
  CUDA 12-compatible drivers in the documented driver range, subject to feature
  and PTX limitations.

Before any model download or vLLM server startup, setup validates:

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda)"
python -c "import vllm; print(vllm.__version__)"
nvidia-smi
python - <<'PY'
import torch
assert torch.cuda.is_available()
print(torch.cuda.get_device_name(0))
x = torch.ones(1, device="cuda")
print(x)
PY
```

If the host driver reports CUDA compatibility below the selected vLLM wheel's
CUDA target, that is recorded but is not treated as an automatic failure. For a
CUDA 12.x wheel, the script rejects only drivers below branch `525`, then treats
the real PyTorch CUDA allocation probe as authoritative. For vLLM `0.26.0`, the
official x86_64 release assets include a `+cu129` wheel; an official `+cu128`
wheel was not found for this release. Do not override `VLLM_CUDA_VERSION` unless
you have verified that the matching official wheel exists.

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

## Troubleshooting CUDA Wheel Mismatches

A previous Runpod attempt failed before real validation because the environment
silently installed an incompatible CUDA stack:

```text
GPU: NVIDIA RTX A5000
driver: 570.211.01
driver-reported CUDA compatibility: 12.8
installed vLLM: 0.26.0
installed torch: 2.11.0+cu130
torch CUDA runtime: 13.0
failure: CUDA 13.0 runtime required a newer NVIDIA driver
```

The root cause was an unconstrained vLLM install path that pulled the default
CUDA 13.0 PyTorch/vLLM dependency set. CUDA 13.x requires a newer driver branch
than the observed `570.211.01` host driver. Do not assume the CUDA version in a
Runpod PyTorch template remains intact after `pip install vllm`.

For this milestone, use a CUDA-specific vLLM wheel and matching PyTorch index.
With vLLM `0.26.0`, the setup script defaults to the official CUDA 12.9 wheel:

```text
vllm-0.26.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl
```

If `nvidia-smi` reports CUDA `12.8` on a driver branch such as `570`, do not
reject the CUDA 12.9 wheel solely because the label is below `12.9`. NVIDIA CUDA
minor-version compatibility is based on the driver branch, not exact equality
with the toolkit minor version. The setup script records the label, installs the
pinned CUDA 12.9 wheel when the driver branch is compatible, and lets the actual
PyTorch CUDA probe decide whether the runtime works.

If that probe fails, stop immediately and preserve the exact exception from
`artifacts/real_vllm/setup/` before attempting model download or vLLM startup.
