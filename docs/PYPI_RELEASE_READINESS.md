# AgentPerf PyPI Release Readiness

Audit date: 2026-08-16

This document prepares for a future package-index release. It does not authorize
or perform a PyPI/TestPyPI upload.

## Current State

- Package name in `pyproject.toml`: `agentperf`
- Current package version: `0.4.0`
- Required Python: `>=3.11`
- Locally validated clean wheel installs: Python 3.11 and Python 3.12 in this
  hardening pass.
- Base runtime dependencies: none
- Optional extras:
  - `dev`
  - `openai-agents`
  - `mini-swe-agent`
  - `langgraph`
- CLI entry point: `agentperf = "agentperf.cli:main"`

## Package Name Status

Read-only PyPI check:

```text
https://pypi.org/pypi/agentperf/json -> 404
```

As of this audit, `agentperf` is not published on PyPI. Availability can change
and must be rechecked immediately before any upload.

## Metadata Readiness

The project has package metadata for:

- name;
- version;
- description;
- README;
- license;
- Python classifiers for 3.11 and 3.12;
- project URLs;
- optional extras;
- console entry point.

Before upload, run:

```bash
python -m build
twine check dist/*
```

Then install the built wheel in clean environments outside the source checkout.

## Clean-Install Smoke

Base wheel:

```bash
python -m venv /tmp/agentperf-clean
/tmp/agentperf-clean/bin/python -m pip install dist/agentperf-*.whl
cd /tmp
agentperf --help
agentperf demo --output /tmp/agentperf-demo --force
agentperf doctor /tmp/agentperf-demo/baseline
agentperf report /tmp/agentperf-demo/baseline --output /tmp/agentperf-report.html
agentperf compare /tmp/agentperf-demo/baseline /tmp/agentperf-demo/candidate
agentperf check /tmp/agentperf-demo/baseline /tmp/agentperf-demo/candidate \
  --policy /tmp/agentperf-demo/agentperf-regression.yaml
```

LangGraph extra:

```bash
python -m venv /tmp/agentperf-langgraph
/tmp/agentperf-langgraph/bin/python -m pip install "dist/agentperf-*.whl[langgraph]"
```

Use shell expansion carefully; some shells require the exact wheel filename.

This audit installed the local wheel in clean Python 3.11 and 3.12 virtual
environments outside the source tree. Base import, `agentperf --help`,
`agentperf demo`, `doctor`, `report`, `compare`, and `check` passed. The
`agentperf[langgraph]` optional extra installed from the local wheel on Python
3.12, and importing `agentperf.integrations.langgraph.instrument` succeeded.

## Trusted Publishing Requirements

Human/repository-owner steps still required:

1. Confirm PyPI project ownership or create the project during the first upload.
2. Decide whether to use PyPI Trusted Publishing or an API token.
3. If using Trusted Publishing, configure the PyPI project publisher with:
   - repository owner/name;
   - workflow filename;
   - release environment if used;
   - branch/tag trigger policy.
4. Add or review a release-only GitHub Actions publishing workflow.
5. Verify that the workflow cannot publish from arbitrary PRs.
6. Perform one explicit release authorization before upload.
7. After upload, verify installation from PyPI in a fresh environment.

## Recommended Safe Workflow

Use a release-triggered workflow, for example `workflow_dispatch` or a tag
pattern, rather than publishing on every push to `main`.

Publishing should remain manual-owner controlled until the project has a stable
release process.

## Non-Goals

This readiness pass does not:

- upload to PyPI;
- upload to TestPyPI;
- create a tag;
- create a GitHub Release;
- change package version;
- reserve a package name;
- configure credentials.

## Current Readiness Assessment

Technical packaging is close to ready. The remaining blocker is release-owner
configuration and explicit publication authorization, not another AgentPerf
feature.
