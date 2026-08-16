from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentperf.cli import main
from agentperf.comparison import compare_paths
from agentperf.regression import evaluate_regression_policy, load_regression_policy
from agentperf.reporters.comparison_html import (
    build_comparison_html_input,
    render_comparison_html,
)

ROOT = Path(__file__).resolve().parents[1]


def test_comparison_html_renders_m3_replay_semantics() -> None:
    baseline = ROOT / "examples/artifacts/m3_raw_full"
    candidate = ROOT / "examples/artifacts/m3_dedup_only"
    comparison = compare_paths(baseline, candidate)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert "<!doctype html>" in html
    assert "Replay Verification" in html
    assert "ACCEPT" in html
    assert "Quality Verification" in html
    assert "Token Accounting" in html
    assert "Model / Provider Usage" in html
    assert "Agent Context Attribution" in html
    assert "TOOL_RESULT" in html
    assert "Finding Lifecycle" in html
    assert "Tool-Output Carry-Forward" in html
    assert "Context-Growth Comparison" in html


def test_comparison_html_shows_provider_component_divergence_for_m13_pair() -> None:
    baseline = ROOT / "benchmarks/openai-agents-support-triage/baseline"
    candidate = ROOT / "examples/dogfooding/openai_agents_support_triage_compact"
    comparison = compare_paths(baseline, candidate)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert comparison.token_deltas.input_tokens.delta == 0
    assert comparison.token_deltas.component_accounting is not None
    assert comparison.token_deltas.component_accounting.total_processed_tokens.delta == -160
    assert "Provider input tokens" in html
    assert "Total processed tokens" in html
    assert "SYSTEM" in html


def test_comparison_html_quality_regression_visually_dominates(tmp_path: Path) -> None:
    baseline = _write(
        tmp_path / "baseline.json",
        _trace("base", task_id="task-1", score=1.0, passed=True),
    )
    candidate = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id="task-1", score=0.1, passed=False, tool_reinjections=0),
    )
    comparison = compare_paths(baseline, candidate, mean_score_tolerance=0.05)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert "REJECT QUALITY REGRESSION" in html
    assert "Quality regression dominates" in html
    assert "Performance improvements are not accepted" in html


def test_comparison_html_marks_missing_quality_unavailable(tmp_path: Path) -> None:
    baseline = _write(tmp_path / "baseline.json", _trace("base", task_id="task-1"))
    candidate = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id="task-1", tool_reinjections=0),
    )
    comparison = compare_paths(baseline, candidate)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert "Quality verification unavailable" in html
    assert "INCONCLUSIVE" in html


def test_comparison_html_renders_task_mismatch_and_escaping(tmp_path: Path) -> None:
    baseline = _write(
        tmp_path / "baseline.json",
        _trace("base", task_id="<script>alert(1)</script>", score=1.0, passed=True),
    )
    candidate = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id="other", score=1.0, passed=True),
    )
    comparison = compare_paths(baseline, candidate)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert "Task sets differ" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_comparison_html_redacts_secret_like_task_and_metadata_values(tmp_path: Path) -> None:
    secret_task = "OPENAI_API_KEY=sk-test-secret"
    baseline = _write(
        tmp_path / "baseline.json",
        _trace("base", task_id=secret_task, score=1.0, passed=True),
    )
    candidate = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id=secret_task, score=0.5, passed=False),
    )
    comparison = compare_paths(baseline, candidate, mean_score_tolerance=0.05)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert "OPENAI_API_KEY=sk-test-secret" not in html
    assert "Authorization: Bearer fake-secret" not in html
    assert "RUNPOD_API_KEY=fake" not in html
    assert "/user/private/path" not in html
    assert "[redacted]" in html


def test_comparison_html_embeds_policy_check_table() -> None:
    baseline = ROOT / "examples/artifacts/m3_raw_full"
    candidate = ROOT / "examples/artifacts/m3_dedup_only"
    comparison = compare_paths(baseline, candidate)
    result = evaluate_regression_policy(
        comparison,
        load_regression_policy(ROOT / "examples/policies/m3-context-regression.yaml"),
    )

    html = render_comparison_html(
        build_comparison_html_input(
            comparison,
            baseline,
            candidate,
            regression_result=result,
            title="Policy report",
        )
    )

    assert "Regression Policy" in html
    assert "Policy result" in html
    assert "PASS" in html
    assert "component.tool_result.processed_tokens" in html


def test_comparison_html_shows_serving_without_calling_missing_zero() -> None:
    trace = ROOT / "examples/traces/replay_baseline.json"
    comparison = compare_paths(trace, trace)

    html = render_comparison_html(build_comparison_html_input(comparison, trace, trace))

    assert "Cross-Layer Serving Correlation" in html
    assert "Exact correlations" in html
    assert "Scheduled-to-first" in html
    assert "not pure GPU prefill kernel latency" in html


def test_comparison_html_shows_model_routing_when_roles_exist(tmp_path: Path) -> None:
    baseline = _write(
        tmp_path / "baseline.json",
        _trace("base", task_id="task-1", score=1.0, passed=True, model="model-4b"),
    )
    candidate = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id="task-1", score=1.0, passed=True, model="model-1b"),
    )
    comparison = compare_paths(baseline, candidate)

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline, candidate)
    )

    assert "Model Routing" in html
    assert "planner" in html
    assert "model-4b" in html
    assert "model-1b" in html


def test_cli_compare_html_and_json_compatibility(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    baseline = _write(
        tmp_path / "baseline.json",
        _trace("base", task_id="task-1", score=1.0, passed=True),
    )
    candidate = _write(
        tmp_path / "candidate.json",
        _trace("candidate", task_id="task-1", score=1.0, passed=True, tool_reinjections=0),
    )
    html_path = tmp_path / "comparison.html"
    json_path = tmp_path / "comparison.json"

    html_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "html",
            "--output",
            str(html_path),
        ]
    )
    json_code = main(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--format",
            "json",
            "--output",
            str(json_path),
        ]
    )
    captured = capsys.readouterr()

    assert html_code == 0
    assert json_code == 0
    assert "<!doctype html>" in html_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["acceptance_result"][
        "verdict"
    ] in {"ACCEPT", "NO_MATERIAL_CHANGE"}
    assert captured.err == ""


def test_cli_check_html_contains_policy_result(tmp_path: Path) -> None:
    baseline = ROOT / "examples/artifacts/m3_raw_full"
    candidate = ROOT / "examples/artifacts/m3_dedup_only"
    output = tmp_path / "check.html"

    code = main(
        [
            "check",
            str(baseline),
            str(candidate),
            "--policy",
            str(ROOT / "examples/policies/m3-context-regression.yaml"),
            "--format",
            "html",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    html = output.read_text(encoding="utf-8")
    assert "AgentPerf Regression Check" in html
    assert "Regression Policy" in html
    assert "Policy result" in html


def _write(path: Path, data: dict[str, object]) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _trace(
    run_id: str,
    *,
    task_id: str | None = None,
    score: float | None = None,
    passed: bool | None = None,
    tool_reinjections: int = 3,
    serving: bool = True,
    model: str = "fixture-model",
) -> dict[str, object]:
    tool_text = " ".join(f"evidence{i}" for i in range(180))
    metadata: dict[str, object] = {}
    if task_id is not None:
        metadata["task_id"] = task_id
        metadata["auth_header"] = "Authorization: Bearer fake-secret"
        metadata["runpod_hint"] = "RUNPOD_API_KEY=fake"
        metadata["private_path"] = "/user/private/path"
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
                    "metadata": {"source_tool_call_ids": ["tool-1"]},
                }
            )
        step: dict[str, Any] = {
            "agent_step_id": f"step-{index + 1}",
            "llm_calls": [
                {
                    "llm_call_id": f"llm-{index + 1}",
                    "llm_request_id": f"req-{index + 1}",
                    "semantic_role": "planner",
                    "model": model,
                    "prompt": prompt,
                    "input_tokens": 220 if index < tool_reinjections else 20,
                    "output_tokens": 8,
                    "tokenization_mode": "APPROXIMATE",
                    "metadata": {"latency_ms": 1000.0},
                }
            ],
        }
        if index == 0:
            step["tool_calls"] = [
                {
                    "tool_call_id": "tool-1",
                    "name": "lookup",
                    "latency_ms": 20,
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
                "queue_latency_ms": 3,
                "prefill_path_latency_ms": 180,
                "decode_latency_ms": 40,
                "ttft_ms": 180,
                "input_tokens": 220,
                "output_tokens": 8,
                "prefix_cache_hit_tokens": 0,
                "prefix_cache_miss_tokens": 220,
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
