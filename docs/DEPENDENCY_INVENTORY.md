# Dependency Inventory

Date: 2026-08-16

This is a local dependency inventory for release-readiness review. It is not a
legal conclusion.

## Base Package

`pyproject.toml` declares no required runtime dependencies:

```text
dependencies = []
```

The base wheel clean-install smoke confirmed:

- `import agentperf`: PASS;
- `agentperf demo`: PASS;
- LangGraph, OpenAI Agents SDK, mini-SWE-agent, vLLM, and SGLang are not
  importable unless separately installed.

## Optional Extras

Declared extras:

| Extra | Direct dependency |
| --- | --- |
| `langgraph` | `langgraph>=1,<2` |
| `openai-agents` | `openai-agents>=0.19,<0.20` |
| `mini-swe-agent` | `mini-swe-agent>=2,<3` |
| `dev` | pytest, ruff, mypy, build, twine, OpenAI Agents SDK, LangGraph |

Optional-extra smokes:

- `agentperf[langgraph]`: resolver/import PASS;
- `agentperf[openai-agents]`: resolver/import PASS;
- `agentperf[mini-swe-agent]`: resolver/import PASS with
  `MSWEA_GLOBAL_CONFIG_DIR` redirected to `/private/tmp` because upstream
  mini-SWE-agent creates a user config directory at import time.

## Dev Environment

The active development environment includes optional and test tooling. It is
not representative of the base package runtime dependency set.

`twine check` and clean wheel/sdist smokes are the authoritative package
installation checks for this audit.
