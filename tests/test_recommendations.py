from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentperf.analyzer import analyze_run
from agentperf.comparison import compare_paths, compare_workloads
from agentperf.recommendations import (
    recommendation_contract_for_finding,
    recommendation_contract_for_id,
    recommendation_verifications,
    verify_recommendation,
)
from agentperf.reporters.comparison_html import (
    build_comparison_html_input,
    render_comparison_html,
)
from agentperf.reporters.html import load_html_report_input, render_html_report
from agentperf.reporters.terminal import render_report
from agentperf.schema.findings import Finding, FindingProvenance
from agentperf.schema.trace import AgentRun, parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def test_tool_output_bloat_contract_is_actionable_and_quality_guarded() -> None:
    report = analyze_run(_run(_trace("baseline", task_id="task", score=1.0)))
    finding = next(finding for finding in report.findings if finding.id == "TOOL_OUTPUT_BLOAT")

    contract = recommendation_contract_for_finding(finding)

    assert contract is not None
    assert contract.applicability == "ACTIONABLE"
    assert contract.quality_requirement == "within_configured_tolerance"
    assert any(
        change.metric == "component.tool_result.processed_tokens"
        and change.direction == "DECREASE"
        and change.required
        for change in contract.expected_metric_changes
    )
    assert any("evidence" in risk.lower() for risk in contract.risks)


def test_context_duplication_low_contract_is_observation_only() -> None:
    finding = Finding(
        id="CONTEXT_DUPLICATION",
        severity="LOW",
        title="Repeated context",
        summary="Repeated context exists.",
        evidence={"materiality": "OBSERVATION"},
        affected_spans=[],
        recommendation="Inspect only.",
        confidence="MEDIUM",
        provenance=FindingProvenance(),
    )

    contract = recommendation_contract_for_finding(finding)

    assert contract is not None
    assert contract.applicability == "OBSERVATION_ONLY"
    assert contract.expected_metric_changes == []
    assert "required" in " ".join(contract.risks).lower()


def test_cross_run_shared_scaffold_has_no_unsafe_removal_intervention() -> None:
    contract = recommendation_contract_for_id("CROSS_RUN_SHARED_SCAFFOLD")

    assert contract is not None
    assert contract.applicability == "OBSERVATION_ONLY"
    assert contract.interventions == []
    assert any("Do not optimize" in item for item in contract.verification_requirements)


def test_cacheability_and_prefill_contracts_are_conditional_when_not_material() -> None:
    cache = recommendation_contract_for_id("CACHEABILITY_HEADROOM")
    prefill = recommendation_contract_for_id("PREFILL_PATH_DOMINANCE")

    assert cache is not None
    assert prefill is not None
    assert cache.applicability == "CONDITIONAL"
    assert prefill.applicability == "CONDITIONAL"
    assert any(
        change.metric == "cache.cached_token_ratio"
        for change in cache.expected_metric_changes
    )
    assert any("not pure GPU" in risk or "Dominant" in risk for risk in prefill.risks)
    assert any(
        "not pure GPU prefill-kernel latency" in change.rationale
        for change in prefill.expected_metric_changes
    )


def test_m3_tool_output_recommendation_verifies_against_replay() -> None:
    comparison = compare_paths(
        ROOT / "examples/artifacts/m3_raw_full",
        ROOT / "examples/artifacts/m3_dedup_only",
    )

    verification = next(
        item
        for item in recommendation_verifications(comparison)
        if item.finding_id == "TOOL_OUTPUT_BLOAT"
    )

    assert comparison.acceptance_result.verdict == "ACCEPT"
    assert verification.status == "VERIFIED"
    assert verification.quality_status == "PASSED"
    tool_check = next(
        check
        for check in verification.metric_checks
        if check.metric == "component.tool_result.processed_tokens"
    )
    assert tool_check.status == "PASSED"
    assert tool_check.delta is not None and tool_check.delta < 0


def test_recommendation_quality_regression_overrides_metric_improvement() -> None:
    baseline = _run(_trace("baseline", task_id="task", score=1.0, passed=True))
    candidate = _run(
        _trace(
            "candidate",
            task_id="task",
            score=0.2,
            passed=False,
            tool_reinjections=0,
        )
    )
    comparison = compare_workloads(
        [baseline],
        [candidate],
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )
    change = next(
        change
        for change in comparison.finding_changes
        if change.finding_id == "TOOL_OUTPUT_BLOAT"
    )
    contract = recommendation_contract_for_id("TOOL_OUTPUT_BLOAT")
    assert contract is not None

    verification = verify_recommendation(
        comparison,
        contract,
        finding_id="TOOL_OUTPUT_BLOAT",
        finding_change=change,
    )

    assert comparison.acceptance_result.verdict == "REJECT_QUALITY_REGRESSION"
    assert verification.status == "QUALITY_REGRESSION"
    assert any(check.status == "PASSED" for check in verification.metric_checks)


def test_expected_metric_unchanged_is_not_verified() -> None:
    run = _run(_trace("baseline", task_id="task", score=1.0, passed=True))
    comparison = compare_workloads([run], [run], mean_score_tolerance=0.0)
    change = next(
        change
        for change in comparison.finding_changes
        if change.finding_id == "TOOL_OUTPUT_BLOAT"
    )
    contract = recommendation_contract_for_id("TOOL_OUTPUT_BLOAT")
    assert contract is not None

    verification = verify_recommendation(
        comparison,
        contract,
        finding_id="TOOL_OUTPUT_BLOAT",
        finding_change=change,
    )

    assert verification.status == "NOT_VERIFIED"
    assert any(
        check.metric == "component.tool_result.processed_tokens"
        for check in verification.metric_checks
    )


def test_missing_comparison_metric_is_inconclusive() -> None:
    run = _run(
        _trace(
            "no-serving",
            task_id="task",
            score=1.0,
            passed=True,
            tool_reinjections=0,
            serving=False,
        )
    )
    comparison = compare_workloads([run], [run])
    contract = recommendation_contract_for_id("MATERIAL_PREFIX_CACHE_OPPORTUNITY")
    assert contract is not None

    verification = verify_recommendation(
        comparison,
        contract,
        finding_id="MATERIAL_PREFIX_CACHE_OPPORTUNITY",
    )

    assert verification.status == "INCONCLUSIVE"
    assert any(check.status == "UNAVAILABLE" for check in verification.metric_checks)


def test_terminal_and_single_run_html_render_structured_contract(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(_trace("baseline", task_id="task", score=1.0)),
        encoding="utf-8",
    )
    report = analyze_run(_run(_trace("baseline", task_id="task", score=1.0)))

    terminal = render_report(report)
    html = render_html_report(load_html_report_input(trace_path))

    assert "Recommendation contract:" in terminal
    assert "component.tool_result.processed_tokens" in terminal
    assert "Recommendation contract" in html
    assert "Expected metric movement" in html


def test_comparison_html_renders_recommendation_verification() -> None:
    baseline = ROOT / "examples/artifacts/m3_raw_full"
    candidate = ROOT / "examples/artifacts/m3_dedup_only"
    comparison = compare_paths(baseline, candidate)

    html = render_comparison_html(build_comparison_html_input(comparison, baseline, candidate))

    assert "Recommendation verification" in html
    assert "component.tool_result.processed_tokens" in html
    assert "VERIFIED" in html


def _run(data: dict[str, object]) -> AgentRun:
    return parse_agentperf_trace(data)


def _trace(
    run_id: str,
    *,
    task_id: str | None = None,
    score: float | None = None,
    passed: bool | None = None,
    tool_reinjections: int = 5,
    serving: bool = True,
) -> dict[str, object]:
    tool_text = " ".join(f"evidence{i}" for i in range(650))
    metadata: dict[str, object] = {"framework": "recommendation-fixture"}
    if task_id is not None:
        metadata["task_id"] = task_id
    if score is not None:
        metadata["quality"] = {"score": score, "passed": bool(passed)}
    steps: list[dict[str, Any]] = []
    llm_call_count = max(1, tool_reinjections)
    for index in range(llm_call_count):
        prompt: list[dict[str, Any]] = [{"name": "system", "text": "You are careful."}]
        if index < tool_reinjections:
            prompt.append(
                {
                    "name": "tool_result",
                    "text": tool_text,
                    "metadata": {"source_tool_call_ids": ["search-1"]},
                }
            )
        step: dict[str, Any] = {
            "agent_step_id": f"step-{index + 1}",
            "llm_calls": [
                {
                    "llm_call_id": f"llm-{index + 1}",
                    "llm_request_id": f"req-{index + 1}",
                    "model": "fixture-model",
                    "prompt": prompt,
                    "input_tokens": 700 if index < tool_reinjections else 50,
                    "output_tokens": 10,
                    "tokenization_mode": "APPROXIMATE",
                    "metadata": {"latency_ms": 1000.0},
                }
            ],
        }
        if index == 0:
            step["tool_calls"] = [
                {
                    "tool_call_id": "search-1",
                    "name": "search",
                    "latency_ms": 25,
                    "output": tool_text,
                }
            ]
        steps.append(step)
    serving_requests = []
    if serving:
        serving_requests = [
            {
                "serving_request_id": f"srv-{index + 1}",
                "llm_request_id": f"req-{index + 1}",
                "queue_latency_ms": 5,
                "prefill_path_latency_ms": 220.0,
                "decode_latency_ms": 50,
                "ttft_ms": 220.0,
                "input_tokens": 700,
                "output_tokens": 10,
                "prefix_cache_hit_tokens": 0,
                "prefix_cache_miss_tokens": 800,
            }
            for index in range(llm_call_count)
        ]
    return {
        "schema_version": "agentperf.trace.v1",
        "agent_run": {
            "agent_run_id": run_id,
            "metadata": metadata,
            "steps": steps,
        },
        "serving_requests": serving_requests,
    }
