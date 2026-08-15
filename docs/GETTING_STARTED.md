# Getting Started

AgentPerf can be used without a GPU, API key, model download, or source checkout
once it is installed as a package.

AgentPerf has not yet been published to PyPI. Until the first PyPI upload, use a
local wheel or editable source install.

Once published on PyPI:

```bash
pip install agentperf
agentperf demo
```

From a source checkout:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
agentperf demo
```

## What The Demo Does

`agentperf demo` runs a deterministic local support-policy agent twice:

- a baseline that carries large tool output into downstream LLM calls;
- a candidate that carries compact policy evidence;
- deterministic task quality for both runs;
- `agentperf compare` over the resulting artifacts;
- a local standalone HTML profiler report;
- a local standalone HTML replay-comparison report.

The default output directory is:

```text
./agentperf-demo/
```

Useful follow-up commands:

```bash
agentperf doctor agentperf-demo/baseline
agentperf report agentperf-demo/baseline --output agentperf-demo/report.html
agentperf compare agentperf-demo/baseline agentperf-demo/candidate \
  --format html \
  --output agentperf-demo/comparison.html
agentperf compare agentperf-demo/baseline agentperf-demo/candidate
agentperf check \
  agentperf-demo/baseline \
  agentperf-demo/candidate \
  --policy agentperf-demo/agentperf-regression.yaml
```

The demo is an onboarding example, not a benchmark claim.

## Profile Your Own Agent

For a framework-free Python agent, start with:

```python
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool

with ExperimentSession(output_path=Path("runs/baseline"), workload_id="support-agent") as exp:
    with trace_run(task_id="ticket-001"):
        with trace_llm(
            model="my-model",
            components={"system": system_prompt, "user": user_prompt},
        ) as call:
            response = invoke_model(...)
            call.record_response(
                output=response.text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                request_id=response.request_id,
            )

        with trace_tool("lookup_policy") as tool:
            result = lookup_policy(...)
            tool.record_output(result)

    exp.record_task_result(task_id="ticket-001", passed=True, quality_score=1.0)
```

Then run:

```bash
agentperf doctor runs/baseline
agentperf report runs/baseline --output report.html
```

`doctor` distinguishes agent-level readiness from optional cross-layer serving
readiness. Missing vLLM/SGLang telemetry does not invalidate normal agent-level
profiling.

## Next Documentation

- [Bring Your Own Agent](BRING_YOUR_OWN_AGENT.md)
- [LangGraph Integration](LANGGRAPH_INTEGRATION.md)
- [CI Integration](CI_INTEGRATION.md)
- [HTML Report](HTML_REPORT.md)
- [Token Accounting](TOKEN_ACCOUNTING.md)
