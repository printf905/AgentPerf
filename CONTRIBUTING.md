# Contributing

Thanks for considering a contribution to AgentPerf.

AgentPerf v0.1 is intentionally narrow: normalized traces, explicit request
correlation, deterministic detectors, terminal reporting, and one vLLM recording
adapter. Please keep changes scoped unless an issue explicitly proposes a larger
direction.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

Run these before opening a pull request:

```bash
pytest
ruff check .
mypy agentperf tests scripts
```

## Pull Requests

PRs should include:

- a clear description of the behavior changed;
- tests for parser, adapter, detector, CLI, or reporter changes;
- updated docs when public behavior or telemetry semantics change;
- explicit notes about any unavailable or approximated backend fields.

Do not fabricate benchmark results. Synthetic traces and schema fixtures must be
clearly labeled as such. Real telemetry should include enough environment and
backend metadata to make the result understandable without overstating it.

## Benchmark And Telemetry Policy

- Synthetic examples are demos and tests, not performance evidence.
- Recorded fixtures may test schema parsing, but are not live-backend validation.
- Real backend results must name the backend version, model, environment,
  repetition count, and configuration.
- Recommendations should remain evidence-backed and should include a validation
  plan where practical.
