from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict, dataclass
from functools import partial
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentperf import __version__
from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.comparison import compare_paths
from agentperf.completeness import assess_path
from agentperf.correlation.correlator import TraceCorrelator
from agentperf.detectors.base import Detector, DetectorContext
from agentperf.detectors.context_duplication import ContextDuplicationDetector
from agentperf.detectors.prefill import PrefillBottleneckDetector
from agentperf.detectors.prefix_cache import PrefixCacheOpportunityDetector
from agentperf.detectors.tool_output_bloat import ToolOutputBloatDetector
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import TraceRecorder, trace_llm, trace_run, trace_tool
from agentperf.regression import evaluate_regression_policy, parse_regression_policy
from agentperf.reporters.html import write_html_report
from agentperf.schema.regression import RegressionPolicy
from agentperf.schema.trace import AgentRun
from scripts.generate_scale_fixture import ScaleFixtureConfig, save_scale_artifact


@dataclass(frozen=True)
class TimingSample:
    wall_ms: float
    cpu_ms: float
    peak_memory_mb: float


@dataclass(frozen=True)
class BenchmarkRecord:
    case: str
    tasks: int
    llm_calls: int
    tool_calls: int
    component_bytes: int
    artifact_bytes: int | None
    report_bytes: int | None
    wall_ms_median: float
    wall_ms_p95: float
    cpu_ms_median: float
    peak_memory_mb_median: float
    repetitions: int
    metadata: dict[str, Any]


def run_benchmark(
    *,
    output: Path,
    call_counts: list[int],
    repetitions: int,
    warmups: int,
    max_report_calls: int,
) -> dict[str, Any]:
    records: list[BenchmarkRecord] = []
    with tempfile.TemporaryDirectory(prefix="agentperf-m21-") as tempdir:
        root = Path(tempdir)
        records.extend(
            instrumentation_overhead(
                repetitions=repetitions,
                warmups=warmups,
                root=root / "instrumentation",
            )
        )
        for call_count in call_counts:
            fixture = _make_fixture(root / f"scale-{call_count}", call_count=call_count)
            artifact = load_artifact(fixture)
            run = artifact.runs_for_comparison()[0]
            report_path = root / f"report-{call_count}.html"
            records.append(
                measure_case(
                    "analyze",
                    artifact=artifact,
                    report_path=None,
                    repetitions=repetitions,
                    warmups=warmups,
                    func=partial(analyze_run, run),
                )
            )
            records.append(
                measure_case(
                    "doctor",
                    artifact=artifact,
                    report_path=None,
                    repetitions=repetitions,
                    warmups=warmups,
                    func=partial(assess_path, fixture),
                )
            )
            if call_count <= max_report_calls:
                records.append(
                    measure_case(
                        "html_report",
                        artifact=artifact,
                        report_path=report_path,
                        repetitions=max(1, min(repetitions, 3)),
                        warmups=min(warmups, 1),
                        func=partial(write_html_report, fixture, report_path),
                    )
                )
            records.extend(
                detector_phase_records(
                    run,
                    artifact=artifact,
                    repetitions=repetitions,
                    warmups=warmups,
                )
            )

        for task_count in [1, 10, 100]:
            baseline_path = _make_fixture(
                root / f"compare-baseline-{task_count}",
                call_count=task_count * 5,
                tasks=task_count,
                artifact_id=f"compare-baseline-{task_count}",
                variant="baseline",
            )
            candidate_path = _make_fixture(
                root / f"compare-candidate-{task_count}",
                call_count=task_count * 5,
                tasks=task_count,
                artifact_id=f"compare-candidate-{task_count}",
                variant="candidate",
                tool_result_tokens=20,
            )
            baseline_artifact = load_artifact(baseline_path)
            records.append(
                measure_case(
                    "compare",
                    artifact=baseline_artifact,
                    report_path=None,
                    repetitions=repetitions,
                    warmups=warmups,
                    func=partial(compare_paths, baseline_path, candidate_path),
                )
            )
            policy = parse_regression_policy(
                {
                    "schema_version": 1,
                    "quality": {"mean_score": {"max_drop": 0.05}},
                    "performance": {
                        "component_total_processed_tokens": {"max_increase_percent": 10},
                    },
                    "task_coverage": {"require_same_tasks": False, "allow_partial": False},
                }
            )
            records.append(
                measure_case(
                    "check",
                    artifact=baseline_artifact,
                    report_path=None,
                    repetitions=repetitions,
                    warmups=warmups,
                    func=partial(
                        _check_paths,
                        baseline_path,
                        candidate_path,
                        policy,
                    ),
                )
            )

    result = {
        "environment": environment_metadata(),
        "methodology": {
            "warmups": warmups,
            "repetitions": repetitions,
            "memory": "Python tracemalloc peak allocations during measured callable",
            "wall_clock": "time.perf_counter",
            "cpu": "time.process_time",
        },
        "records": [asdict(record) for record in records],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def instrumentation_overhead(
    *,
    repetitions: int,
    warmups: int,
    root: Path,
) -> list[BenchmarkRecord]:
    tasks = 20
    calls_per_task = 10
    tool_calls_per_task = 2
    records: list[BenchmarkRecord] = []
    records.append(
        _measure_instrumentation_case(
            "instrumentation_off",
            tasks=tasks,
            calls_per_task=calls_per_task,
            tool_calls_per_task=tool_calls_per_task,
            repetitions=repetitions,
            warmups=warmups,
            func=lambda: _run_uninstrumented(tasks, calls_per_task, tool_calls_per_task),
        )
    )
    records.append(
        _measure_instrumentation_case(
            "instrumentation_minimal",
            tasks=tasks,
            calls_per_task=calls_per_task,
            tool_calls_per_task=tool_calls_per_task,
            repetitions=repetitions,
            warmups=warmups,
            func=lambda: _run_instrumented(
                tasks,
                calls_per_task,
                tool_calls_per_task,
                components=False,
            ),
        )
    )
    records.append(
        _measure_instrumentation_case(
            "instrumentation_full",
            tasks=tasks,
            calls_per_task=calls_per_task,
            tool_calls_per_task=tool_calls_per_task,
            repetitions=repetitions,
            warmups=warmups,
            func=lambda: _run_instrumented(
                tasks,
                calls_per_task,
                tool_calls_per_task,
                components=True,
            ),
        )
    )
    records.append(
        _measure_instrumentation_case(
            "instrumentation_full_with_artifact",
            tasks=tasks,
            calls_per_task=calls_per_task,
            tool_calls_per_task=tool_calls_per_task,
            repetitions=max(1, min(repetitions, 3)),
            warmups=min(warmups, 1),
            func=lambda: _run_session_with_artifact(
                root / "session-artifact",
                tasks,
                calls_per_task,
                tool_calls_per_task,
            ),
        )
    )
    return records


def measure_case(
    case: str,
    *,
    artifact: ExperimentArtifact,
    report_path: Path | None,
    repetitions: int,
    warmups: int,
    func: Callable[[], object],
) -> BenchmarkRecord:
    samples = measure(func, repetitions=repetitions, warmups=warmups)
    run = artifact.runs_for_comparison()[0]
    artifact_bytes = _dir_size(_artifact_path_from_manifest(artifact))
    return _record(
        case,
        run=run,
        artifact_bytes=artifact_bytes,
        report_bytes=report_path.stat().st_size if report_path and report_path.exists() else None,
        samples=samples,
        repetitions=repetitions,
    )


def detector_phase_records(
    run: AgentRun,
    *,
    artifact: ExperimentArtifact,
    repetitions: int,
    warmups: int,
) -> list[BenchmarkRecord]:
    detectors: list[tuple[str, Callable[[], object]]] = []

    def correlate() -> DetectorContext:
        correlation = TraceCorrelator().correlate(run)
        return DetectorContext(run=run, correlation=correlation)

    context = correlate()
    detector_instances: list[Detector] = [
        ContextDuplicationDetector(),
        ToolOutputBloatDetector(),
        PrefixCacheOpportunityDetector(),
        PrefillBottleneckDetector(),
    ]
    detectors.append(("phase_correlate", correlate))
    for detector in detector_instances:
        detectors.append(
            (
                f"phase_detector_{detector.__class__.__name__}",
                partial(_detect, detector, context),
            )
        )

    records = []
    for name, func in detectors:
        samples = measure(func, repetitions=repetitions, warmups=warmups)
        records.append(
            _record(
                name,
                run=run,
                artifact_bytes=_dir_size(_artifact_path_from_manifest(artifact)),
                report_bytes=None,
                samples=samples,
                repetitions=repetitions,
            )
        )
    return records


def _check_paths(baseline_path: Path, candidate_path: Path, policy: RegressionPolicy) -> object:
    return evaluate_regression_policy(compare_paths(baseline_path, candidate_path), policy)


def _detect(detector: Detector, context: DetectorContext) -> object:
    return detector.detect(context)


def measure(
    func: Callable[[], object],
    *,
    repetitions: int,
    warmups: int,
) -> list[TimingSample]:
    for _ in range(warmups):
        func()
    samples: list[TimingSample] = []
    for _ in range(repetitions):
        tracemalloc.start()
        start_wall = time.perf_counter()
        start_cpu = time.process_time()
        func()
        cpu_ms = (time.process_time() - start_cpu) * 1000
        wall_ms = (time.perf_counter() - start_wall) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        samples.append(
            TimingSample(
                wall_ms=wall_ms,
                cpu_ms=cpu_ms,
                peak_memory_mb=peak / (1024 * 1024),
            )
        )
    return samples


def _make_fixture(
    output: Path,
    *,
    call_count: int,
    tasks: int | None = None,
    artifact_id: str | None = None,
    variant: str = "baseline",
    tool_result_tokens: int = 50,
) -> Path:
    if call_count <= 0:
        resolved_tasks = 0 if tasks is None else tasks
        calls_per_task = 0
    else:
        resolved_tasks = tasks or max(1, min(call_count, max(1, call_count // 10)))
        calls_per_task = max(1, call_count // resolved_tasks)
    config = ScaleFixtureConfig(
        tasks=resolved_tasks,
        llm_calls_per_task=calls_per_task,
        tool_calls_per_task=2,
        system_tokens=40,
        user_tokens=20,
        history_tokens_per_step=5,
        tool_result_tokens=tool_result_tokens,
        retrieved_context_tokens=25,
        serving_telemetry=True,
        request_ids=True,
        output=output,
        artifact_id=artifact_id or f"scale-{call_count}",
        workload_id=f"m21-scale-{call_count}",
        variant=variant,
    )
    save_scale_artifact(config)
    return output


def _measure_instrumentation_case(
    case: str,
    *,
    tasks: int,
    calls_per_task: int,
    tool_calls_per_task: int,
    repetitions: int,
    warmups: int,
    func: Callable[[], object],
) -> BenchmarkRecord:
    samples = measure(func, repetitions=repetitions, warmups=warmups)
    llm_calls = tasks * calls_per_task
    tool_calls = tasks * tool_calls_per_task
    return BenchmarkRecord(
        case=case,
        tasks=tasks,
        llm_calls=llm_calls,
        tool_calls=tool_calls,
        component_bytes=0,
        artifact_bytes=None,
        report_bytes=None,
        wall_ms_median=_median([sample.wall_ms for sample in samples]),
        wall_ms_p95=_p95([sample.wall_ms for sample in samples]),
        cpu_ms_median=_median([sample.cpu_ms for sample in samples]),
        peak_memory_mb_median=_median([sample.peak_memory_mb for sample in samples]),
        repetitions=repetitions,
        metadata={
            "spans": tasks + llm_calls + tool_calls,
            "per_span_wall_us": _median([sample.wall_ms for sample in samples])
            * 1000
            / max(1, tasks + llm_calls + tool_calls),
        },
    )


def _record(
    case: str,
    *,
    run: AgentRun,
    artifact_bytes: int | None,
    report_bytes: int | None,
    samples: list[TimingSample],
    repetitions: int,
) -> BenchmarkRecord:
    component_bytes = sum(
        len(component.text.encode("utf-8"))
        for call in run.llm_calls
        for component in call.prompt_components
    )
    return BenchmarkRecord(
        case=case,
        tasks=_task_count(run),
        llm_calls=len(run.llm_calls),
        tool_calls=len(run.tool_calls),
        component_bytes=component_bytes,
        artifact_bytes=artifact_bytes,
        report_bytes=report_bytes,
        wall_ms_median=_median([sample.wall_ms for sample in samples]),
        wall_ms_p95=_p95([sample.wall_ms for sample in samples]),
        cpu_ms_median=_median([sample.cpu_ms for sample in samples]),
        peak_memory_mb_median=_median([sample.peak_memory_mb for sample in samples]),
        repetitions=repetitions,
        metadata={},
    )


def _run_uninstrumented(tasks: int, calls_per_task: int, tool_calls_per_task: int) -> int:
    total = 0
    for task_index in range(tasks):
        total += task_index
        for tool_index in range(tool_calls_per_task):
            total += len(f"tool-{task_index}-{tool_index}")
        for call_index in range(calls_per_task):
            total += len(f"prompt-{task_index}-{call_index}")
    return total


def _run_instrumented(
    tasks: int,
    calls_per_task: int,
    tool_calls_per_task: int,
    *,
    components: bool,
) -> AgentRun:
    recorder = TraceRecorder(agent_run_id="instrumented", trace_id="instrumented-trace")
    with recorder.as_current():
        for task_index in range(tasks):
            with trace_run(task_id=f"task-{task_index:04d}"):
                for tool_index in range(tool_calls_per_task):
                    with trace_tool(f"tool-{tool_index}") as tool:
                        tool.record_output(f"tool output {task_index} {tool_index}")
                for call_index in range(calls_per_task):
                    prompt = (
                        {
                            "system": "stable system prompt",
                            "user": f"task {task_index} call {call_index}",
                            "history": "prior context",
                        }
                        if components
                        else None
                    )
                    with trace_llm(model="fake-model", components=prompt) as call:
                        call.record_response(
                            output="ok",
                            input_tokens=12 if components else None,
                            output_tokens=2,
                            request_id=f"req-{task_index}-{call_index}",
                        )
    return recorder.finish()


def _run_session_with_artifact(
    output: Path,
    tasks: int,
    calls_per_task: int,
    tool_calls_per_task: int,
) -> object:
    if output.exists():
        _remove_tree(output)
    with ExperimentSession(
        output_path=output,
        artifact_id="instrumentation-session",
        workload_id="instrumentation-session",
        expected_task_count=tasks,
        framework="framework-free",
        model="fake-model",
    ) as experiment:
        for task_index in range(tasks):
            with trace_run(task_id=f"task-{task_index:04d}"):
                for tool_index in range(tool_calls_per_task):
                    with trace_tool(f"tool-{tool_index}") as tool:
                        tool.record_output(f"tool output {task_index} {tool_index}")
                for call_index in range(calls_per_task):
                    with trace_llm(
                        model="fake-model",
                        components={
                            "system": "stable system prompt",
                            "user": f"task {task_index} call {call_index}",
                            "history": "prior context",
                        },
                    ) as call:
                        call.record_response(
                            output="ok",
                            input_tokens=12,
                            output_tokens=2,
                            request_id=f"req-{task_index}-{call_index}",
                        )
            experiment.record_task_result(
                task_id=f"task-{task_index:04d}",
                passed=True,
                quality_score=1.0,
                status="COMPLETE",
            )
    return output


def _remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()


def _dir_size(path: Path | None) -> int | None:
    if path is None or not path.exists():
        return None
    total = 0
    for root, _, files in os.walk(path):
        for filename in files:
            total += (Path(root) / filename).stat().st_size
    return total


def _artifact_path_from_manifest(artifact: ExperimentArtifact) -> Path | None:
    raw = artifact.manifest.metadata.get("scale_fixture")
    if isinstance(raw, dict) and isinstance(raw.get("output"), str):
        return Path(raw["output"])
    return None


def _task_count(run: AgentRun) -> int:
    value = run.metadata.get("task_count")
    return int(value) if isinstance(value, int) else len(run.steps)


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 4)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return round(ordered[index], 4)


def environment_metadata() -> dict[str, str]:
    return {
        "agentperf_version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "commit": _git_commit(),
    }


def _git_commit() -> str:
    head = Path(".git/HEAD")
    if not head.exists():
        return "unknown"
    text = head.read_text(encoding="utf-8").strip()
    if not text.startswith("ref: "):
        return text
    ref = Path(".git") / text.removeprefix("ref: ")
    return ref.read_text(encoding="utf-8").strip() if ref.exists() else "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AgentPerf M21 scale benchmarks.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--call-counts",
        default="10,100,1000",
        help="Comma-separated LLM call counts for scale fixtures.",
    )
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument(
        "--max-report-calls",
        type=int,
        default=1000,
        help="Skip HTML report generation above this call count.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    call_counts = [int(value) for value in args.call_counts.split(",") if value.strip()]
    result = run_benchmark(
        output=args.output,
        call_counts=call_counts,
        repetitions=args.repetitions,
        warmups=args.warmups,
        max_report_calls=args.max_report_calls,
    )
    print(f"Wrote benchmark results: {args.output}")
    print(f"records={len(result['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
