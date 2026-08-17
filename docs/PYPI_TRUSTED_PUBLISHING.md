# PyPI Trusted Publishing Plan

Audit date: 2026-08-16

This plan prepares a future PyPI upload. It does not publish AgentPerf, create a
tag, create a release, or configure PyPI account ownership.

## Current Name State

Read-only PyPI checks on 2026-08-16 during v0.5.0 release prep:

```text
https://pypi.org/pypi/agentperf/json -> 404
https://pypi.org/project/agentperf/ -> project page not found
```

The `agentperf` name is not currently published on PyPI. This does not reserve
the name. Recheck immediately before the first upload.

## Recommended Publisher

Use PyPI Trusted Publishing with GitHub Actions OIDC.

Trusted Publishing avoids storing a long-lived PyPI API token in GitHub. The
PyPI account owner still needs to configure a publisher on PyPI before the
workflow can upload.

Recommended PyPI publisher settings:

```text
PyPI project: agentperf
GitHub owner: printf905
GitHub repository: AgentPerf
Workflow filename: publish-pypi.yml
Environment: pypi
```

The GitHub `pypi` environment should require manual approval by a trusted
maintainer before deployment.

## Workflow Behavior

The prepared workflow is:

```text
.github/workflows/publish-pypi.yml
```

It is intentionally release-triggered:

```text
on:
  release:
    types: [published]
```

It does not run on pull requests or pushes. It does not contain PyPI API tokens.

The workflow:

1. builds the wheel and sdist once;
2. runs `twine check dist/*`;
3. uploads the built distributions as a GitHub Actions artifact;
4. publishes those exact distributions in a separate job using OIDC.

The publish job grants only:

```text
permissions:
  id-token: write
```

at the job level, as required for Trusted Publishing.

## First Project Creation

If the PyPI project does not exist, the release owner can configure a pending
Trusted Publisher for `agentperf`. PyPI states that a pending publisher does not
create or reserve the project name until it is used for the first publish.

Human action required:

1. Sign in to PyPI with the intended owner account.
2. Ensure account security requirements, including 2FA where required.
3. Add a pending GitHub Actions Trusted Publisher with the settings above.
4. Confirm the GitHub `pypi` environment exists and requires approval.
5. Publish only from a reviewed GitHub Release after package validation passes.

## TestPyPI Decision

Recommendation: use TestPyPI first for the first package-index publication.

Reason: AgentPerf has never been uploaded to a package index. TestPyPI can verify
the OIDC publisher configuration, upload mechanics, rendered metadata, and
wheel installation without consuming the real PyPI project name/version.

TestPyPI human steps:

1. Configure a TestPyPI pending Trusted Publisher with the same owner and
   repository, but with the dedicated TestPyPI workflow and environment.
2. Run the dedicated manual TestPyPI workflow, which points
   `pypa/gh-action-pypi-publish` at `https://test.pypi.org/legacy/`.
3. Install from TestPyPI in a fresh environment.
4. Keep the TestPyPI path clearly separated from the production PyPI workflow.

Do not publish to TestPyPI from normal CI.

Recommended TestPyPI publisher settings:

```text
TestPyPI project: agentperf
GitHub owner: printf905
GitHub repository: AgentPerf
Workflow filename: publish-testpypi.yml
Environment: testpypi
Repository URL in publish action: https://test.pypi.org/legacy/
```

Do not reuse the production PyPI environment or workflow for TestPyPI.

After a human-authorized TestPyPI upload:

```bash
python -m venv /tmp/agentperf-testpypi-smoke
source /tmp/agentperf-testpypi-smoke/bin/activate
python -m pip install --upgrade pip
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  agentperf==0.5.0
agentperf --help
agentperf demo --output /tmp/agentperf-testpypi-demo --force
agentperf doctor /tmp/agentperf-testpypi-demo/baseline
agentperf report /tmp/agentperf-testpypi-demo/baseline \
  --output /tmp/agentperf-testpypi-report.html
agentperf compare \
  /tmp/agentperf-testpypi-demo/baseline \
  /tmp/agentperf-testpypi-demo/candidate
agentperf check \
  /tmp/agentperf-testpypi-demo/baseline \
  /tmp/agentperf-testpypi-demo/candidate \
  --policy /tmp/agentperf-testpypi-demo/agentperf-regression.yaml
```

## Post-Publish Verification

After a future PyPI upload:

```bash
python -m venv /tmp/agentperf-pypi-postpublish
source /tmp/agentperf-pypi-postpublish/bin/activate
python -m pip install --upgrade pip
pip install agentperf==0.5.0
agentperf --help
agentperf demo --output /tmp/agentperf-pypi-demo --force
agentperf doctor /tmp/agentperf-pypi-demo/baseline
agentperf report /tmp/agentperf-pypi-demo/baseline \
  --output /tmp/agentperf-pypi-report.html
agentperf compare \
  /tmp/agentperf-pypi-demo/baseline \
  /tmp/agentperf-pypi-demo/candidate
agentperf check \
  /tmp/agentperf-pypi-demo/baseline \
  /tmp/agentperf-pypi-demo/candidate \
  --policy /tmp/agentperf-pypi-demo/agentperf-regression.yaml
```

Also verify the PyPI project page, README rendering, project URLs, license
metadata, and `pip install "agentperf[langgraph]"`.
