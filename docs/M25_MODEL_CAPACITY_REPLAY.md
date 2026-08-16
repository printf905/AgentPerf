# M25 Model-Capacity Replay and Routing Verification

## Goal

AgentPerf already distinguishes cacheability waste and context/harness waste.
M25 adds the missing model-capacity workflow:

```text
current routing
-> one-role counterfactual replay
-> local role-sensitivity evidence
-> candidate routing
-> full mixed-routing replay
-> quality-aware verification
```

The product claim is deliberately narrow: AgentPerf can evaluate tested
role/model substitutions through replay evidence. It does not choose the
smallest model automatically, and it does not infer untested routing behavior.

## Historical M4 Audit

Preserved M4 material lives in:

- `docs/MODEL_CHOICE_PROFILING.md`
- `docs/MODEL_CHOICE_RESULTS.md`
- `scripts/run_model_choice_phase_a.py`
- `scripts/run_model_choice_phase_b.py`
- `agentperf/model_choice.py`

Phase A completed on a real RTX 3090 with sequential vLLM model loading. The
tested roles were workload-defined:

- `planner`
- `evidence_reviewer`
- `final_synthesizer`

The model ladder was same-family Qwen3:

- `Qwen/Qwen3-0.6B`
- `Qwen/Qwen3-1.7B`
- `Qwen/Qwen3-4B`

Phase A changed one role at a time while holding the other roles fixed or
regenerating downstream strong continuations. It produced local
role-sensitivity evidence and `MODEL_CHOICE_HEADROOM` findings.

The key historical limitation remains important: Phase A did not run a full
mixed-routing replay. M25 migrates the preserved Phase A table into
`docs/data/m25_historical_m4_phase_a.json`, but that file is explicitly
historical local-headroom evidence, not a new mixed-routing result.

## Role and Model Identity

AgentPerf uses existing normalized trace fields:

- `LLMCall.semantic_role`
- `LLMCall.model`
- `LLMCall.backend`
- `LLMCall.llm_call_id`

The public instrumentation API now accepts `role=` as a clear alias for
`semantic_role=`:

```python
with trace_llm(role="planner", model="Qwen/Qwen3-4B") as call:
    ...
```

If both `role` and `semantic_role` are supplied, they must match. This avoids
silently recording contradictory model-routing metadata.

## Routing Representation

M25 adds small routing data structures in `agentperf.model_choice`:

- `RoleExecution`: role, model, backend, LLM call IDs, calls, tokens.
- `ModelRouting`: a collection of role executions from a trace.
- `CandidateRouting`: a candidate assembled from local role counterfactuals.
- `RoutingVerification`: full mixed-routing replay status.

Experiment artifacts persist an optional `summary.model_routing` section when
role/model metadata exists. Historical artifacts without it still load.

## Counterfactual Semantics

One-role counterfactuals are classified as:

- `SAFE_WITHIN_TOLERANCE`
- `QUALITY_REGRESSION`
- `NO_MATERIAL_BENEFIT`
- `INCONCLUSIVE`

`SAFE_WITHIN_TOLERANCE` means the tested role substitution preserved configured
quality and improved either relative model-capacity cost proxy or available
latency evidence.

It does not mean the substitution should be deployed.

## Candidate Routing

AgentPerf may assemble a candidate routing from quality-preserving one-role
substitutions. The candidate status is:

```text
CANDIDATE_TO_VERIFY
```

When multiple substitutions exist for the same role, AgentPerf prefers quality
margin before marginally lower cost. This reflects the M4 finding that model
sensitivity can be non-monotonic.

For the migrated historical M4 Phase A table, the candidate routing is:

```text
planner             strong -> medium
evidence_reviewer   strong -> small
final_synthesizer   strong -> small
```

This remains a candidate until a full mixed-routing replay is run.

## Full Routing Verification

Mixed routing is evaluated separately from local role headroom:

- `VERIFIED`: full replay preserved quality and improved cost proxy or latency.
- `REJECTED_QUALITY_REGRESSION`: full replay violated quality tolerance.
- `NO_MATERIAL_BENEFIT`: quality passed but efficiency did not improve.
- `CANDIDATE_TO_VERIFY`: no mixed replay exists yet.
- `INCONCLUSIVE`: selected mixed config is missing or evidence is incomplete.

This closes the conceptual M4 gap in product semantics: local role headroom and
global routing verification are not conflated.

## Cost Semantics

M25 keeps historical M4 cost semantics:

```text
relative token-weighted model-capacity proxy
```

This is not commercial pricing. AgentPerf does not hardcode provider prices or
query a pricing service. Future users can provide richer pricing evidence, but
M25 only labels the available value as a relative cost proxy.

## Latency Semantics

Latency is compared only when recorded. Client P95 deltas are treated as
observed replay evidence, not as proof that model size caused all end-to-end
latency movement. If hardware/backend changes, existing comparison warnings
remain the authoritative environment signal.

## Recommendation Contract

`MODEL_CHOICE_HEADROOM` now has an M24 recommendation contract:

- objective: reduce unnecessary model capacity for a specific role;
- intervention: route a tested role to a replayed smaller/cheaper model;
- expected metric: `model.relative_cost_proxy` decreases;
- supporting metric: `latency.client_p95_ms` may decrease;
- risk: role capability or quality regression;
- verification: run full mixed-routing replay and require quality tolerance.

The contract is `CONDITIONAL` because local role counterfactuals are not enough
to accept a complete routing policy.

## Reporting

`agentperf analyze-model-choice` now shows:

- role sensitivity status;
- candidate routing;
- full routing verification status;
- recommendation verification when a mixed replay exists.

M23 comparison HTML now includes an optional **Model Routing** section when
baseline/candidate artifacts include role/model metadata.

## Validation

M25 validation uses:

- the existing historical M4 Phase A evidence document;
- a compact migrated Phase A JSON file for regression tests;
- the existing deterministic/mock Phase B runner;
- normal AgentPerf comparison, HTML, recommendation, and artifact paths.

No new GPU run was performed during this implementation. The product capability
for mixed-routing verification is implemented and tested, but new real Phase B
closure remains pending until a bounded real model run is executed.

## Limitations

- Historical Phase A evidence is small and workload-specific.
- The migrated M4 data is derived from preserved documentation, not a newly
  generated artifact bundle.
- Relative model-capacity cost is not dollar cost.
- No universal model-size monotonicity is assumed.
- No automatic routing, prompt rewriting, or optimizer agent is implemented.
- A new real mixed-routing replay is still required before claiming the M4
  real-model model-capacity axis is empirically closed.
