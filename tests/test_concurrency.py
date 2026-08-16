from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentperf.artifacts import load_artifact
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import trace_llm, trace_run, trace_tool


def test_async_fanout_keeps_spans_attached_to_each_task_run(tmp_path: Path) -> None:
    output = tmp_path / "async-fanout"

    async def branch(task_id: str, delay: float) -> None:
        with trace_run(task_id=task_id):
            with trace_llm(
                components={"user": f"question for {task_id}"},
                llm_call_id=f"{task_id}-llm",
            ) as call:
                await asyncio.sleep(delay)
                call.record_response(input_tokens=10, output_tokens=2)
            with trace_tool("lookup", tool_call_id=f"{task_id}-tool") as tool:
                await asyncio.sleep(delay)
                tool.record_output({"task_id": task_id})
        experiment.record_task_result(
            task_id=task_id,
            passed=True,
            quality_score=1.0,
            status="COMPLETE",
        )

    async def run() -> None:
        await asyncio.gather(branch("task-a", 0.001), branch("task-b", 0.0))

    with ExperimentSession(
        output_path=output,
        artifact_id="async-fanout",
        workload_id="async-fanout",
        expected_task_count=2,
    ) as experiment:
        asyncio.run(run())

    artifact = load_artifact(output)
    run_artifact = artifact.runs[0]
    task_steps = {
        step.metadata["task_id"]: step
        for step in run_artifact.steps
        if step.metadata.get("instrumentation") == "agentperf.trace_run"
    }

    assert artifact.manifest.status == "COMPLETE"
    assert set(task_steps) == {"task-a", "task-b"}
    assert all(step.parent_span_id is None for step in task_steps.values())
    for task_id, step in task_steps.items():
        assert [call.llm_call_id for call in step.llm_calls] == [f"{task_id}-llm"]
        assert [call.tool_call_id for call in step.tool_calls] == [f"{task_id}-tool"]
        assert step.llm_calls[0].metadata["status"] == "COMPLETE"
        assert step.tool_calls[0].metadata["status"] == "COMPLETE"


def test_async_branch_exception_does_not_corrupt_sibling_run(tmp_path: Path) -> None:
    output = tmp_path / "async-exception"

    async def healthy_branch() -> None:
        with trace_run(task_id="healthy"), trace_llm(
            components={"user": "healthy"},
            llm_call_id="healthy-llm",
        ) as call:
            await asyncio.sleep(0.001)
            call.record_response(input_tokens=4, output_tokens=1)
        experiment.record_task_result(
            task_id="healthy",
            passed=True,
            quality_score=1.0,
            status="COMPLETE",
        )

    async def failing_branch() -> None:
        with (
            trace_run(task_id="failing"),
            pytest.raises(RuntimeError),
            trace_tool("broken-tool", tool_call_id="failing-tool"),
        ):
            await asyncio.sleep(0.0)
            raise RuntimeError("tool failed")
        experiment.record_task_result(
            task_id="failing",
            passed=False,
            quality_score=0.0,
            status="FAILED",
            error="RuntimeError: tool failed",
        )

    async def run() -> None:
        await asyncio.gather(healthy_branch(), failing_branch())

    with ExperimentSession(
        output_path=output,
        artifact_id="async-exception",
        workload_id="async-exception",
        expected_task_count=2,
    ) as experiment:
        asyncio.run(run())

    artifact = load_artifact(output)
    task_steps = {
        step.metadata["task_id"]: step
        for step in artifact.runs[0].steps
        if step.metadata.get("instrumentation") == "agentperf.trace_run"
    }

    assert artifact.manifest.status == "FAILED"
    assert task_steps["healthy"].llm_calls[0].llm_call_id == "healthy-llm"
    assert task_steps["healthy"].llm_calls[0].metadata["status"] == "COMPLETE"
    assert task_steps["failing"].tool_calls[0].tool_call_id == "failing-tool"
    assert task_steps["failing"].tool_calls[0].metadata["status"] == "FAILED"
    assert "RuntimeError: tool failed" in task_steps["failing"].tool_calls[0].metadata["error"]


def test_async_cancellation_records_failed_span_and_partial_artifact(tmp_path: Path) -> None:
    output = tmp_path / "async-cancelled"

    async def cancelled_branch() -> None:
        with trace_run(task_id="cancelled"), trace_llm(
            components={"user": "wait"},
            llm_call_id="cancelled-llm",
        ):
            await asyncio.sleep(10)

    async def run() -> None:
        task = asyncio.create_task(cancelled_branch())
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with ExperimentSession(
        output_path=output,
        artifact_id="async-cancelled",
        workload_id="async-cancelled",
        expected_task_count=1,
    ):
        asyncio.run(run())

    artifact = load_artifact(output)
    task_step = next(
        step
        for step in artifact.runs[0].steps
        if step.metadata.get("task_id") == "cancelled"
    )

    assert artifact.manifest.status == "PARTIAL"
    assert task_step.llm_calls[0].metadata["status"] == "FAILED"
    assert "CancelledError" in task_step.llm_calls[0].metadata["error"]
