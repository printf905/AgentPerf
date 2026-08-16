# AgentPerf Historical Compatibility Matrix

Audit date: 2026-08-16

Commit: `258e0e3a299d7d440aefed2632e5e7c23f74ef21`

Status values:

- PASS: deterministic local check passed in this hardening pass or in the full
  test suite.
- PARTIAL: usable with documented missing optional evidence.
- NOT_APPLICABLE: the workflow intentionally does not use that capability.
- BLOCKED: local check could not run or failed.

## Matrix

| Area | Status | Evidence |
|---|---|---|
| M3 compare | PASS | `agentperf compare examples/artifacts/m3_raw_full examples/artifacts/m3_dedup_only` returned ACCEPT. |
| M3 check | PASS | `agentperf check ... --policy examples/policies/m3-context-regression.yaml` returned PASS. |
| M3 suite | PASS | `agentperf suite check examples/benchmark_suites/m3_context examples/artifacts/m3_dedup_only` returned PASS. |
| M18 provenance/materiality | PASS | `agentperf analyze examples/traces/multi_problem_agent.json --show-provenance` preserved provenance, materiality gates, and recommendation contracts. |
| M19 BYOA | PASS | `examples/bring_your_own_agent/run.py` generated an artifact; `agentperf doctor` reported agent READY and cross-layer NOT_APPLICABLE. |
| M20 generalization | PASS | `scripts/m20_generalization_report.py` reported 3 workloads, 19 tasks, 3 reviewed findings, and expected review categories. |
| M21 scale smoke | PASS | `scripts/m21_scale_benchmark.py` ran 10/100/500/1,000-call local scale fixtures. |
| M22 demo | PASS | `agentperf demo` ran from `/tmp`, produced baseline/candidate artifacts, single-run HTML, comparison HTML, ACCEPT, and policy PASS. |
| M23 comparison HTML | PASS | `agentperf compare ... --format html` generated M3 comparison HTML. |
| M24 recommendation contracts | PASS | `tests/test_recommendations.py` passed in the targeted compatibility test run. |
| M25 model-capacity Phase B | PASS | `agentperf analyze-model-choice docs/data/m25_phase_b/model_choice_phase_b_comparison.json` reported routing verification VERIFIED. |
| OpenAI Agents SDK | PASS | `tests/test_openai_agents_integration.py` passed in the targeted compatibility test run. |
| LangGraph | PASS | `tests/test_langgraph_integration.py` passed in the targeted compatibility test run. |
| mini-SWE | PASS | M20 summary preserves mini-SWE structural finding validation; full test suite includes mini-SWE adapter tests. |
| vLLM fixture | PASS | `agentperf analyze-vllm-recording examples/recorded_telemetry/vllm_openai_response_fixture.json` succeeded with cross-layer READY. |
| SGLang fixture | PASS | `agentperf analyze-sglang-recording examples/recorded_telemetry/sglang_openai_response_fixture.json` succeeded with cross-layer READY for available telemetry. |
| Single-run HTML | PASS | Existing tests and demo generated standalone HTML without server/CDN. |
| Comparison HTML | PASS | Existing tests and M3 HTML smoke passed. |
| Doctor/readiness | PASS | BYOA and demo artifacts reported expected READY / NOT_APPLICABLE semantics. |
| PyPI publication | BLOCKED | Package is not published on PyPI; endpoint returned 404. Publication is intentionally out of scope for this branch. |
| GPU validation | NOT_APPLICABLE | No GPU was used. M25 Phase B artifacts are preserved; GPU experiment was not rerun. |
| Paid API validation | NOT_APPLICABLE | No paid API was used. |

## Notes

The vLLM/SGLang fixture checks use recorded local telemetry only. They do not
start live backends and do not require GPU resources.

The M25 Phase B check analyzes preserved sanitized artifacts and result data. It
does not rerun the real model experiment.
