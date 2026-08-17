# Backward Compatibility

Date: 2026-08-16

Compatibility direction required for public releases:

```text
old AgentPerf artifact -> current AgentPerf loader/analyzer/reporter
```

The reverse direction is not required:

```text
current AgentPerf artifact -> old AgentPerf implementation
```

## Stable Release Baseline

Latest stable tag used for generated compatibility evidence:

```text
v0.4.0
```

Temporary validation environment:

```text
/private/tmp/agentperf-v040-venv
```

Source archive:

```text
/private/tmp/agentperf-v040-src
```

## Generated v0.4.0 Artifact

A representative framework-free artifact was generated with the installed
`agentperf==0.4.0` package from outside the current source checkout.

Generated artifact:

```text
/private/tmp/agentperf-v040-generated-artifact-real
```

Current main loaded it successfully:

```text
agentperf_version: 0.4.0
artifact_schema_version: 1
current load: PASS
current analyze: PASS
current doctor: PASS
current HTML report: PASS
```

## Historical Corpus

Current main also loads/analyzes/reports representative tracked artifacts:

- `examples/artifacts/m3_raw_full`
- `examples/artifacts/m3_dedup_only`
- `examples/artifacts/m17_sglang_support_triage`
- `examples/benchmark_suites/synthetic_replay/baseline`
- `examples/benchmark_suites/synthetic_replay/candidate`
- `examples/dogfooding/openai_agents_support_triage_compact`
- `docs/data/m25_phase_b/strong_control/agentperf_artifact`
- `docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact`

## Older Optional Metadata

Artifacts without newer optional metadata remain valid:

- no `RecommendationContract` persisted on old findings;
- no model-routing metadata;
- no multi-agent metadata;
- no checkpoint metadata.

Current AgentPerf reconstructs deterministic recommendations where supported
and treats unavailable optional evidence as unavailable, not as zero or pass.

## Result

No backward-compatibility blocker was found for artifact schema version `1`.

