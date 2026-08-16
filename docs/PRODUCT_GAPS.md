# AgentPerf Product Gaps

Audit date: 2026-08-16

This file records gaps that emerged from product-hardening audits and tests. It
does not include speculative feature wishes.

Severity:

- P0: misleading/corrupt core result, security issue, broken main workflow.
- P1: broad real-agent limitation.
- P2: usability/performance improvement.

## Top Remaining Gaps

### P1: PyPI publication and release-owner setup are not complete

Evidence:

- `pyproject.toml` defines package `agentperf`.
- Wheel and sdist build locally.
- Clean wheel installation has been validated in prior M22 work and should be
  rerun before any release.
- Public PyPI JSON endpoint for `agentperf` returned `404` during this audit.

User impact:

Developers cannot yet complete the ideal journey with `pip install agentperf`
from PyPI. They need a local wheel or source checkout.

Reproducer:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/agentperf/json
```

Workaround:

Build a local wheel and install it into a clean virtual environment.

Minimum fix:

Prepare a release, configure PyPI ownership or Trusted Publishing, upload only
after explicit human release authorization, and verify post-upload install.

Recommended timing:

Next. Distribution is now a larger adoption blocker than another feature.

### P1: Long-running production capture lacks incremental recovery

Evidence:

- `ExperimentSession` finalizes a complete artifact atomically at session end.
- New tests confirm failed validation does not publish an incomplete artifact and
  does not overwrite an existing valid artifact.
- There is no incremental span flush, crash recovery, append-only capture log, or
  multi-process writer coordination.

User impact:

Long-running agents, daemons, or production processes can lose in-memory trace
data if interrupted before finalization. This is acceptable for current local
offline experiments but limits broader production capture.

Reproducer:

Interrupt a process before `ExperimentSession.finalize()` completes. The final
artifact path is not marked COMPLETE prematurely, but captured in-memory spans
are not recoverable unless the user emitted their own intermediate data.

Workaround:

Use bounded experiment sessions, frequent task batches, and external process
supervision. Treat AgentPerf as an offline/local profiler.

Minimum fix:

Design an append-only or periodic flush mechanism with explicit PARTIAL artifact
semantics. This requires product review before implementation.

Recommended timing:

After PyPI/distribution if production capture becomes a priority.

### P2: Parallel branch and multi-agent semantics are not first-class

Evidence:

- Hardening tests now cover `asyncio.gather`, concurrent tool/LLM branches,
  exceptions, cancellation, nested run scopes, and context propagation.
- The schema still represents spans, runs, roles, and metadata, not explicit
  branch/fan-in or multi-agent handoff entities.

User impact:

Highly parallel graph agents or multi-agent systems can be profiled, but reports
may not visually explain branch causality, handoffs, or cross-agent context as
first-class concepts.

Reproducer:

Create a graph with multiple concurrent branches and a fan-in summarizer. The
spans attach to the correct run, but branch identity must be inferred from
metadata.

Workaround:

Add branch, agent, and handoff identifiers in metadata today.

Minimum fix:

Design first-class branch/agent/handoff schema semantics and HTML visualization.
This is a product design decision, not a small hardening fix.

Recommended timing:

Only after real users need first-class multi-agent or parallel-graph reporting.

## P0 Gaps

No P0 product gap was found in this audit.

## Explicitly Out Of Scope

The following are not required for core completeness based on current evidence:

- hosted dashboard;
- cloud artifact registry;
- third serving backend;
- additional random framework adapters;
- automatic code rewriting;
- LLM-generated recommendation engine;
- universal evaluator;
- GPU kernel tracing;
- distributed scheduling;
- historical SaaS analytics.
