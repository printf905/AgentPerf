# External Agent Benchmark

Status: M5 local external-agent integration benchmark.

This benchmark asks whether AgentPerf can observe an agent that was built with
an external framework rather than AgentPerf's internal research-agent harness.
It is not a serving-performance benchmark and it does not use a GPU.

## Agent

Framework: OpenAI Agents SDK (`openai-agents-python` optional dependency).

Example:
`examples/external_agents/openai_agents_support_triage.py`

The agent is a small support-triage workflow:

```text
user support request
    -> Support Triage Agent LLM step
    -> lookup_policy(query) function tool
    -> Support Triage Agent LLM step
    -> final routed answer
```

The workload uses the real OpenAI Agents SDK `Agent`, `Runner`, and
`function_tool` lifecycle. The model is a deterministic local scripted SDK
`Model` implementation so the benchmark can run without OpenAI API credentials,
network calls, or GPU rental.

This design intentionally tests framework integration, prompt-component
normalization, tool-result provenance, and graceful agent-only analysis. It does
not test vLLM serving correlation.

## Workload

Tasks: 10 deterministic support requests.

Domains:

- refunds;
- account security;
- billing duplicates;
- integration rate-limit increases.

Tool: deterministic local `lookup_policy(query)` over four policy passages.

Expected behavior: the agent should call the policy lookup tool and return:

```text
ROUTE=<route>; POLICY=<policy id>; ACTION=<short action>
```

Evaluation: rule-based scorer. Each answer receives:

- 0.5 for expected policy ID;
- 0.5 for expected route.

No LLM judge is used.

## Running

Install the optional integration dependency:

```bash
pip install -e ".[dev,openai-agents]"
```

Run the benchmark:

```bash
python examples/external_agents/openai_agents_support_triage.py \
  --output-dir /tmp/agentperf_m5_openai_agents
```

Artifacts written:

- `openai_agents_export.json`: raw SDK trace/span export preserved by the
  adapter;
- `agentperf_trace.json`: normalized AgentPerf trace;
- `agentperf_report.txt`: terminal report;
- `summary.json`: task-level correctness summary.

## Observed Local Result

Date: local M5 development run.

| Metric | Value |
| --- | ---: |
| Tasks | 10 |
| LLM calls | 20 |
| Tool calls | 10 |
| Correlated serving requests | 0 |
| Input tokens | 1,604 |
| Output tokens | 153 |
| Component processed tokens | 1,320 |
| Component unique tokens | 310 |
| Mean score | 1.000 |
| Pass rate | 100% |

Token attribution used approximate tokenization:

| Component | Processed | Unique | Share |
| --- | ---: | ---: | ---: |
| System | 680 | 34 | 51.5% |
| User | 264 | 132 | 20.0% |
| Tool schema | 20 | 1 | 1.5% |
| Tool result | 266 | 107 | 20.2% |
| Other | 90 | 36 | 6.8% |

AgentPerf emitted low-severity `CONTEXT_DUPLICATION` with
`materiality=OBSERVATION` because the short system instructions and repeated
prompt scaffolding recur across all calls.

Materiality interpretation: this is an observation, not a high-confidence
optimization story. The whole run processed only 1,604 input tokens and had no
serving telemetry. AgentPerf did not find a material external-agent issue worth
optimizing in this tiny support-triage workload.

No optimization/replay was applied for M5 because doing so would require
manufacturing a pathology that did not naturally matter in the observed run.

## Integration Cost

The example uses approximately five conceptual integration changes:

1. import `TraceRecorder`, `AgentPerfModelWrapper`, and
   `OpenAIAgentsTraceProcessor`;
2. instantiate a recorder;
3. register a tracing processor with `set_trace_processors`;
4. wrap the SDK model;
5. run the agent inside `recorder.as_current()` and write artifacts.

No OpenAI Agents SDK internals were modified. The framework tool behavior was
unchanged. Serving correlation was not required.

## Limitations

- The model is scripted for determinism, so this is not a model-quality
  benchmark.
- The local tool corpus is intentionally small.
- No vLLM telemetry is present; serving/cache/prefill findings correctly remain
  unavailable.
- The workload is useful for integration validation but too small to support a
  material performance recommendation.
