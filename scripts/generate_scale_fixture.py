from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentperf.artifacts import ExperimentArtifact
from agentperf.schema.artifacts import QualityMetric, TaskResult
from agentperf.schema.trace import (
    AgentRun,
    AgentStep,
    LLMCall,
    PromptComponent,
    ServingRequest,
    ToolCall,
)


@dataclass(frozen=True)
class ScaleFixtureConfig:
    tasks: int = 10
    llm_calls_per_task: int = 10
    tool_calls_per_task: int = 2
    system_tokens: int = 40
    user_tokens: int = 20
    history_tokens_per_step: int = 5
    tool_result_tokens: int = 50
    retrieved_context_tokens: int = 0
    serving_telemetry: bool = False
    request_ids: bool = True
    component_attribution: str = "full"
    task_failure_rate: float = 0.0
    output: Path = Path("/tmp/agentperf-scale-fixture")
    artifact_id: str = "scale-fixture"
    workload_id: str = "scale-fixture"
    variant: str = "baseline"

    @property
    def llm_calls(self) -> int:
        return self.tasks * self.llm_calls_per_task

    @property
    def tool_calls(self) -> int:
        return self.tasks * self.tool_calls_per_task


def build_scale_run(config: ScaleFixtureConfig) -> tuple[AgentRun, list[TaskResult]]:
    """Build a deterministic AgentRun for offline scale characterization."""

    base = datetime(2026, 1, 1, tzinfo=UTC)
    steps: list[AgentStep] = []
    serving_requests: list[ServingRequest] = []
    task_results: list[TaskResult] = []
    run_id = f"{config.artifact_id}-run"
    trace_id = f"{config.artifact_id}-trace"
    system_text = _tokens("system", config.system_tokens)
    tool_schema_text = _tokens("schema", 24)
    shared_retrieved_text = _tokens("retrieved", config.retrieved_context_tokens)

    for task_index in range(config.tasks):
        task_id = f"task-{task_index + 1:04d}"
        step_start = base + timedelta(milliseconds=task_index * 1000)
        tool_calls = [
            ToolCall(
                tool_call_id=f"tool-{task_index + 1:04d}-{tool_index + 1:02d}",
                name=f"lookup_{tool_index + 1}",
                trace_id=trace_id,
                span_id=f"span-tool-{task_index + 1:04d}-{tool_index + 1:02d}",
                parent_span_id=f"span-task-{task_index + 1:04d}",
                started_at=_iso(step_start + timedelta(milliseconds=tool_index * 10)),
                ended_at=_iso(step_start + timedelta(milliseconds=tool_index * 10 + 3)),
                latency_ms=3.0,
                output=_tokens(
                    f"toolout_{task_index + 1}_{tool_index + 1}",
                    config.tool_result_tokens,
                ),
                metadata={"status": "COMPLETE"},
            )
            for tool_index in range(config.tool_calls_per_task)
        ]
        llm_calls: list[LLMCall] = []
        for call_index in range(config.llm_calls_per_task):
            llm_call_id = f"llm-{task_index + 1:04d}-{call_index + 1:03d}"
            request_id = f"req-{task_index + 1:04d}-{call_index + 1:03d}"
            prompt_components = _prompt_components(
                config,
                task_index=task_index,
                call_index=call_index,
                system_text=system_text,
                tool_schema_text=tool_schema_text,
                retrieved_text=shared_retrieved_text,
                tool_calls=tool_calls,
            )
            input_tokens = sum(_component_token_count(component) for component in prompt_components)
            started = step_start + timedelta(milliseconds=20 + call_index * 20)
            ended = started + timedelta(milliseconds=8)
            llm_calls.append(
                LLMCall(
                    llm_call_id=llm_call_id,
                    trace_id=trace_id,
                    span_id=f"span-{llm_call_id}",
                    parent_span_id=f"span-task-{task_index + 1:04d}",
                    agent_step_id=f"step-{task_index + 1:04d}",
                    llm_request_id=request_id if config.request_ids else None,
                    serving_request_id=request_id if config.request_ids else None,
                    model="deterministic-scale-model",
                    provider="deterministic",
                    backend="scale-fixture",
                    started_at=_iso(started),
                    ended_at=_iso(ended),
                    prompt_components=prompt_components,
                    input_tokens=input_tokens,
                    output_tokens=16,
                    tokenization_mode="APPROXIMATE",
                    metadata={"latency_ms": 8.0, "task_id": task_id},
                )
            )
            if config.serving_telemetry:
                cached = max(0, int(input_tokens * 0.25))
                miss = max(0, input_tokens - cached)
                serving_requests.append(
                    ServingRequest(
                        serving_request_id=request_id,
                        llm_request_id=request_id,
                        model="deterministic-scale-model",
                        backend="scale-fixture",
                        started_at=_iso(started),
                        ended_at=_iso(ended),
                        queue_latency_ms=1.0,
                        prefill_path_latency_ms=5.0,
                        decode_latency_ms=2.0,
                        ttft_ms=7.0,
                        input_tokens=input_tokens,
                        output_tokens=16,
                        prefix_cache_hit_tokens=cached,
                        prefix_cache_miss_tokens=miss,
                        tokenization_mode="APPROXIMATE",
                        metadata={"source": "deterministic_scale_fixture"},
                    )
                )
        steps.append(
            AgentStep(
                agent_step_id=f"step-{task_index + 1:04d}",
                trace_id=trace_id,
                span_id=f"span-task-{task_index + 1:04d}",
                started_at=_iso(step_start),
                ended_at=_iso(step_start + timedelta(milliseconds=200)),
                llm_calls=llm_calls,
                tool_calls=tool_calls,
                metadata={"task_id": task_id, "workload_item_id": task_id},
            )
        )
        failed = _task_failed(task_index, config.task_failure_rate)
        task_results.append(
            TaskResult(
                task_id=task_id,
                passed=not failed,
                quality_score=0.0 if failed else 1.0,
                duration_ms=200.0,
                client_latency_ms=200.0,
                status="FAILED" if failed else "COMPLETE",
                agent_run_ids=[run_id],
            )
        )

    run = AgentRun(
        agent_run_id=run_id,
        trace_id=trace_id,
        name=config.workload_id,
        started_at=_iso(base),
        ended_at=_iso(base + timedelta(milliseconds=config.tasks * 1000 + 200)),
        steps=steps,
        serving_requests=serving_requests,
        synthetic=True,
        schema_version="agentperf.trace.v1",
        metadata={
            "workload_id": config.workload_id,
            "task_count": config.tasks,
            "fixture": "m21_scale",
            "variant": config.variant,
        },
    )
    return run, task_results


def save_scale_artifact(config: ScaleFixtureConfig) -> ExperimentArtifact:
    run, task_results = build_scale_run(config)
    artifact = ExperimentArtifact.from_run(
        run,
        artifact_id=config.artifact_id,
        workload_id=config.workload_id,
        task_results=task_results,
        task_count=config.tasks,
        quality_metrics=[
            QualityMetric(
                name="mean_score",
                value=sum(task.quality_score or 0 for task in task_results)
                / max(1, len(task_results)),
                aggregation="mean",
            ),
            QualityMetric(
                name="pass_rate",
                value=sum(1 for task in task_results if task.passed) / max(1, len(task_results)),
                aggregation="rate",
            ),
        ],
        environment={"fixture": "m21_scale", "deterministic": True},
        summary={
            "tasks": config.tasks,
            "llm_calls": config.llm_calls,
            "tool_calls": config.tool_calls,
            "serving_telemetry": config.serving_telemetry,
            "component_attribution": config.component_attribution,
        },
        framework="framework-free",
        agent_name="m21-scale-fixture",
        backend="scale-fixture" if config.serving_telemetry else None,
        model="deterministic-scale-model",
        serving_telemetry=config.serving_telemetry,
        metadata={"scale_fixture": asdict(config) | {"output": str(config.output)}},
    )
    artifact.save(config.output)
    return artifact


def _prompt_components(
    config: ScaleFixtureConfig,
    *,
    task_index: int,
    call_index: int,
    system_text: str,
    tool_schema_text: str,
    retrieved_text: str,
    tool_calls: list[ToolCall],
) -> list[PromptComponent]:
    if config.component_attribution == "none":
        return []
    components = [
        PromptComponent("system", system_text),
        PromptComponent("tool_schema", tool_schema_text),
        PromptComponent("user", _tokens(f"user_{task_index + 1}", config.user_tokens)),
    ]
    history_tokens = config.history_tokens_per_step * call_index
    if history_tokens:
        components.append(PromptComponent("history", _tokens("history", history_tokens)))
    if retrieved_text:
        components.append(PromptComponent("retrieved_context", retrieved_text))
    if tool_calls and config.tool_result_tokens:
        source_tool = tool_calls[call_index % len(tool_calls)]
        components.append(
            PromptComponent(
                "tool_result",
                str(source_tool.output),
                metadata={"source_tool_call_ids": [source_tool.tool_call_id]},
            )
        )
    if config.component_attribution == "partial" and (task_index + call_index) % 3 == 0:
        return []
    return components


def _tokens(prefix: str, count: int) -> str:
    if count <= 0:
        return ""
    return " ".join(f"{prefix}_{index:05d}" for index in range(count))


def _component_token_count(component: PromptComponent) -> int:
    return len(component.text.split()) if component.text else 0


def _task_failed(task_index: int, failure_rate: float) -> bool:
    if failure_rate <= 0:
        return False
    period = max(1, round(1 / failure_rate))
    return (task_index + 1) % period == 0


def _iso(value: datetime) -> str:
    return value.isoformat()


def parse_args() -> ScaleFixtureConfig:
    parser = argparse.ArgumentParser(description="Generate deterministic AgentPerf scale fixtures.")
    parser.add_argument("--tasks", type=int, default=10)
    parser.add_argument("--llm-calls-per-task", type=int, default=10)
    parser.add_argument("--tool-calls-per-task", type=int, default=2)
    parser.add_argument("--system-tokens", type=int, default=40)
    parser.add_argument("--user-tokens", type=int, default=20)
    parser.add_argument("--history-tokens-per-step", type=int, default=5)
    parser.add_argument("--tool-result-tokens", type=int, default=50)
    parser.add_argument("--retrieved-context-tokens", type=int, default=0)
    parser.add_argument("--serving-telemetry", action="store_true")
    parser.add_argument("--no-request-ids", action="store_true")
    parser.add_argument(
        "--component-attribution",
        choices=["full", "partial", "none"],
        default="full",
    )
    parser.add_argument("--task-failure-rate", type=float, default=0.0)
    parser.add_argument("--artifact-id", default="scale-fixture")
    parser.add_argument("--workload-id", default="scale-fixture")
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    return ScaleFixtureConfig(
        tasks=args.tasks,
        llm_calls_per_task=args.llm_calls_per_task,
        tool_calls_per_task=args.tool_calls_per_task,
        system_tokens=args.system_tokens,
        user_tokens=args.user_tokens,
        history_tokens_per_step=args.history_tokens_per_step,
        tool_result_tokens=args.tool_result_tokens,
        retrieved_context_tokens=args.retrieved_context_tokens,
        serving_telemetry=args.serving_telemetry,
        request_ids=not args.no_request_ids,
        component_attribution=args.component_attribution,
        task_failure_rate=args.task_failure_rate,
        artifact_id=args.artifact_id,
        workload_id=args.workload_id,
        variant=args.variant,
        output=args.output,
    )


def main() -> int:
    config = parse_args()
    artifact = save_scale_artifact(config)
    print(f"Wrote AgentPerf scale artifact: {config.output}")
    print(f"tasks={config.tasks} llm_calls={config.llm_calls} tool_calls={config.tool_calls}")
    print(f"artifact_id={artifact.manifest.artifact_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
