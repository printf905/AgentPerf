# AgentPerf v0.5.0 Release Review

Review date: 2026-08-16

This review prepares release readiness only. It does not authorize a tag,
GitHub Release, TestPyPI upload, or PyPI upload.

## Release Candidate

- Branch: `release/v0.5.0-prep`
- Package version: `0.5.0`
- Artifact schema version: `1`
- Suite schema version: `1`
- Regression-policy schema version: `1`
- Intended title: `AgentPerf v0.5.0 — From Your Agent to Verified Performance Changes`

## Blocker Review

| Area | Status | Evidence |
|---|---|---|
| Install | CLEAR | Local wheel clean-install smoke is required before merge; no base framework/backend dependencies are intended. |
| Package metadata | CLEAR | `pyproject.toml` contains name, version, README, license, URLs, classifiers, extras, and CLI entry point. |
| Public claims | CLEAR | README and release notes scope M3, M25, demo, multi-agent, long-running, vLLM, and SGLang claims conservatively. |
| Security | CLEAR | Release prep does not add runtime capture. Fake secret fixtures are test data for redaction. |
| Demo | CLEAR | `agentperf demo` remains the first local smoke target. |
| Core regression | CLEAR | Full unit and compatibility validation are required before merge. |
| PyPI workflow | CLEAR | Workflow uses release trigger, no API token, OIDC, and `pypi` environment. |
| Dependency leak | CLEAR | Base dependencies remain empty; framework extras remain optional. |

## Should Fix Before Release

- Complete human PyPI/TestPyPI Trusted Publisher setup.
- Recheck `agentperf` package-name availability immediately before upload.
- Run TestPyPI first and verify fresh install.
- Create the tag and GitHub Release only after release-prep validation is
  accepted.

## Sdist Artifact Decision

The sdist intentionally includes docs, examples, scripts, tests, and compact
preserved validation artifacts needed for source-distribution reproducibility.
The largest members are M25 Phase B and M3 trace artifacts. They materially
increase the source archive but not the runtime wheel.

Decision: keep these artifacts in the v0.5.0 sdist. They are tracked Git
evidence, support reproducibility, and the compressed sdist remains small enough
for normal package-index distribution. Do not include generated HTML reports,
Runpod logs, model weights, private configuration, or scratch review files.

## Nice To Have

- External adopter feedback after first PyPI publication.
- More screenshots or short walkthrough media for docs.

## Post Release

- Monitor installation, demo, BYOA, and optional-extra issues from real users.
- Fix any bad package publication with a new patch version; do not delete and
  reuse an already published PyPI version.

## Not Release Blockers

- No hosted dashboard.
- No remote artifact registry.
- No distributed ingestion.
- No graph edit-distance alignment.
- No third serving backend.
- No additional framework integration.
- Limited external adoption before first PyPI release.

## Decision

Release candidate state should be classified after final validation as one of:

- READY FOR HUMAN TESTPYPI SETUP
- READY AFTER SPECIFIC FIXES
- NOT READY
