# Validation Marathon

Date: 2026-08-16

Starting commit:

```text
f930b4e Merge pull request #37 from printf905/feature/deep-reliability-audit
```

Branch:

```text
feature/validation-marathon
```

Package version: `0.5.0`

Latest stable tag: `v0.4.0`

Supported Python versions claimed by metadata: Python `>=3.11`; clean
validation remains scoped to Python 3.11 and 3.12.

## Mutation Testing

See `docs/MUTATION_TESTING.md`.

Summary:

```text
5 targeted semantic mutations
5 killed
0 survived
```

Scope was comparison/regression/recommendation/model-choice semantics. This is
not a repository-wide mutation score.

## Backward Compatibility

See `docs/BACKWARD_COMPATIBILITY.md`.

Current main successfully loaded, analyzed, doctored, and rendered a
v0.4.0-generated artifact produced from a temporary install outside the current
checkout.

Tracked historical artifacts also load through public loaders.

## API / CLI / HTML Differential

Added `tests/test_validation_marathon.py` to compare semantic output from:

- Python API;
- CLI JSON;
- terminal output markers;
- markdown check output;
- HTML embedded structured data.

Validated semantic agreement for:

- comparison verdict;
- quality result;
- task matching;
- token totals;
- finding lifecycle;
- regression policy checks.

## Python 3.11 / 3.12 Equivalence

The same deterministic M3 and M25 summaries were run under Python 3.11 and
Python 3.12. The generated JSON summaries matched byte-for-byte after excluding
volatile paths/timestamps.

## Distribution

Validation performed:

- wheel clean install on Python 3.11: PASS;
- wheel clean install on Python 3.12: PASS;
- sdist clean install on Python 3.11: PASS;
- sdist clean install on Python 3.12: PASS;
- offline base wheel install with `--no-index` on Python 3.11: PASS;
- offline base wheel install with `--no-index` on Python 3.12: PASS;
- base wheel import leakage check: LangGraph, OpenAI Agents SDK,
  mini-SWE-agent, vLLM, and SGLang were not importable in the base wheel
  environment;
- `agentperf[langgraph]`: PASS;
- `agentperf[openai-agents]`: PASS;
- `agentperf[mini-swe-agent]`: PASS with upstream mini-SWE config redirected
  via `MSWEA_GLOBAL_CONFIG_DIR` to avoid writing user-level config during the
  sandboxed smoke.

Offline validation used a local wheelhouse with package-index access disabled.
It proves the installed base package and demo do not need runtime network
access, but it does not prove dependency installation can occur without a
pre-populated wheelhouse.

## Exit-Code Matrix

Added tests for:

- `check` PASS -> exit `0`;
- `check` FAIL -> exit `1`;
- `check` INCONCLUSIVE for `PARTIAL` candidate -> exit `3`;
- malformed policy/artifact/report input -> exit `2`;
- `doctor` not-ready/malformed input -> non-success.

## Filesystem Matrix

Added tests for:

- output paths containing spaces;
- nested output directories;
- symlinked HTML output target;
- existing empty demo directory;
- existing non-empty demo directory requiring `--force`.

No unrelated file overwrite was observed.

## Process Termination

Added subprocess SIGTERM coverage:

- child writes 12 completed tasks;
- explicit checkpoint is created;
- process receives SIGTERM;
- current loader recovers latest checkpoint as `PARTIAL`;
- completed span count is preserved;
- completed LLM calls retain end times.

SIGKILL still cannot trigger final cleanup; AgentPerf only guarantees evidence
through the latest completed checkpoint.

## HTML Semantic Corpus

Added tests for:

- embedded comparison JSON;
- `PARTIAL` marker visibility;
- missing quality not becoming `ACCEPT`;
- fake secrets redacted;
- HTML-breaking labels escaped;
- agent/branch call-scope indexing.

## JSON Fixture Corpus

Relevant tracked JSON fixtures are classified before loading. AgentPerf traces
and artifacts are loaded through public loaders; serving raw telemetry fixtures
are parsed as JSON and covered by backend-specific ingestion tests.

## Performance Hotspots

Profiling a 1,000-call deterministic workload showed a single-run HTML hotspot
in repeated call-scope lookup. The renderer now builds a call-scope index once
per report.

Profiled 1,000-call single-run HTML changed from roughly:

```text
8.1 s -> 1.3 s
```

The 5,000-call local baseline measured:

```text
single-run HTML: 5.2 s
comparison HTML: 8.3 s
```

Remaining P2 hotspot:

- high-frequency checkpointing writes full recoverable artifacts.

## Security / History

Current-tree and history scans found no real credential. Pattern hits were:

- request IDs that resemble secret patterns by substring;
- intentional fake-secret redaction tests.

Largest reachable Git blobs are expected trace/evidence fixtures, all below
about 1.9 MB.

## Build Reproducibility

Two isolated builds from the same source state produced matching semantic
contents:

- wheel file list: PASS;
- wheel `METADATA`: PASS;
- wheel `entry_points.txt`: PASS;
- sdist file list: PASS.

Byte-for-byte archive hashes were not treated as required because archive
metadata and compression timestamps may differ across builds.

## Release-Candidate Corpus

Added:

```text
scripts/release_candidate_corpus.py
```

It runs deterministic no-GPU/no-API commands for:

- demo;
- doctor/report/compare/check;
- M3 compare/check/suite/HTML;
- BYOA raw/optimized comparison;
- M25 preserved model-choice analysis;
- vLLM fixture;
- SGLang fixture.

Run result:

```text
Release-candidate corpus PASS
```

## Final Gates

Final local validation:

- `pytest`: 273 passed;
- `ruff check .`: PASS;
- `mypy agentperf tests scripts`: PASS;
- `git diff --check`: PASS;
- `python -m build`: PASS;
- `twine check dist/*`: PASS.

## Result

No P0 or P1 bug was found in this marathon. One P2 performance issue was fixed
in the single-run HTML renderer. High-frequency checkpoint overhead remains a
P2 scalability limitation, not a public-distribution blocker.
