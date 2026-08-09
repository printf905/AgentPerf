from __future__ import annotations

import json
from pathlib import Path

from agentperf.cli import main as cli_main
from agentperf.metrics.roles import role_profiles
from agentperf.model_choice import analyze_model_choice_data
from agentperf.schema.trace import parse_agentperf_trace


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
    assert report.selected_mixed_config == "mixed_evidence_backed"


def test_pareto_marks_quality_violating_candidate() -> None:
    report = analyze_model_choice_data(_comparison_fixture())
    pareto = {row["config"]: row for row in report.pareto}

    assert pareto["synthesizer_small"]["quality_preserving"] is False
    assert pareto["mixed_evidence_backed"]["quality_preserving"] is True


def test_model_choice_cli_renders_report(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "model_choice.json"
    path.write_text(json.dumps(_comparison_fixture()), encoding="utf-8")

    code = cli_main(["analyze-model-choice", str(path)])
    output = capsys.readouterr().out

    assert code == 0
    assert "AgentPerf Model-Choice Report" in output
    assert "MODEL_CHOICE_HEADROOM" in output


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
