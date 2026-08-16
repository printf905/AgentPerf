from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import asdict, replace
from pathlib import Path

from agentperf.artifacts import load_artifact
from agentperf.comparison import compare_workloads
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import (
    TraceRecorder,
    record_handoff,
    trace_llm,
    trace_run,
    trace_tool,
)
from agentperf.multi_agent import compare_profiles, profile_runs, profile_to_dict
from agentperf.reporters.comparison_html import build_comparison_html_input, render_comparison_html
from agentperf.reporters.html import load_html_report_input, render_html_report
from agentperf.schema.findings import Finding, FindingProvenance
from agentperf.schema.trace import AgentRun


def test_agent_role_branch_and_handoff_metadata_are_recorded() -> None:
    run = _multi_agent_run().to_agent_run()
    profile = profile_runs([run])
    data = profile_to_dict(profile)

    assert profile.has_metadata is True
    assert {agent["agent_id"] for agent in data["agents"]} >= {
        "coordinator",
        "researcher",
        "critic",
        "writer",
    }
    researcher = next(agent for agent in data["agents"] if agent["agent_id"] == "researcher")
    assert researcher["role"] == "researcher"
    assert researcher["llm_calls"] == 3
    assert researcher["tool_calls"] == 3
    assert {"search-a", "search-b", "search-c"} <= set(researcher["branch_ids"])
    assert any(handoff["from_agent_id"] == "coordinator" for handoff in data["handoffs"])
    assert any(fanout["parent_branch_id"] == "research" for fanout in data["fanouts"])


def test_root_agent_metadata_inherits_to_auto_created_call_steps() -> None:
    with trace_run(
        "root-agent",
        agent_id="planner",
        role="planner",
    ) as recorder, trace_llm(components={"user": "plan"}, model="small") as call:
        call.record_response(input_tokens=1, output_tokens=1)

    run = recorder.to_agent_run()
    assert run.steps[0].metadata["agent_id"] == "planner"
    assert run.steps[0].metadata["agent_role"] == "planner"
    assert profile_runs([run]).agents[0].llm_calls == 1


def test_trace_llm_role_remains_model_role_not_agent_role() -> None:
    with trace_run(
        "role-distinction",
        agent_id="researcher-2",
        role="researcher",
    ) as recorder, trace_llm(
        role="evidence_reviewer",
        model="qwen-fixture",
        components={"user": "review evidence"},
    ) as call:
        call.record_response(input_tokens=2, output_tokens=1)

    run = recorder.to_agent_run()
    assert run.llm_calls[0].semantic_role == "evidence_reviewer"
    profile = profile_runs([run])
    assert profile.agents[0].agent_id == "researcher-2"
    assert profile.agents[0].role == "researcher"


def test_async_parallel_branch_failure_does_not_contaminate_siblings() -> None:
    async def branch(name: str, *, fail: bool = False) -> None:
        with trace_run(
            f"branch-{name}",
            agent_id="researcher",
            role="researcher",
            branch_id=name,
            parent_branch_id="research",
        ):
            try:
                with trace_tool("search", tool_call_id=f"tool-{name}") as tool:
                    if fail:
                        raise RuntimeError("search failed")
                    tool.record_output(f"result {name}")
            except RuntimeError:
                pass
            with trace_llm(
                components={"tool_result": f"result {name}", "user": "summarize"},
                model="fixture",
            ) as call:
                call.record_response(input_tokens=4, output_tokens=1)

    async def scenario() -> TraceRecorder:
        with trace_run("task", agent_run_id="run-async", task_id="task-async") as recorder:
            await asyncio.gather(branch("a"), branch("b", fail=True), branch("c"))
        return recorder

    recorder = asyncio.run(scenario())
    run = recorder.to_agent_run()
    profile = profile_runs([run])

    assert len(run.tool_calls) == 3
    assert [call.metadata["status"] for call in run.tool_calls].count("FAILED") == 1
    assert {branch.branch_id for branch in profile.branches} == {"a", "b", "c"}
    assert all(branch.llm_calls == 1 for branch in profile.branches)


def test_branch_cancellation_preserves_completed_sibling() -> None:
    async def completed_branch() -> None:
        with trace_run(
            "branch-ok",
            agent_id="researcher",
            branch_id="ok",
        ), trace_llm(components={"user": "ok"}, model="fixture") as call:
            call.record_response(input_tokens=1, output_tokens=1)

    async def cancelled_branch() -> None:
        with trace_run("branch-cancel", agent_id="researcher", branch_id="cancelled"):
            await asyncio.sleep(1)

    async def scenario() -> TraceRecorder:
        with trace_run("task", agent_run_id="run-cancel") as recorder:
            task = asyncio.create_task(cancelled_branch())
            await asyncio.sleep(0)
            await completed_branch()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return recorder

    recorder = asyncio.run(scenario())
    run = recorder.to_agent_run()
    profile = profile_runs([run])

    assert any(branch.branch_id == "ok" and branch.llm_calls == 1 for branch in profile.branches)
    assert any(
        branch.branch_id == "cancelled" and branch.llm_calls == 0
        for branch in profile.branches
    )


def test_multi_agent_comparison_uses_stable_ids_without_graph_matching() -> None:
    baseline = _multi_agent_run(branches=("search-a", "search-b", "search-c")).to_agent_run()
    candidate = _multi_agent_run(branches=("search-a", "search-b")).to_agent_run()

    comparison = compare_workloads([baseline], [candidate])
    data = comparison.metadata["multi_agent_comparison"]

    assert data["has_metadata"] is True
    assert data["removed_branches"] == ["search-c"]
    researcher_delta = next(
        item for item in data["agent_deltas"] if item["agent_id"] == "researcher"
    )
    assert researcher_delta["llm_call_delta"] == -1
    assert researcher_delta["tool_call_delta"] == -1


def test_added_and_removed_agents_are_explicitly_reported() -> None:
    baseline = _single_agent_run("researcher")
    candidate = _single_agent_run("writer")

    result = compare_profiles(profile_runs([baseline]), profile_runs([candidate]))

    assert result["removed_agents"] == ["researcher"]
    assert result["added_agents"] == ["writer"]


def test_single_run_html_renders_multi_agent_structure_and_escapes_labels(tmp_path: Path) -> None:
    run = _single_agent_run("<script>alert(1)</script>")
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(run_to_trace(run)), encoding="utf-8")

    html = render_html_report(load_html_report_input(path))

    assert "Multi-Agent and Parallel Structure" in html
    assert "Agent Attribution" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_single_run_html_scopes_findings_to_agent_and_branch(tmp_path: Path) -> None:
    run = _multi_agent_run().to_agent_run()
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(run_to_trace(run)), encoding="utf-8")
    report_input = replace(
        load_html_report_input(path),
        findings=[
            Finding(
                id="TOOL_OUTPUT_BLOAT",
                severity="MEDIUM",
                title="Tool output bloat",
                summary="fixture",
                evidence={"scope": "trace"},
                affected_spans=[],
                recommendation="fixture",
                confidence="HIGH",
                provenance=FindingProvenance(llm_call_ids=["llm-1"]),
            )
        ],
    )

    html = render_html_report(report_input)

    assert "trace · agent:researcher branch:search-a" in html


def test_comparison_html_renders_multi_agent_deltas(tmp_path: Path) -> None:
    baseline = _multi_agent_run(branches=("search-a", "search-b", "search-c")).to_agent_run()
    candidate = _multi_agent_run(branches=("search-a", "search-b")).to_agent_run()
    comparison = compare_workloads([baseline], [candidate])
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(json.dumps(run_to_trace(baseline)), encoding="utf-8")
    candidate_path.write_text(json.dumps(run_to_trace(candidate)), encoding="utf-8")

    html = render_comparison_html(
        build_comparison_html_input(comparison, baseline_path, candidate_path)
    )

    assert "Multi-Agent Comparison" in html
    assert "Removed branches" in html
    assert "search-c" in html
    assert "Agent and branch comparison uses explicit stable IDs" in html


def test_checkpoint_recovery_preserves_multi_agent_metadata(tmp_path: Path) -> None:
    output = tmp_path / "checkpointed"

    with ExperimentSession(output_path=output, artifact_id="ma", workload_id="ma") as session:
        with trace_run("coordinator", task_id="task-1", agent_id="coordinator", role="coordinator"):
            record_handoff(
                from_agent_id="coordinator",
                to_agent_id="researcher",
                context_components={"user": "question"},
            )
            with trace_run(
                "branch-a",
                agent_id="researcher",
                role="researcher",
                branch_id="search-a",
                parent_branch_id="research",
            ), trace_llm(components={"user": "search"}, model="fixture") as call:
                call.record_response(input_tokens=1, output_tokens=1)
        session.record_task_result(
            task_id="task-1",
            passed=True,
            quality_score=1.0,
            status="COMPLETE",
        )
        session.flush()
        recovered = load_artifact(output)
        assert recovered.manifest.status == "PARTIAL"

    finalized = load_artifact(output)
    assert finalized.manifest.status == "COMPLETE"
    profile = profile_runs(finalized.runs_for_comparison())
    assert profile.has_metadata is True
    assert any(agent.agent_id == "researcher" for agent in profile.agents)
    assert any(branch.branch_id == "search-a" for branch in profile.branches)


def test_old_single_agent_artifact_has_no_multi_agent_metadata() -> None:
    with trace_run("single", agent_run_id="run-single") as recorder, trace_llm(
        components={"user": "hello"},
        model="fixture",
    ) as call:
        call.record_response(input_tokens=1, output_tokens=1)

    profile = profile_runs([recorder.to_agent_run()])

    assert profile.has_metadata is False
    assert profile.agents == []
    assert profile.branches == []


def _multi_agent_run(
    branches: tuple[str, ...] = ("search-a", "search-b", "search-c"),
) -> TraceRecorder:
    with trace_run(
        "multi-agent-task",
        agent_run_id="run-multi",
        task_id="task-1",
        agent_id="coordinator",
        role="coordinator",
    ) as recorder:
        record_handoff(
            from_agent_id="coordinator",
            to_agent_id="researcher",
            context_components={"user": "research question"},
            branch_id="research",
        )
        for branch in branches:
            with trace_run(
                branch,
                agent_id="researcher",
                role="researcher",
                branch_id=branch,
                parent_branch_id="research",
            ):
                with trace_tool("search", tool_call_id=f"tool-{branch}") as tool:
                    tool.record_output(f"evidence for {branch}")
                with trace_llm(
                    components={
                        "tool_result": f"evidence for {branch}",
                        "user": "summarize evidence",
                    },
                    model="fixture-model",
                ) as call:
                    call.record_response(input_tokens=10, output_tokens=2)
        with trace_run(
            "join",
            agent_id="researcher",
            role="researcher",
            branch_id="research-join",
            parent_branch_id="research",
            branch_event="join",
        ):
            pass
        record_handoff(from_agent_id="researcher", to_agent_id="critic", context_tokens=12)
        with trace_run("critic", agent_id="critic", role="critic"), trace_llm(
            components={"history": "summaries"},
            model="fixture-model",
        ) as call:
            call.record_response(input_tokens=5, output_tokens=1)
        record_handoff(from_agent_id="critic", to_agent_id="writer", context_tokens=5)
        with trace_run("writer", agent_id="writer", role="writer"), trace_llm(
            components={"history": "critique"},
            model="fixture-model",
        ) as call:
            call.record_response(input_tokens=5, output_tokens=1)
    return recorder


def _single_agent_run(agent_id: str) -> AgentRun:
    with trace_run(
        "single",
        agent_run_id=f"run-{agent_id}",
        task_id="task-1",
        agent_id=agent_id,
    ) as recorder, trace_llm(components={"user": "hello"}, model="fixture") as call:
        call.record_response(input_tokens=1, output_tokens=1)
    return recorder.to_agent_run()


def run_to_trace(run: AgentRun) -> dict[str, object]:
    return {"agent_run": asdict(run)}
