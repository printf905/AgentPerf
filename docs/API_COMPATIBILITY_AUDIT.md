# AgentPerf API Compatibility Audit

Date: 2026-08-16

Baseline compared: `v0.4.0`

Current audited commit: `1efe59f`

Current package version: `0.5.0`

## Summary

No accidental public API removal was found in the audited core Python and CLI
surfaces. Post-`v0.4.0` changes are additive: new optional parameters, new
subcommands, new optional modules, and new metadata-backed capabilities.

Artifact schema remains `1`.

## Python API Surface

| API | Compatibility Result | Notes |
| --- | --- | --- |
| `ExperimentSession(...)` | Compatible, additive | Added optional `checkpoint_interval`; existing required/optional arguments retained. |
| `ExperimentSession.run_task(...)` | Compatible | Signature unchanged. |
| `ExperimentSession.record_task_result(...)` | Compatible | Signature unchanged. |
| `ExperimentSession.finalize(...)` | Compatible | Signature unchanged. |
| `ExperimentSession.flush(...)` | Added | New explicit checkpoint API. |
| `ExperimentSession.recover(...)` | Added | New read-only recovery API for finalized artifacts or latest checkpoint. |
| `trace_run(...)` | Compatible, additive | Added optional `agent_id`, `role`, `agent_role`, `parent_agent_id`, `branch_id`, `parent_branch_id`, and `branch_event`. Existing call shape retained. |
| `trace_llm(...)` | Compatible, additive | Added optional `role` alias while preserving `semantic_role`; conflicting aliases raise `ValueError`. |
| `trace_tool(...)` | Compatible | Signature unchanged. |
| `ExperimentArtifact.from_run(...)` | Compatible | Signature unchanged. |
| `ExperimentArtifact.from_analysis(...)` | Compatible | Signature unchanged. |
| `ExperimentArtifact.save(...)` | Compatible | Signature unchanged. |
| `load_artifact(...)` | Compatible, additive | Can now recover latest checkpoint when no finalized manifest exists. |
| `analyze_artifact(...)` | Compatible | Signature unchanged. |
| `inspect_artifact(...)` | Compatible | Signature unchanged. |
| `compare_paths(...)` | Compatible | Signature unchanged. |
| `compare_workloads(...)` | Compatible | Signature unchanged. |
| `comparison_to_dict(...)` | Compatible, additive output | Adds optional metadata for recommendations, model routing, and multi-agent evidence. Existing top-level fields remain. |
| `load_regression_policy(...)` | Compatible | Signature unchanged. |
| `evaluate_regression_policy(...)` | Compatible | Signature unchanged. |

## Added Public Modules

| Module | Purpose | Compatibility Notes |
| --- | --- | --- |
| `agentperf.recommendations` | Structured recommendation contracts and replay verification | Additive. Historical findings without contracts load normally and can be deterministically enriched. |
| `agentperf.model_choice` | Model-role routing and counterfactual/mixed-routing analysis | Additive. Uses optional role/model metadata. |
| `agentperf.multi_agent` | Agent/branch/handoff attribution and comparison summaries | Additive. Single-agent artifacts do not require multi-agent metadata. |
| `agentperf.integrations.langgraph` | Optional LangGraph wrapper | Additive and gated by the `langgraph` extra. |

## CLI Surface

`v0.4.0` commands:

```text
analyze
analyze-vllm-recording
analyze-sglang-recording
analyze-openai-agents-export
analyze-model-choice
compare
check
inspect
doctor
report
suite
```

Current commands:

```text
demo
analyze
analyze-vllm-recording
analyze-sglang-recording
analyze-openai-agents-export
analyze-model-choice
compare
check
inspect
doctor
report
suite
```

The only top-level command addition is `demo`. Existing command names remain.
The audited help text shows no removed top-level command.

## Semantic Compatibility

- Existing bounded `ExperimentSession` usage still finalizes to a normal
  `COMPLETE`, `PARTIAL`, or `FAILED` artifact.
- Users who do not enable checkpointing do not need to change code.
- Existing single-agent traces remain valid; multi-agent metadata is optional.
- Existing `compare --format json` semantics remain stable with optional
  additive fields.
- Missing optional evidence continues to be represented as unavailable or
  inconclusive rather than `0` or `PASS`.

## Regression Coverage Added

`tests/test_deep_reliability_invariants.py` adds compatibility and invariant
coverage for:

- historical artifact corpus loading/analyzing/reporting/comparing;
- randomized deterministic comparison cases;
- partial/failed artifacts under strict policy;
- recommendation verification quality requirements;
- local role headroom versus global model-routing verification;
- task order/display metadata metamorphic behavior;
- trace serialization/reload comparison equivalence;
- HTML escaping/redaction of malicious labels and fake secrets;
- conservative `CROSS_RUN_SHARED_SCAFFOLD` recommendation behavior.

## Result

No breaking public API change was identified. New capabilities are additive and
backward-compatible with the audited `v0.4.0` public surface.
