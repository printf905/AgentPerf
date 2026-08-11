# AgentPerf Project Story

This document is for interviews, project writeups, and external readers. It is
intentionally conservative: do not claim unvalidated benchmark results or
production impact.

## 30-Second Explanation

AgentPerf is a cross-layer profiler for agentic LLM workloads. Agent tracing
tools show what the agent did, and inference servers show what the model server
measured. AgentPerf correlates those layers so a developer can see why an agent
is slow or expensive, which tokens are repeatedly processed, whether repeated
tokens are reusable by prefix caching, and which optimization should be replayed
under a quality constraint.

## 2-Minute Technical Explanation

AgentPerf normalizes agent traces into runs, steps, LLM calls, tool calls, and
serving requests. It uses explicit request IDs to correlate application-level LLM
calls with vLLM telemetry such as cached prompt tokens, queue time,
scheduled-to-first-token timing, generation timing, and ITL.

The profiler then computes deterministic metrics and findings:

- context duplication across prompts;
- prefix-cache opportunity versus lower-severity cacheability headroom;
- prefill-path dominance versus material first-token bottlenecks;
- component token attribution for system, history, tool schema, and tool
  results;
- tool-output bloat from reinjected tool results;
- model-choice headroom from role-specific counterfactual replay.

The important product stance is that recommendations must be backed by evidence
and replay. AgentPerf is not an LLM that reads a trace and invents advice.

## 8-10 Minute Interview Deep Dive

The project started from a gap between two observability layers. Agent
observability systems are good at showing LLM calls, tool calls, prompts,
outputs, token usage, and latency. Serving engines such as vLLM expose lower
level request behavior: prefix-cache tokens, request timing, scheduled-to-first
token, generation timing, and token-level details. Developers still struggle to
connect those facts back to concrete agent-harness decisions.

The first design decision was to build a normalized trace model rather than a
dashboard. The schema supports agent-only traces, serving-only traces, and
correlated cross-layer traces. Correlation is explicit-ID based. If a serving
request cannot be proven to correspond to an LLM call, AgentPerf leaves it
unresolved instead of guessing from timestamps.

The second design decision was deterministic diagnosis. The detector pipeline is
telemetry -> metrics -> evidence -> finding -> validation plan. That matters
because performance advice can be wrong if it is not tied to measured
quantities. For example, repeated text is not automatically waste, and a latency
component that dominates a tiny request is not necessarily worth optimizing.

M2 validated the prefix/cacheability mechanism on real vLLM. A controlled
workload used the same semantic content in two layouts. With dynamic content
before stable context, repeated text did not become reusable prefix-cache
blocks. Moving the same stable context into the prefix made the request layout
cacheable. AgentPerf found the baseline pathology and the prefix-cache finding
disappeared after replay. The exact measurements are kept in the detailed
reproducibility docs rather than used as promotional headline numbers.

M3 moved from a controlled request workload to a real framework-free research
agent with planner, local search, evidence review, another search, and final
synthesis. The first aggressive compaction reduced tokens but harmed answer
quality, which was a useful failure. The benchmark was then fixed and multiple
deterministic carry-forward strategies were evaluated. The accepted strategy,
DEDUP_ONLY, reduced processed input tokens by 28.1% and tool-result processed
tokens by 30.0% while staying within an explicit quality tolerance.

M4 is only partially complete. Phase A replayed role-specific counterfactuals
for planner, reviewer, and synthesizer using Qwen3 0.6B, 1.7B, and 4B models.
It found role-specific model headroom, but Phase B end-to-end mixed routing did
not complete because GPU/runtime setup attempts failed before replay. The
proposed mixed candidate must not be presented as validated.

## Strong Engineering Challenges

1. Request correlation had to be explicit and auditable. Timestamp-based joins
   would have made the profiler look complete while silently creating false
   evidence.
2. vLLM telemetry semantics needed careful naming. `scheduled_to_first_token` is
   useful, but it is not pure GPU prefill kernel time.
3. Detector materiality required real-data calibration. Dominance alone created
   misleading prefill findings until absolute latency and uncached-token volume
   were included.
4. Agent quality had to be preserved. The first context compaction looked great
   for tokens and latency but degraded task quality, so the accepted
   recommendation became quality-constrained.
5. GPU environment reproducibility was nontrivial. CUDA runtime, driver labels,
   vLLM wheels, container startup, and Runpod node variability all affected live
   execution.

## Strong Quantitative Results

1. Real-agent context-waste story: DEDUP_ONLY reduced processed input tokens
   from 132,756 to 95,479 and tool-result processed tokens from 112,287 to
   78,566 while staying within the declared quality tolerance.
2. Real-agent latency story: under DEDUP_ONLY, P95 scheduled-to-first-token
   latency fell from 312.18 ms to 176.53 ms and P95 client latency fell from
   1607.11 ms to 1247.62 ms.
3. External framework/correlation story: OpenAI Agents SDK integration
   preserved the agent loop and M6 correlated 10/10 external-agent LLM calls to
   real vLLM serving requests with propagated request IDs.
4. M4 Phase A: all-4B baseline quality was 0.967 mean score and 90% pass rate;
   one-role replay found several quality-preserving smaller-model candidates.
   This is counterfactual evidence only, not an end-to-end mixed-routing result.

## Failure And Learning Stories

- Repeated content is not the same as reusable prefix. vLLM caches reusable
  prefix blocks; repeated content after changing dynamic prefixes did not create
  cache reuse.
- Dominant does not mean material. A first-token path can dominate because queue
  time is near zero even when absolute latency is too small to prioritize.
- Aggressive context reduction can harm quality. The first compact
  representation reduced tokens dramatically but degraded correctness, so the
  final story became quality-constrained optimization.
- Model sensitivity is role-specific and non-monotonic. In M4 Phase A, the
  reviewer role had a noisy result where 1.7B violated quality while 0.6B did
  not. That should be investigated, not generalized.
- Runtime reproducibility matters. A profiler that depends on live serving
  telemetry must treat CUDA/vLLM/container setup as part of the engineering
  system, not background detail.

## What Not To Claim

- Do not claim AgentPerf is production-ready.
- Do not claim it replaces Langfuse, Phoenix, vLLM, SGLang, or ThunderAgent.
- Do not claim it invented agent-aware KV-cache optimization.
- Do not turn the controlled M2 prefix/cacheability numbers into a release
  headline, resume bullet, or general speedup claim.
- Do not call scheduled-to-first-token pure GPU prefill latency.
- Do not claim optimal KV-cache sizing.
- Do not claim M4 mixed routing is validated.
- Do not claim small models are generally better for the reviewer role.
- Do not present synthetic fixtures as benchmark results.

## Resume Bullets

- Built AgentPerf, an open-source cross-layer profiler that correlates agent
  traces with vLLM serving telemetry to diagnose token, cacheability, and
  first-token latency pathologies using deterministic evidence rather than
  LLM-generated advice.
- Validated a real multi-step research-agent optimization where
  quality-constrained tool-result deduplication reduced processed input tokens
  by 28.1% and tool-result processing by 30.0% while staying within a declared
  quality tolerance.
- Experimental: implemented model-choice counterfactual profiling by semantic
  agent role and validated Phase A role sensitivity on Qwen3 0.6B/1.7B/4B; the
  end-to-end mixed-routing replay remains pending.
