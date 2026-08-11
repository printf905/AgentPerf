from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from agentperf.cli import main
from agentperf.comparison import compare_paths
from agentperf.regression import (
    evaluate_regression_policy,
    load_regression_policy,
    parse_regression_policy,
    regression_exit_code,
    regression_result_to_dict,
)
from agentperf.schema.comparison import (
    AcceptanceResult,
    CacheDelta,
    ComponentAccountingSummary,
    ContextGrowthDelta,
    FindingChange,
    LatencyDelta,
    MetricDelta,
    QualityDelta,
    RunComparison,
    TokenDelta,
)
from agentperf.schema.regression import RegressionPolicy


def test_policy_parsing_simple_yaml(tmp_path: Path) -> None:
    path = tmp_path / "agentperf-regression.yaml"
    path.write_text(
        """
schema_version: 1
quality:
  mean_score:
    max_drop: 0.05
performance:
  input_tokens:
    max_increase_percent: 15
findings:
  fail_on_new_material_findings: true
task_coverage:
  require_same_tasks: true
""",
        encoding="utf-8",
    )

    policy = load_regression_policy(path)

    assert policy.quality["mean_score"].max_drop == 0.05
    assert policy.performance["input_tokens"].max_increase_percent == 15
    assert policy.findings.fail_on_new_material_findings is True
    assert policy.task_coverage.require_same_tasks is True


def test_component_metric_policy_parsing_and_unknown_rejection() -> None:
    policy = parse_regression_policy(
        {
            "performance": {
                "provider.input_tokens": {"max_increase_percent": 10},
                "component.total.processed_tokens": {"max_increase_percent": 10},
                "component.system.processed_tokens": {"max_increase_percent": 5},
                "component.tool_result.processed_tokens": {"max_increase_percent": 15},
                "component_history_tokens": {"max_increase_percent": 20},
                "component.tool_schema.processed_tokens": {
                    "max_increase_percent": 20,
                    "min_attribution_coverage": 0.8,
                    "require_attribution_confidence": "APPROXIMATE",
                },
            }
        }
    )

    assert "component.system.processed_tokens" in policy.performance
    assert "component_history_tokens" in policy.performance
    assert (
        policy.performance["component.tool_schema.processed_tokens"]
        .min_attribution_coverage
        == 0.8
    )
    try:
        parse_regression_policy(
            {"performance": {"component.typo.processed_tokens": {"max_increase_percent": 1}}}
        )
    except ValueError as exc:
        assert "unsupported performance metric" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected unknown component metric to fail")


def test_invalid_policy_fails() -> None:
    try:
        parse_regression_policy({"schema_version": 999})
    except ValueError as exc:
        assert "unsupported regression policy" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected policy error")


def test_quality_pass_and_failure() -> None:
    policy = parse_regression_policy(
        {
            "quality": {
                "mean_score": {"max_drop": 0.05},
                "pass_rate": {"max_drop": 0.10},
            }
        }
    )

    passing = evaluate_regression_policy(_comparison(), policy)
    failing = evaluate_regression_policy(
        _comparison(mean_candidate=0.70, pass_candidate=0.60),
        policy,
    )

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
    assert regression_exit_code(failing) == 1


def test_quality_failure_wins_over_performance_improvement() -> None:
    policy = parse_regression_policy(
        {
            "quality": {"mean_score": {"max_drop": 0.05}},
            "performance": {"input_tokens": {"max_increase_percent": 15}},
        }
    )
    comparison = _comparison(
        mean_candidate=0.50,
        input_baseline=100_000,
        input_candidate=10_000,
        client_baseline=1000,
        client_candidate=300,
    )

    result = evaluate_regression_policy(comparison, policy)

    assert result.status == "FAIL"
    assert any(check.category == "QUALITY" and check.result == "FAIL" for check in result.checks)


def test_performance_pass_and_failure() -> None:
    policy = parse_regression_policy(
        {
            "quality": {"mean_score": {"max_drop": 0.05}},
            "performance": {
                "input_tokens": {"max_increase_percent": 15},
                "client_latency_p95": {"max_increase_percent": 20},
            },
        }
    )

    passing = evaluate_regression_policy(
        _comparison(input_candidate=90_000, client_candidate=900),
        policy,
    )
    failing = evaluate_regression_policy(
        _comparison(input_candidate=130_000, client_candidate=1300),
        policy,
    )

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
    assert {
        check.metric
        for check in failing.checks
        if check.category == "PERFORMANCE" and check.result == "FAIL"
    } == {"input_tokens", "client_latency_p95"}


def test_component_performance_pass_and_failure() -> None:
    policy = parse_regression_policy(
        {
            "performance": {
                "component.total.processed_tokens": {"max_increase_percent": 10},
                "component.system.processed_tokens": {"max_increase_percent": 5},
                "component.history.processed_tokens": {"max_increase_percent": 10},
                "component.tool_result.processed_tokens": {"max_increase_percent": 10},
            }
        }
    )
    passing = evaluate_regression_policy(
        _comparison(
            component_baseline={
                "system": 680,
                "history": 100,
                "tool_result": 266,
            },
            component_candidate={
                "system": 520,
                "history": 100,
                "tool_result": 266,
            },
        ),
        policy,
    )
    failing = evaluate_regression_policy(
        _comparison(
            component_baseline={
                "system": 680,
                "history": 100,
                "tool_result": 12_000,
            },
            component_candidate={
                "system": 900,
                "history": 130,
                "tool_result": 17_500,
            },
        ),
        policy,
    )

    assert passing.status == "PASS"
    assert failing.status == "FAIL"
    assert {
        check.metric
        for check in failing.checks
        if check.category == "PERFORMANCE" and check.result == "FAIL"
    } == {
        "component.total.processed_tokens",
        "component.system.processed_tokens",
        "component.history.processed_tokens",
        "component.tool_result.processed_tokens",
    }
    assert all(
        check.evidence.get("accounting_source") == "agentperf_component_attribution"
        for check in passing.checks
        if check.category == "PERFORMANCE"
    )


def test_missing_component_metadata_is_inconclusive() -> None:
    policy = parse_regression_policy(
        {"performance": {"component.system.processed_tokens": {"max_increase_percent": 5}}}
    )

    result = evaluate_regression_policy(_comparison(component_baseline={}), policy)

    assert result.status == "INCONCLUSIVE"
    assert any(
        check.metric == "component.system.processed_tokens" and check.result == "INCONCLUSIVE"
        for check in result.checks
    )


def test_component_attribution_coverage_and_confidence_requirements() -> None:
    policy = parse_regression_policy(
        {
            "performance": {
                "component.system.processed_tokens": {
                    "max_increase_percent": 5,
                    "min_attribution_coverage": 0.9,
                    "require_attribution_confidence": "STRUCTURED",
                }
            }
        }
    )

    passing = evaluate_regression_policy(
        _comparison(
            component_baseline={"system": 100, "other": 5},
            component_candidate={"system": 90, "other": 5},
            attribution_coverage=(0.95, 0.95),
            attribution_confidence=("STRUCTURED", "STRUCTURED"),
        ),
        policy,
    )
    low_coverage = evaluate_regression_policy(
        _comparison(
            component_baseline={"system": 100, "other": 50},
            component_candidate={"system": 90, "other": 50},
            attribution_coverage=(0.67, 0.67),
            attribution_confidence=("STRUCTURED", "STRUCTURED"),
        ),
        policy,
    )
    approximate = evaluate_regression_policy(
        _comparison(
            component_baseline={"system": 100, "other": 5},
            component_candidate={"system": 90, "other": 5},
            attribution_coverage=(0.95, 0.95),
            attribution_confidence=("APPROXIMATE", "APPROXIMATE"),
        ),
        policy,
    )

    assert passing.status == "PASS"
    assert low_coverage.status == "INCONCLUSIVE"
    assert approximate.status == "INCONCLUSIVE"


def test_finding_regression_respects_materiality() -> None:
    policy = parse_regression_policy(
        {"findings": {"fail_on_new_material_findings": True}},
    )
    low_observation = _comparison(
        findings=[
            FindingChange(
                finding_id="CROSS_RUN_SHARED_SCAFFOLD",
                lifecycle="NEW",
                baseline_severity=None,
                candidate_severity="LOW",
                candidate_materiality="OBSERVATION",
            )
        ]
    )
    material = _comparison(
        findings=[
            FindingChange(
                finding_id="TOOL_OUTPUT_BLOAT",
                lifecycle="NEW",
                baseline_severity=None,
                candidate_severity="HIGH",
                candidate_materiality="MATERIAL",
            )
        ]
    )

    assert evaluate_regression_policy(low_observation, policy).status == "PASS"
    assert evaluate_regression_policy(material, policy).status == "FAIL"


def test_task_coverage_and_partial_artifact_are_conservative() -> None:
    policy = parse_regression_policy(
        {"task_coverage": {"require_same_tasks": True, "minimum_task_coverage": 0.90}},
    )

    missing_tasks = evaluate_regression_policy(
        _comparison(matched=("task-1",), unmatched_baseline=("task-2", "task-3")),
        policy,
    )
    partial = evaluate_regression_policy(
        replace(
            _comparison(),
            metadata={
                "baseline_artifact_status": "COMPLETE",
                "candidate_artifact_status": "PARTIAL",
            },
        ),
        policy,
    )

    assert missing_tasks.status == "FAIL"
    assert partial.status == "INCONCLUSIVE"


def test_failed_artifact_fails_policy() -> None:
    policy = RegressionPolicy()
    result = evaluate_regression_policy(
        replace(
            _comparison(),
            metadata={
                "baseline_artifact_status": "COMPLETE",
                "candidate_artifact_status": "FAILED",
            },
        ),
        policy,
    )

    assert result.status == "FAIL"


def test_json_and_markdown_cli_output(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
quality:
  mean_score:
    max_drop: 0.05
task_coverage:
  require_same_tasks: true
""",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps(_trace("baseline", score=1.0)), encoding="utf-8")
    candidate.write_text(json.dumps(_trace("candidate", score=1.0)), encoding="utf-8")
    output = tmp_path / "summary.md"

    json_code = main(
        [
            "check",
            str(baseline),
            str(candidate),
            "--policy",
            str(policy),
            "--format",
            "json",
        ]
    )
    json_output = capsys.readouterr().out
    markdown_code = main(
        [
            "check",
            str(baseline),
            str(candidate),
            "--policy",
            str(policy),
            "--format",
            "markdown",
            "--output",
            str(output),
        ]
    )

    assert json_code == 0
    assert json.loads(json_output)["status"] == "PASS"
    assert markdown_code == 0
    assert "AgentPerf Regression Check" in output.read_text(encoding="utf-8")


def test_cli_exit_codes_for_fail_and_inconclusive(tmp_path: Path) -> None:
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        """
quality:
  mean_score:
    max_drop: 0.05
""",
        encoding="utf-8",
    )
    baseline = tmp_path / "baseline.json"
    candidate_fail = tmp_path / "candidate_fail.json"
    candidate_missing_quality = tmp_path / "candidate_missing_quality.json"
    baseline.write_text(json.dumps(_trace("baseline", score=1.0)), encoding="utf-8")
    candidate_fail.write_text(json.dumps(_trace("candidate", score=0.5)), encoding="utf-8")
    candidate_missing_quality.write_text(
        json.dumps(_trace("candidate", score=None)),
        encoding="utf-8",
    )

    assert main(["check", str(baseline), str(candidate_fail), "--policy", str(policy)]) == 1
    assert (
        main(["check", str(baseline), str(candidate_missing_quality), "--policy", str(policy)])
        == 3
    )
    assert main(["check", str(baseline), str(candidate_fail), "--policy", "missing.yaml"]) == 2


def test_real_m3_artifacts_pass_sample_policy() -> None:
    comparison = compare_paths(
        Path("examples/artifacts/m3_raw_full"),
        Path("examples/artifacts/m3_dedup_only"),
    )
    policy = load_regression_policy(Path("examples/policies/m3-context-regression.yaml"))
    result = evaluate_regression_policy(comparison, policy)

    assert result.status == "PASS"
    assert comparison.acceptance_result.verdict == "ACCEPT"


def test_real_m13_dogfood_component_policy_passes() -> None:
    comparison = compare_paths(
        Path("benchmarks/openai-agents-support-triage/baseline"),
        Path("examples/dogfooding/openai_agents_support_triage_compact"),
    )
    policy = load_regression_policy(Path("benchmarks/openai-agents-support-triage/policy.yaml"))
    result = evaluate_regression_policy(comparison, policy)

    assert result.status == "PASS"
    assert comparison.token_deltas.input_tokens.delta == 0
    assert comparison.token_deltas.component_accounting is not None
    assert comparison.token_deltas.component_accounting.total_processed_tokens.delta == -160
    assert comparison.token_deltas.component_processed_tokens["system"].delta == -160
    system_check = next(
        check for check in result.checks if check.metric == "component.system.processed_tokens"
    )
    assert system_check.result == "PASS"
    assert system_check.evidence["accounting_source"] == "agentperf_component_attribution"


def test_real_m3_tool_result_component_policy_passes() -> None:
    comparison = compare_paths(
        Path("examples/artifacts/m3_raw_full"),
        Path("examples/artifacts/m3_dedup_only"),
    )
    policy = parse_regression_policy(
        {
            "quality": {
                "mean_score": {"max_drop": 0.05},
                "pass_rate": {"max_drop": 0.10},
            },
            "performance": {
                "component.tool_result.processed_tokens": {"max_increase_percent": 15}
            },
        }
    )

    result = evaluate_regression_policy(comparison, policy)

    assert result.status == "PASS"
    assert comparison.token_deltas.component_processed_tokens["tool_result"].baseline == 112_287
    assert comparison.token_deltas.component_processed_tokens["tool_result"].candidate == 78_566


def test_quality_regression_still_overrides_component_improvement() -> None:
    policy = parse_regression_policy(
        {
            "quality": {"mean_score": {"max_drop": 0.05}},
            "performance": {
                "component.tool_result.processed_tokens": {"max_increase_percent": 15}
            },
        }
    )

    result = evaluate_regression_policy(
        _comparison(
            mean_candidate=0.50,
            component_baseline={"tool_result": 100_000},
            component_candidate={"tool_result": 10_000},
        ),
        policy,
    )

    assert result.status == "FAIL"
    assert any(check.category == "QUALITY" and check.result == "FAIL" for check in result.checks)


def test_regression_result_serializes_to_json_safe_dict() -> None:
    result = evaluate_regression_policy(
        _comparison(),
        parse_regression_policy({"quality": {"mean_score": {"max_drop": 0.05}}}),
    )
    data = regression_result_to_dict(result)

    assert data["status"] == "PASS"
    assert json.loads(json.dumps(data))["checks"][0]["result"] == "PASS"


def _comparison(
    *,
    mean_baseline: float = 0.933,
    mean_candidate: float = 0.908,
    pass_baseline: float = 0.80,
    pass_candidate: float = 0.70,
    input_baseline: int = 100_000,
    input_candidate: int = 90_000,
    client_baseline: float = 1000.0,
    client_candidate: float = 900.0,
    component_baseline: dict[str, int] | None = None,
    component_candidate: dict[str, int] | None = None,
    attribution_coverage: tuple[float, float] = (1.0, 1.0),
    attribution_confidence: tuple[str, str] = ("STRUCTURED", "STRUCTURED"),
    findings: list[FindingChange] | None = None,
    matched: tuple[str, ...] = ("task-1",),
    unmatched_baseline: tuple[str, ...] = (),
    unmatched_candidate: tuple[str, ...] = (),
) -> RunComparison:
    component_baseline = (
        {"tool_result": 50_000} if component_baseline is None else component_baseline
    )
    component_candidate = (
        {"tool_result": 40_000} if component_candidate is None else component_candidate
    )
    component_keys = sorted(set(component_baseline) | set(component_candidate))
    baseline_component_total = sum(component_baseline.values()) if component_baseline else None
    candidate_component_total = sum(component_candidate.values()) if component_candidate else None
    component_accounting = (
        None
        if baseline_component_total is None and candidate_component_total is None
        else ComponentAccountingSummary(
            total_processed_tokens=_delta(baseline_component_total, candidate_component_total),
            total_unique_tokens=_delta(baseline_component_total, candidate_component_total),
            other_processed_tokens=_delta(
                component_baseline.get("other") if component_baseline else None,
                component_candidate.get("other") if component_candidate else None,
            ),
            attribution_coverage_ratio=_delta(
                attribution_coverage[0],
                attribution_coverage[1],
            ),
            baseline_confidence=attribution_confidence[0],
            candidate_confidence=attribution_confidence[1],
        )
    )
    return RunComparison(
        baseline_id="baseline",
        candidate_id="candidate",
        matched_tasks=list(matched),
        unmatched_baseline_tasks=list(unmatched_baseline),
        unmatched_candidate_tasks=list(unmatched_candidate),
        token_deltas=TokenDelta(
            input_tokens=_delta(input_baseline, input_candidate),
            output_tokens=_delta(1000, 1000),
            component_processed_tokens={
                key: _delta(component_baseline.get(key), component_candidate.get(key))
                for key in component_keys
            },
            component_accounting=component_accounting,
        ),
        context_growth_delta=ContextGrowthDelta(
            final_step_input_tokens=_delta(10_000, 9000),
            max_step_input_tokens=_delta(10_000, 9000),
            growth_slope_tokens_per_step=_delta(1000, 900),
            baseline_steps=3,
            candidate_steps=3,
        ),
        latency_deltas=LatencyDelta(
            tool_latency_ms=_delta(100, 100),
            queue_p50_ms=_delta(None, None),
            queue_p95_ms=_delta(None, None),
            scheduled_to_first_p50_ms=_delta(None, None),
            scheduled_to_first_p95_ms=_delta(None, None),
            generation_p50_ms=_delta(None, None),
            generation_p95_ms=_delta(None, None),
            client_p50_ms=_delta(client_baseline, client_candidate),
            client_p95_ms=_delta(client_baseline, client_candidate),
        ),
        cache_deltas=CacheDelta(
            cached_tokens=_delta(None, None),
            cache_miss_tokens=_delta(None, None),
            cached_token_ratio=_delta(None, None),
        ),
        quality_deltas=QualityDelta(
            mean_score=_delta(mean_baseline, mean_candidate),
            pass_rate=_delta(pass_baseline, pass_candidate),
            baseline_tasks_with_quality=10,
            candidate_tasks_with_quality=10,
            mean_score_tolerance=0.05,
            pass_rate_tolerance=0.10,
            passed=True,
        ),
        finding_changes=findings or [],
        acceptance_result=AcceptanceResult(
            verdict="ACCEPT",
            reason="fixture",
            performance_improved=True,
            quality_passed=True,
            material_regression=False,
        ),
        metadata={"baseline_artifact_status": "COMPLETE", "candidate_artifact_status": "COMPLETE"},
    )


def _delta(baseline: float | int | None, candidate: float | int | None) -> MetricDelta:
    if baseline is None or candidate is None:
        return MetricDelta(baseline, candidate, None, None, measurement_quality="UNAVAILABLE")
    return MetricDelta(
        baseline=baseline,
        candidate=candidate,
        delta=candidate - baseline,
        percent_delta=(candidate - baseline) / baseline if baseline else None,
    )


def _trace(run_id: str, *, score: float | None) -> dict[str, object]:
    metadata: dict[str, object] = {"task_id": "task-1"}
    if score is not None:
        metadata["quality"] = {"score": score, "passed": score >= 0.9}
    return {
        "schema_version": "agentperf.trace.v1",
        "agent_run": {
            "agent_run_id": run_id,
            "metadata": metadata,
            "steps": [
                {
                    "agent_step_id": "step-1",
                    "llm_calls": [
                        {
                            "llm_call_id": "llm-1",
                            "model": "fixture",
                            "input_tokens": 100,
                            "output_tokens": 10,
                            "prompt": [{"name": "system", "text": "You are careful."}],
                        }
                    ],
                }
            ],
        },
    }
