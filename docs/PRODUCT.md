# AgentPerf Product Contract

## MVP Promise

Given one agent execution trace and optional serving telemetry, AgentPerf explains where tokens and latency went and surfaces the strongest evidence-backed optimization opportunities.

## Non-Goals

- No web dashboard.
- No transparent execution interception.
- No LLM-based diagnosis engine.
- No model-choice optimization.
- No distributed storage.
- No production deployment architecture.
- No guarantee of optimal KV-cache sizing or scheduler configuration.

## Target User

The target user is an engineer building or operating agentic LLM workloads who can collect application traces and may also have vLLM/SGLang-style serving telemetry. They need to answer whether cost or latency comes from prompt construction, serving queueing, prefill, decode, or poor prefix-cache reuse.

## First Vertical Slice

Input:

- A JSON trace file containing an `agent_run`, agent steps, LLM calls, tool calls, and optional serving requests.

Output:

- A terminal report with run summary, latency attribution, serving summary, and deterministic findings.

Implemented MVP findings:

- `CONTEXT_DUPLICATION`
- `PREFIX_CACHE_OPPORTUNITY`
- `PREFILL_PATH_DOMINANCE`
- `MATERIAL_PREFILL_BOTTLENECK`

## Recommendation Contract

Every recommendation must be backed by derived metrics. A recommendation is framed as an experiment to evaluate, not as a guaranteed fix.

Example:

> Evaluate whether stable instructions, tool schemas, and shared context can be organized into a consistent cacheable prefix.

This is acceptable only when evidence shows substantial shared or repeated
stable content, low actual prefix-cache reuse, and meaningful prefill-path
contribution.

## Synthetic Data Policy

Synthetic traces are development fixtures and demos only. They are never benchmark results.
