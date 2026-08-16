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

### P2: Adoption and real-user validation remain limited

Evidence:

- AgentPerf now has local/offline product coverage for capture, profiling,
  diagnosis, recommendations, replay verification, CI checks, HTML reports,
  checkpoint recovery, and explicit multi-agent/branch semantics.
- Most validation is still deterministic, local, and maintainer-run.
- PyPI publication has not happened, so external package-index installation has
  not yet produced real user feedback.

User impact:

The next unknown is less about missing core functionality and more about whether
new users can successfully adopt the package, instrument their own agents, and
trust the outputs without maintainer guidance.

Reproducer:

Publish a reviewed release, then ask users outside the project to run
`pip install agentperf`, `agentperf demo`, and a small BYOA instrumentation path.

Workaround:

Use local wheel/source installs and the deterministic demo until a package-index
release is approved.

Minimum fix:

Complete a controlled release, publish through the approved PyPI process, and
collect issue/PR feedback from real users before adding more product surface.

Recommended timing:

After release-owner approval for package publication.

## P0 Gaps

No P0 product gap was found in this audit.

## P1 Gaps

No implementation P1 product gap remains for the intended local/offline profiler
scope. PyPI publication and release-owner setup remain a P1 distribution gap
because they block the canonical `pip install agentperf` onboarding path.

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
