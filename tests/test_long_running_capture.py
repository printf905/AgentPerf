from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentperf.artifacts import analyze_artifact, load_artifact
from agentperf.comparison import compare_paths
from agentperf.completeness import assess_path
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import trace_llm, trace_run, trace_tool
from agentperf.reporters.html import write_html_report


def test_explicit_flush_writes_recoverable_partial_artifact(tmp_path: Path) -> None:
    output = tmp_path / "long-running"
    session = ExperimentSession(
        output_path=output,
        artifact_id="checkpointed",
        workload_id="checkpointed",
        expected_task_count=2,
    )
    with session:
        _record_task(session, "task-1")
        checkpoint = session.flush()
        assert checkpoint.manifest.status == "PARTIAL"
        recovered = ExperimentSession.recover(output)
        assert recovered.manifest.status == "PARTIAL"
        assert recovered.manifest.metadata["capture_state"] == "RECOVERED_FROM_CHECKPOINT"
        assert len(recovered.task_results) == 1

    finalized = load_artifact(output)
    assert finalized.manifest.status == "PARTIAL"
    assert finalized.summary["capture_state"] == "FINALIZED"
    assert len(finalized.task_results) == 1


def test_checkpoint_interval_flushes_completed_capture_events(tmp_path: Path) -> None:
    output = tmp_path / "interval"

    with ExperimentSession(
        output_path=output,
        artifact_id="interval",
        workload_id="interval",
        expected_task_count=2,
        checkpoint_interval=2,
    ) as experiment:
        with (
            trace_run(task_id="task-1"),
            trace_llm(components={"user": "hello"}, llm_call_id="task-1-llm") as call,
        ):
            call.record_response(input_tokens=3, output_tokens=1)
        recovered = load_artifact(output)
        assert recovered.manifest.status == "PARTIAL"
        assert recovered.summary["llm_calls"] == 1
        _record_task(experiment, "task-1")


def test_repeated_flush_keeps_latest_checkpoint(tmp_path: Path) -> None:
    output = tmp_path / "repeated"
    session = ExperimentSession(
        output_path=output,
        artifact_id="repeated",
        workload_id="repeated",
        expected_task_count=3,
    )
    with session:
        _record_task(session, "task-1")
        session.flush()
        _record_task(session, "task-2")
        session.flush()
        recovered = load_artifact(output)
        assert [task.task_id for task in recovered.task_results] == ["task-1", "task-2"]
        checkpoints = [
            path
            for path in (output / ".agentperf_checkpoints").iterdir()
            if path.name.startswith("checkpoint-")
        ]
        assert [path.name for path in checkpoints] == ["checkpoint-000002"]


def test_successful_finalization_after_checkpoints_is_complete(tmp_path: Path) -> None:
    output = tmp_path / "complete"

    with ExperimentSession(
        output_path=output,
        artifact_id="complete",
        workload_id="complete",
        expected_task_count=2,
    ) as experiment:
        _record_task(experiment, "task-1")
        experiment.flush()
        _record_task(experiment, "task-2")

    artifact = load_artifact(output)
    assert artifact.manifest.status == "COMPLETE"
    assert artifact.summary["capture_state"] == "FINALIZED"
    assert not (output / ".agentperf_checkpoints").exists()


def test_hard_process_crash_recovers_latest_valid_checkpoint(tmp_path: Path) -> None:
    output = tmp_path / "crashed"
    script = f"""
import os
from pathlib import Path
from agentperf import ExperimentSession, trace_llm, trace_run

out = Path({str(output)!r})
experiment = ExperimentSession(
    output_path=out,
    artifact_id="crashed",
    workload_id="crashed",
    expected_task_count=30,
)
experiment.__enter__()
for index in range(20):
    task_id = f"task-{{index}}"
    with trace_run(task_id=task_id):
        with trace_llm(components={{"user": task_id}}, llm_call_id=f"{{task_id}}-llm") as call:
            call.record_response(input_tokens=4, output_tokens=1)
    experiment.record_task_result(
        task_id=task_id,
        passed=True,
        quality_score=1.0,
        status="COMPLETE",
    )
experiment.flush()
for index in range(20, 30):
    task_id = f"task-{{index}}"
    with trace_run(task_id=task_id):
        with trace_llm(components={{"user": task_id}}, llm_call_id=f"{{task_id}}-llm") as call:
            call.record_response(input_tokens=4, output_tokens=1)
    experiment.record_task_result(
        task_id=task_id,
        passed=True,
        quality_score=1.0,
        status="COMPLETE",
    )
os._exit(17)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 17
    recovered = load_artifact(output)
    assert recovered.manifest.status == "PARTIAL"
    assert recovered.manifest.metadata["capture_state"] == "RECOVERED_FROM_CHECKPOINT"
    assert len(recovered.task_results) == 20
    assert len(recovered.runs[0].llm_calls) == 20


def test_interrupted_checkpoint_write_preserves_previous_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "interrupted-write"
    session = ExperimentSession(
        output_path=output,
        artifact_id="interrupted-write",
        workload_id="interrupted-write",
        expected_task_count=2,
    )
    with session:
        _record_task(session, "task-1")
        session.flush()
        _record_task(session, "task-2")

        def fail_latest(path: Path, data: dict[str, object]) -> None:
            raise OSError(f"interrupted latest pointer write: {path.name}")

        monkeypatch.setattr("agentperf.experiments._atomic_write_json", fail_latest)
        with pytest.raises(OSError, match="interrupted latest pointer"):
            session.flush()

        recovered = load_artifact(output)
        assert [task.task_id for task in recovered.task_results] == ["task-1"]


def test_exception_exit_preserves_evidence_and_original_exception(tmp_path: Path) -> None:
    output = tmp_path / "exception"

    with pytest.raises(RuntimeError, match="user failure"), ExperimentSession(
        output_path=output,
        artifact_id="exception",
        workload_id="exception",
        expected_task_count=2,
        checkpoint_interval=1,
    ) as experiment:
        _record_task(experiment, "task-1")
        raise RuntimeError("user failure")

    artifact = load_artifact(output)
    assert artifact.manifest.status == "FAILED"
    assert len(artifact.task_results) == 1


def test_keyboard_interrupt_exit_preserves_failed_artifact(tmp_path: Path) -> None:
    output = tmp_path / "keyboard"

    with pytest.raises(KeyboardInterrupt), ExperimentSession(
        output_path=output,
        artifact_id="keyboard",
        workload_id="keyboard",
        expected_task_count=1,
    ) as experiment:
        _record_task(experiment, "task-1")
        raise KeyboardInterrupt

    artifact = load_artifact(output)
    assert artifact.manifest.status == "FAILED"
    assert len(artifact.task_results) == 1


def test_active_span_checkpoint_is_not_marked_complete(tmp_path: Path) -> None:
    output = tmp_path / "active"
    session = ExperimentSession(
        output_path=output,
        artifact_id="active",
        workload_id="active",
        expected_task_count=1,
    )
    with session, trace_run(task_id="task-1"):
        with trace_llm(components={"user": "active"}, llm_call_id="active-llm") as call:
            call.record_response(input_tokens=2, output_tokens=1)
        session.flush()
        recovered = load_artifact(output)
        task_step = next(
            step
            for step in recovered.runs[0].steps
            if step.metadata.get("task_id") == "task-1"
        )
        assert task_step.ended_at is None
        assert task_step.llm_calls[0].ended_at is not None


def test_concurrent_spans_can_checkpoint_between_completed_branches(tmp_path: Path) -> None:
    import asyncio

    output = tmp_path / "concurrent"

    async def branch(experiment: ExperimentSession, task_id: str) -> None:
        with trace_run(task_id=task_id):
            with trace_llm(components={"user": task_id}, llm_call_id=f"{task_id}-llm") as call:
                await asyncio.sleep(0)
                call.record_response(input_tokens=5, output_tokens=1)
            with trace_tool("lookup", tool_call_id=f"{task_id}-tool") as tool:
                await asyncio.sleep(0)
                tool.record_output({"ok": True})
        experiment.record_task_result(
            task_id=task_id,
            passed=True,
            quality_score=1.0,
            status="COMPLETE",
        )

    async def run(experiment: ExperimentSession) -> None:
        await asyncio.gather(branch(experiment, "task-a"), branch(experiment, "task-b"))

    with ExperimentSession(
        output_path=output,
        artifact_id="concurrent",
        workload_id="concurrent",
        expected_task_count=2,
        checkpoint_interval=3,
    ) as experiment:
        asyncio.run(run(experiment))
        recovered = load_artifact(output)
        assert recovered.manifest.status == "PARTIAL"
        assert {task.task_id for task in recovered.task_results} <= {"task-a", "task-b"}
        assert len(recovered.runs[0].llm_calls) >= 1


def test_partial_checkpoint_supports_analyze_doctor_report_and_compare(tmp_path: Path) -> None:
    partial = tmp_path / "partial"
    complete = tmp_path / "complete"

    session = ExperimentSession(
        output_path=partial,
        artifact_id="partial",
        workload_id="shared",
        expected_task_count=2,
    )
    with session.recorder.as_current():
        _record_task(session, "task-1")
        session.flush()

    with ExperimentSession(
        output_path=complete,
        artifact_id="complete",
        workload_id="shared",
        expected_task_count=2,
    ) as experiment:
        _record_task(experiment, "task-1")
        _record_task(experiment, "task-2")

    reports = analyze_artifact(partial)
    doctor = assess_path(partial)
    html_path = tmp_path / "partial.html"
    write_html_report(partial, html_path)
    comparison = compare_paths(complete, partial)

    assert reports[0].run.llm_calls
    assert doctor.agent_profiling_readiness == "PARTIAL"
    assert "artifact recovered from latest checkpoint" in doctor.limitations
    assert "PARTIAL" in html_path.read_text(encoding="utf-8")
    assert comparison.acceptance_result.verdict == "INCONCLUSIVE"
    assert any("status is PARTIAL" in warning for warning in comparison.warnings)


def _record_task(experiment: ExperimentSession, task_id: str) -> None:
    with (
        trace_run(task_id=task_id),
        trace_llm(
            components={"user": f"question {task_id}"},
            llm_call_id=f"{task_id}-llm",
        ) as call,
    ):
        call.record_response(input_tokens=4, output_tokens=1)
    experiment.record_task_result(
        task_id=task_id,
        passed=True,
        quality_score=1.0,
        status="COMPLETE",
    )
