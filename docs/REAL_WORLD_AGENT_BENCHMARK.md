# Real-World Agent Benchmark

Status: M7 benchmark defined for `mini-swe-agent`.

## Purpose

M7 asks whether AgentPerf can profile an existing agent whose behavior was not
designed around AgentPerf. This benchmark uses `mini-swe-agent` as the upstream
agent and records its natural model/action/observation loop.

This is not a SWE-bench claim. It is a small, bounded profiling workload for
integration and profiler generalization.

## Agent

Target: `mini-swe-agent` `DefaultAgent`.

Upstream purpose: solve coding tasks by repeatedly asking a model for bash
actions, executing those actions in an environment, appending observations to
history, and continuing until submission.

Integration file:

- `agentperf/integrations/mini_swe_agent.py`

Runner:

- `examples/real_world_agents/mini_swe_agent_repo_repair.py`

The adapter wraps:

- the mini-SWE-agent model boundary, recording each `query(messages)` as an
  AgentPerf `LLMCall`;
- the mini-SWE-agent environment boundary, recording each bash action as an
  AgentPerf `ToolCall`.

No upstream framework internals are patched. The agent still uses upstream
`DefaultAgent`, its message history, its action execution loop, and its normal
submission behavior.

## Workload

Tasks: five small repository-repair tasks.

Each task creates a tiny local Python repository with:

- one buggy implementation file;
- one failing pytest file;
- a natural issue-style instruction.

The agent's expected lifecycle is:

```text
task instruction
  -> inspect repository
  -> inspect failing test
  -> inspect implementation
  -> edit file
  -> run pytest
  -> submit
```

The checked-in local mode uses mini-SWE-agent's official deterministic test
model. This keeps the benchmark reproducible without API credentials, live
network access, or GPU rental. It still exercises the upstream agent loop and
local environment execution path.

Optional real-model mode can use mini-SWE-agent's LiteLLM model path:

```bash
python examples/real_world_agents/mini_swe_agent_repo_repair.py \
  --mode litellm \
  --model-name <litellm-model-name> \
  --output-dir /tmp/agentperf_m7_mini_swe_real_model
```

For a local vLLM endpoint, use the model naming/API-base configuration
recommended by mini-SWE-agent/LiteLLM. Do not use timestamp-only serving
correlation.

## Running The Local Profile

Install the optional dependency:

```bash
pip install -e ".[dev,mini-swe-agent]"
```

Run:

```bash
python examples/real_world_agents/mini_swe_agent_repo_repair.py \
  --output-dir /tmp/agentperf_m7_mini_swe
```

Artifacts:

- `agentperf_trace.json`: normalized AgentPerf trace;
- `agentperf_report.txt`: terminal report;
- `summary.json`: task-level pass/fail summary;
- `repos/*/mini_swe_trajectory.json`: upstream mini-SWE-agent trajectories.

## Evaluation

Task success is deterministic:

- after the agent submits, the runner executes `pytest -q` in the task repo;
- a task passes when pytest exits with code 0.

No LLM judge is used.

## Metrics

AgentPerf reports:

- task count;
- LLM calls;
- bash/tool calls;
- processed input tokens;
- output tokens;
- component token attribution;
- context growth by LLM call;
- tool-output reinjection;
- existing findings from the frozen detector set.

Serving fields are unavailable in the local deterministic run:

- queue latency;
- scheduled-to-first-token;
- generation latency;
- prefix-cache tokens;
- KV/cache metrics.

## Controls

- The agent target is upstream `mini-swe-agent`.
- The integration does not patch framework internals.
- The local benchmark avoids live web search and external APIs.
- The detector set is unchanged from the existing AgentPerf profiler.
- The benchmark intentionally does not add a pathology to trigger a finding.

## Limitations

- The checked-in local run uses a deterministic model, so it is not a model
  quality benchmark.
- The five repair tasks are small and created for bounded local profiling; they
  are not an existing SWE-bench slice.
- Agent-layer results can show context and tool-output accounting, but serving
  telemetry is absent unless the optional real-model/vLLM path is run.
- The benchmark is meant to test generalization to an existing agent
  architecture, not to measure broad coding-agent performance.
