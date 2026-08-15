from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from agentperf.artifacts import load_artifact
from agentperf.comparison import compare_paths
from agentperf.completeness import assess_path
from agentperf.metrics.attribution import component_token_attribution
from agentperf.metrics.tokens import compute_duplication_metrics
from agentperf.schema.trace import LLMCall, PromptComponent

ROOT = Path(__file__).resolve().parents[1]


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


generator = _load_module(ROOT / "scripts/generate_scale_fixture.py", "generate_scale_fixture")
benchmark = _load_module(ROOT / "scripts/m21_scale_benchmark.py", "m21_scale_benchmark")


def test_scale_fixture_generator_is_deterministic_for_trace_payload(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    config_left = generator.ScaleFixtureConfig(
        tasks=2,
        llm_calls_per_task=3,
        tool_calls_per_task=1,
        serving_telemetry=True,
        output=left,
        artifact_id="same",
        workload_id="same",
    )
    config_right = generator.ScaleFixtureConfig(
        tasks=2,
        llm_calls_per_task=3,
        tool_calls_per_task=1,
        serving_telemetry=True,
        output=right,
        artifact_id="same",
        workload_id="same",
    )

    generator.save_scale_artifact(config_left)
    generator.save_scale_artifact(config_right)

    assert json.loads((left / "trace.json").read_text()) == json.loads(
        (right / "trace.json").read_text()
    )
    assert json.loads((left / "tasks.json").read_text()) == json.loads(
        (right / "tasks.json").read_text()
    )


def test_scale_fixture_counts_and_component_totals(tmp_path: Path) -> None:
    output = tmp_path / "fixture"
    generator.save_scale_artifact(
        generator.ScaleFixtureConfig(
            tasks=4,
            llm_calls_per_task=5,
            tool_calls_per_task=2,
            serving_telemetry=True,
            output=output,
        )
    )

    artifact = load_artifact(output)
    run = artifact.runs_for_comparison()[0]
    attribution = component_token_attribution(run)

    assert len(run.steps) == 4
    assert len(run.llm_calls) == 20
    assert len(run.tool_calls) == 8
    assert len(run.serving_requests) == 20
    assert len(artifact.task_results) == 4
    assert attribution.total_processed_tokens == sum(
        call.input_tokens or 0 for call in run.llm_calls
    )


def test_large_scale_fixture_doctor_and_compare_remain_correct(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    generator.save_scale_artifact(
        generator.ScaleFixtureConfig(
            tasks=20,
            llm_calls_per_task=5,
            tool_calls_per_task=2,
            serving_telemetry=True,
            output=baseline,
            artifact_id="baseline",
            workload_id="scale-compare",
        )
    )
    generator.save_scale_artifact(
        generator.ScaleFixtureConfig(
            tasks=20,
            llm_calls_per_task=5,
            tool_calls_per_task=2,
            serving_telemetry=True,
            output=candidate,
            artifact_id="candidate",
            workload_id="scale-compare",
            tool_result_tokens=20,
        )
    )

    doctor = assess_path(baseline)
    comparison = compare_paths(baseline, candidate)

    assert doctor.agent_profiling_readiness == "READY"
    assert doctor.cross_layer_readiness == "READY"
    assert doctor.llm_calls_observed == 100
    assert doctor.exact_serving_correlations == 100
    assert len(comparison.matched_tasks) == 20
    baseline_tokens = comparison.token_deltas.input_tokens.baseline
    candidate_tokens = comparison.token_deltas.input_tokens.candidate
    assert baseline_tokens is not None
    assert candidate_tokens is not None
    assert candidate_tokens < baseline_tokens


def test_benchmark_script_writes_stable_schema_for_zero_call_case(tmp_path: Path) -> None:
    output = tmp_path / "results.json"

    result = benchmark.run_benchmark(
        output=output,
        call_counts=[0],
        repetitions=1,
        warmups=0,
        max_report_calls=0,
    )

    written = json.loads(output.read_text())
    assert written == result
    assert written["environment"]["agentperf_version"]
    cases = {record["case"] for record in written["records"]}
    assert {"instrumentation_off", "analyze", "doctor", "compare", "check"} <= cases
    for record in written["records"]:
        assert "wall_ms_median" in record
        assert "peak_memory_mb_median" in record


def test_duplication_prefix_metrics_preserve_expected_values() -> None:
    calls = [
        LLMCall(
            llm_call_id="a",
            prompt_components=[
                PromptComponent("system", "alpha beta gamma"),
                PromptComponent("user", "one"),
            ],
        ),
        LLMCall(
            llm_call_id="b",
            prompt_components=[
                PromptComponent("system", "alpha beta delta"),
                PromptComponent("user", "two"),
            ],
        ),
        LLMCall(
            llm_call_id="c",
            prompt_components=[
                PromptComponent("system", "zeta eta theta"),
                PromptComponent("user", "three"),
            ],
        ),
    ]

    metrics = compute_duplication_metrics(calls)

    assert metrics.largest_common_prefix_tokens == 2
    assert metrics.affected_call_ids == ["a", "b"]
