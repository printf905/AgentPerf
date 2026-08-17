# AgentPerf PyPI Release Readiness

Audit date: 2026-08-16

This document prepares for a future package-index release. It does not authorize
or perform a PyPI/TestPyPI upload.

## Current State

- Latest GitHub Release at this audit: `v0.4.0`
- Package name in `pyproject.toml`: `agentperf`
- Current package version: `0.5.0` on the release-prep branch
- Artifact schema version: `1`
- Required Python: `>=3.11`
- Locally validated clean wheel installs: Python 3.11 and Python 3.12 in this
  distribution-readiness pass.
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

As of 2026-08-16, `agentperf` is not published on PyPI. This does not reserve
the project name; availability can change and must be rechecked immediately
before any upload.

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

The project URLs include Homepage, Repository, Issues, Documentation, Changelog,
and Releases.

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

The v0.5.0 release-prep audit must install the local wheel in clean Python 3.11
and 3.12 virtual environments outside the source tree. Base import,
`agentperf --help`, `agentperf demo`, `doctor`, `report`, `compare`, and
`check` must pass. The `agentperf[langgraph]` optional extra should be validated
from the release-candidate wheel on Python 3.12.

## Trusted Publishing Requirements

Human/repository-owner steps still required:

1. Confirm or create the PyPI owner account with required account security.
2. Configure a pending PyPI Trusted Publisher for `agentperf`, or configure a
   trusted publisher on the existing project if the first upload has already
   happened.
3. Use:
   - GitHub owner: `printf905`;
   - repository: `AgentPerf`;
   - workflow filename: `publish-pypi.yml`;
   - environment: `pypi`.
4. Configure the GitHub `pypi` environment with human approval.
5. Review `.github/workflows/publish-pypi.yml` before any release publication.
6. Recheck package-name availability immediately before the first upload.
7. Perform one explicit release authorization before upload.
8. After upload, verify installation from PyPI in a fresh environment.
9. For TestPyPI, use the separate pending publisher:
   - GitHub owner: `printf905`;
   - repository: `AgentPerf`;
   - workflow filename: `publish-testpypi.yml`;
   - environment: `testpypi`.
10. Configure the GitHub `testpypi` environment with human approval.

## Recommended Safe Workflow

Use `.github/workflows/publish-pypi.yml`, which runs only for a published
GitHub Release and publishes through PyPI Trusted Publishing. The publish job
uses job-level `id-token: write` and no long-lived PyPI token.

Publishing should remain manual-owner controlled through GitHub Release review
and the `pypi` environment approval gate.

See [PYPI_TRUSTED_PUBLISHING.md](PYPI_TRUSTED_PUBLISHING.md) for the detailed
plan and post-publish verification commands.
See [RELEASE_OPERATOR_RUNBOOK.md](RELEASE_OPERATOR_RUNBOOK.md) for the
human-executable TestPyPI and production sequence.

## Non-Goals

This readiness pass does not:

- upload to PyPI;
- upload to TestPyPI;
- create a tag;
- create a GitHub Release;
- change package version outside the explicit release-prep branch;
- reserve a package name;
- configure credentials.

## Current Readiness Assessment

Technical packaging is close to ready. The remaining blocker is release-owner
configuration and explicit publication authorization, not another AgentPerf
feature.

The release-prep branch bumps the package version to `0.5.0`. Publication still
requires explicit human authorization, TestPyPI/PyPI Trusted Publisher setup,
and post-upload verification.
