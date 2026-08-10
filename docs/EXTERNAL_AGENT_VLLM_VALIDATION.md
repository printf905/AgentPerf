# External Agent + vLLM Cross-Layer Validation

This document records the M6 validation path and first real result for an
external OpenAI Agents SDK agent running through a real vLLM OpenAI-compatible
backend.

## Agent and Framework

- Framework: OpenAI Agents SDK (`openai-agents-python`).
- Agent: the existing deterministic support-triage agent from
  `examples/external_agents/openai_agents_support_triage.py`.
- Tool: `lookup_policy`.
- Tasks: the existing M5 deterministic support-triage task set, normally run
  with `--task-limit 5` to `--task-limit 10`.

The M6 runner reuses the M5 task corpus, scoring function, tool, and agent
instructions. It does not enlarge tool outputs or add artificial token waste.

## Backend, Model, and GPU

The final successful run used:

- Backend: vLLM `0.26.0+cu129`.
- GPU: NVIDIA RTX 3090 24GB on Runpod community cloud.
- Image/runtime: `runpod/pytorch:1.0.3-cu1281-torch291-ubuntu2404` plus the
  pinned vLLM wheel from `scripts/remote_vllm/setup.sh`.
- Model: `Qwen/Qwen3-4B`.
- Served model name: `agentperf-vllm-demo`.

The initial preferred model, `Qwen/Qwen3-0.6B`, and an intermediate
`Qwen/Qwen3-1.7B` attempt both produced explicitly correlated vLLM requests,
but did not naturally execute the OpenAI Agents SDK tool lifecycle under
`tool_choice=auto`. They returned empty or reasoning-style text without
framework tool calls. The final run therefore used the previously validated
Qwen3-4B model and a narrow first-turn `lookup_policy` tool-choice control to
exercise the existing support-triage tool lifecycle. This is a compatibility
control for vLLM/Qwen tool calling; it is not a new AgentPerf detector and does
not enlarge the workload or introduce artificial token waste.

Start vLLM with tool calling enabled:

```bash
source .venv/bin/activate
vllm serve Qwen/Qwen3-4B \
  --served-model-name agentperf-vllm-demo \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.80 \
  --enable-prefix-caching \
  --prefix-caching-hash-algo sha256_cbor \
  --enable-prompt-tokens-details \
  --enable-per-request-metrics \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_xml
```

The preferred validation GPU is one inexpensive 24GB GPU, using the previously
successful vLLM container/runtime path documented in `docs/REAL_VLLM_RUNBOOK.md`.

Before running the agent workload, use bounded preflight:

```bash
python - <<'PY'
import torch
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))
PY
timeout 60 python -c "import vllm; print(vllm.__version__)"
MODEL=agentperf-vllm-demo bash scripts/remote_vllm/smoke_test.sh
```

If setup fails twice, stop and report the failure instead of sampling more
nodes.

## Correlation Mechanism

M6 uses explicit request IDs. It does not use timestamp matching.

1. `AgentPerfModelWrapper` creates an AgentPerf request ID before each SDK model
   call, for example `agentperf-m6-openai-agents-llm-1-<nonce>`.
2. The wrapper injects that ID into the SDK `ModelSettings.extra_body` as
   `request_id`.
3. `OpenAIChatCompletionsModel` sends the extra body through the OpenAI SDK to
   vLLM's OpenAI-compatible endpoint.
4. `OpenAICompatibleRequestRecorder` captures the raw HTTP request/response via
   an injected `httpx.AsyncClient` response hook.
5. `build_vllm_recording_from_agent_run` joins agent-layer `LLMCall` records to
   vLLM responses by exact `client_request_id == llm_request_id`.
6. `VLLMTelemetryProvider` normalizes the joined data into one AgentPerf run
   containing agent steps, tool calls, LLM calls, and serving requests.

The expected proof shape is:

```text
AgentRun m6-openai-agents-vllm-cross-layer
  AgentStep task-refund-1
    LLMCall openai-agents-llm-1
      llm_request_id=agentperf-m6-openai-agents-llm-1-...
      serving_request_id=<vLLM response id>
    ToolCall lookup_policy
    LLMCall openai-agents-llm-2
      llm_request_id=agentperf-m6-openai-agents-llm-2-...
      serving_request_id=<vLLM response id>
  ServingRequest <vLLM response id>
    llm_request_id=agentperf-m6-openai-agents-llm-1-...
```

In the real M6 run, the final summary included exact request ID joins such as:

```text
LLMCall openai-agents-llm-1
  llm_request_id      agentperf-m6-openai-agents-llm-1-95f7f04f
  serving_request_id  chatcmpl-agentperf-m6-openai-agents-llm-1-95f7f04f

LLMCall openai-agents-llm-2
  llm_request_id      agentperf-m6-openai-agents-llm-2-cdc295a2
  serving_request_id  chatcmpl-agentperf-m6-openai-agents-llm-2-cdc295a2
```

## Runner

Run the validation workload against a live vLLM server:

```bash
BASE_URL=http://localhost:8000/v1 \
MODEL=agentperf-vllm-demo \
TASK_LIMIT=5 \
OUTPUT_DIR=artifacts/m6_external_vllm \
bash scripts/remote_vllm/run_external_agent_vllm_cross_layer.sh
```

Equivalent direct invocation:

```bash
python scripts/run_external_agent_vllm_cross_layer.py \
  --base-url http://localhost:8000/v1 \
  --model agentperf-vllm-demo \
  --task-limit 5 \
  --output-dir artifacts/m6_external_vllm
```

## Artifacts

The runner writes:

- `openai_agents_export.json`: OpenAI Agents SDK trace export.
- `agentperf_agent_trace.json`: agent-layer AgentPerf trace.
- `vllm_recording.json`: raw captured vLLM response bundle joined by explicit
  request ID.
- `unified_trace.json`: normalized AgentPerf run with agent and serving layers.
- `unified_report.txt`: terminal AgentPerf report with provenance.
- `summary.json`: task counts, call counts, correlation success rate, token
  counts, serving timings, findings, and one trace example.

## Telemetry Fields

When vLLM returns them, AgentPerf ingests:

- response ID;
- prompt tokens;
- completion tokens;
- prompt token IDs;
- generated token IDs;
- queue time;
- scheduled-to-first-token;
- generation time;
- mean ITL;
- cached prompt tokens.

`scheduled-to-first-token` remains labeled as a prefill path proxy. It is not
reported as pure GPU prefill kernel time.

## Real Result

Final successful run:

| Metric | Value |
| --- | ---: |
| Tasks | 5 |
| LLM calls | 10 |
| Tool calls | 5 |
| vLLM serving requests | 10 |
| Explicit correlation success | 100% |
| Input tokens | 2,955 |
| Output tokens | 770 |
| Cached prompt tokens | 2,848 |
| Queue latency P50 / P95 | 0.01 ms / 0.02 ms |
| Scheduled-to-first-token P50 / P95 | 16.52 ms / 36.26 ms |
| Decode latency P50 / P95 | 803.97 ms / 1,491.08 ms |
| Mean task score | 0.700 |
| Pass rate | 60% |

The unified report emitted one low-severity finding:
`PREFILL_PATH_DOMINANCE`. This was correctly not material: TTFT P95 was
36.26 ms and P95 uncached input volume was only 15 tokens. No material
actionable performance issue was found, which is acceptable for M6 because the
goal is cross-layer integration validation.

Token attribution from the real run:

| Component | Processed tokens | Unique tokens | Share |
| --- | ---: | ---: | ---: |
| Tool Result | 455 | 134 | 44.9% |
| System | 340 | 34 | 33.5% |
| User | 124 | 62 | 12.2% |
| Other | 85 | 85 | 8.4% |
| Tool Schema | 10 | 1 | 1.0% |

Artifacts were preserved locally under
`artifacts/m6_external_vllm/artifacts/m6_external_vllm_final/` during the
validation run. The large artifacts directory remains git-ignored; commit only
small sanitized fixtures if they are needed later.

## Missing Fields

The current vLLM OpenAI-compatible response path does not expose request-level
KV-cache capacity, request-level KV-cache evictions, or pure prefill kernel time
separate from scheduled-to-first-token.

## Findings and Release Gate

M6 does not require a material finding. A successful run may legitimately report
only low-severity or observation-level issues, or no material actionable issue.

The release-readiness claim is justified only after a real GPU run demonstrates:

- OpenAI Agents SDK agent runs normally;
- LLM calls reach real vLLM;
- every expected LLM call has a matching vLLM serving request by explicit ID;
- tool calls and LLM calls remain in the same unified trace;
- tests, ruff, and mypy pass;
- the GPU pod is cleaned up.

Validation status:

- request-ID propagation path: implemented and unit-tested;
- OpenAI-compatible HTTP capture path: implemented and unit-tested;
- unified recording merge: implemented and unit-tested;
- runner help/import path: verified locally;
- real GPU/vLLM execution: completed;
- Runpod cleanup: completed, `runpodctl pod list` returned `[]`.
