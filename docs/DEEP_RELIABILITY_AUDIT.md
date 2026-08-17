# Deep Reliability Audit

Date: 2026-08-16

Starting commit: `1efe59f`

Branch: `feature/deep-reliability-audit`

Scope: local/offline reliability, compatibility, reproducibility, executable
documentation, packaging/security correctness.

Out of scope:

- new detectors;
- new frameworks/backends;
- remote ingestion;
- hosted dashboard;
- distributed tracing;
- PyPI upload;
- release/tag creation;
- GPU or paid API validation.

## Findings by Severity

### P0

None found.

### P1

None found.

### P2

| Finding | Evidence | User Impact | Workaround | Minimum Fix |
| --- | --- | --- | --- | --- |
| High-frequency checkpointing writes full recoverable artifacts | 10,000-span checkpoint stress with `checkpoint_interval=250` took 279,668.8 ms; checkpoint P95 was 3,926.6 ms in the validation-marathon rerun. | Long-running local capture works, but frequent checkpoints on large runs add overhead. | Increase checkpoint interval or call `flush()` at meaningful task boundaries. | Consider a future incremental checkpoint format only with a schema/product decision. |

### INFO

- Public Python API changes since `v0.4.0` are additive.
- Artifact schema remains `1`.
- Historical compatibility corpus loads and reports under current main.
- Missing quality/serving/cache evidence remains unavailable or inconclusive in
  generated invariant tests.
- Fake secrets are covered by renderer redaction tests; raw artifacts remain
  local plaintext by design.
- The previous large single-run HTML hotspot was fixed during the validation
  marathon by indexing call scopes once per report. A profiled 1,000-call
  single-run HTML render dropped from roughly 8.1 seconds to roughly
  1.3 seconds on the audited host.

## Tests Added

`tests/test_deep_reliability_invariants.py` adds 9 behavioral tests covering:

- historical artifact corpus compatibility;
- deterministic generated comparison invariants;
- strict policy behavior for `FAILED` and `PARTIAL` artifacts;
- recommendation verification and quality requirements;
- local role headroom versus global routing verification;
- metamorphic task ordering and irrelevant display metadata;
- serialization/reload semantic equality;
- HTML escaping/redaction;
- conservative cross-run scaffold recommendation behavior.

## Reproducibility Tooling Added

`scripts/deep_reliability_local_baseline.py` records deterministic host-local
timings for artifact operations and checkpoint stress.

Measured results are recorded in `docs/LOCAL_PERFORMANCE_BASELINE.md`.

## Compatibility Corpus

Validated corpus in the added tests:

- `examples/artifacts/m3_raw_full`
- `examples/artifacts/m3_dedup_only`
- `examples/artifacts/m17_sglang_support_triage`
- `examples/benchmark_suites/synthetic_replay/baseline`
- `examples/benchmark_suites/synthetic_replay/candidate`
- `examples/dogfooding/openai_agents_support_triage_compact`
- `docs/data/m25_phase_b/strong_control/agentperf_artifact`
- `docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact`

## Determinism Audit

Repeated deterministic checks passed:

- M3 comparison repeated 20 times;
- M25 Phase B model-choice analysis repeated 20 times;
- multi-agent attribution repeated 20 times after excluding expected timing
  variance fields;
- checkpoint/recovery summary repeated 20 times;
- `agentperf demo` generated twice and produced stable verdict, task matching,
  and finding lifecycle.

Expected volatile fields such as durations, timestamps, and generated IDs were
not treated as deterministic output.

## Distribution Validation

- `python -m build`: PASS when isolated build dependency installation had
  network access.
- `python -m twine check dist/*`: PASS.
- Python 3.11 clean wheel first-user path: PASS.
- Python 3.12 clean wheel first-user path: PASS.
- Python 3.12 `agentperf[langgraph]` optional-extra smoke: PASS.

## Released-Version Impact

No bug was found that requires a v0.4.x emergency patch. The added tests mainly
guard post-v0.4 additive capabilities and preserved v0.4 artifact semantics.

## Remaining Reliability Gaps

No public-distribution blocker was identified. Remaining gaps are P2:

1. high-frequency full-artifact checkpoint cost;
2. broader external-user adoption evidence after PyPI publication.

## Result

No blocker remains before public distribution based on this audit. Final
release/distribution should still require normal human approval, PyPI account
setup, and post-publish clean-install verification.
