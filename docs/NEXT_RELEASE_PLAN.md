# Next Release Plan

Audit date: 2026-08-16

This document plans the next release without performing release work. It does
not bump the package version, create a tag, create a GitHub Release, upload to
TestPyPI, or upload to PyPI.

## Actual Release State

- Latest stable tag: `v0.4.0`
- Latest GitHub Release: `AgentPerf v0.4.0 — Bring Your Own Agent and Trustworthy Diagnosis`
- Release commit: `1f1002ede596d63e0e945e43c2bb416b3e787139`
- Current main at audit: `ad5e6f727e72942d302c5837a4b469a2e3b80fa7`
- Commits since `v0.4.0`: 19
- Current package version at the final productization audit: `0.4.0`
- Artifact schema version: `1`

## Post-v0.4 Capability Groups

### Easier Onboarding And Distribution

- source-tree-independent `agentperf demo`;
- clean wheel/sdist packaging and smoke validation;
- getting-started and CI documentation;
- copyable GitHub Actions regression example;
- PyPI Trusted Publishing plan and release checklist.

### Broader Capture

- framework-free BYOA remains the base path;
- LangGraph optional integration;
- async/concurrent-safe tracing;
- long-running checkpoint and crash recovery;
- first-class explicit multi-agent, branch, and handoff metadata.

### Profiler Trust And Recommendations

- measured instrumentation overhead and local scale characterization;
- structured recommendation contracts;
- recommendation verification against replay;
- stronger provenance/materiality wording preserved across reports.

### Replay And Visual Verification

- standalone before/after comparison HTML;
- policy-aware HTML checks;
- quality-aware comparison and CI regression gates.

### Model-Capacity Closure

- role-level model counterfactual representation;
- local model-choice headroom semantics;
- full mixed-routing verification;
- one bounded M25 Phase B result marked `GLOBAL_ROUTING_VERIFIED`.

## Version Recommendation

Recommended next version: `v0.5.0`.

Reasoning: `v0.4.0` is already the latest stable release, and current main has
substantial post-v0.4 user-facing functionality: standalone onboarding,
distribution readiness, LangGraph, visual comparison reports, structured
recommendations, model-capacity routing verification, crash-recoverable capture,
and multi-agent semantics. This is not a patch-only change set.

The `release/v0.5.0-prep` branch is the authorized release-prep branch that
bumps the package version to `0.5.0`. Do not publish from it until the release
owner completes TestPyPI/PyPI setup and explicitly approves publication.

Files likely involved in a future release-prep PR:

- `pyproject.toml`
- `agentperf/__init__.py`
- `CHANGELOG.md`
- release notes for `v0.5.0`
- README install wording after PyPI publication

The artifact schema version remains independent and should not change unless an
artifact compatibility change requires it.

## Candidate Release Stories

| Story | Clarity | Accuracy | Coherence | Differentiation | Overclaim risk |
|---|---|---|---|---|---|
| AgentPerf v0.5.0 — Complete Local Agent Performance Profiling | High | High if "local" remains explicit | High | High | Medium |
| AgentPerf v0.5.0 — Multi-Agent Profiling, Replay Verification, and Easy Onboarding | Medium | High | Medium | Medium | Low |
| AgentPerf v0.5.0 — From Your Agent to Verified Performance Changes | High | High | High | High | Low |

Recommended story:

```text
AgentPerf v0.5.0 — From Your Agent to Verified Performance Changes
```

This keeps the release centered on the full user loop without implying hosted
production infrastructure or universal optimization.

## Release Notes Outline

```markdown
# AgentPerf v0.5.0

## Install and try it locally

- pip install agentperf
- agentperf demo

## Profile more realistic agent structures

- async/concurrent-safe tracing
- long-running checkpoint recovery
- explicit multi-agent, branch, and handoff semantics

## Diagnose and verify changes

- structured recommendation contracts
- recommendation verification
- standalone comparison HTML
- quality-aware CI regression checks

## Model-capacity replay

- role-level counterfactual evidence
- full mixed-routing verification on one bounded workload

## Ecosystem

- framework-free BYOA
- LangGraph
- OpenAI Agents SDK
- vLLM and SGLang correlation

## Validation and limitations

- M3 remains the primary scoped quantitative optimization example
- local/offline scope
- backend-dependent serving telemetry
- no distributed ingestion
- no hosted dashboard
- no universal detector accuracy or model-routing claim
```

## PyPI And Release Sequence

Recommended sequence:

1. Open a release-prep PR that bumps the version, finalizes changelog/release
   notes, and switches install wording only when publication is imminent.
2. Merge the release-prep PR after validation.
3. Configure PyPI Trusted Publishing for project `agentperf`:
   - owner: `printf905`;
   - repository: `AgentPerf`;
   - workflow filename: `publish-pypi.yml`;
   - environment: `pypi`.
4. Configure the GitHub `pypi` environment with human approval.
5. Recheck `https://pypi.org/pypi/agentperf/json`.
6. Prefer a TestPyPI publish first because this will be AgentPerf's first
   package-index publication.
7. Run final main validation.
8. Create the `v0.5.0` tag.
9. Publish the GitHub Release.
10. Approve the protected `pypi` environment deployment only after release
    artifacts are reviewed.
11. Verify the PyPI upload and fresh `pip install agentperf==0.5.0`.

If PyPI publication fails after the GitHub Release is published, immediately
mark the GitHub Release notes with the package-publication status, avoid
advertising `pip install agentperf` as available, fix the packaging/publisher
issue in a reviewed PR, and rerun the publish workflow from a corrected release
process.

## TestPyPI Recommendation

Recommendation: TESTPYPI FIRST.

Reason: AgentPerf has not previously been published to a package index. TestPyPI
can validate OIDC publisher setup, metadata rendering, and install behavior
without consuming the real PyPI name/version.

## Human Actions Required

- Choose and approve the next version.
- Approve a release-prep PR.
- Configure PyPI account ownership and required security controls.
- Configure pending PyPI Trusted Publisher.
- Configure GitHub `pypi` environment approval.
- Authorize any TestPyPI or PyPI upload.
- Verify post-publish installation.
