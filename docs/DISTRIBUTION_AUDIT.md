# Distribution Audit

Date: 2026-08-16

Audited commit: `1efe59f`

Current package version: `0.5.0`

Python requirement: `>=3.11`

## Runtime Dependencies

The base package declares no required third-party runtime dependencies.

Optional extras:

| Extra | Dependencies | Notes |
| --- | --- | --- |
| `openai-agents` | `openai-agents>=0.19,<0.20` | Optional OpenAI Agents SDK integration. |
| `mini-swe-agent` | `mini-swe-agent>=2,<3` | Optional mini-SWE validation path. |
| `langgraph` | `langgraph>=1,<2` | Optional LangGraph integration. |
| `dev` | pytest, ruff, mypy, build, twine, OpenAI Agents, LangGraph | Development and validation only. |

Base import must not import LangGraph, OpenAI Agents SDK, mini-SWE-agent, vLLM,
or SGLang.

## Package Metadata

Audited metadata fields:

- name: `agentperf`
- version: `0.5.0`
- requires-python: `>=3.11`
- console entry point: `agentperf`
- artifact schema version: `1`

No version/schema mismatch was found in source files.

## Security and Secret Audit

Repository scan looked for common secret markers including:

- `OPENAI_API_KEY=`
- `sk-...`
- `RUNPOD_API_KEY`
- `HF_TOKEN=`
- `Authorization: Bearer`
- private-key markers

Findings:

- Fake secret strings are intentionally present in redaction tests and security
  documentation.
- `docs/VLLM_RUNPOD_CONTAINER.md` contains a command template using
  `${RUNPOD_API_KEY}`, not a concrete credential.
- No concrete credential was identified by the audit scan.
- The three untracked scratch review files remain outside packaging and were
  not staged.

## Build Status

Initial `python -m build` in the restricted sandbox failed while creating an
isolated build environment because `pypi.org` DNS was unavailable. Rerunning
the same command with network access for build dependencies succeeded.

Built artifacts:

- `dist/agentperf-0.5.0-py3-none-any.whl`: 157,529 bytes
- `dist/agentperf-0.5.0.tar.gz`: 823,212 bytes

`python -m twine check dist/*` passed for all local dist artifacts present,
including the current `0.5.0` wheel and sdist.

Wheel contents were runtime-focused and included:

- CLI entry point;
- `agentperf/py.typed`;
- core modules;
- detectors;
- reporters;
- integrations;
- recommendation/model-choice/multi-agent/checkpoint logic.

Largest `0.5.0` wheel members:

| Size | File |
| ---: | --- |
| 52,700 | `agentperf/reporters/html.py` |
| 48,169 | `agentperf/reporters/comparison_html.py` |
| 41,121 | `agentperf/comparison.py` |
| 40,757 | `agentperf/reporters/terminal.py` |
| 32,646 | `agentperf/model_choice.py` |

Largest `0.5.0` sdist members are preserved reproducibility artifacts:

| Size | File |
| ---: | --- |
| 1,890,797 | `docs/data/m25_phase_b/strong_control/agentperf_artifact/trace.json` |
| 1,889,757 | `docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact/trace.json` |
| 1,509,174 | `examples/artifacts/m3_raw_full/trace.json` |
| 1,285,261 | `examples/artifacts/m3_dedup_only/trace.json` |
| 100,154 | `examples/dogfooding/openai_agents_support_triage_compact/trace.json` |

These large files are intentionally in the sdist for source-distribution
reproducibility, not in the wheel.

## Clean Install Results

| Environment | Result |
| --- | --- |
| Python 3.11 wheel install outside repo | PASS: `agentperf --help`, `demo`, `doctor`, `report`, `compare`, and `check`. |
| Python 3.12 wheel install outside repo | PASS: `agentperf --help`, `demo`, `doctor`, `report`, `compare`, and `check`. |
| Base wheel without optional extras | PASS: `import agentperf`; LangGraph is not importable unless extra is installed. |
| Python 3.12 `agentperf[langgraph]` extra | PASS: optional dependency install and one local LangGraph instrumented run. |

## Distribution Boundary

Artifacts, checkpoints, and reports are local plaintext profiler evidence.
AgentPerf redacts rendered HTML by default, but it does not encrypt raw local
artifact data.

## License Notes

This audit did not identify vendored third-party source code requiring new
attribution. Dependency license metadata should still be reviewed by a human
release owner before first PyPI publication.
