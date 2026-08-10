# Real-World Agent Selection

Status: M7 selection completed. Selected target: `mini-swe-agent`.

This review used current official repositories and documentation. The goal is
to test AgentPerf against an agent that existed independently of AgentPerf, not
to create another custom workload tuned around existing detectors.

## Selection Criteria

| Criterion | Why it matters |
| --- | --- |
| Independent purpose | M7 should profile an agent people might actually run without AgentPerf. |
| Multi-step execution | Token/context growth requires repeated model calls. |
| Tools or environment actions | AgentPerf must observe downstream tool/output carry-forward. |
| Meaningful state/history | The profiler should see how the harness carries prior observations. |
| Reproducibility | A small benchmark must be runnable without live web/API nondeterminism. |
| OpenAI-compatible serving path | vLLM correlation should remain possible where practical. |
| Public instrumentation boundary | Avoid framework-internal monkey-patching. |
| Maintenance/activity | Do not start with deprecated or abandoned agent software. |
| Dependency and runtime weight | M7 should not become a deployment project. |
| Evaluation cost | Small, bounded local/GPU runs are preferable. |

## Candidates

### mini-SWE-agent

Sources:

- https://github.com/SWE-agent/mini-swe-agent
- https://mini-swe-agent.com/latest/reference/agents/default/
- https://mini-swe-agent.com/latest/advanced/environments/
- https://mini-swe-agent.com/latest/models/local_models/
- https://mini-swe-agent.com/latest/usage/output_files/

Assessment:

- Original purpose: coding/repository agent that uses an LM plus a shell
  environment to fix tasks.
- Maintenance/activity: strong. The README describes mini-SWE-agent v2 as the
  current default over the older SWE-agent path and shows active current docs.
- Workflow: issue/task text -> model proposes bash action -> environment
  executes command -> observation is appended -> repeated until submission.
- LLM calls: naturally multiple.
- Tools/environment actions: bash is the primary tool.
- History/context behavior: strong fit. The official README describes a
  completely linear history where every step appends to the messages passed to
  the LM.
- OpenAI-compatible support: possible through LiteLLM/local model
  configuration.
- Instrumentation difficulty: low to moderate. Python bindings expose
  `DefaultAgent`, model, and environment objects. AgentPerf can wrap the model
  and environment boundaries without patching upstream internals.
- Dependency weight: optional, but adds LiteLLM/transitive dependencies when
  installed.
- Expected cost: local deterministic smoke tests are cheap; real vLLM execution
  is possible but not required for the first M7 agent-layer profile.

Reasons for selection:

1. It is a genuinely existing coding agent, not an AgentPerf demo agent.
2. It has a natural multi-step inspect/test/edit loop with environment outputs.
3. Its linear-history design is exactly the kind of harness behavior a profiler
   should be able to measure.
4. The adapter can sit at public model/environment object boundaries.
5. The same integration can later be routed through LiteLLM to an
   OpenAI-compatible vLLM endpoint.

Known caveat:

The initial checked-in M7 runner uses mini-SWE-agent's official deterministic
test model for local reproducibility. That validates framework transfer,
history/tool attribution, and integration cost. A real-model/vLLM run remains
the next optional validation layer if we want cross-layer serving data for this
specific external agent.

### SWE-agent

Sources:

- https://github.com/swe-agent/swe-agent
- https://github.com/SWE-agent/mini-swe-agent

Assessment:

- Original purpose: full SWE-bench-style coding agent.
- Workflow: rich coding agent lifecycle with repository tools and benchmark
  support.
- LLM/tool behavior: strong.
- Maintenance/activity: the official SWE-agent README says current development
  effort is on mini-SWE-agent and recommends mini-SWE-agent for most new use.
- Integration difficulty: higher than mini-SWE-agent because the full system
  has more configuration and tool abstractions.
- Expected cost: higher.

Decision: not selected. It is a strong future target, but the upstream project
itself points new users toward mini-SWE-agent.

### OpenHands

Sources:

- https://github.com/OpenHands/OpenHands
- https://www.openhands.dev/

Assessment:

- Original purpose: full AI software development platform/agent.
- Workflow: real coding agent lifecycle with CLI, GUI, SDK, and hosted/cloud
  surfaces.
- LLM/tool behavior: strong.
- Maintenance/activity: strong.
- Integration difficulty: high for this milestone. Running a representative
  OpenHands setup would likely involve heavier container/UI/runtime choices
  than M7 needs.
- Expected cost: moderate to high.

Decision: not selected for M7. Good future credibility target once AgentPerf's
adapter story is more mature.

### Hugging Face smolagents

Sources:

- https://github.com/huggingface/smolagents
- https://huggingface.co/docs/smolagents

Assessment:

- Original purpose: lightweight library for code-oriented agents.
- Workflow: CodeAgent/tool-using patterns are natural and well documented.
- OpenAI-compatible support: documented through `OpenAIModel` and external
  provider examples.
- Instrumentation difficulty: likely moderate; model/tool wrappers are possible.
- Reproducibility: good with local tools.
- Expected cost: manageable.

Decision: not selected for this milestone because mini-SWE-agent gives a more
concrete existing coding-agent loop with linear history and shell observations,
which are directly relevant to AgentPerf's context accounting.

### LangGraph / LangChain Agents

Sources:

- https://docs.langchain.com/oss/python/langgraph/quickstart
- https://github.com/langchain-ai/langgraph

Assessment:

- Original purpose: graph-based agent/workflow runtime.
- Workflow: strong for tool-using agents and stateful graphs.
- Instrumentation hooks: strong through LangChain/LangGraph event and callback
  surfaces.
- Dependency weight: higher than needed for a single M7 target.
- Risk: official quickstarts are often small examples, and using them directly
  could look like another framework demo rather than a real existing agent.

Decision: keep as future adapter candidate, not the M7 target.

## Decision

Choose `mini-swe-agent`.

M7 will use upstream `DefaultAgent` with a wrapped model and wrapped local
environment. The wrappers record AgentPerf spans but do not change the agent's
control flow, prompts, history policy, bash-action execution, or submission
logic. The first benchmark is a small repository-repair workload designed to
exercise mini-SWE-agent's natural inspect/test/edit/submit lifecycle with
bounded local execution.
