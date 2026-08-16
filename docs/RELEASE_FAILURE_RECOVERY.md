# Release Failure Recovery

This document covers the v0.5.0 GitHub Release, TestPyPI, and PyPI publication
path. It does not authorize publishing.

## TestPyPI Fails

If TestPyPI upload or install verification fails:

1. Do not proceed to production PyPI.
2. Preserve the workflow logs.
3. Fix packaging, metadata, or Trusted Publisher configuration in a reviewed PR.
4. Rebuild and rerun `twine check dist/*`.
5. Retry TestPyPI only after explicit maintainer approval.

## PyPI Trusted Publishing Fails

If production PyPI Trusted Publishing fails before any file is uploaded:

1. Do not create a replacement package name.
2. Verify the PyPI pending publisher settings:
   - owner: `printf905`;
   - repository: `AgentPerf`;
   - workflow filename: `publish-pypi.yml`;
   - environment: `pypi`.
3. Verify the GitHub `pypi` environment approval and OIDC permissions.
4. Fix configuration or workflow issues in a reviewed PR when repository changes
   are needed.

## GitHub Release Succeeds But PyPI Fails

If the GitHub Release is published but PyPI publication fails:

1. Immediately update the GitHub Release body to state that PyPI publication is
   pending or failed.
2. Do not advertise `pip install agentperf` as available until PyPI succeeds.
3. Fix the failure through a reviewed PR or publisher configuration change.
4. Re-run the publish workflow only after maintainer approval.

## PyPI Succeeds But Post-Install Smoke Fails

If `agentperf==0.5.0` uploads successfully but a post-install smoke fails:

1. Do not delete or reuse the already published PyPI version.
2. Yank the release only if the maintainer decides the package is harmful or
   unusable for new installs.
3. Fix the issue in a new reviewed PR.
4. Publish a new patch version, for example `0.5.1`, after validation.

## Bad Release Claim

If a release note or README claim is discovered to be misleading:

1. Correct the GitHub Release text immediately.
2. Fix repository docs in a reviewed PR.
3. Avoid changing package artifacts unless the installed package itself is
   misleading or broken.

