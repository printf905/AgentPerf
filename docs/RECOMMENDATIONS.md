# Structured Recommendations

AgentPerf findings are deterministic detector outputs. M24 adds a small
structured recommendation contract beside the existing prose recommendation so
a developer can connect:

```text
diagnosis -> proposed class of change -> replay evidence -> verification
```

This is not automatic code optimization. AgentPerf does not rewrite prompts,
summarize tool output, patch agent source code, or call an LLM to generate
advice.

## Contract

A recommendation contract records:

- objective: what the recommendation is trying to improve;
- applicability: whether the finding is observation-only, conditional,
  investigatory, or actionable;
- interventions: classes of changes a developer may consider;
- expected metric movement: which metric should move and in what direction;
- risks: quality or correctness hazards introduced by the intervention;
- verification requirements: what replay must show before trusting the change;
- quality requirement: whether configured quality tolerance must pass.

Contracts are detector-authored and backend/framework-independent. Historical
findings without a persisted contract still load normally; current AgentPerf
can reconstruct known contracts deterministically from the finding id,
severity, and materiality evidence.

## Applicability

Applicability is not a second severity scale.

- `OBSERVATION_ONLY`: record the evidence; do not infer an optimization target.
- `CONDITIONAL`: consider the change only when required evidence is available
  and material enough.
- `INVESTIGATE`: inspect whether the repeated or expensive structure is safely
  reducible.
- `ACTIONABLE`: the finding identifies a concrete optimization hypothesis worth
  replaying, subject to quality constraints.

The existing AgentPerf principles still apply:

```text
dominant != material
repeated != removable
headroom != actionable
missing evidence != negative evidence
structural repetition != optimization target
performance improvement != acceptable if quality regresses
```

M20 human review labels such as `ACTIONABLE`, `VALID_NON_ACTIONABLE`, and
`EXPECTED_STRUCTURAL` remain validation annotations. They are not automatically
emitted detector classifications.

## Expected Metric Movement

Each machine-checkable expectation is intentionally simple:

```text
metric
direction
required/supporting
rationale
```

Common directions are:

- `DECREASE`
- `INCREASE`
- `NO_REGRESSION`
- `RESOLVE_OR_IMPROVE_FINDING`

AgentPerf avoids exact percentage requirements unless a detector has a
defensible reason. Most optimization hypotheses say a metric should move in a
direction, not that it must improve by a fixed amount.

Example for `TOOL_OUTPUT_BLOAT`:

```text
Expected:
component.tool_result.processed_tokens decreases

Required:
task quality remains within configured tolerance

Risk:
necessary evidence may be removed from downstream prompts
```

## Verification

Recommendation verification is separate from the replay verdict.

`RunComparison` still answers:

```text
Should the candidate be accepted overall?
```

Recommendation verification answers:

```text
Did the evidence move in the direction this recommendation predicted?
```

Possible states:

- `VERIFIED`: required recommendation evidence moved as expected and quality did
  not fail.
- `PARTIALLY_VERIFIED`: supporting evidence moved, but verification is not
  complete.
- `NOT_VERIFIED`: required evidence was available but did not move as expected.
- `QUALITY_REGRESSION`: performance evidence may have moved, but configured
  quality failed.
- `INCONCLUSIVE`: required evidence is unavailable or the recommendation has no
  machine-checkable metric expectation.

Quality failures dominate performance movement. A candidate that reduces
tool-result processing but violates the configured quality tolerance is not a
verified success.

## Examples

### TOOL_OUTPUT_BLOAT

Objective:

```text
Reduce cumulative downstream processing of tool-result content.
```

Possible interventions:

- carry forward only needed tool-result fields;
- avoid reinjecting identical tool results into multiple later prompts;
- compact or summarize tool results before reinjection when quality permits;
- store large results out-of-band and retrieve details on demand.

Verification:

- replay the same task set;
- require quality to remain within configured tolerance;
- confirm `component.tool_result.processed_tokens` decreases.

In the controlled M3 research-agent replay, tool-result processed tokens moved
from 112,287 to 78,566 and the predefined quality tolerance passed, so the
recommendation expectation is verified. This is scoped evidence for that
workload, not a universal performance claim.

### CONTEXT_DUPLICATION

Repeated context is not automatically removable. Low-materiality duplication is
observation-only. Higher-materiality duplication is an investigation prompt:
separate required context from accidental carry-forward, replay any change, and
require quality to remain acceptable.

### CROSS_RUN_SHARED_SCAFFOLD

Shared scaffold across independent tasks is observation-only. AgentPerf does
not recommend removing shared system or policy instructions merely because they
repeat across tasks.

### CACHEABILITY_HEADROOM

Cacheability headroom is conditional. A useful replay should compare compatible
backend cache evidence, such as cache hit ratio or uncached prompt tokens. If
that evidence is unavailable, verification is inconclusive rather than negative.

### PREFILL_PATH_DOMINANCE

Prefill-path dominance remains materiality-aware. `scheduled-to-first` evidence
is not pure GPU prefill-kernel latency. AgentPerf recommends prioritizing this
path only when the materiality gates and quality-preserving replay evidence
support it.

### MODEL_CHOICE_HEADROOM

Model-choice headroom is conditional. AgentPerf does not recommend "use the
smallest model." It records replay evidence for a specific role/model
substitution.

Expected evidence:

- configured task quality remains within tolerance;
- `model.relative_cost_proxy` decreases when relative model-capacity evidence is
  available;
- latency may decrease, but latency is supporting evidence rather than the sole
  definition of headroom.

A one-role counterfactual can produce local role headroom and a candidate
routing to verify. It does not validate a mixed routing policy. Full mixed
routing must be replayed end to end before the recommendation can be accepted.

## Outputs

Structured recommendation contracts appear in:

- `agentperf analyze` terminal finding output;
- single-run HTML profiler reports;
- persisted finding JSON for newly generated artifacts;
- comparison JSON as derived `recommendation_verifications`;
- visual comparison HTML reports.

The legacy prose `recommendation` and `validation_plan` fields remain present
for compatibility.

## Limitations

- Contracts currently cover production detector families that have stable
  recommendation semantics.
- Verification uses existing comparison metrics. It does not create new
  telemetry.
- Missing serving or quality evidence produces conservative verification states.
- AgentPerf does not judge semantic safety automatically; replay quality
  evidence remains required.
