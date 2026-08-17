from __future__ import annotations

import json
import random
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.comparison import compare_paths, compare_workloads, comparison_to_dict
from agentperf.model_choice import analyze_model_choice_data
from agentperf.recommendations import (
    recommendation_contract_for_id,
    recommendation_verifications,
    verify_recommendation,
)
from agentperf.regression import evaluate_regression_policy, parse_regression_policy
from agentperf.reporters.comparison_html import (
    build_comparison_html_input,
    render_comparison_html,
)
from agentperf.reporters.html import load_html_report_input, render_html_report
from agentperf.schema.artifacts import ArtifactStatus, QualityMetric, TaskResult
from agentperf.schema.trace import AgentRun, parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def test_historical_artifact_corpus_loads_analyzes_reports_and_compares() -> None:
    corpus = [
        ROOT / "examples/artifacts/m3_raw_full",
        ROOT / "examples/artifacts/m3_dedup_only",
        ROOT / "examples/artifacts/m17_sglang_support_triage",
        ROOT / "examples/benchmark_suites/synthetic_replay/baseline",
        ROOT / "examples/benchmark_suites/synthetic_replay/candidate",
        ROOT / "examples/dogfooding/openai_agents_support_triage_compact",
        ROOT / "docs/data/m25_phase_b/strong_control/agentperf_artifact",
        ROOT / "docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact",
    ]

    for path in corpus:
        artifact = load_artifact(path)
        reports = [analyze_run(run) for run in artifact.runs_for_comparison()]
        html = render_html_report(load_html_report_input(path))

        assert artifact.manifest.artifact_schema_version == 1
        assert reports
        assert "AgentPerf" in html

    comparisons = [
        (
            ROOT / "examples/artifacts/m3_raw_full",
            ROOT / "examples/artifacts/m3_dedup_only",
            "ACCEPT",
        ),
        (
            ROOT / "examples/benchmark_suites/synthetic_replay/baseline",
            ROOT / "examples/benchmark_suites/synthetic_replay/candidate",
            "ACCEPT",
        ),
        (
            ROOT / "docs/data/m25_phase_b/strong_control/agentperf_artifact",
            ROOT / "docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact",
            "ACCEPT",
        ),
    ]
    for baseline, candidate, verdict in comparisons:
        comparison = compare_paths(baseline, candidate)
        html = render_comparison_html(
            build_comparison_html_input(comparison, baseline, candidate)
        )

        assert comparison.acceptance_result.verdict == verdict
        assert comparison.matched_tasks
        assert "Replay Verification" in html


def test_generated_comparison_invariants_do_not_turn_missing_evidence_into_success() -> None:
    rng = random.Random(2605)

    for index in range(150):
        task_count = rng.randint(1, 5)
        baseline_tasks = [f"task-{item}" for item in range(task_count)]
        candidate_tasks = list(baseline_tasks)
        if rng.random() < 0.25 and len(candidate_tasks) > 1:
            candidate_tasks.pop(rng.randrange(len(candidate_tasks)))
        if rng.random() < 0.25:
            candidate_tasks.append(f"candidate-only-{index}")

        quality_mode = rng.choice(["pass", "regress", "missing"])
        if quality_mode == "pass":
            base_score: float | None = 0.9
            cand_score: float | None = rng.choice([0.9, 0.88, 0.86])
            base_passed: bool | None = True
            assert cand_score is not None
            cand_passed: bool | None = cand_score >= 0.86
        elif quality_mode == "regress":
            base_score = 0.9
            cand_score = 0.5
            base_passed = True
            cand_passed = False
        else:
            base_score = cand_score = None
            base_passed = cand_passed = None

        baseline = [
            _run(
                f"base-{task}",
                task_id=task,
                score=base_score,
                passed=base_passed,
                serving=rng.choice([True, False]),
                cached_tokens=rng.choice([0, 10, None]),
                cache_miss_tokens=rng.choice([90, None]),
                tool_reinjections=rng.randint(1, 4),
            )
            for task in baseline_tasks
        ]
        candidate = [
            _run(
                f"cand-{task}",
                task_id=task,
                score=cand_score,
                passed=cand_passed,
                serving=rng.choice([True, False]),
                cached_tokens=rng.choice([0, 60, None]),
                cache_miss_tokens=rng.choice([40, None]),
                tool_reinjections=rng.randint(0, 4),
            )
            for task in candidate_tasks
        ]

        comparison = compare_workloads(
            baseline,
            candidate,
            mean_score_tolerance=0.05,
            pass_rate_tolerance=0.10,
        )
        data = comparison_to_dict(comparison)

        assert len(comparison.matched_tasks) <= len(baseline_tasks)
        assert len(comparison.matched_tasks) <= len(candidate_tasks)
        assert set(comparison.matched_tasks).isdisjoint(comparison.unmatched_baseline_tasks)
        assert set(comparison.matched_tasks).isdisjoint(comparison.unmatched_candidate_tasks)
        assert data["matched_tasks"] == comparison.matched_tasks

        if comparison.quality_deltas.passed is False:
            assert comparison.acceptance_result.verdict != "ACCEPT"
        if comparison.quality_deltas.passed is None:
            assert comparison.acceptance_result.verdict != "ACCEPT"
            assert "PERFORMANCE_IMPROVEMENT_UNVERIFIED_FOR_QUALITY" in comparison.warnings
        if comparison.unmatched_baseline_tasks or comparison.unmatched_candidate_tasks:
            assert comparison.acceptance_result.verdict != "ACCEPT"

        if all(not run.serving_requests for run in baseline + candidate):
            assert comparison.latency_deltas.scheduled_to_first_p95_ms.baseline is None
            assert comparison.latency_deltas.scheduled_to_first_p95_ms.candidate is None
            assert comparison.cache_deltas.cached_token_ratio.baseline is None
            assert comparison.cache_deltas.cached_token_ratio.candidate is None


def test_failed_or_partial_artifacts_cannot_be_accepted_under_strict_policy(
    tmp_path: Path,
) -> None:
    complete = _artifact(
        tmp_path / "complete",
        status="COMPLETE",
        tasks=["task-1", "task-2"],
        quality_score=1.0,
        pass_rate=1.0,
        tool_reinjections=4,
    )
    failed = _artifact(
        tmp_path / "failed",
        status="FAILED",
        tasks=["task-1", "task-2"],
        quality_score=1.0,
        pass_rate=1.0,
        tool_reinjections=0,
    )
    partial = _artifact(
        tmp_path / "partial",
        status="PARTIAL",
        tasks=["task-1"],
        quality_score=1.0,
        pass_rate=1.0,
        tool_reinjections=0,
    )
    policy = parse_regression_policy(
        {
            "quality": {"mean_score": {"max_drop": 0.05}},
            "task_coverage": {"require_same_tasks": True},
        }
    )

    for candidate in (failed, partial):
        comparison = compare_paths(complete, candidate)
        result = evaluate_regression_policy(comparison, policy)

        assert comparison.acceptance_result.verdict == "INCONCLUSIVE"
        assert result.status != "PASS"


def test_recommendation_verification_requires_metric_and_quality_evidence() -> None:
    contract = recommendation_contract_for_id("TOOL_OUTPUT_BLOAT")
    assert contract is not None

    verified = compare_workloads(
        [_run("baseline", task_id="task", score=1.0, passed=True, tool_reinjections=4)],
        [_run("candidate", task_id="task", score=1.0, passed=True, tool_reinjections=0)],
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )
    quality_regression = compare_workloads(
        [_run("baseline", task_id="task", score=1.0, passed=True, tool_reinjections=4)],
        [_run("candidate", task_id="task", score=0.5, passed=False, tool_reinjections=0)],
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )
    unchanged = compare_workloads(
        [_run("baseline", task_id="task", score=1.0, passed=True, tool_reinjections=4)],
        [_run("candidate", task_id="task", score=1.0, passed=True, tool_reinjections=4)],
        mean_score_tolerance=0.05,
        pass_rate_tolerance=0.10,
    )

    assert recommendation_verifications(verified)[0].status == "PARTIALLY_VERIFIED"
    assert recommendation_verifications(quality_regression)[0].status == "QUALITY_REGRESSION"
    assert (
        verify_recommendation(
            unchanged,
            contract,
            finding_id="TOOL_OUTPUT_BLOAT",
            finding_change=next(
                change
                for change in unchanged.finding_changes
                if change.finding_id == "TOOL_OUTPUT_BLOAT"
            ),
        ).status
        == "NOT_VERIFIED"
    )


def test_model_choice_global_verification_requires_selected_mixed_replay() -> None:
    phase_a_only = json.loads(
        (ROOT / "docs/data/m25_historical_m4_phase_a.json").read_text(encoding="utf-8")
    )
    phase_b = json.loads(
        (ROOT / "docs/data/m25_phase_b/model_choice_phase_b_comparison.json").read_text(
            encoding="utf-8"
        )
    )

    local = analyze_model_choice_data(phase_a_only)
    global_verified = analyze_model_choice_data(phase_b)

    assert local.routing_verification.status == "CANDIDATE_TO_VERIFY"
    assert local.routing_verification.recommendation_verification is None
    assert all(
        finding.evidence.get("headroom_scope") != "GLOBAL_ROUTING_VERIFIED"
        for finding in local.findings
    )
    assert global_verified.routing_verification.status == "VERIFIED"
    assert global_verified.routing_verification.recommendation_verification is not None
    assert (
        global_verified.routing_verification.recommendation_verification.status
        == "VERIFIED"
    )


def test_metamorphic_task_order_and_display_metadata_do_not_change_semantics() -> None:
    ordered = [
        _run("baseline-a", task_id="task-a", score=1.0, passed=True),
        _run("baseline-b", task_id="task-b", score=1.0, passed=True),
    ]
    reordered = list(reversed(ordered))
    candidate = [
        _run("candidate-b", task_id="task-b", score=1.0, passed=True, tool_reinjections=0),
        _run("candidate-a", task_id="task-a", score=1.0, passed=True, tool_reinjections=0),
    ]

    first = compare_workloads(ordered, candidate, mean_score_tolerance=0.05)
    second = compare_workloads(reordered, candidate, mean_score_tolerance=0.05)

    assert first.acceptance_result.verdict == second.acceptance_result.verdict
    assert first.matched_tasks == second.matched_tasks == ["task-a", "task-b"]
    assert first.token_deltas.input_tokens == second.token_deltas.input_tokens

    baseline_titled = [
        _replace_run_metadata(run, {"display_title": "<b>demo</b>"}) for run in ordered
    ]
    third = compare_workloads(baseline_titled, candidate, mean_score_tolerance=0.05)

    assert third.acceptance_result.verdict == first.acceptance_result.verdict
    assert [
        (change.finding_id, change.lifecycle) for change in third.finding_changes
    ] == [(change.finding_id, change.lifecycle) for change in first.finding_changes]


def test_serialization_roundtrip_preserves_semantic_comparison_result(tmp_path: Path) -> None:
    baseline = _run("baseline", task_id="task", score=1.0, passed=True)
    candidate = _run("candidate", task_id="task", score=1.0, passed=True, tool_reinjections=0)
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(_trace_payload(baseline)), encoding="utf-8")
    candidate_path.write_text(json.dumps(_trace_payload(candidate)), encoding="utf-8")

    direct = compare_workloads([baseline], [candidate], mean_score_tolerance=0.05)
    reloaded = compare_paths(baseline_path, candidate_path, mean_score_tolerance=0.05)

    assert comparison_to_dict(reloaded)["acceptance_result"] == comparison_to_dict(direct)[
        "acceptance_result"
    ]
    assert comparison_to_dict(reloaded)["finding_changes"] == comparison_to_dict(direct)[
        "finding_changes"
    ]


def test_html_redaction_and_escaping_cover_script_breakouts_and_secret_labels(
    tmp_path: Path,
) -> None:
    run = _run(
        "secret",
        task_id="task",
        score=1.0,
        passed=True,
        metadata={
            "agent_id": "</script><script>alert(1)</script>",
            "branch_id": '<img src=x onerror=alert(1)>',
            "Authorization": "Bearer fake-secret",
            "OPENAI_API_KEY": "sk-test-secret",
            "path": "/user/private/path",
        },
    )
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(_trace_payload(run)), encoding="utf-8")

    single = render_html_report(load_html_report_input(path))
    comparison = compare_workloads([run], [run], mean_score_tolerance=0.05)
    before_after = render_comparison_html(build_comparison_html_input(comparison, path, path))

    for html in (single, before_after):
        assert "sk-test-secret" not in html
        assert "Bearer fake-secret" not in html
        assert "</script><script>alert(1)</script>" not in html
        assert '<img src=x onerror=alert(1)>' not in html


def test_cross_run_shared_scaffold_contract_stays_observation_only() -> None:
    contract = recommendation_contract_for_id(
        "CROSS_RUN_SHARED_SCAFFOLD",
        severity="LOW",
        materiality="OBSERVATION",
    )

    assert contract is not None
    assert contract.applicability == "OBSERVATION_ONLY"
    assert contract.interventions == []
    assert contract.expected_metric_changes == []
    assert not any("remove" in item.lower() for item in contract.verification_requirements)


def _run(
    run_id: str,
    *,
    task_id: str | None = None,
    score: float | None = None,
    passed: bool | None = None,
    tool_reinjections: int = 4,
    extra_other_tokens: int = 0,
    client_latency_ms: float = 1000.0,
    serving_ttft_ms: float = 220.0,
    cached_tokens: int | None = 0,
    cache_miss_tokens: int | None = 800,
    serving: bool = True,
    metadata: dict[str, object] | None = None,
) -> AgentRun:
    trace = _trace(
        run_id,
        task_id=task_id,
        score=score,
        passed=passed,
        tool_reinjections=tool_reinjections,
        extra_other_tokens=extra_other_tokens,
        client_latency_ms=client_latency_ms,
        serving_ttft_ms=serving_ttft_ms,
        cached_tokens=cached_tokens,
        cache_miss_tokens=cache_miss_tokens,
        serving=serving,
        metadata=metadata,
    )
    return parse_agentperf_trace(trace)


def _trace(
    run_id: str,
    *,
    task_id: str | None,
    score: float | None,
    passed: bool | None,
    tool_reinjections: int,
    extra_other_tokens: int = 0,
    client_latency_ms: float = 1000.0,
    serving_ttft_ms: float = 220.0,
    cached_tokens: int | None = 0,
    cache_miss_tokens: int | None = 800,
    serving: bool = True,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    tool_text = " ".join(f"evidence{i}" for i in range(650))
    other_text = " ".join(f"other{i}" for i in range(extra_other_tokens))
    run_metadata: dict[str, object] = {"framework": "reliability-fixture", **(metadata or {})}
    if task_id is not None:
        run_metadata["task_id"] = task_id
    if score is not None or passed is not None:
        run_metadata["quality"] = {"score": score, "passed": passed}

    steps: list[dict[str, object]] = []
    llm_call_count = max(1, tool_reinjections)
    for index in range(llm_call_count):
        prompt: list[dict[str, object]] = [{"name": "system", "text": "You are careful."}]
        if index < tool_reinjections:
            prompt.append(
                {
                    "name": "tool_result",
                    "text": tool_text,
                    "metadata": {"source_tool_call_ids": ["search-1"]},
                }
            )
        if other_text:
            prompt.append({"name": "other_context", "text": other_text})
        step: dict[str, object] = {
            "agent_step_id": f"step-{index + 1}",
            "metadata": {
                key: run_metadata[key]
                for key in ("agent_id", "agent_role", "branch_id", "parent_branch_id")
                if key in run_metadata
            },
            "llm_calls": [
                {
                    "llm_call_id": f"llm-{index + 1}",
                    "llm_request_id": f"req-{index + 1}",
                    "model": "fixture-model",
                    "prompt": prompt,
                    "input_tokens": (700 if index < tool_reinjections else 50)
                    + extra_other_tokens,
                    "output_tokens": 10,
                    "tokenization_mode": "APPROXIMATE",
                    "metadata": {"latency_ms": client_latency_ms},
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

    serving_requests: list[dict[str, object]] = []
    if serving:
        serving_requests = [
            {
                "serving_request_id": f"srv-{index + 1}",
                "llm_request_id": f"req-{index + 1}",
                "queue_latency_ms": 5,
                "prefill_path_latency_ms": serving_ttft_ms,
                "decode_latency_ms": 50,
                "ttft_ms": serving_ttft_ms,
                "input_tokens": 700 + extra_other_tokens,
                "output_tokens": 10,
                "prefix_cache_hit_tokens": cached_tokens,
                "prefix_cache_miss_tokens": cache_miss_tokens,
            }
            for index in range(llm_call_count)
        ]
    return {
        "schema_version": "agentperf.trace.v1",
        "agent_run": {
            "agent_run_id": run_id,
            "metadata": run_metadata,
            "steps": steps,
        },
        "serving_requests": serving_requests,
    }


def _trace_payload(run: AgentRun) -> dict[str, object]:
    return {
        "schema_version": run.schema_version,
        "synthetic": run.synthetic,
        "agent_run": {
            "agent_run_id": run.agent_run_id,
            "trace_id": run.trace_id,
            "span_id": run.span_id,
            "parent_span_id": run.parent_span_id,
            "name": run.name,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "metadata": run.metadata,
            "steps": [
                {
                    "agent_step_id": step.agent_step_id,
                    "trace_id": step.trace_id,
                    "span_id": step.span_id,
                    "parent_span_id": step.parent_span_id,
                    "started_at": step.started_at,
                    "ended_at": step.ended_at,
                    "metadata": step.metadata,
                    "llm_calls": [
                        {**asdict(call), "prompt": asdict(call)["prompt_components"]}
                        for call in step.llm_calls
                    ],
                    "tool_calls": [asdict(tool) for tool in step.tool_calls],
                }
                for step in run.steps
            ],
        },
        "serving_requests": [asdict(request) for request in run.serving_requests],
    }


def _replace_run_metadata(run: AgentRun, updates: dict[str, object]) -> AgentRun:
    data = _trace_payload(run)
    agent_run = data["agent_run"]
    assert isinstance(agent_run, dict)
    metadata = agent_run["metadata"]
    assert isinstance(metadata, dict)
    metadata.update(updates)
    return parse_agentperf_trace(data)


def _artifact(
    path: Path,
    *,
    status: str,
    tasks: list[str],
    quality_score: float,
    pass_rate: float,
    tool_reinjections: int,
) -> Path:
    run = _run(
        path.name,
        task_id=None,
        score=None,
        passed=None,
        tool_reinjections=tool_reinjections,
    )
    report = analyze_run(run)
    task_results = [
        TaskResult(
            task_id=task_id,
            passed=index < round(pass_rate * len(tasks)),
            quality_score=quality_score,
            agent_run_ids=[run.agent_run_id],
            status=status,
        )
        for index, task_id in enumerate(tasks)
    ]
    artifact = ExperimentArtifact.from_analysis(
        report,
        artifact_id=path.name,
        workload_id="strict-policy",
        task_results=task_results,
        task_count=len(tasks),
        quality_metrics=[
            QualityMetric(
                name="mean_score",
                value=quality_score,
                aggregation="mean",
                tolerance=0.05,
            ),
            QualityMetric(
                name="pass_rate",
                value=pass_rate,
                aggregation="rate",
                tolerance=0.10,
            ),
        ],
        summary={"status": status},
        metadata={"status": status},
    )
    artifact = ExperimentArtifact(
        manifest=replace(artifact.manifest, status=cast(ArtifactStatus, status)),
        runs=artifact.runs,
        task_results=artifact.task_results,
        quality_metrics=artifact.quality_metrics,
        findings=artifact.findings,
        environment=artifact.environment,
        summary=artifact.summary,
    )
    artifact.save(path)
    return path
