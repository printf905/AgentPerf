# PyPI Release Checklist

This checklist prepares a future package-index release. Do not upload to PyPI
or TestPyPI unless the release owner explicitly approves it.

Target release: `v0.5.0`

## Pre-Release

- Confirm `main` is clean and up to date.
- Confirm the intended package version in `pyproject.toml` and
  `agentperf.__version__`.
- Confirm the intended version is not already published on PyPI.
- Confirm artifact schema, benchmark-suite schema, and regression-policy schema
  compatibility.
- Review README and release notes for claims that imply PyPI availability.
- Confirm optional dependencies remain optional.
- Recheck `https://pypi.org/pypi/agentperf/json` immediately before first
  upload.

## Validation

```bash
pytest
ruff check .
mypy agentperf tests scripts
git diff --check
python -m build
twine check dist/*
```

## Fresh Wheel Smoke

Run from outside the source checkout:

```bash
python scripts/m22_distribution_smoke.py --wheel dist/agentperf-<version>-py3-none-any.whl
```

The smoke should install the wheel into a fresh virtual environment and run:

- `agentperf --help`
- `agentperf demo`
- `agentperf doctor`
- `agentperf report`
- `agentperf compare`
- `agentperf check`

## Optional Extra Smoke

In a separate fresh environment:

```bash
pip install "dist/agentperf-<version>-py3-none-any.whl[langgraph]"
python examples/langgraph_agent/run.py --variant raw --output-root /tmp/agentperf-langgraph
agentperf doctor /tmp/agentperf-langgraph/raw
```

Base `import agentperf` must not require LangGraph, OpenAI Agents SDK, vLLM,
SGLang, or mini-SWE-agent.

## Security And Hygiene

Check tracked files and package contents for:

- API keys or provider tokens;
- HF tokens;
- Runpod credentials;
- SSH private material;
- private local paths;
- temporary reports or local review notes;
- raw GPU/model/server logs;
- local dependency state such as `.venv`.

## Release

- Recommended first index publication path: TestPyPI first, then production
  PyPI.
- Confirm PyPI account ownership and required account security.
- Configure a pending PyPI Trusted Publisher for `agentperf` if the project does
  not yet exist.
- Configure the GitHub publisher with:
  - owner: `printf905`;
  - repository: `AgentPerf`;
  - workflow filename: `publish-pypi.yml`;
  - environment: `pypi`.
- Configure the GitHub `pypi` environment to require human approval.
- Configure a separate TestPyPI pending publisher with:
  - owner: `printf905`;
  - repository: `AgentPerf`;
  - workflow filename: `publish-testpypi.yml`;
  - environment: `testpypi`.
- Configure the GitHub `testpypi` environment to require human approval.
- Create and push the release tag only after validation passes.
- Create the GitHub Release from the tag.
- Publish to PyPI only after explicit approval.
- Do not upload private experiment data, Runpod bundles, or temporary HTML
  reports as release assets.

See [PYPI_TRUSTED_PUBLISHING.md](PYPI_TRUSTED_PUBLISHING.md) for the prepared
OIDC workflow and human configuration plan.

## Post-Upload Verification

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

After a real PyPI upload:

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

Also verify:

- PyPI project metadata renders correctly;
- README links are usable from PyPI;
- `pip install "agentperf[langgraph]"` works;
- the GitHub Release and PyPI version point to the same source state.
