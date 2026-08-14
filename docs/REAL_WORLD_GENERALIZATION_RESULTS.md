# Real-World Generalization Results

Status: M7 local agent-layer profile completed; M7.1 materiality correction
applied. M20 extends this with a heterogeneous three-workload generalization
review in [M20_REAL_WORLD_GENERALIZATION.md](M20_REAL_WORLD_GENERALIZATION.md).

## Summary

M7 profiled `mini-swe-agent`, an existing upstream coding agent, using
AgentPerf's public instrumentation boundary. The run used mini-SWE-agent's
upstream `DefaultAgent`, local shell environment, default prompt templates, and
normal action/observation loop.

The checked-in run did not use a GPU or vLLM serving telemetry. It validates
agent-layer generalization and exposed one materiality issue in AgentPerf's
original duplication detector semantics. M7.1 fixed that issue by making
duplication materiality aware of execution boundaries.

## Environment

| Field | Value |
| --- | --- |
| Agent | `mini-swe-agent` `DefaultAgent` |
| mini-SWE-agent version | `2.4.6` |
| Model mode | upstream deterministic test model |
| Environment | upstream local shell environment |
| Workload | five small repository-repair tasks |
| Serving backend | none |
| Tokenization | approximate |
| GPU | none |

The run redirected mini-SWE-agent's config directory to `/tmp` to avoid writing
outside the workspace sandbox. No framework internals were patched.

## Baseline Result

| Metric | Value |
| --- | ---: |
| Tasks | 5 |
| Task success | 5 / 5 |
| Pass rate | 100% |
| LLM calls | 30 |
| Bash/environment calls | 30 |
| Processed input tokens | 25,318 |
| Output tokens | unavailable from deterministic model |
| Component unique tokens | 4,129 |
| Tool latency | 1.7 s |
| Correlated serving requests | 0 |

Component attribution:

| Component | Processed tokens | Unique tokens | Share |
| --- | ---: | ---: | ---: |
| System | 3,090 | 103 | 12.2% |
| User | 17,352 | 2,892 | 68.5% |
| History | 335 | 23 | 1.3% |
| Tool result | 4,541 | 1,111 | 17.9% |

Context growth per task was modest. Example `calc-add` LLM-call input tokens:

```text
683 -> 777 -> 816 -> 873 -> 893 -> 924
```

The largest individual tool-output reinjection contribution was small:

| Tool call | Raw output tokens | Downstream calls | Processed contribution |
| --- | ---: | ---: | ---: |
| `mini-swe-dates-window-tool-2` | 43 | 4 | 493 |
| `mini-swe-calc-add-tool-1` | 75 | 5 | 450 |
| `mini-swe-strings-slug-tool-1` | 75 | 5 | 450 |

No `TOOL_OUTPUT_BLOAT` finding fired.

## Findings

Before M7.1, AgentPerf emitted:

- `CONTEXT_DUPLICATION` / `HIGH`

Evidence:

- affected LLM calls: 30;
- repeated context tokens: 21,189;
- repeated context ratio: 83.7%;
- repeated tokens by component:
  - user: 14,460;
  - tool_result: 3,430;
  - system: 2,987;
  - history: 312.

Interpretation:

The detector is measuring real repeated prompt components, mostly upstream
mini-SWE-agent's default system/instance prompt template repeated across the
five task runs. However, in this benchmark those repetitions are partly a
batching artifact: AgentPerf treats five independent repair tasks as one
`AgentRun`, while mini-SWE-agent naturally starts each task with the same
prompt scaffold.

M7 therefore does not accept this as a replay-worthy material optimization.
The report is still useful because it identifies exactly where token processing
goes, but the current detector overstates actionability for batched independent
tasks without serving telemetry.

That was a correct repeated-token measurement but an over-strong actionability
classification.

After M7.1, the same mini-SWE-agent workload emits:

- `CROSS_RUN_SHARED_SCAFFOLD` / `LOW`

Evidence:

- independent execution scopes: 5;
- affected LLM calls: 30;
- cross-run repeated scaffold tokens: 668;
- repeated tokens by component:
  - system: 412;
  - tool_result: 164;
  - history: 92;
- materiality: `OBSERVATION`;
- serving telemetry present: false.

The scoped repeated-token count is smaller because it counts content repeated
across task scopes once per scope. It does not collapse all within-task prompt
repetition and all cross-task prompt scaffold into one actionability score.

Suppressed by detector semantics:

- `CONTEXT_DUPLICATION` as an actionable optimization finding.

Not emitted:

- `TOOL_OUTPUT_BLOAT`, because per-tool downstream contribution was small.
- cache/prefix/prefill findings, because no serving telemetry was present.
- model-choice findings, because no semantic role counterfactual replay was
  part of M7.

## Intervention

No optimization/replay was applied.

Reason:

The only emitted finding was not a strong natural pathology in the selected
local run. Applying a fix would require changing mini-SWE-agent's default prompt
scaffold, changing task batching semantics, or adding serving-specific prefix
cache validation. Those would exceed M7's rule to avoid redesigning the
external agent or manufacturing a pathology.

## What Generalized

| Surface | Result |
| --- | --- |
| Public recorder API | Worked unchanged. |
| Prompt-component attribution | Worked through the mini-SWE model wrapper. |
| Tool/environment spans | Worked through the environment wrapper. |
| Tool-output reinjection accounting | Worked after preserving source tool IDs. |
| Context growth table | Worked on mini-SWE-agent's linear history. |
| Existing detectors | Ran without framework-specific detector code. |
| Serving optionality | Worked; missing vLLM telemetry did not crash analysis. |

## What Required M7-Specific Adaptation

- A mini-SWE-agent model wrapper was needed because mini-SWE-agent calls
  `model.query(messages)` directly.
- A mini-SWE-agent environment wrapper was needed because bash is represented
  as environment actions rather than framework tool spans.
- Prompt components needed a mini-SWE-specific mapping from OpenAI-style
  message history:
  - first system message -> `system`;
  - first task message -> `user`;
  - assistant messages -> `history`;
  - observation messages containing `<returncode>`/`<output>` -> `tool_result`.
- Wrapper-generated IDs needed task-specific prefixes so multiple independent
  task runs could share one AgentPerf workload trace without ID collisions.

## Assumptions That Failed Or Weakened

1. A workload batch is not always one coherent agent run. Repeated system/user
   prompt scaffolding across independent tasks can inflate context-duplication
   severity when run boundaries are ignored.
2. Prompt-component metadata is framework-specific. mini-SWE-agent exposes
   message history, but not AgentPerf component labels.
3. Tool output exists as shell observations, not named domain tools.
4. The deterministic local model does not expose meaningful output-token usage.
5. Serving/cache materiality cannot be assessed without a real backend trace.

## Comparison

| Workload | Ownership | Integration | Calls/tools | Findings | Replay |
| --- | --- | --- | ---: | --- | --- |
| M3 research agent | AgentPerf-controlled | native trace fields | 30 LLM / 20 tools | `TOOL_OUTPUT_BLOAT` material | yes, `DEDUP_ONLY` |
| M5 support triage | external framework pattern | OpenAI Agents SDK hooks/wrapper | 20 LLM / 10 tools | low context observation | no |
| M6 support triage + vLLM | external framework pattern | OpenAI Agents SDK + vLLM correlation | 10 LLM / 5 tools / 10 serving | no material issue | no |
| M7 mini-SWE-agent | existing upstream agent | model/env wrappers | 30 LLM / 30 bash | `CROSS_RUN_SHARED_SCAFFOLD` observation | no |

## Generalization Conclusion

AgentPerf's core trace and analysis architecture generalized to a second,
independent agent runtime without detector-specific code. M7.1 fixed the main
materiality weakness exposed by that run: AgentPerf now distinguishes repeated
scaffold across independent task scopes from actionable within-run context
duplication.

M7 should be considered an agent-layer generalization validation, not a new
optimization win.
