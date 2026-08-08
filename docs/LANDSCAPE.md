# AgentPerf Landscape Review

This review was created before significant implementation work. It uses primary sources where possible and treats novelty claims conservatively.

## Executive Conclusion

The proposed AgentPerf MVP remains defensible, but only if it is positioned narrowly:

- AgentPerf is not a generic tracing dashboard.
- AgentPerf is not a replacement for vLLM, SGLang, or ThunderAgent.
- AgentPerf is not an automatic optimizer.
- AgentPerf is a developer-facing profiler that normalizes agent traces and optional serving telemetry, correlates them when identifiers prove a relationship, and emits deterministic, evidence-backed findings about token and latency waste.

The most important competitive pressure is ThunderAgent. ThunderAgent already identifies agent workflows as a scheduling unit, improves KV-cache hit rate, manages tool lifecycle, and reports throughput improvements. AgentPerf should not claim to invent KV-cache optimization for agents. The defensible gap is diagnosis: explain why a workload is inefficient and what experiment to run, including when the serving layer already exposes low-level telemetry but the developer cannot connect it back to agent structure.

## Sources Inspected

- ThunderAgent paper: https://arxiv.org/pdf/2602.13692
- ThunderAgent repository: https://github.com/ThunderAgent-org/ThunderAgent
- OpenTelemetry GenAI semantic conventions: https://github.com/open-telemetry/semantic-conventions-genai
- vLLM metrics docs: https://docs.vllm.ai/en/v0.12.0/design/metrics/
- SGLang observability docs: https://docs.sglang.io/docs/advanced_features/observability
- Langfuse observability docs: https://langfuse.com/docs/observability/overview
- Arize Phoenix docs: https://arize.com/docs/phoenix
- OpenInference docs: https://arize-ai.github.io/openinference/
- TraceRoot repository: https://github.com/traceroot-ai/traceroot
- AgentOpt repository: https://github.com/AgentOptimizer/agentopt
- Opik docs: https://www.comet.com/docs/opik/v1
- Opik Agent Optimizer docs: https://www.comet.com/docs/opik/development/optimization-runs/overview
- OpenLIT docs/repository: https://docs.openlit.io/latest/overview and https://github.com/openlit/openlit
- OpenLLMetry docs: https://docs.traceloop.com/docs/openllmetry/introduction
- Helicone repository: https://github.com/helicone/helicone

## System Reviews

### ThunderAgent

1. Problem solved: Program-aware agentic inference and rollout. It treats an agent workflow as an "LLM Program" so scheduling can account for KV cache, workflow phase, and tool resources.
2. What it traces: Program/workflow state, total tokens, tool-use time, per-program profiling, and backend-facing request lifecycle information.
3. Serving-level information exposed: KV-cache hit rate, memory pressure behavior, backend integration with vLLM and SGLang, scheduling state, throughput.
4. Agent-server correlation: Yes, but as a runtime control plane/scheduler. It asks callers to provide a `program_id` and uses that abstraction as a scheduling unit.
5. Diagnoses performance pathologies: Partly. The paper and system identify KV-cache thrashing, memory imbalance, and tool lifecycle problems, but the product goal is runtime optimization rather than offline developer diagnosis.
6. Recommendations: Not its main interface. It optimizes execution rather than producing explanatory recommendations.
7. Model choice optimization: No primary focus found.
8. Context/token waste: It tracks total tokens and exploits prefix-like workflow structure, but does not appear to focus on developer-facing context duplication diagnosis.
9. KV/prefix-cache behavior: Strong. This is core to the system.
10. Replay validation: Evaluation uses real workloads and backend comparisons; not a local profiler replay loop for user-supplied traces.
11. Overlap with AgentPerf: Very high on agent-aware KV/prefix-cache behavior and serving-aware agent execution.
12. Defensible differentiation: AgentPerf must be a profiler and diagnostic layer. ThunderAgent can be a backend or baseline. Competing on scheduling would be weak without substantial new evidence.

### OpenTelemetry GenAI Semantic Conventions

1. Problem solved: Standard names and attributes for GenAI spans, metrics, events, agents, workflows, tools, providers, and token usage.
2. What it traces: GenAI operations such as chat, retrieval, tool execution, agent invocation, workflow invocation, and provider calls.
3. Serving-level information exposed: Includes model server metrics such as request duration, time to first token, and time per output token, but not detailed KV-cache semantics.
4. Agent-server correlation: Provides trace/span vocabulary and identifiers; it does not itself correlate agent spans with model-server spans.
5. Diagnoses pathologies: No.
6. Recommendations: No.
7. Model choice optimization: No.
8. Context/token waste: Token usage metrics exist, but not waste diagnosis.
9. KV/prefix-cache behavior: Not materially covered in the inspected GenAI conventions.
10. Replay validation: No.
11. Overlap with AgentPerf: Schema and naming overlap. AgentPerf should align to OTel terms where useful.
12. Defensible differentiation: AgentPerf can be an analysis layer above OTel-style traces.

### SGLang Observability

1. Problem solved: Production observability for the SGLang serving runtime.
2. What it traces: Server metrics, request logging, request dumps, crash dumps, and replayable request dumps.
3. Serving-level information exposed: Prometheus metrics, logs, request dump/replay. The observed docs emphasize production metrics and request replay rather than agent-level diagnosis.
4. Agent-server correlation: Not generally, unless users propagate identifiers.
5. Diagnoses pathologies: Runtime metrics help humans diagnose, but no inspected developer-facing agent diagnosis layer.
6. Recommendations: No.
7. Model choice optimization: No.
8. Context/token waste: No agent-level context analysis found.
9. KV/prefix-cache behavior: SGLang supports prefix-cache serving features and exposes runtime metrics, but the inspected observability page is not a cross-layer profiler.
10. Replay validation: Yes for request dumps, but serving request replay is not equivalent to agent-level recommendation validation.
11. Overlap with AgentPerf: Serving telemetry source and future ingestion target.
12. Defensible differentiation: AgentPerf can consume SGLang telemetry and explain it in agent terms.

### vLLM Observability

1. Problem solved: Engine and request-level monitoring for vLLM.
2. What it traces: Prometheus metrics, logging, and OpenTelemetry tracing support.
3. Serving-level information exposed: Queue/running request counts, KV-cache usage, prefix-cache queries/hits, request timing, TTFT/TPOT-oriented metrics, cache offloading metrics, and request-level histograms.
4. Agent-server correlation: Not by itself. vLLM exposes serving facts; agent-level correlation requires propagated identifiers or external analysis.
5. Diagnoses pathologies: Metrics support diagnosis, but vLLM does not appear to emit agent-specific recommendations.
6. Recommendations: No.
7. Model choice optimization: No.
8. Context/token waste: No agent context duplication analysis.
9. KV/prefix-cache behavior: Strong serving telemetry, especially prefix-cache hits/queries and KV-cache usage.
10. Replay validation: Not the inspected metrics layer.
11. Overlap with AgentPerf: Serving metrics and future ingestion target.
12. Defensible differentiation: AgentPerf can bridge vLLM's server metrics to agent prompt structure and findings.

### Langfuse

1. Problem solved: Open-source LLM application observability, tracing, prompt management, evaluation, datasets, and experiments.
2. What it traces: Nested observations including LLM calls, tools, retrieval, prompts, outputs, token usage, cost, latency, sessions, and custom metadata.
3. Serving-level information exposed: Primarily application/provider metrics. No inspected evidence of vLLM/SGLang prefill/decode/KV-cache attribution.
4. Agent-server correlation: Distributed tracing/custom trace IDs are supported, but cross-layer model-server correlation is not its central claim.
5. Diagnoses pathologies: Helps inspect latency/cost and quality; deterministic serving-aware pathology detectors were not found.
6. Recommendations: Offers broader improve/evaluate workflows; not deterministic cache/prefill recommendations from serving telemetry.
7. Model choice optimization: Experiments can compare changes; not a serving-aware model-choice optimizer.
8. Context/token waste: Token/cost tracking exists; no inspected exact context duplication detector.
9. KV/prefix-cache behavior: Not found.
10. Replay validation: Experiments/datasets can validate prompt/application changes.
11. Overlap with AgentPerf: Strong on tracing UI, token/cost/latency visibility, experiments.
12. Defensible differentiation: AgentPerf should avoid dashboard parity and focus on cross-layer performance findings.

### Arize Phoenix and OpenInference

1. Problem solved: Open-source AI observability, evaluation, troubleshooting, datasets, experiments, prompt engineering, and OpenTelemetry/OpenInference-based tracing.
2. What it traces: LLM calls, retrieval, tool use, custom logic, prompts, model metadata, and eval annotations via OpenInference instrumentation.
3. Serving-level information exposed: Primarily application-layer spans. No inspected direct KV/prefix-cache or prefill/decode attribution.
4. Agent-server correlation: Accepts OTLP traces and can represent causal spans, but correlation with model-server spans is not a core inspected feature.
5. Diagnoses pathologies: Helps debug behavior and latency; deterministic serving-aware detectors were not found.
6. Recommendations: Supports evals, prompt iteration, and experiments, but not deterministic cache/prefill recommendations.
7. Model choice optimization: Prompt playground/experiments can compare models. It is not specifically a cross-layer model-choice optimizer.
8. Context/token waste: Can inspect prompts/tokens; no inspected context duplication analyzer.
9. KV/prefix-cache behavior: Not found.
10. Replay validation: Span Replay exists for LLM calls, and datasets/experiments support validation workflows.
11. Overlap with AgentPerf: Strong on traces, replay, experiments, and OpenTelemetry ecosystem.
12. Defensible differentiation: AgentPerf should use Phoenix/OpenInference as compatible telemetry inputs, not try to replace them.

### TraceRoot

1. Problem solved: AI agent observability plus AI-assisted debugging tied to source code and GitHub history.
2. What it traces: LLM calls, agent actions, tool usage, token usage, framework/provider integrations through OpenTelemetry-compatible SDKs.
3. Serving-level information exposed: No inspected vLLM/SGLang-level queue/prefill/decode/KV-cache analysis.
4. Agent-server correlation: OpenTelemetry-compatible traces; not specifically model-server correlation.
5. Diagnoses pathologies: Focuses on agentic debugging and identifying failing code/commits rather than deterministic performance detectors.
6. Recommendations: AI debugging can suggest fixes; not evidence-backed serving performance recommendations.
7. Model choice optimization: No primary focus found.
8. Context/token waste: Token tracing exists; no inspected context duplication detector.
9. KV/prefix-cache behavior: Not found.
10. Replay validation: Not a main inspected feature.
11. Overlap with AgentPerf: Agent tracing and debugging.
12. Defensible differentiation: AgentPerf should stay performance/profiling specific and deterministic.

### AgentOpt

1. Problem solved: Framework-agnostic interception of LLM HTTP calls for tracking, caching, routing, and offline model selection.
2. What it traces: Provider, model, prompt/completion tokens, latency, cost, cache hit/miss per LLM call.
3. Serving-level information exposed: LLM API/proxy-level data and cache hit/miss in its own layer. No inspected vLLM/SGLang queue/prefill/decode/KV-cache telemetry.
4. Agent-server correlation: It intercepts outbound LLM calls, so it has strong application-level call attribution, but not server-internal request spans.
5. Diagnoses pathologies: Tracks and optimizes cost/latency/model choices; not the requested cross-layer cache/prefill profiler.
6. Recommendations: Yes for model selection/routing use cases, based on experiments.
7. Model choice optimization: Strong. This overlaps with AgentPerf's future phase 3 and should not be implemented in the MVP.
8. Context/token waste: Tracks tokens; no inspected exact repeated-context/prefix-cache opportunity diagnosis.
9. KV/prefix-cache behavior: Mentions cache hit/miss for its request cache; not model-server KV-cache behavior.
10. Replay validation: Uses cached responses and evaluation datasets for selection experiments.
11. Overlap with AgentPerf: High for future model-choice profiler; moderate for tracking/cost/latency.
12. Defensible differentiation: AgentPerf should defer model choice and focus on serving-layer attribution.

### Opik and Opik Agent Optimizer

1. Problem solved: Open-source LLM observability, debugging, evaluation, prompt management, and optimization.
2. What it traces: LLM calls, agent activity, traces, prompts, evaluation data, cost/latency-oriented logs.
3. Serving-level information exposed: No inspected direct vLLM/SGLang prefill/decode/KV-cache attribution.
4. Agent-server correlation: Application trace correlation, not model-server span correlation.
5. Diagnoses pathologies: Evaluation and debugging workflows; not deterministic serving pathologies.
6. Recommendations: Agent Optimizer can automatically tune prompts/tools/workflows.
7. Model choice optimization: Opik platform includes model/prompt experimentation; Agent Optimizer focuses on agent/prompt/workflow optimization.
8. Context/token waste: Logs prompt/context data, but no inspected deterministic duplicate-context detector.
9. KV/prefix-cache behavior: Not found.
10. Replay validation: Evaluation/experiment workflows exist.
11. Overlap with AgentPerf: High on observability/evals/optimization platform; low on serving-specific KV/prefill diagnosis.
12. Defensible differentiation: AgentPerf should remain a small CLI/library profiler with serving-aware evidence.

### OpenLIT / OpenLLMetry / Helicone

1. Problem solved: LLM observability platforms and OpenTelemetry-native instrumentation for LLM applications.
2. What they trace: LLM calls, vector database operations, framework spans, tokens, cost, latency, model metadata, errors, evaluations, and dashboards.
3. Serving-level information exposed: OpenLIT also mentions GPU monitoring, but no inspected cross-layer vLLM/SGLang KV/prefix-cache diagnosis.
4. Agent-server correlation: OpenTelemetry-compatible traces can carry IDs. Correlation to model-server internals is not the central inspected feature.
5. Diagnoses pathologies: Dashboards and evaluations help users inspect issues; deterministic cache/prefill detectors were not found.
6. Recommendations: Some platforms include optimization/evaluation workflows; not the AgentPerf MVP style of deterministic evidence-backed serving findings.
7. Model choice optimization: Gateways and playgrounds may compare or route models, but not the requested cross-layer diagnosis.
8. Context/token waste: Token/cost tracking exists; no inspected exact repeated-context detector.
9. KV/prefix-cache behavior: Not found as a first-class diagnostic capability.
10. Replay validation: Some provide playgrounds/evals, not serving-aware replay validation.
11. Overlap with AgentPerf: Generic observability and dashboards overlap strongly.
12. Defensible differentiation: AgentPerf should integrate with or export to these systems later rather than clone them.

## Does Another OSS System Already Implement Most of AgentPerf?

No single inspected open-source system appears to implement most of the specific AgentPerf MVP:

- agent trace plus optional serving trace normalization;
- proven LLMCall-to-ServingRequest correlation;
- deterministic context duplication, prefix-cache opportunity, and prefill bottleneck detectors;
- evidence-backed recommendations with validation plans;
- explicit refusal to fabricate relationships when correlation is unresolved.

However, the overlap is significant:

- ThunderAgent overlaps strongly with agent-aware KV-cache runtime behavior.
- Phoenix/Langfuse/Opik/OpenLIT/TraceRoot overlap strongly with agent tracing and AI observability.
- AgentOpt overlaps strongly with future model-choice and routing optimization.
- vLLM/SGLang already expose the serving telemetry AgentPerf would consume.

AgentPerf's novelty is therefore not "new telemetry" or "new scheduling." The surviving differentiation is cross-layer interpretation for developers.

## Capability Comparison

| Capability | Langfuse | Phoenix | ThunderAgent | Other relevant systems | AgentPerf MVP |
| --- | --- | --- | --- | --- | --- |
| agent tracing | Yes | Yes | Yes, through program abstraction | TraceRoot, Opik, OpenLIT, OpenLLMetry, Helicone | Yes, normalized input schema |
| tool tracing | Yes | Yes | Yes, including lifecycle management | TraceRoot, Opik, OpenLIT | Yes, summary only |
| token attribution | Yes | Yes | Tracks total tokens/per-program metrics | AgentOpt, Opik, OpenLIT, Helicone | Yes, input/output and repeated-token metrics |
| queue attribution | Not found | Not found | Runtime scheduling focus | vLLM/SGLang expose queue-related telemetry | Yes when serving data is provided |
| prefill attribution | Not found | Not found | Runtime-level performance focus | vLLM/SGLang expose serving timings depending on config/version | Yes when provided |
| decode attribution | Not found | Not found | Runtime-level performance focus | vLLM/SGLang metrics include generation-oriented timing | Yes when provided |
| prefix-cache diagnosis | Not found | Not found | Strong runtime optimization | vLLM exposes prefix-cache hits/queries; SGLang supports prefix caching | Yes, diagnostic only |
| context duplication detection | Not found | Not found | Not as developer-facing detector | Generic tools expose prompts/tokens | Yes |
| cross-layer correlation | Possible with IDs, not core | Possible with OTLP spans, not core | Yes as scheduler/control plane | OTel-compatible systems can carry IDs | Yes, explicit-ID only in MVP |
| evidence-backed recommendation | Partial product workflows | Partial eval/prompt workflows | Runtime optimization, not profiler recommendation | AgentOpt/Opik recommend optimizations in other domains | Yes, deterministic detector evidence |
| counterfactual replay | Experiments/datasets | Span Replay and experiments | Backend evaluations | AgentOpt cached/eval runs, SGLang request replay | Validation plan only, no automatic replay |
| model-choice optimization | Experiments, not main | Playground/experiments | No | AgentOpt strong; Opik optimizer related | No, documented future work |

## Defensible Differentiation Statement

Agent observability tools tell developers what happened at the application level. Inference runtimes tell operators what happened inside the serving engine. ThunderAgent changes the runtime to improve agentic inference. AgentPerf should connect existing traces and telemetry to explain why a specific agent workload is slow or expensive, surface only evidence-backed optimization opportunities, and give a validation plan without claiming automatic optimization.

