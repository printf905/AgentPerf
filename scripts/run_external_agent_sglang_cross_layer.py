#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact
from agentperf.backends.sglang import SGLangTelemetryProvider
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.openai_agents import (
    AgentPerfModelWrapper,
    OpenAIAgentsTraceProcessor,
)
from agentperf.integrations.openai_compatible import (
    OpenAICompatibleRequestRecorder,
    build_sglang_recording_from_agent_run,
    correlation_summary,
)
from agentperf.reporters.html import write_html_report
from agentperf.reporters.terminal import render_report
from agentperf.schema.artifacts import QualityMetric, TaskResult

try:
    from agents import Agent, ModelSettings, Runner
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
    from agents.tracing import set_trace_processors
    from openai import AsyncOpenAI
except ImportError as exc:  # pragma: no cover - optional dependency boundary
    raise SystemExit(
        "Install the optional integration dependency first: "
        'pip install -e ".[openai-agents]"'
    ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run OpenAI Agents SDK + SGLang cross-layer validation."
    )
    parser.add_argument("--base-url", default="http://localhost:30000/v1")
    parser.add_argument("--model", default="agentperf-sglang-demo")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/m17_sglang"))
    parser.add_argument("--task-limit", type=int, default=5)
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--metrics-url",
        default=None,
        help="Optional SGLang Prometheus metrics URL, for example http://localhost:30000/metrics",
    )
    return asyncio.run(_run(parser.parse_args()))


async def _run(args: argparse.Namespace) -> int:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    tasks, lookup_policy, score_answer = _load_m5_support_triage()
    selected_tasks = tasks[: args.task_limit]
    request_recorder = OpenAICompatibleRequestRecorder()
    http_client = request_recorder.http_client(timeout=args.timeout)
    openai_client = AsyncOpenAI(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
        max_retries=0,
        http_client=http_client,
    )
    recorder = TraceRecorder(
        agent_run_id="m17-openai-agents-sglang-cross-layer",
        name="OpenAI Agents SDK support triage through SGLang",
        metadata={
            "framework": "openai-agents-python",
            "workload": "deterministic support triage",
            "task_count": len(selected_tasks),
            "backend": "sglang",
            "model": args.model,
        },
    )
    processor = OpenAIAgentsTraceProcessor(recorder, capture_function_spans=False)
    set_trace_processors([cast(Any, processor)])
    sdk_model = OpenAIChatCompletionsModel(
        model=args.model,
        openai_client=openai_client,
        strict_feature_validation=False,
    )
    model = AgentPerfModelWrapper(
        sdk_model,
        recorder,
        model_name=args.model,
        provider="openai-agents-python",
        request_id_factory=lambda llm_call_id: (
            f"agentperf-m17-sglang-{llm_call_id}-{uuid4().hex[:8]}"
        ),
        model_settings_transform=_force_lookup_policy_on_first_turn,
    )
    agent = Agent(
        name="Support Triage Agent",
        instructions=(
            "Classify the support request. Use lookup_policy before answering. "
            "Final answer format: ROUTE=<route>; POLICY=<policy id>; ACTION=<short action>."
        ),
        tools=[lookup_policy],
        model=model,
        model_settings=ModelSettings(
            temperature=0,
            max_tokens=128,
            parallel_tool_calls=False,
        ),
    )

    results: list[dict[str, Any]] = []
    try:
        with recorder.as_current():
            for task in selected_tasks:
                task_start = datetime.now(UTC)
                with recorder.step(str(task["id"]), metadata={"task_id": task["id"]}):
                    result = await Runner.run(agent, str(task["text"]))
                task_end = datetime.now(UTC)
                final = str(result.final_output)
                score = score_answer(final, task)
                results.append(
                    {
                        "task_id": task["id"],
                        "input": task["text"],
                        "expected_policy": task["expected_policy"],
                        "expected_route": task["expected_route"],
                        "answer": final,
                        "score": score,
                        "passed": score == 1.0,
                        "client_latency_ms": (
                            task_end - task_start
                        ).total_seconds()
                        * 1000,
                    }
                )
    finally:
        await openai_client.close()
        await http_client.aclose()

    agent_run = recorder.finish()
    server_metrics = await _fetch_sglang_metrics(args.metrics_url, args.timeout)
    environment = _environment(args, server_metrics)
    recording = build_sglang_recording_from_agent_run(
        agent_run=agent_run,
        captured_records=request_recorder.records,
        model=args.model,
        environment=environment,
    )
    for record in recording.get("records", []):
        if isinstance(record, dict) and server_metrics:
            record["server_metrics"] = server_metrics
    run = SGLangTelemetryProvider().build_run(recording)
    report = analyze_run(run)
    task_results = [
        TaskResult(
            task_id=str(item["task_id"]),
            execution_id=str(item["task_id"]),
            passed=bool(item["passed"]),
            quality_score=float(item["score"]),
            evaluator="support-triage-rule-v1",
            input_tokens=sum(
                call.input_tokens or 0
                for call in run.llm_calls
                if str(item["task_id"]) in str(call.agent_step_id or "")
            ),
            client_latency_ms=float(item["client_latency_ms"]),
            status="PASS" if item["passed"] else "FAIL",
            agent_run_ids=[run.agent_run_id],
        )
        for item in results
    ]
    pass_rate = (
        sum(1 for item in results if item["passed"]) / len(results)
        if results
        else 0.0
    )
    mean_score = (
        sum(float(item["score"]) for item in results) / len(results)
        if results
        else 0.0
    )
    quality_metrics = [
        QualityMetric(
            name="mean_score",
            value=mean_score,
            aggregation="mean",
            tolerance=0.05,
            metadata={"evaluator": "support-triage-rule-v1"},
        ),
        QualityMetric(
            name="pass_rate",
            value=pass_rate,
            aggregation="rate",
            tolerance=0.10,
            metadata={"evaluator": "support-triage-rule-v1"},
        ),
    ]
    summary = {
        "framework": "openai-agents-python",
        "agent": "Support Triage Agent",
        "backend": "sglang",
        "model": args.model,
        "tasks": len(selected_tasks),
        "llm_calls": len(agent_run.llm_calls),
        "tool_calls": len(agent_run.tool_calls),
        "serving_requests": len(run.serving_requests),
        **correlation_summary(recording, expected_llm_calls=len(agent_run.llm_calls)),
        "input_tokens": sum(call.input_tokens or 0 for call in run.llm_calls),
        "output_tokens": sum(call.output_tokens or 0 for call in run.llm_calls),
        "serving_timing": _serving_timing_summary(run.serving_requests),
        "mean_score": mean_score,
        "pass_rate": pass_rate,
        "findings": [finding.id for finding in report.findings],
        "material_finding": any(
            finding.severity in {"HIGH", "CRITICAL"} for finding in report.findings
        ),
        "trace_example": _trace_example(run.steps),
        "task_results": results,
    }
    artifact = ExperimentArtifact.from_analysis(
        report,
        artifact_id="m17-openai-agents-sglang",
        workload_id="m17-openai-agents-support-triage-sglang",
        task_results=task_results,
        quality_metrics=quality_metrics,
        environment=environment,
        summary=summary,
        framework="openai-agents-python",
        agent_name="Support Triage Agent",
        backend="sglang",
        model=args.model,
        serving_telemetry=bool(run.serving_requests),
    )

    processor.write_export(args.output_dir / "openai_agents_export.json")
    (args.output_dir / "agentperf_agent_trace.json").write_text(
        json.dumps({"agent_run": asdict(agent_run)}, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "sglang_recording.json").write_text(
        json.dumps(recording, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "unified_trace.json").write_text(
        json.dumps({"agent_run": asdict(run)}, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "unified_report.txt").write_text(
        render_report(report, show_provenance=True),
        encoding="utf-8",
    )
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    artifact_dir = args.output_dir / "artifact"
    artifact.save(artifact_dir)
    write_html_report(artifact_dir, args.output_dir / "agentperf_sglang_report.html")
    print(render_report(report, show_provenance=True))
    print(json.dumps(summary, indent=2))
    return 0


async def _fetch_sglang_metrics(metrics_url: str | None, timeout: float) -> dict[str, Any]:
    if metrics_url is None:
        return {}
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(metrics_url)
            response.raise_for_status()
        return _parse_prometheus_metrics(response.text)
    except Exception as exc:  # pragma: no cover - network/environment boundary
        return {"metrics_fetch_error": str(exc)}


def _parse_prometheus_metrics(text: str) -> dict[str, Any]:
    selected_prefixes = (
        "sglang:cache_hit_rate",
        "sglang:num_queue_reqs",
        "sglang:prompt_tokens_total",
        "sglang:generation_tokens_total",
        "sglang:time_to_first_token_seconds_count",
        "sglang:e2e_request_latency_seconds_count",
    )
    metrics: dict[str, Any] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith(selected_prefixes):
            continue
        name_and_labels, _, raw_value = line.rpartition(" ")
        if not name_and_labels or not raw_value:
            continue
        metric_name = name_and_labels.split("{", 1)[0]
        try:
            value: Any = float(raw_value)
        except ValueError:
            value = raw_value
        metrics[metric_name] = value
    metrics["metric_scope"] = "aggregate_snapshot"
    return metrics


def _serving_timing_summary(serving_requests: list[Any]) -> dict[str, float | None]:
    return {
        "queue_latency_ms": _sum_optional(
            [request.queue_latency_ms for request in serving_requests]
        ),
        "client_ttft_ms": _sum_optional([request.ttft_ms for request in serving_requests]),
        "generation_time_ms": _sum_optional(
            [request.decode_latency_ms for request in serving_requests]
        ),
        "time_per_output_token_ms_average": _mean_optional(
            [float(request.tpot_ms) for request in serving_requests if request.tpot_ms is not None]
        ),
        "cached_prompt_tokens": sum(
            int(request.prefix_cache_hit_tokens or 0) for request in serving_requests
        ),
    }


def _trace_example(steps: list[Any]) -> dict[str, Any]:
    for step in steps:
        if step.llm_calls and step.tool_calls:
            return {
                "agent_step_id": step.agent_step_id,
                "agent_span_id": step.span_id,
                "tool_span_ids": [tool.span_id for tool in step.tool_calls],
                "tool_call_ids": [tool.tool_call_id for tool in step.tool_calls],
                "llm_calls": [_call_example(call) for call in step.llm_calls],
            }
    llm_calls = [call for step in steps for call in step.llm_calls]
    tool_calls = [tool for step in steps for tool in step.tool_calls]
    if not llm_calls:
        return {}
    return {
        "agent_step_ids": [step.agent_step_id for step in steps[:4]],
        "tool_call_ids": [tool.tool_call_id for tool in tool_calls[:3]],
        "llm_calls": [_call_example(call) for call in llm_calls[:4]],
    }


def _call_example(call: Any) -> dict[str, Any]:
    return {
        "llm_call_id": call.llm_call_id,
        "llm_request_id": call.llm_request_id,
        "serving_request_id": call.serving_request_id,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
    }


def _environment(args: argparse.Namespace, server_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "sglang",
        "base_url": args.base_url,
        "metrics_url": args.metrics_url,
        "model": args.model,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "gpu": _detect_gpu(),
        "agentperf_version": "0.2.0",
        "telemetry_source": "OpenAI-compatible HTTP response body captured by httpx hook",
        "aggregate_server_metrics_recorded": bool(server_metrics),
        "tool_choice_control": (
            "lookup_policy forced only before the first tool result so SGLang/model "
            "configuration exercises the existing support-triage tool lifecycle"
        ),
    }


def _detect_gpu() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def _force_lookup_policy_on_first_turn(
    llm_call_id: str,
    input: Any,
    model_settings: Any,
    tools: list[Any],
) -> Any:
    del llm_call_id
    if not tools or _has_tool_result(input):
        return model_settings
    from dataclasses import replace

    extra_args = dict(getattr(model_settings, "extra_args", None) or {})
    extra_args["tool_choice"] = {"type": "function", "function": {"name": "lookup_policy"}}
    return replace(model_settings, extra_args=extra_args)


def _has_tool_result(input: Any) -> bool:
    if not isinstance(input, list):
        return False
    for item in input:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"function_call_output", "tool_call_output"}:
            return True
    return False


def _sum_optional(values: list[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None]
    if not known:
        return None
    return sum(known)


def _mean_optional(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _load_m5_support_triage() -> tuple[list[dict[str, str]], Any, Any]:
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from examples.external_agents.openai_agents_support_triage import (
        TASKS,
        lookup_policy,
        score_answer,
    )

    return TASKS, lookup_policy, score_answer


if __name__ == "__main__":
    raise SystemExit(main())
