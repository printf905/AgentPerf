# External Agent Selection

Status: M5 selection completed. Selected framework: OpenAI Agents SDK.

This review used current official documentation and official repositories. The
goal was not to pick a fashionable framework; it was to choose one existing
agent runtime that can test whether AgentPerf generalizes beyond agents written
specifically for AgentPerf.

## Selection Criteria

| Criterion | Why it matters |
| --- | --- |
| Genuine multi-step agent behavior | AgentPerf must observe a real agent loop, not one manual prompt. |
| Real tool calls | Tool spans and tool-result reinjection are central M3/M5 surfaces. |
| Multiple LLM calls | Token attribution and context growth require repeated calls. |
| Conversation/state carry-forward | The profiler needs to see what the harness resends. |
| Reproducibility | M5 should run without external search/API nondeterminism. |
| OpenAI-compatible endpoint support | Later vLLM validation should be possible. |
| Instrumentation hooks | Adapter should use public hooks, not monkey-patching internals. |
| Maintenance/activity | Public users should not start from a deprecated runtime. |
| Dependency weight | AgentPerf core should remain lightweight. |
| Integration complexity | Adoption cost is a product metric. |

## Candidates

### OpenAI Agents SDK

Sources:

- https://openai.github.io/openai-agents-python/
- https://openai.github.io/openai-agents-python/tools/
- https://openai.github.io/openai-agents-python/ref/tracing/
- https://openai.github.io/openai-agents-python/models/
- https://github.com/openai/openai-agents-python

Assessment:

- Multi-step behavior: yes. The SDK provides an agent loop that handles tool
  invocation and continues until the task is complete.
- Tool calls: yes. Function tools are a first-class concept.
- Multiple LLM calls: yes for tool-using agents.
- State carry-forward: yes. Tool results are passed back into later model calls.
- Reproducibility: good when using deterministic local tools and a scripted or
  local model.
- OpenAI-compatible endpoint support: good. The model docs describe custom
  OpenAI-compatible endpoints and Chat Completions model configuration.
- Instrumentation hooks: strong. The SDK exposes tracing processors with trace
  and span lifecycle callbacks.
- Maintenance/activity: strong, official OpenAI repository and docs.
- Dependency weight: moderate; keep as optional `openai-agents` extra.
- Integration complexity: low. A trace processor plus optional model wrapper
  captures useful agent-layer data without patching SDK internals.

Limitations:

- Built-in `ResponseSpanData.export()` currently exposes response ID and usage,
  but not full prompt input. AgentPerf therefore uses a model wrapper when prompt
  component attribution is required.
- A deterministic local model is useful for M5 reproducibility, but it is not a
  quality benchmark for OpenAI-hosted models.

### LangGraph / LangChain Agents

Sources:

- https://docs.langchain.com/oss/python/langchain/agents
- https://docs.langchain.com/oss/python/langchain/middleware/overview
- https://docs.langchain.com/oss/python/langchain/middleware/custom
- https://docs.langchain.com/oss/python/langgraph/event-streaming
- https://github.com/langchain-ai/langgraph

Assessment:

- Multi-step behavior: yes. LangChain agents are implemented as graph-based
  agent loops over model and tool nodes.
- Tool calls: yes.
- Multiple LLM calls: yes.
- State carry-forward: yes.
- Reproducibility: good with fake/local chat models and deterministic tools.
- OpenAI-compatible endpoint support: good through LangChain model providers.
- Instrumentation hooks: strong. Middleware exposes before/after and wrap hooks
  for model and tool calls; LangGraph also has event streaming.
- Maintenance/activity: strong.
- Dependency weight: high for AgentPerf's current minimal package.
- Integration complexity: moderate. Middleware is powerful but introduces more
  framework-specific request/handler abstractions than M5 needs.

Decision: good future adapter candidate, but not the first M5 target.

### AutoGen

Sources:

- https://github.com/microsoft/autogen
- https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/models.html

Assessment:

- Multi-step behavior: yes.
- Tool calls: yes.
- Multiple LLM calls: yes.
- OpenAI-compatible endpoint support: possible.
- Maintenance/activity: not ideal for new integration. The official repository
  now states AutoGen is in maintenance mode and points new users toward
  Microsoft Agent Framework.

Decision: not selected. A new AgentPerf adapter should not start from a runtime
whose own README tells new users to migrate elsewhere.

### CrewAI

Sources:

- https://github.com/crewAIInc/crewAI
- https://github.com/orgs/crewAIInc/repositories

Assessment:

- Multi-agent and tool behavior: strong.
- OpenAI-compatible/local model support: available through its LLM configuration
  ecosystem.
- Maintenance/activity: strong.
- Dependency and integration complexity: higher than needed for M5.
- Reproducibility: many official examples use external search/API tools, which
  would add nondeterminism unless replaced.

Decision: plausible future adapter, but not selected for the first
generalization milestone.

## Decision

Choose OpenAI Agents SDK for M5.

Rationale:

1. It is an actively maintained official framework with real tool-using agent
   examples.
2. It has public tracing lifecycle hooks, so AgentPerf can integrate without
   monkey-patching internals.
3. It supports OpenAI-compatible model paths for future vLLM validation.
4. It is small enough to keep AgentPerf's core dependency-free by making the
   integration optional.
5. A deterministic local scripted model can exercise the real SDK agent loop
   without external API credentials or GPU rental.

The selected workload is based on the SDK's basic function-tool agent pattern:
a support triage agent calls a deterministic local policy lookup tool before
returning a routed answer. This is not designed to trigger a particular
AgentPerf detector; it is a natural small tool-using agent shape.
