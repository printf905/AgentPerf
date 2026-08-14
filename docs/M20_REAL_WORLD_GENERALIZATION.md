# M20 Real-World Generalization

## Goal

M20 asks whether AgentPerf remains useful and non-misleading on heterogeneous
agent workloads that were not built solely to make one detector look good.

This is a small controlled engineering validation. It is not a benchmark suite,
not a detector-accuracy study, and not evidence of universal agent-framework
coverage.

The main principle added by M20 is:

```text
a technically correct finding is not necessarily a useful finding
```

## Workloads

### A. Coding / Repository-Repair Agent

Workload: `mini-SWE-agent` `DefaultAgent` on five bounded local repair tasks.

Why selected:

- existing upstream coding-agent control loop;
- inspect/read/edit/test/submit structure;
- variable prompt growth across tasks;
- shell/environment tool calls;
- existing AgentPerf mini-SWE wrapper and historical M7 validation.

Command:

```bash
HOME=/tmp/agentperf-mini-home \
python examples/real_world_agents/mini_swe_agent_repo_repair.py \
  --output-dir /tmp/agentperf-m20-mini-swe \
  --mode deterministic
```

Observed:

- tasks: 5;
- task success: 5 / 5;
- LLM calls: 30;
- tool/environment calls: 30;
- input tokens: 25,318;
- finding: `CROSS_RUN_SHARED_SCAFFOLD`;
- agent-level readiness: `READY`;
- cross-layer readiness: `NOT_APPLICABLE`.

No replay was performed. The only finding is expected cross-task scaffold and
does not justify changing the external agent.

### B. Tool-Heavy Multi-Step Agent

Workload: deterministic local research/support agent in
`examples/m20_tool_heavy_agent/run.py`.

Why selected:

- multiple meaningful tools per task;
- varied tool-result sizes;
- retrieved context plus policy/tool-result context;
- one repeated evidence path that is plausibly reducible;
- one smaller repeated audit path that is structurally necessary;
- uses the public framework-free M19 instrumentation API.

Commands:

```bash
python examples/m20_tool_heavy_agent/run.py \
  --variant raw \
  --output-root /tmp/agentperf-m20-tool-heavy

python examples/m20_tool_heavy_agent/run.py \
  --variant optimized \
  --output-root /tmp/agentperf-m20-tool-heavy
```

Observed raw artifact:

- tasks: 4;
- task success: 4 / 4;
- LLM calls: 12;
- tool calls: 11;
- input tokens: 11,973;
- component processed tokens: 11,973;
- retrieved-context tokens: 6,802;
- tool-result tokens: 4,694;
- finding: `TOOL_OUTPUT_BLOAT`;
- agent-level readiness: `READY`;
- cross-layer readiness: `NOT_APPLICABLE`.

Replay:

```bash
agentperf compare \
  /tmp/agentperf-m20-tool-heavy/raw \
  /tmp/agentperf-m20-tool-heavy/optimized

agentperf check \
  /tmp/agentperf-m20-tool-heavy/raw \
  /tmp/agentperf-m20-tool-heavy/optimized \
  --policy examples/policies/m20-tool-heavy-regression.yaml
```

Result:

- verdict: `ACCEPT`;
- quality: `1.000 -> 1.000`;
- provider input tokens: `11,973 -> 1,541`;
- component processed tokens: `11,973 -> 1,541`;
- retrieved-context tokens: `6,802 -> 140`;
- tool-result tokens: `4,694 -> 924`;
- finding lifecycle: `TOOL_OUTPUT_BLOAT MEDIUM -> absent`.

This validates one actionable finding through controlled replay without changing
the evaluator.

### C. Framework Agent

Workload: deterministic OpenAI Agents SDK support-triage agent.

Why selected:

- real framework lifecycle instrumentation;
- OpenAI Agents SDK tool path;
- task-level quality;
- existing deterministic local model boundary;
- no paid API, GPU, or serving backend required.

Commands:

```bash
python examples/external_agents/openai_agents_support_triage.py \
  --output-dir /tmp/agentperf-m20-openai-standard \
  --instruction-style standard

python examples/external_agents/openai_agents_support_triage.py \
  --output-dir /tmp/agentperf-m20-openai-compact \
  --instruction-style compact
```

Observed standard artifact:

- tasks: 10;
- task success: 10 / 10;
- LLM calls: 20;
- tool calls: 10;
- provider input tokens: 1,604;
- component processed tokens: 1,320;
- finding: `CONTEXT_DUPLICATION` / `LOW`;
- agent-level readiness: `READY`;
- cross-layer readiness: `NOT_APPLICABLE`.

Replay:

```bash
agentperf compare \
  /tmp/agentperf-m20-openai-standard/agentperf_artifact \
  /tmp/agentperf-m20-openai-compact/agentperf_artifact
```

Result:

- verdict: `NO_MATERIAL_CHANGE`;
- quality: `1.000 -> 1.000`;
- provider input tokens: `1,604 -> 1,604`;
- component processed tokens: `1,320 -> 1,160`;
- system component tokens: `680 -> 520`;
- finding lifecycle: `CONTEXT_DUPLICATION LOW -> LOW`.

The finding is technically correct but not an actionable bottleneck in this
small local workload.

## Generalization Matrix

Generated from `docs/m20_finding_reviews.json` by:

```bash
python scripts/m20_generalization_report.py
```

```text
Capability                   coding_agent_mini_swe         tool_heavy_research_support   openai_agents_support_triage
Tasks captured               YES                           YES                           YES
Run structure                YES                           YES                           YES
LLM timing                   FULL                          FULL                          FULL
Tool timing                  FULL                          FULL                          FULL
Provider usage               FULL                          FULL                          FULL
Component attribution        FULL                          FULL                          FULL
Task quality                 YES                           YES                           YES
Serving correlation          NOT_APPLICABLE                NOT_APPLICABLE                NOT_APPLICABLE
Context findings             YES                           YES                           YES
Replay validation            NOT_PERFORMED                 YES                           PARTIAL
```

All three workloads were agent-level `READY`. Cross-layer readiness was
`NOT_APPLICABLE` because no serving telemetry was recorded in the primary M20
local path.

## Finding Review Methodology

M20 uses a manual engineering-review taxonomy:

- `ACTIONABLE`: a reasonable agent engineer would test a change.
- `VALID_NON_ACTIONABLE`: the finding is correct, but not worth changing for
  this workload.
- `EXPECTED_STRUCTURAL`: the repeated/costly structure is inherent to the
  intended agent behavior.
- `INSUFFICIENT_EVIDENCE`: AgentPerf exposes a plausible signal, but evidence
  cannot support a stronger conclusion.
- `FALSE_POSITIVE`: the finding is technically misleading for the workload.

The review artifact is `docs/m20_finding_reviews.json`. It records workload
identity, task IDs, finding IDs, review classifications, rationales, and replay
evidence when available.

## Results

Reviewed findings:

```text
ACTIONABLE                       1
VALID_NON_ACTIONABLE             1
EXPECTED_STRUCTURAL              1
INSUFFICIENT_EVIDENCE            0
FALSE_POSITIVE                   0
```

Representative examples:

- `ACTIONABLE`: `TOOL_OUTPUT_BLOAT` in the tool-heavy workload. Compacting
  reducible retrieved/policy evidence preserved quality and resolved the
  finding.
- `VALID_NON_ACTIONABLE`: `CONTEXT_DUPLICATION` in the OpenAI Agents SDK
  workload. The repeated prompt structure is real, but the workload is tiny and
  lacks serving evidence for a stronger operational claim.
- `EXPECTED_STRUCTURAL`: `CROSS_RUN_SHARED_SCAFFOLD` in mini-SWE-agent. The
  repeated scaffold appears across independent repair tasks and is explicitly
  not treated as removable within-task waste.

These are counts from three small M20 workloads, not universal detector rates.

## Detector Lessons

`CONTEXT_DUPLICATION` and `CROSS_RUN_SHARED_SCAFFOLD` generalized cleanly to
variable agent structures. The M7.1/M18 distinction between same-run duplication
and cross-run scaffold remained important for mini-SWE-agent.

`TOOL_OUTPUT_BLOAT` produced the clearest actionable M20 result. The first
tool-heavy draft also showed why review is necessary: a large repeated audit log
can be structurally required even when repeated processing is technically true.
The final workload keeps that necessary path below the material bloat threshold
and uses replay to validate the reducible path.

Cacheability and prefill-path findings did not run on the three primary M20
workloads because no serving telemetry was recorded. This is correct missing
evidence behavior, not negative cache evidence.

No detector correctness bug was found during M20. No thresholds were changed.

## Replay Results

### Tool-Heavy Replay

Verdict: `ACCEPT`.

The raw run carried large retrieved/policy evidence into reviewer and final
prompts. The optimized run carried compact evidence summaries while preserving
the evaluator and task semantics.

Quality stayed at `1.000 -> 1.000`. Component processing fell from `11,973` to
`1,541` tokens, and `TOOL_OUTPUT_BLOAT` resolved.

### OpenAI Agents SDK Replay

Verdict: `NO_MATERIAL_CHANGE`.

The compact-instruction candidate preserved quality and reduced system-component
processing (`680 -> 520`), while provider input tokens remained unchanged
(`1,604 -> 1,604`). This is useful accounting evidence but not a material
optimization under the default replay rule.

### Coding Agent

No candidate was created. The emitted finding was expected structural scaffold,
not a safe optimization target.

## Failure And Partial Paths

The mini-SWE deterministic tasks all succeeded in this run. The M20 tests add a
heterogeneous artifact with one failed task to verify that failed task outcomes
do not corrupt completeness denominators or agent-level readiness.

M20 did not manufacture exotic failures solely to increase coverage.

## What AgentPerf Can Currently Claim

Across three small heterogeneous local workload classes, AgentPerf captured
varied agent execution structures, computed readiness consistently, and produced
technically valid findings that could be manually separated into actionable,
valid-but-non-actionable, and expected-structural categories.

This supports a conservative claim of integration and diagnostic
generalization on the tested workloads.

## What AgentPerf Cannot Claim

AgentPerf cannot claim:

- universal detector accuracy;
- universal false-positive rate;
- performance savings across agents;
- SWE-bench validation;
- cross-layer readiness for workloads without serving telemetry;
- support for untested frameworks;
- automatic distinction between every necessary and reducible repeated context
  pattern.

## Reproducibility Commands

Summary:

```bash
python scripts/m20_generalization_report.py
```

Mini-SWE:

```bash
HOME=/tmp/agentperf-mini-home \
python examples/real_world_agents/mini_swe_agent_repo_repair.py \
  --output-dir /tmp/agentperf-m20-mini-swe \
  --mode deterministic

agentperf doctor /tmp/agentperf-m20-mini-swe/agentperf_artifact
agentperf report /tmp/agentperf-m20-mini-swe/agentperf_artifact \
  --output /tmp/agentperf-m20-mini-swe.html
```

Tool-heavy:

```bash
python examples/m20_tool_heavy_agent/run.py --variant raw \
  --output-root /tmp/agentperf-m20-tool-heavy
python examples/m20_tool_heavy_agent/run.py --variant optimized \
  --output-root /tmp/agentperf-m20-tool-heavy

agentperf doctor /tmp/agentperf-m20-tool-heavy/raw
agentperf analyze /tmp/agentperf-m20-tool-heavy/raw
agentperf report /tmp/agentperf-m20-tool-heavy/raw \
  --output /tmp/agentperf-m20-tool-heavy-raw.html
agentperf compare /tmp/agentperf-m20-tool-heavy/raw \
  /tmp/agentperf-m20-tool-heavy/optimized
agentperf check /tmp/agentperf-m20-tool-heavy/raw \
  /tmp/agentperf-m20-tool-heavy/optimized \
  --policy examples/policies/m20-tool-heavy-regression.yaml
```

OpenAI Agents SDK:

```bash
python examples/external_agents/openai_agents_support_triage.py \
  --output-dir /tmp/agentperf-m20-openai-standard \
  --instruction-style standard
python examples/external_agents/openai_agents_support_triage.py \
  --output-dir /tmp/agentperf-m20-openai-compact \
  --instruction-style compact

agentperf doctor /tmp/agentperf-m20-openai-standard/agentperf_artifact
agentperf compare /tmp/agentperf-m20-openai-standard/agentperf_artifact \
  /tmp/agentperf-m20-openai-compact/agentperf_artifact
```

Compatibility checks:

```bash
agentperf analyze examples/traces/multi_problem_agent.json
agentperf compare examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only
agentperf check examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only \
  --policy examples/policies/m3-context-regression.yaml
agentperf suite check examples/benchmark_suites/m3_context examples/artifacts/m3_dedup_only
```

## Remaining Limitations

- Sample size is small.
- Finding review is manual and subjective.
- No primary M20 workload used serving telemetry, so vLLM/SGLang behavior is
  compatibility-checked through existing tests and fixtures rather than
  expanded here.
- The tool-heavy workload is deterministic and local; it is realistic enough to
  exercise multi-tool behavior but not a production external agent.
- AgentPerf still cannot automatically prove that repeated context is removable;
  replay remains the validation mechanism.
