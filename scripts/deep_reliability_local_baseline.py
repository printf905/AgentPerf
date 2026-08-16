from __future__ import annotations

import argparse
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from agentperf.analyzer import AnalysisReport, analyze_run
from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.comparison import compare_paths
from agentperf.completeness import assess_path
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import trace_llm, trace_run, trace_tool
from agentperf.reporters.comparison_html import (
    build_comparison_html_input,
    render_comparison_html,
)
from agentperf.reporters.html import load_html_report_input, render_html_report
from agentperf.schema.artifacts import QualityMetric, TaskResult
from agentperf.schema.comparison import RunComparison
from agentperf.schema.trace import AgentRun, parse_agentperf_trace

T = TypeVar("T")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run deterministic local reliability/performance smoke measurements. "
            "Results are host-local characterization, not production benchmarks."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/private/tmp/agentperf-reliability-baseline"),
    )
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[10, 100, 500, 1000, 5000],
    )
    parser.add_argument(
        "--skip-html",
        action="store_true",
        help="Skip single-run and comparison HTML timing.",
    )
    parser.add_argument(
        "--checkpoint-stress",
        action="store_true",
        help="Run checkpoint capture stress instead of artifact operation timings.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.checkpoint_stress:
        _checkpoint_stress(args.output_dir, args.sizes)
    else:
        _artifact_operation_baseline(args.output_dir, args.sizes, skip_html=args.skip_html)
    return 0


def _artifact_operation_baseline(
    output_dir: Path,
    sizes: list[int],
    *,
    skip_html: bool,
) -> None:
    print(
        "size,artifact_mb,load_ms,analyze_ms,compare_ms,"
        "report_html_ms,comparison_html_ms,html_mb,comparison_html_mb,peak_mb"
    )
    for size in sizes:
        baseline = _save_artifact(output_dir / f"base-{size}", "base", size, 5)
        candidate = _save_artifact(output_dir / f"cand-{size}", "cand", size, 10)
        artifact_mb = _tree_size_mb(baseline)

        def load_current(path: Path = baseline) -> ExperimentArtifact:
            return load_artifact(path)

        def analyze_current(path: Path = baseline) -> list[AnalysisReport]:
            return [analyze_run(run) for run in load_artifact(path).runs_for_comparison()]

        def compare_current(
            baseline_path: Path = baseline,
            candidate_path: Path = candidate,
        ) -> RunComparison:
            return compare_paths(baseline_path, candidate_path)

        load_ms, load_peak, _ = _measure(load_current)
        analyze_ms, analyze_peak, _ = _measure(
            analyze_current
        )
        compare_ms, compare_peak, comparison = _measure(
            compare_current
        )
        if skip_html:
            report_ms = comparison_html_ms = html_mb = comparison_html_mb = 0.0
            report_peak = comparison_html_peak = 0.0
        else:
            def render_single_html(path: Path = baseline) -> str:
                return render_html_report(load_html_report_input(path))

            def render_before_after_html(
                current_comparison: RunComparison = comparison,
                baseline_path: Path = baseline,
                candidate_path: Path = candidate,
            ) -> str:
                return render_comparison_html(
                    build_comparison_html_input(
                        current_comparison,
                        baseline_path,
                        candidate_path,
                    )
                )

            report_ms, report_peak, html = _measure(
                render_single_html
            )
            comparison_html_ms, comparison_html_peak, comparison_html = _measure(
                render_before_after_html
            )
            html_mb = len(html) / 1024 / 1024
            comparison_html_mb = len(comparison_html) / 1024 / 1024

        print(
            f"{size},{artifact_mb:.3f},{load_ms:.1f},{analyze_ms:.1f},"
            f"{compare_ms:.1f},{report_ms:.1f},{comparison_html_ms:.1f},"
            f"{html_mb:.3f},{comparison_html_mb:.3f},"
            f"{max(load_peak, analyze_peak, compare_peak, report_peak, comparison_html_peak):.1f}"
        )


def _checkpoint_stress(output_dir: Path, sizes: list[int]) -> None:
    print(
        "spans,capture_ms,artifact_mb,checkpoint_count,checkpoint_p50_ms,"
        "checkpoint_p95_ms,checkpoint_max_ms,load_ms,analyze_ms,doctor_ms,peak_mb"
    )
    for size in sizes:
        tracemalloc.start()
        started = time.perf_counter()
        output, checkpoint_latencies = _run_checkpoint_capture(output_dir, size)
        capture_ms = (time.perf_counter() - started) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        def load_checkpoint_artifact(path: Path = output) -> ExperimentArtifact:
            return load_artifact(path)

        def analyze_checkpoint_artifact(path: Path = output) -> list[AnalysisReport]:
            return [analyze_run(run) for run in load_artifact(path).runs_for_comparison()]

        def doctor_checkpoint_artifact(path: Path = output) -> object:
            return assess_path(path)

        load_ms, _, _ = _measure(load_checkpoint_artifact)
        analyze_ms, _, _ = _measure(analyze_checkpoint_artifact)
        doctor_ms, _, _ = _measure(doctor_checkpoint_artifact)
        ordered = sorted(checkpoint_latencies)
        p50 = ordered[len(ordered) // 2] if ordered else 0.0
        p95 = ordered[int(len(ordered) * 0.95) - 1] if ordered else 0.0
        print(
            f"{size},{capture_ms:.1f},{_tree_size_mb(output):.3f},"
            f"{len(ordered)},{p50:.1f},{p95:.1f},"
            f"{max(ordered) if ordered else 0.0:.1f},"
            f"{load_ms:.1f},{analyze_ms:.1f},{doctor_ms:.1f},"
            f"{peak / 1024 / 1024:.1f}"
        )


def _run_checkpoint_capture(output_dir: Path, size: int) -> tuple[Path, list[float]]:
    output = output_dir / f"capture-{size}"
    latencies: list[float] = []
    with ExperimentSession(
        output_path=output,
        artifact_id=f"capture-{size}",
        workload_id=f"capture-{size}",
        expected_task_count=size,
        checkpoint_interval=250,
    ) as experiment:
        original_flush = experiment.flush

        def timed_flush(*, status: str = "PARTIAL") -> ExperimentArtifact:
            started = time.perf_counter()
            result = original_flush(status=status)
            latencies.append((time.perf_counter() - started) * 1000)
            return result

        experiment.flush = timed_flush  # type: ignore[method-assign]
        for index in range(size):
            task_id = f"task-{index}"
            with trace_run(task_id=task_id):
                with trace_llm(
                    components={"user": f"task {index}"},
                    llm_call_id=f"llm-{index}",
                ) as call:
                    call.record_response(input_tokens=5, output_tokens=1)
                if index % 5 == 0:
                    with trace_tool("lookup", tool_call_id=f"tool-{index}") as tool:
                        tool.record_output({"ok": True})
            experiment.record_task_result(
                task_id=task_id,
                passed=True,
                quality_score=1.0,
                status="COMPLETE",
            )
    return output, latencies


def _save_artifact(path: Path, run_id: str, size: int, tool_every: int) -> Path:
    run = _scale_run(run_id, size, tool_every)
    report = analyze_run(run)
    artifact = ExperimentArtifact.from_analysis(
        report,
        artifact_id=run_id,
        workload_id="scale",
        task_results=[
            TaskResult(
                task_id="scale",
                passed=True,
                quality_score=1.0,
                agent_run_ids=[run_id],
            )
        ],
        quality_metrics=[
            QualityMetric(name="mean_score", value=1.0, tolerance=0.05),
            QualityMetric(name="pass_rate", value=1.0, aggregation="rate", tolerance=0.10),
        ],
        summary={"llm_calls": size},
        backend="fixture",
        model="fixture",
    )
    artifact.save(path)
    return path


def _scale_run(run_id: str, size: int, tool_every: int) -> AgentRun:
    steps: list[dict[str, Any]] = []
    serving: list[dict[str, Any]] = []
    tool_text = " ".join(f"t{index}" for index in range(80))
    for index in range(size):
        prompt: list[dict[str, Any]] = [
            {"name": "system", "text": "You are careful."},
            {"name": "user", "text": f"task {index}"},
        ]
        if index % tool_every == 0:
            prompt.append(
                {
                    "name": "tool_result",
                    "text": tool_text,
                    "metadata": {"source_tool_call_ids": [f"tool-{index}"]},
                }
            )
        step: dict[str, Any] = {
            "agent_step_id": f"step-{index}",
            "llm_calls": [
                {
                    "llm_call_id": f"llm-{index}",
                    "llm_request_id": f"req-{index}",
                    "model": "fixture",
                    "prompt": prompt,
                    "input_tokens": 120 + (80 if index % tool_every == 0 else 0),
                    "output_tokens": 10,
                    "metadata": {"latency_ms": 2.0},
                }
            ],
        }
        if index % tool_every == 0:
            step["tool_calls"] = [
                {
                    "tool_call_id": f"tool-{index}",
                    "name": "lookup",
                    "latency_ms": 1.0,
                    "output": tool_text,
                }
            ]
        steps.append(step)
        serving.append(
            {
                "serving_request_id": f"srv-{index}",
                "llm_request_id": f"req-{index}",
                "queue_latency_ms": 1.0,
                "prefill_path_latency_ms": 5.0,
                "decode_latency_ms": 2.0,
                "input_tokens": 120,
                "output_tokens": 10,
                "prefix_cache_hit_tokens": 20,
                "prefix_cache_miss_tokens": 100,
            }
        )
    return parse_agentperf_trace(
        {
            "schema_version": "agentperf.trace.v1",
            "agent_run": {
                "agent_run_id": run_id,
                "metadata": {"task_id": run_id, "quality": {"score": 1.0, "passed": True}},
                "steps": steps,
            },
            "serving_requests": serving,
        }
    )


def _measure(function: Callable[[], T]) -> tuple[float, float, T]:
    tracemalloc.start()
    started = time.perf_counter()
    result = function()
    elapsed_ms = (time.perf_counter() - started) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed_ms, peak / 1024 / 1024, result


def _tree_size_mb(path: Path) -> float:
    return sum(child.stat().st_size for child in path.rglob("*") if child.is_file()) / 1024 / 1024


if __name__ == "__main__":
    raise SystemExit(main())
