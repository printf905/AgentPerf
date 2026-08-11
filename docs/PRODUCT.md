# AgentPerf Product Contract

## Promise

Given an agent execution trace or self-contained experiment artifact, and
optional serving telemetry, AgentPerf explains where tokens and latency went,
surfaces evidence-backed performance findings, and helps verify whether a
developer change improved the workload without violating task-quality
constraints.

## Core Workflow

```text
TRACE -> PROFILE -> DIAGNOSE -> RECOMMEND -> REPLAY -> VERIFY
```

Current local workflow:

```text
ExperimentSession
  -> ExperimentArtifact
  -> agentperf compare
  -> RegressionPolicy
  -> agentperf check
  -> BenchmarkSuite
  -> reviewed baseline
  -> agentperf suite check
```

## Target User

The target user is an engineer building or operating agentic LLM workloads who
can collect application traces and may also have vLLM/SGLang-style serving
telemetry. They need to answer whether cost or latency comes from prompt
construction, tool-output carry-forward, serving queueing, first-token path
behavior, decode/generation, or poor prefix-cache reuse.

## Implemented Inputs

- Raw normalized AgentPerf trace JSON.
- Portable AgentPerf experiment artifact directories.
- Recorded vLLM OpenAI-compatible response bundles.
- Recorded SGLang OpenAI-compatible response bundles.
- OpenAI Agents SDK exports/wrappers.
- mini-SWE-agent model/environment wrappers.

## Implemented Outputs

- Terminal profiling report.
- JSON comparison/regression outputs.
- Markdown CI summaries.
- Standalone local HTML profiler report.
- Benchmark-suite validation/check/proposal reports.

## Recommendation Contract

Every recommendation must be backed by derived metrics. A recommendation is
framed as an experiment to evaluate, not as a guaranteed fix.

Example:

> Evaluate whether stable instructions, tool schemas, and shared context can be
> organized into a consistent cacheable prefix.

This is acceptable only when evidence shows substantial shared or repeated
stable content, low actual prefix-cache reuse, and meaningful first-token-path
or uncached-token contribution.

## Materiality Principles

- Dominant does not necessarily mean material.
- Repeated does not necessarily mean removable.
- Headroom does not necessarily mean actionable.
- Missing evidence does not mean negative evidence.
- Performance improvement is not acceptable if task quality violates the
  configured tolerance.

## Non-Goals

- No hosted dashboard.
- No transparent execution interception.
- No LLM-based diagnosis engine.
- No automatic optimization.
- No distributed storage or remote artifact registry.
- No production deployment architecture.
- No guarantee of optimal KV-cache sizing or scheduler configuration.
- No claim that vLLM and SGLang expose feature-equivalent telemetry.

## Synthetic Data Policy

Synthetic traces are development fixtures and demos only. They are never
benchmark results.
