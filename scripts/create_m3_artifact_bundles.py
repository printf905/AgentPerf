from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact
from agentperf.schema.artifacts import QualityMetric
from agentperf.schema.trace import parse_agentperf_trace


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create compact AgentPerf artifact bundles from recorded M3 results.",
    )
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    comparison = _read_json(args.source_root / "comparison.json")
    environment = _sanitize_environment(comparison.get("environment", {}))
    for strategy, output_name in (
        ("raw_full", "m3_raw_full"),
        ("dedup_only", "m3_dedup_only"),
    ):
        _write_strategy_bundle(
            args.source_root,
            args.output_root / output_name,
            strategy,
            comparison,
            environment,
        )
    return 0


def _write_strategy_bundle(
    source_root: Path,
    output_path: Path,
    strategy: str,
    comparison: dict[str, Any],
    environment: dict[str, Any],
) -> None:
    strategy_summary = comparison["strategies"][strategy]
    trace_data = _read_json(source_root / strategy / "normalized" / "trace.json")
    _sanitize_trace(trace_data)
    run = parse_agentperf_trace(trace_data)
    report = analyze_run(run)
    if output_path.exists():
        shutil.rmtree(output_path)
    artifact = ExperimentArtifact.from_analysis(
        report,
        artifact_id=f"m3-{strategy}",
        workload_id="m3-real-agent-context-waste",
        quality_metrics=[
            QualityMetric(
                name="mean_score",
                value=strategy_summary["correctness"]["mean_score"],
                aggregation="mean",
                tolerance=0.05,
                metadata={"source": "recorded_m3_comparison_json"},
            ),
            QualityMetric(
                name="pass_rate",
                value=strategy_summary["correctness"]["pass_rate"],
                aggregation="rate",
                tolerance=0.10,
                metadata={"source": "recorded_m3_comparison_json"},
            ),
        ],
        task_count=strategy_summary["questions"],
        environment=environment,
        summary={
            "source": "recorded_real_m3_quality_constrained_context_waste",
            "strategy": strategy,
            "task_count": strategy_summary["questions"],
            "input_tokens": strategy_summary["input_tokens"],
            "output_tokens": strategy_summary["output_tokens"],
            "tool_result_processed_tokens": strategy_summary["processed_tokens_by_component"][
                "tool_result"
            ],
            "ttft_p95_ms": strategy_summary["ttft_p95_ms"],
            "client_latency_p95_ms": strategy_summary["client_latency_p95_ms"],
            "task_level_quality_available": False,
            "quality_limitation": (
                "Historical M3 artifacts preserved aggregate mean score and pass rate, "
                "but not per-task quality rows."
            ),
        },
        framework="none",
        agent_name="m3-framework-free-research-agent",
        backend="vllm",
        model=environment.get("model"),
        serving_telemetry=True,
        created_at=comparison["created_at"],
        metadata={
            "recorded_real": True,
            "synthetic": False,
            "quality_granularity": "aggregate",
        },
    )
    artifact.save(output_path)


def _sanitize_trace(data: dict[str, Any]) -> None:
    metadata = data.get("agent_run", {}).get("metadata", {})
    if isinstance(metadata, dict):
        environment = metadata.get("environment")
        if isinstance(environment, dict):
            metadata["environment"] = _sanitize_environment(environment)


def _sanitize_environment(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    environment = dict(data)
    gpu = environment.get("gpu")
    if isinstance(gpu, str) and "UUID" in gpu:
        environment["gpu"] = gpu.split("(UUID", maxsplit=1)[0].strip()
    environment.pop("base_url", None)
    return environment


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
