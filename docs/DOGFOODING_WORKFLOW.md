# Dogfooding Workflow

M13 validates the full AgentPerf developer workflow on one supported agent:

```text
existing agent baseline
-> realistic developer change
-> candidate artifact
-> suite validate
-> suite check
-> Markdown / JSON / terminal evidence
-> explicit baseline proposal
```

This is workflow validation, not a new detector or benchmark claim.

## Agent Selection

Selected agent: OpenAI Agents SDK support-triage example.

The preferred first target was the mini-SWE-agent local repair workload because
it is a more realistic iterative coding loop. In the local sandbox, its runtime
attempted to write dependency state under the user application-support
directory before the workload could run:

```text
PermissionError: Operation not permitted: '$HOME/Library/Application Support/mini-swe-agent'
```

Rather than turn M13 into another runtime-environment milestone, the dogfooding
run uses the deterministic OpenAI Agents SDK support-triage workload. It is
already AgentPerf-supported, runs without network/API/GPU access, and emits
complete ExperimentSession artifacts with task rows, quality, latency,
findings, and environment metadata.

## Baseline Suite

Suite:

```text
benchmarks/openai-agents-support-triage/
  suite.yaml
  policy.yaml
  baseline/
```

Baseline command:

```bash
python examples/external_agents/openai_agents_support_triage.py \
  --instruction-style standard \
  --output-dir /tmp/agentperf_m13_support_standard
```

The resulting ExperimentSession artifact was stored as:

```text
benchmarks/openai-agents-support-triage/baseline/
```

Baseline metrics:

| Metric | Value |
| --- | ---: |
| Tasks | 10 |
| LLM calls | 20 |
| Tool calls | 10 |
| Task success | 10 / 10 |
| Mean score | 1.000 |
| Pass rate | 100% |
| Trace input tokens | 1,604 |
| Output tokens | 153 |
| Prompt-component processed tokens | 1,320 |
| System component tokens | 680 |
| Client duration summary | 58.385 ms |
| Findings | LOW `CONTEXT_DUPLICATION` observation |

The suite manifest records an expected task count of 10 and a task-set
fingerprint derived from the stable task IDs:

```text
0c47d26cf05a9f3067874affb160babb0144a1dc22db946058a778915a3997fe
```

## Developer Change

Candidate change: compact the support-agent instruction string while preserving
the same tool requirement and final answer format.

Why a developer might make it:

- reduce prompt scaffold size;
- preserve the same task behavior;
- test whether smaller instructions change quality or findings.

This is not an intentionally bad regression and does not inject a fake
performance pathology.

Candidate command:

```bash
python examples/external_agents/openai_agents_support_triage.py \
  --instruction-style compact \
  --output-dir /tmp/agentperf_m13_support_compact
```

The resulting artifact was stored as:

```text
examples/dogfooding/openai_agents_support_triage_compact/
```

Candidate metrics:

| Metric | Baseline | Candidate |
| --- | ---: | ---: |
| Tasks | 10 | 10 |
| LLM calls | 20 | 20 |
| Tool calls | 10 | 10 |
| Task success | 10 / 10 | 10 / 10 |
| Mean score | 1.000 | 1.000 |
| Pass rate | 100% | 100% |
| Trace input tokens | 1,604 | 1,604 |
| Output tokens | 153 | 153 |
| Prompt-component processed tokens | 1,320 | 1,160 |
| System component tokens | 680 | 520 |
| Client duration summary | 58.385 ms | 58.390 ms |
| Findings | LOW observation | LOW observation |

The compact prompt reduced AgentPerf prompt-component attribution for system
instructions by 160 processed tokens. The trace-level `input_tokens` field did
not change because the scripted OpenAI Agents model usage accounting does not
include `system_instructions` in its reported token usage. That mismatch is a
useful dogfooding friction point: component attribution can expose prompt
changes even when a provider/model usage field is incomplete or approximate.

## Suite Commands

Validation:

```bash
agentperf suite validate benchmarks/openai-agents-support-triage
```

Result: `PASS`.

Policy check:

```bash
agentperf suite check \
  benchmarks/openai-agents-support-triage \
  examples/dogfooding/openai_agents_support_triage_compact
```

Result: `PASS`.

The suite check verified:

- both artifacts are `COMPLETE`;
- the configured task-set fingerprint matches;
- mean score and pass rate stayed within policy;
- input tokens did not regress;
- no new or regressed material findings appeared.

The M8 comparison layer matched one workload-level AgentRun, while the M12
suite layer verified the 10 stable task IDs through the task-set fingerprint.

## CI Simulation

The GitHub Actions-compatible command is:

```bash
agentperf suite check \
  benchmarks/openai-agents-support-triage \
  examples/dogfooding/openai_agents_support_triage_compact \
  --format markdown \
  --output agentperf-dogfood.md
cat agentperf-dogfood.md >> "$GITHUB_STEP_SUMMARY"
```

The generated Markdown answers the reviewer-facing questions:

- task coverage;
- quality and pass-rate status;
- input-token policy status;
- material finding regressions;
- final policy result.

AgentPerf's own CI now runs this deterministic suite check offline. It does not
call an LLM API, rent GPU resources, or use network storage.

## Failure Path

Failure semantics were validated separately with a synthetic candidate artifact
based on the existing synthetic replay suite. The candidate kept improved
tokens but changed quality to:

```text
mean_score: 0.5
pass_rate: 0.0
```

Command:

```bash
agentperf suite check /tmp/agentperf_m13_failure_suite \
  /tmp/agentperf_m13_failure_suite/candidate
```

Result: `FAIL`, exit code `1`.

The failed checks were `QUALITY:mean_score` and `QUALITY:pass_rate`. This
confirms the M11 quality guard remains first-class: token improvement does not
make a quality regression acceptable.

## Baseline Proposal

Command:

```bash
agentperf suite propose-baseline \
  benchmarks/openai-agents-support-triage \
  examples/dogfooding/openai_agents_support_triage_compact \
  --format markdown \
  --output baseline-proposal.md
```

Result: `SAFE TO REVIEW`.

The command did not replace the baseline. A maintainer would still review
whether the compact prompt should become the accepted baseline. Because the
trace-level token count and latency did not improve, the candidate is a safe
workflow demonstration but not a compelling baseline replacement on performance
grounds.

## User Friction

Observed friction:

- mini-SWE-agent was not reliable in the local sandbox because dependency state
  setup wrote outside the workspace;
- scripted model usage does not include system instructions, so trace-level
  input tokens missed the compact-prompt delta;
- suite check output reports one matched workload-level run, while task-level
  identity is verified by the suite fingerprint;
- a developer still needs to know whether to look at trace-level token usage or
  component attribution for scripted/offline models.

High-value fixes made in M13:

- the OpenAI Agents SDK example can now emit standard and compact instruction
  artifacts without changing business logic;
- a real suite and candidate artifact are committed for offline dogfooding;
- CI runs the suite check and can append Markdown output to the step summary;
- the dogfooding suite is covered by regression tests.

## Limitations

- No live vLLM telemetry was used in M13.
- The selected dogfooding workload is deterministic and small.
- The compact-instruction candidate passed policy but did not produce a
  trace-level token or latency win.
- The failure-path validation uses a clearly labeled synthetic candidate, not
  the real dogfooding agent.
- Baseline replacement remains explicit and manual.
