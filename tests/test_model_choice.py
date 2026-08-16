from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path

from agentperf.cli import main as cli_main
from agentperf.comparison import compare_paths, compare_workloads
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import trace_llm, trace_run
from agentperf.metrics.roles import role_profiles
from agentperf.model_choice import (
    analyze_model_choice_data,
    routing_summary_from_run,
)
from agentperf.recommendations import recommendation_contract_for_finding
from agentperf.schema.trace import parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def _load_phase_a_main() -> Callable[[list[str]], int]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "run_model_choice_phase_a",
        ROOT / "scripts" / "run_model_choice_phase_a.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_model_choice_phase_a"] = module
    spec.loader.exec_module(module)
    return module.main  # type: ignore[no-any-return]


def _load_phase_b_main() -> Callable[[list[str]], int]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "run_model_choice_phase_b",
        ROOT / "scripts" / "run_model_choice_phase_b.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_model_choice_phase_b"] = module
    spec.loader.exec_module(module)
    return module.main  # type: ignore[no-any-return]


def test_role_attribution_normalizes_legacy_roles() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "roles",
                "steps": [
                    {
                        "agent_step_id": "s1",
                        "llm_calls": [
                            {
                                "llm_call_id": "planner",
                                "semantic_role": "planner",
                                "input_tokens": 10,
                                "output_tokens": 2,
                            },
                            {
                                "llm_call_id": "review",
                                "metadata": {"role": "evidence-review"},
                                "input_tokens": 20,
                                "output_tokens": 3,
                            },
                            {
                                "llm_call_id": "final",
                                "metadata": {"role": "final"},
                                "input_tokens": 30,
                                "output_tokens": 4,
                            },
                        ],
                    }
                ],
            }
        }
    )

    profiles = {profile.role: profile for profile in role_profiles(run)}

    assert profiles["planner"].calls == 1
    assert profiles["evidence_reviewer"].input_tokens == 20
    assert profiles["final_synthesizer"].output_tokens == 4


def test_model_choice_headroom_requires_quality_preserving_replay() -> None:
    report = analyze_model_choice_data(_comparison_fixture())

    finding_roles = {finding.evidence["role"] for finding in report.findings}
    sensitivity = {
        (row.role, row.candidate_model): row for row in report.role_sensitivity
    }

    assert "planner" in finding_roles
    assert "final_synthesizer" not in finding_roles
    assert sensitivity[("final_synthesizer", "small")].quality_preserving is False
    assert sensitivity[("planner", "small")].status == "SAFE_WITHIN_TOLERANCE"
    assert report.selected_mixed_config == "mixed_evidence_backed"
    local = next(
        finding
        for finding in report.findings
        if finding.evidence.get("evidence_source") == "COUNTERFACTUAL_ROLE_REPLAY"
    )
    assert local.evidence["headroom_scope"] == "LOCAL_ROLE_HEADROOM"
    assert (
        local.provenance.derived_metrics["validation_status"]
        == "LOCAL_ROLE_HEADROOM_CANDIDATE_TO_VERIFY"
    )


def test_pareto_marks_quality_violating_candidate() -> None:
    report = analyze_model_choice_data(_comparison_fixture())
    pareto = {row["config"]: row for row in report.pareto}

    assert pareto["synthesizer_small"]["quality_preserving"] is False
    assert pareto["mixed_evidence_backed"]["quality_preserving"] is True


def test_end_to_end_mixed_finding_uses_validated_evidence() -> None:
    report = analyze_model_choice_data(_comparison_fixture())
    mixed = next(
        finding
        for finding in report.findings
        if finding.evidence.get("evidence_source") == "END_TO_END_VALIDATED"
    )

    assert mixed.evidence["config_name"] == "mixed_evidence_backed"
    assert mixed.evidence["headroom_scope"] == "GLOBAL_ROUTING_VERIFIED"
    assert mixed.provenance.derived_metrics["validation_status"] == "END_TO_END_VALIDATED"
    assert report.routing_verification.status == "VERIFIED"
    assert report.routing_verification.recommendation_verification is not None
    assert report.routing_verification.recommendation_verification.status == "VERIFIED"


def test_model_choice_contract_requires_full_routing_replay() -> None:
    report = analyze_model_choice_data(_phase_a_only_fixture())
    finding = next(finding for finding in report.findings if finding.id == "MODEL_CHOICE_HEADROOM")
    contract = recommendation_contract_for_finding(finding)

    assert contract is not None
    assert contract.applicability == "CONDITIONAL"
    assert any("full mixed routing" in item.lower() for item in contract.verification_requirements)
    assert report.routing_verification.status == "CANDIDATE_TO_VERIFY"
    assert report.routing_verification.recommendation_verification is None


def test_historical_m4_phase_a_migration_stays_local_headroom_only() -> None:
    data = json.loads(
        (ROOT / "docs/data/m25_historical_m4_phase_a.json").read_text(encoding="utf-8")
    )

    report = analyze_model_choice_data(data)

    assert report.routing_verification.status == "CANDIDATE_TO_VERIFY"
    assert report.candidate_routing is not None
    assert report.candidate_routing.routing == data["proposed_mixed_routing_candidate"]
    assert any(
        finding.evidence.get("headroom_scope") == "LOCAL_ROLE_HEADROOM"
        for finding in report.findings
    )
    assert not any(
        finding.evidence.get("headroom_scope") == "GLOBAL_ROUTING_VERIFIED"
        for finding in report.findings
    )


def test_real_m25_phase_b_evidence_verifies_global_routing() -> None:
    data = json.loads(
        (ROOT / "docs/data/m25_phase_b/model_choice_phase_b_comparison.json").read_text(
            encoding="utf-8"
        )
    )

    report = analyze_model_choice_data(data)
    verification = report.routing_verification

    assert verification.status == "VERIFIED"
    assert verification.config_name == "mixed_evidence_backed"
    assert verification.quality_preserving is True
    assert verification.recommendation_verification is not None
    assert verification.recommendation_verification.status == "VERIFIED"
    assert verification.relative_cost_delta is not None
    assert verification.relative_cost_delta < 0
    assert verification.client_latency_p95_delta_ms is not None
    assert verification.client_latency_p95_delta_ms < 0

    mixed = next(
        finding
        for finding in report.findings
        if finding.evidence.get("evidence_source") == "END_TO_END_VALIDATED"
    )
    assert mixed.evidence["headroom_scope"] == "GLOBAL_ROUTING_VERIFIED"
    assert mixed.evidence["changed_roles"] == [
        {
            "role": "planner",
            "baseline_model": "strong",
            "selected_model": "medium",
        },
        {
            "role": "evidence_reviewer",
            "baseline_model": "strong",
            "selected_model": "small",
        },
        {
            "role": "final_synthesizer",
            "baseline_model": "strong",
            "selected_model": "small",
        },
    ]


def test_real_m25_phase_b_artifacts_compare_as_accept() -> None:
    base = ROOT / "docs/data/m25_phase_b"

    comparison = compare_paths(
        base / "strong_control/agentperf_artifact",
        base / "mixed_evidence_backed/agentperf_artifact",
    )

    assert comparison.acceptance_result.verdict == "ACCEPT"
    assert comparison.quality_deltas.passed is True
    assert comparison.quality_deltas.mean_score.delta == -0.033333333333333215
    assert comparison.quality_deltas.pass_rate.delta == -0.09999999999999998
    assert comparison.matched_tasks == [
        "q01-cache",
        "q02-jobs",
        "q03-region",
        "q04-auth",
        "q05-webhooks",
        "q06-cache-owner",
        "q07-jobs-no-scale",
        "q08-region-writes",
        "q09-auth-risk",
        "q10-webhook-drain",
    ]
    assert comparison.metadata["baseline_model_routing"]["role_model_map"] == {
        "evidence_reviewer": "agentperf-qwen3-4b",
        "final_synthesizer": "agentperf-qwen3-4b",
        "planner": "agentperf-qwen3-4b",
    }
    assert comparison.metadata["candidate_model_routing"]["role_model_map"] == {
        "evidence_reviewer": "agentperf-qwen3-0.6b",
        "final_synthesizer": "agentperf-qwen3-0.6b",
        "planner": "agentperf-qwen3-1.7b",
    }
    assert comparison.metadata["task_quality_changes"] == [
        {
            "task_id": "q09-auth-risk",
            "baseline_score": 1.0,
            "candidate_score": 0.6666666666666666,
            "baseline_passed": True,
            "candidate_passed": False,
        }
    ]


def test_real_m25_phase_b_html_renders_model_routing() -> None:
    html = (
        ROOT / "docs/data/m25_phase_b/model_choice_phase_b_comparison.html"
    ).read_text(encoding="utf-8")

    assert "Model Routing" in html
    assert "agentperf-qwen3-4b -&gt; agentperf-qwen3-1.7b" in html
    assert "agentperf-qwen3-4b -&gt; agentperf-qwen3-0.6b" in html
    assert "Replay Verification" in html
    assert "ACCEPT" in html


def test_candidate_routing_prefers_quality_margin_over_tiniest_model() -> None:
    report = analyze_model_choice_data(_phase_a_non_monotonic_fixture())

    assert report.candidate_routing is not None
    assert report.candidate_routing.status == "CANDIDATE_TO_VERIFY"
    assert report.candidate_routing.routing["planner"] == "medium"
    assert report.candidate_routing.routing["evidence_reviewer"] == "small"
    assert report.candidate_routing.routing["final_synthesizer"] == "small"


def test_mixed_routing_quality_failure_is_rejected() -> None:
    fixture = _comparison_fixture()
    mixed = fixture["configurations"]["mixed_evidence_backed"]  # type: ignore[index]
    assert isinstance(mixed, dict)
    mixed["correctness"] = {"mean_score": 0.60, "pass_rate": 0.40}

    report = analyze_model_choice_data(fixture)

    assert report.routing_verification.status == "REJECTED_QUALITY_REGRESSION"
    assert report.routing_verification.recommendation_verification is None


def test_role_model_metadata_roundtrips_through_instrumentation(tmp_path: Path) -> None:
    artifact_path = tmp_path / "artifact"
    with ExperimentSession(output_path=artifact_path, workload_id="routing-test") as exp:
        with trace_run(task_id="task-1"):
            with trace_llm(role="planner", model="model-a") as call:
                call.record_response(input_tokens=10, output_tokens=2)
            with trace_llm(semantic_role="reviewer", model="model-b") as call:
                call.record_response(input_tokens=20, output_tokens=3)
        exp.record_task_result(task_id="task-1", passed=True, quality_score=1.0)

    trace = json.loads((artifact_path / "trace.json").read_text(encoding="utf-8"))
    run = parse_agentperf_trace(trace)
    summary = json.loads((artifact_path / "summary.json").read_text(encoding="utf-8"))

    routing = routing_summary_from_run(run)
    assert routing["available"] is True
    assert routing["role_model_map"] == {"planner": "model-a", "reviewer": "model-b"}
    assert summary["model_routing"]["role_model_map"]["planner"] == "model-a"


def test_trace_llm_rejects_conflicting_role_aliases() -> None:
    try:
        with (
            trace_run(task_id="task"),
            trace_llm(role="planner", semantic_role="reviewer", model="model"),
        ):
            pass
    except ValueError as exc:
        assert "role and semantic_role" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("conflicting role aliases should fail")


def test_comparison_metadata_exposes_model_routing() -> None:
    baseline = parse_agentperf_trace(_routing_trace("baseline", "planner", "model-4b"))
    candidate = parse_agentperf_trace(_routing_trace("candidate", "planner", "model-1b"))

    comparison = compare_workloads([baseline], [candidate], mean_score_tolerance=0.05)

    assert comparison.metadata["baseline_model_routing"]["role_model_map"] == {
        "planner": "model-4b"
    }
    assert comparison.metadata["candidate_model_routing"]["role_model_map"] == {
        "planner": "model-1b"
    }


def test_model_choice_cli_renders_report(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "model_choice.json"
    path.write_text(json.dumps(_comparison_fixture()), encoding="utf-8")

    code = cli_main(["analyze-model-choice", str(path)])
    output = capsys.readouterr().out

    assert code == 0
    assert "AgentPerf Model-Choice Report" in output
    assert "MODEL_CHOICE_HEADROOM" in output
    assert "Full Routing Verification" in output


def test_phase_a_sequential_replay_regenerates_downstream_strong_calls(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "phase_a"
    phase_a_main = _load_phase_a_main()

    assert phase_a_main(
        [
            "--stage",
            "strong-baseline",
            "--tier",
            "strong",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0
    assert phase_a_main(
        [
            "--stage",
            "candidate-tier",
            "--tier",
            "small",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0
    assert phase_a_main(
        [
            "--stage",
            "strong-continuations",
            "--tier",
            "strong",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    planner_small = json.loads(
        (output_dir / "planner_small" / "raw" / "recording.json").read_text(
            encoding="utf-8"
        )
    )
    first_task_records = planner_small["records"][:3]

    assert [record["semantic_role"] for record in first_task_records] == [
        "planner",
        "evidence_reviewer",
        "final_synthesizer",
    ]
    assert first_task_records[0]["metadata"]["model_tier"] == "small"
    assert first_task_records[1]["metadata"]["model_tier"] == "strong"
    assert first_task_records[2]["metadata"]["model_tier"] == "strong"
    assert (
        first_task_records[1]["metadata"]["replay_stage"]
        == "small_planner_strong_review_continuation"
    )

    comparison = json.loads(
        (output_dir / "model_choice_comparison.json").read_text(encoding="utf-8")
    )
    assert set(comparison["configurations"]) >= {
        "strong_all",
        "planner_small",
        "reviewer_small",
        "synthesizer_small",
    }


def test_phase_b_mock_replay_writes_mixed_and_repeatability(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "phase_b"
    phase_b_main = _load_phase_b_main()

    assert phase_b_main(
        [
            "--stage",
            "strong-control",
            "--tier",
            "strong",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0
    for tier in ("medium", "small"):
        assert phase_b_main(
            [
                "--stage",
                "reviewer-candidates",
                "--tier",
                tier,
                "--mock-llm",
                "--output-dir",
                str(output_dir),
                "--repeat-count",
                "1",
            ]
        ) == 0
    assert phase_b_main(
        [
            "--stage",
            "reviewer-continuations",
            "--tier",
            "strong",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
            "--repeat-count",
            "1",
        ]
    ) == 0
    assert phase_b_main(
        [
            "--stage",
            "mixed-end-to-end",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
        ]
    ) == 0

    comparison = json.loads(
        (output_dir / "model_choice_phase_b_comparison.json").read_text(
            encoding="utf-8"
        )
    )
    assert set(comparison["configurations"]) == {
        "strong_control",
        "mixed_evidence_backed",
    }
    assert comparison["reviewer_repeatability"]["small"]["runs"]
    assert comparison["configurations"]["mixed_evidence_backed"]["routing"] == {
        "planner": "medium",
        "evidence_reviewer": "small",
        "final_synthesizer": "small",
    }


def _summary(
    *,
    mean_score: float,
    pass_rate: float,
    cost: float,
    latency: float,
    routing: dict[str, str],
) -> dict[str, object]:
    return {
        "correctness": {"mean_score": mean_score, "pass_rate": pass_rate},
        "routing": routing,
        "input_tokens": 1000,
        "output_tokens": 100,
        "ttft_p95_ms": latency / 2,
        "client_latency_p95_ms": latency,
        "relative_cost": cost,
        "role_profiles": {},
    }


def _comparison_fixture() -> dict[str, object]:
    strong = {
        "planner": "strong",
        "evidence_reviewer": "strong",
        "final_synthesizer": "strong",
    }
    return {
        "baseline_config": "strong_all",
        "selected_mixed_config": "mixed_evidence_backed",
        "quality_constraint": {
            "mean_score_tolerance": 0.05,
            "pass_rate_tolerance": 0.10,
        },
        "configurations": {
            "strong_all": _summary(
                mean_score=0.93,
                pass_rate=0.80,
                cost=1.0,
                latency=1000,
                routing=strong,
            ),
            "planner_small": _summary(
                mean_score=0.91,
                pass_rate=0.80,
                cost=0.8,
                latency=800,
                routing={**strong, "planner": "small"},
            ),
            "synthesizer_small": _summary(
                mean_score=0.70,
                pass_rate=0.50,
                cost=0.6,
                latency=600,
                routing={**strong, "final_synthesizer": "small"},
            ),
            "mixed_evidence_backed": _summary(
                mean_score=0.90,
                pass_rate=0.70,
                cost=0.7,
                latency=700,
                routing={
                    "planner": "small",
                    "evidence_reviewer": "medium",
                    "final_synthesizer": "strong",
                },
            ),
        },
    }


def _phase_a_only_fixture() -> dict[str, object]:
    fixture = _comparison_fixture()
    configs = fixture["configurations"]
    assert isinstance(configs, dict)
    configs.pop("mixed_evidence_backed")
    fixture.pop("selected_mixed_config")
    return fixture


def _phase_a_non_monotonic_fixture() -> dict[str, object]:
    strong = {
        "planner": "strong",
        "evidence_reviewer": "strong",
        "final_synthesizer": "strong",
    }
    return {
        "baseline_config": "strong_all",
        "quality_constraint": {
            "mean_score_tolerance": 0.05,
            "pass_rate_tolerance": 0.10,
        },
        "configurations": {
            "strong_all": _summary(
                mean_score=0.967,
                pass_rate=0.90,
                cost=0.401,
                latency=4660.6,
                routing=strong,
            ),
            "planner_medium": _summary(
                mean_score=0.967,
                pass_rate=0.90,
                cost=0.395,
                latency=4403.8,
                routing={**strong, "planner": "medium"},
            ),
            "planner_small": _summary(
                mean_score=0.933,
                pass_rate=0.80,
                cost=0.394,
                latency=4759.7,
                routing={**strong, "planner": "small"},
            ),
            "reviewer_medium": _summary(
                mean_score=0.900,
                pass_rate=0.70,
                cost=0.297,
                latency=4767.9,
                routing={**strong, "evidence_reviewer": "medium"},
            ),
            "reviewer_small": _summary(
                mean_score=0.967,
                pass_rate=0.90,
                cost=0.248,
                latency=4886.7,
                routing={**strong, "evidence_reviewer": "small"},
            ),
            "synthesizer_medium": _summary(
                mean_score=0.967,
                pass_rate=0.90,
                cost=0.280,
                latency=2654.1,
                routing={**strong, "final_synthesizer": "medium"},
            ),
            "synthesizer_small": _summary(
                mean_score=0.967,
                pass_rate=0.90,
                cost=0.222,
                latency=2654.1,
                routing={**strong, "final_synthesizer": "small"},
            ),
        },
    }


def _routing_trace(run_id: str, role: str, model: str) -> dict[str, object]:
    return {
        "agent_run": {
            "agent_run_id": run_id,
            "metadata": {"task_id": "task", "quality": {"score": 1.0, "passed": True}},
            "steps": [
                {
                    "agent_step_id": "step-1",
                    "llm_calls": [
                        {
                            "llm_call_id": f"{run_id}-llm",
                            "semantic_role": role,
                            "model": model,
                            "input_tokens": 10,
                            "output_tokens": 2,
                            "metadata": {"client_elapsed_ms": 10.0},
                        }
                    ],
                }
            ],
        }
    }
