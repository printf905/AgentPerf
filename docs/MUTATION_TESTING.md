# Mutation Testing

Date: 2026-08-16

Audited branch: `feature/validation-marathon`

This was a targeted semantic mutation pass, not whole-repository mutation
testing. The scope was intentionally limited to correctness-sensitive branches
where a surviving mutation would indicate a meaningful product risk.

## Scope

Targeted modules:

- `agentperf/comparison.py`
- `agentperf/regression.py`
- `agentperf/recommendations.py`
- `agentperf/model_choice.py`

Targeted semantics:

- quality evidence missing versus quality pass;
- `PARTIAL` artifact versus accepted replay;
- regression `FAIL` exit code;
- recommendation quality guard;
- local role headroom versus global mixed-routing verification.

## Method

A temporary overlay package was created under `/private/tmp/agentperf-mutants`.
For each mutation, only the selected `agentperf` module was modified in the
overlay, then focused repository tests were run with the overlay first on
`PYTHONPATH`.

No mutation tool or dependency was added to the project.

## Results

| Mutation | Result | Killing test evidence |
| --- | --- | --- |
| Remove missing-quality warning/guard in comparison | KILLED | `test_generated_comparison_invariants_do_not_turn_missing_evidence_into_success` |
| Disable `PARTIAL` artifact acceptance guard | KILLED | `test_failed_or_partial_artifacts_cannot_be_accepted_under_strict_policy` |
| Change regression `FAIL` exit code to success | KILLED | regression and validation-marathon exit-code tests |
| Ignore recommendation quality regression | KILLED | recommendation quality-regression tests |
| Treat Phase A candidate as globally verified | KILLED | model-choice local/global verification tests |

Scoped mutation result:

```text
5 targeted semantic mutations
5 killed
0 survived
```

Do not interpret this as a repository-wide mutation score.

## Survived Mutations

None in this targeted pass.

## Tests Added From Mutation Gaps

The validation-marathon branch added differential and exit-code tests before
the mutation pass. Those tests contributed to killing the regression exit-code
and comparison semantic mutations.

