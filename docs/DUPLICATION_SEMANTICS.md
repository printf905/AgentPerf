# Duplication Semantics

Status: M7.1 run-boundary materiality semantics.

M7 showed that "repeated tokens" is not enough to decide whether a developer
should remove or compact context. The mini-SWE-agent profile processed 25,318
approximate input tokens and measured 21,189 repeated-context tokens, but most
of that repetition was the same upstream prompt scaffold repeated across five
independent repository-repair tasks.

That is real repetition. It is not automatically avoidable within one task.

## Core Distinctions

### WITHIN_RUN_DUPLICATION

Content repeatedly processed across multiple LLM calls belonging to the same
execution scope.

Example:

```text
read_file(foo.py) -> 6K tokens

LLM call 2 includes full foo.py
LLM call 3 includes full foo.py
LLM call 4 includes full foo.py
LLM call 5 includes full foo.py
```

This can be actionable harness/context waste when it materially contributes to
processed input tokens or latency. AgentPerf may recommend replaying a
developer-level change such as deduplication, bounded evidence carry-forward,
or compact references, provided task quality is checked.

### CROSS_RUN_SHARED_SCAFFOLD

Stable instructions, tool descriptions, templates, or task scaffolding repeated
across independent execution scopes.

Example:

```text
Task A prompt = mini-SWE-agent default scaffold + issue A
Task B prompt = mini-SWE-agent default scaffold + issue B
Task C prompt = mini-SWE-agent default scaffold + issue C
```

This is not evidence that the scaffold should be removed. It may be relevant to
static prompt caching, prefix caching, or workload-level serving efficiency, but
it should not produce a high-severity context-removal warning by itself.

### WITHIN_RUN_SHARED_PREFIX

Stable content repeated within one execution scope as a common prefix.

This can be legitimate and necessary. When serving telemetry is available, it
often maps more naturally to cacheability analysis than to context deletion.
AgentPerf should ask whether the backend is actually reusing the prefix before
claiming a material prefix-cache problem.

## Execution Scopes

AgentPerf's normalized trace has one `AgentRun`, but a single trace file can
represent either:

- one agent execution;
- a batch of independent tasks;
- an experiment containing several workload items.

For duplication materiality, AgentPerf now derives execution scopes as follows:

1. If steps expose `metadata.task_id`, `metadata.execution_id`,
   `metadata.workload_item_id`, or `metadata.run_id`, LLM calls are grouped by
   that value.
2. If the trace declares `agent_run.metadata.task_count > 1` but lacks per-step
   scope IDs, each step is treated conservatively as its own execution scope.
3. Otherwise, all LLM calls belong to the single `AgentRun` scope.

This preserves single-run M2/M3 behavior while preventing batched independent
tasks from being collapsed into one actionable duplication finding.

## Finding Semantics

### CONTEXT_DUPLICATION

Scope: `within_run_duplication`.

Meaning: repeated prompt components appear across LLM calls in the same
execution scope.

Materiality:

- `OBSERVATION`: repeated tokens are real but small.
- `HEADROOM`: repeated tokens are substantial but not clearly operationally
  material.
- `MATERIAL`: repeated tokens are substantial enough to justify inspecting
  carry-forward behavior and replaying a change.

Recommendation: inspect within-run context carry-forward. Do not assume every
repeated token can be deleted.

### CROSS_RUN_SHARED_SCAFFOLD

Scope: `cross_run_shared_scaffold`.

Meaning: repeated prompt components appear across independent execution scopes.

Materiality:

- `OBSERVATION` when no serving telemetry is available.
- `CACHEABILITY_HEADROOM` when serving telemetry exists, because the same
  scaffold may be relevant to prefix/static caching.

Recommendation: no context-removal recommendation. Evaluate caching only when
the backend supports it and telemetry shows material latency or cache-miss
cost.

## M7 Interpretation

Before M7.1:

```text
mini-SWE-agent batch
  5 independent repo-repair tasks
  30 LLM calls
  21,189 repeated-context tokens
  83.7% repeated ratio
  -> HIGH CONTEXT_DUPLICATION
```

After M7.1:

```text
same trace
  repeated scaffold across task scopes
  -> LOW CROSS_RUN_SHARED_SCAFFOLD
```

The old repeated-token measurement was correct. The old actionability was too
strong because it ignored execution boundaries.

## General Principle

A profiler must understand execution boundaries. Repetition across independent
tasks is not equivalent to redundant context within one task.
