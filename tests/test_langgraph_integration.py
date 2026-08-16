from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from agentperf.artifacts import load_artifact
from agentperf.completeness import assess_path
from agentperf.experiments import ExperimentSession
from agentperf.integrations import langgraph as langgraph_integration
from agentperf.integrations.langgraph import AgentPerfLangGraph, LangGraphIntegrationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_langgraph_integration_import_does_not_require_optional_dependency() -> None:
    assert AgentPerfLangGraph is not None


def test_langgraph_missing_dependency_error_is_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "langgraph":
            return None
        return original_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)

    with (
        ExperimentSession(output_path=tmp_path / "artifact") as experiment,
        pytest.raises(LangGraphIntegrationError) as excinfo,
    ):
        langgraph_integration.instrument(object(), experiment=experiment)

    assert "pip install \"agentperf[langgraph]\"" in str(excinfo.value)


def test_langgraph_example_creates_ready_artifact(tmp_path: Path) -> None:
    pytest.importorskip("langgraph.graph")

    from examples.langgraph_agent.run import TASKS, build_graph

    output = tmp_path / "langgraph"
    graph = build_graph(variant="raw")
    with ExperimentSession(
        output_path=output,
        artifact_id="langgraph-test",
        workload_id="langgraph-test",
        expected_task_count=len(TASKS),
        framework="langgraph",
        backend="deterministic-local",
        model="fake-langgraph-model",
    ) as experiment:
        runner = langgraph_integration.instrument(graph, experiment=experiment)
        for task in TASKS:
            result = runner.invoke(
                {
                    "task_id": task["task_id"],
                    "query": task["query"],
                    "topic": task["topic"],
                },
                task_id=task["task_id"],
            )
            answer = str(result.get("answer", ""))
            passed = task["expected"] in answer.lower()
            experiment.record_task_result(
                task_id=task["task_id"],
                passed=passed,
                quality_score=1.0 if passed else 0.0,
                evaluator="deterministic-route-match@1",
                status="COMPLETE",
            )

    artifact = load_artifact(output)
    readiness = assess_path(output)

    assert artifact.manifest.status == "COMPLETE"
    assert artifact.manifest.framework == "langgraph"
    assert artifact.summary["llm_calls"] == 9
    assert artifact.summary["tool_calls"] == 3
    assert len(artifact.task_results) == 3
    assert all(task.quality_score == 1.0 for task in artifact.task_results)
    assert readiness.agent_profiling_readiness == "READY"
    assert readiness.cross_layer_readiness == "NOT_APPLICABLE"
    assert readiness.llm_calls_with_component_attribution == 9
    assert readiness.llm_calls_with_provider_usage == 9


def test_langgraph_async_wrapper_records_run(tmp_path: Path) -> None:
    pytest.importorskip("langgraph.graph")

    from examples.langgraph_agent.run import build_graph

    graph = build_graph(variant="optimized")
    output = tmp_path / "langgraph-async"
    async def run() -> dict[str, object]:
        with ExperimentSession(
            output_path=output,
            artifact_id="langgraph-async-test",
            workload_id="langgraph-async-test",
            expected_task_count=1,
            framework="langgraph",
        ) as experiment:
            runner = langgraph_integration.instrument(graph, experiment=experiment)
            result = await runner.ainvoke(
                {
                    "task_id": "async-task",
                    "query": "Route a refund request.",
                    "topic": "refund",
                },
                task_id="async-task",
                record_task_result=True,
                passed=True,
                quality_score=1.0,
                evaluator="async-fixture@1",
            )
            return cast(dict[str, object], result)

    result = asyncio.run(run())

    artifact = load_artifact(output)

    assert "refund" in str(result["answer"]).lower()
    assert artifact.summary["llm_calls"] == 3
    assert artifact.summary["tool_calls"] == 1
    assert artifact.task_results[0].quality_score == 1.0
