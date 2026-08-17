# Release Operator Runbook

This runbook is for the human-controlled AgentPerf `v0.5.0` package-index
release. It does not authorize publishing by itself.

Official references reviewed on 2026-08-17:

- <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
- <https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>
- <https://docs.pypi.org/trusted-publishers/security-model/>

## A. Preconditions

1. Confirm the release PR is merged and `main` is up to date.
2. Confirm package version is `0.5.0` in `pyproject.toml` and
   `agentperf.__version__`.
3. Confirm `agentperf` is still available on PyPI/TestPyPI immediately before
   first upload.
4. Run:

```bash
python scripts/validate_release_candidate.py --version 0.5.0
```

The helper runs local deterministic validation only. It does not use GPU, paid
APIs, external model services, tags, releases, or package uploads.

## B. TestPyPI Setup

In a browser:

1. Sign in to TestPyPI with the intended owner account.
2. Enable required account security.
3. Open account Publishing / Trusted Publishers.
4. Add a pending GitHub Actions publisher:
   - project name: `agentperf`;
   - owner: `printf905`;
   - repository: `AgentPerf`;
   - workflow filename: `publish-testpypi.yml`;
   - environment: `testpypi`.
5. In GitHub, create the `testpypi` environment.
6. Add required reviewers for `testpypi`.
7. Do not add PyPI API tokens or secrets.

## C. TestPyPI Publish

Use only the manual workflow:

1. GitHub -> Actions -> `Publish to TestPyPI`.
2. Click `Run workflow`.
3. Select branch `main`.
4. Enter:
   - `version`: `0.5.0`;
   - `confirm_target`: `TESTPYPI`.
5. Approve the `testpypi` environment deployment when ready.

Safety properties:

- workflow trigger is `workflow_dispatch` only;
- environment is `testpypi`;
- OIDC permission is job-local to the publish job;
- publish action uses `repository-url: https://test.pypi.org/legacy/`;
- it cannot publish on push or pull request.

## D. TestPyPI Fresh-Install Verification

After TestPyPI publication succeeds:

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

Also inspect the TestPyPI project page metadata and README rendering.

## E. Production PyPI Setup

In a browser:

1. Sign in to PyPI with the intended owner account.
2. Enable required account security.
3. Open account Publishing / Trusted Publishers.
4. Add a pending GitHub Actions publisher:
   - project name: `agentperf`;
   - owner: `printf905`;
   - repository: `AgentPerf`;
   - workflow filename: `publish-pypi.yml`;
   - environment: `pypi`.
5. In GitHub, create the `pypi` environment.
6. Add required reviewers for `pypi`.
7. Do not add PyPI API tokens or secrets.

## F. Final Main Validation

Immediately before tagging:

```bash
git checkout main
git pull --ff-only origin main
python scripts/validate_release_candidate.py --version 0.5.0
git status --short
```

Stop if the worktree is dirty for any reason other than known local scratch
files.

## G. v0.5.0 Tag

Only after TestPyPI verification and final validation:

```bash
git tag -a v0.5.0 -m "AgentPerf v0.5.0"
git push origin v0.5.0
```

Do not reuse the tag if a publish failure later requires code changes.

## H. GitHub Release

1. Create a GitHub Release for tag `v0.5.0`.
2. Title:

```text
AgentPerf v0.5.0 — From Your Agent to Verified Performance Changes
```

3. Use `docs/RELEASE_NOTES_v0.5.0.md` as the body.
4. Publishing the GitHub Release triggers `.github/workflows/publish-pypi.yml`.

## I. Production PyPI Approval

The production workflow:

- runs only for published GitHub Releases;
- requires release tag `v0.5.0` to match package version `0.5.0`;
- uses the `pypi` GitHub environment;
- grants `id-token: write` only to the publish job;
- uses `pypa/gh-action-pypi-publish@release/v1` without tokens.

Approve the `pypi` environment deployment only after confirming the release tag,
workflow, and built artifacts are expected.

## J. Fresh `pip install agentperf==0.5.0`

After production PyPI publication succeeds:

```bash
python -m venv /tmp/agentperf-pypi-smoke
source /tmp/agentperf-pypi-smoke/bin/activate
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

Also verify the production PyPI project page, README rendering, project URLs,
license metadata, and:

```bash
pip install "agentperf[langgraph]==0.5.0"
```

## K. Failure Recovery

TestPyPI fails:

1. Do not proceed to production.
2. Preserve workflow logs.
3. Fix configuration or packaging in a reviewed PR.
4. Retry TestPyPI only after explicit human approval.

Production Trusted Publishing fails before upload:

1. Do not choose a new package name.
2. Check PyPI pending publisher values exactly.
3. Check GitHub `pypi` environment approval and workflow filename.
4. Fix repository changes through a reviewed PR.

GitHub Release succeeds but PyPI fails:

1. Update the GitHub Release body to say PyPI publication is pending or failed.
2. Do not advertise `pip install agentperf` until PyPI succeeds.
3. Fix through configuration or a reviewed PR.

PyPI upload succeeds but post-install smoke fails:

1. Do not delete or reuse `0.5.0`.
2. Yank only if the maintainer decides the package is harmful or unusable.
3. Fix in a reviewed PR and publish a new patch version.
