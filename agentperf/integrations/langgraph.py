from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agentperf import ExperimentSession, trace_run


class LangGraphIntegrationError(RuntimeError):
    """Raised when the optional LangGraph integration cannot be used."""


@dataclass
class AgentPerfLangGraph:
    """Thin wrapper that records LangGraph invocations as AgentPerf runs.

    The wrapper uses LangGraph's public graph invocation surface. It records the
    graph/task boundary and relies on node code, model wrappers, or public
    AgentPerf helpers to record exact LLM and tool calls where available.
    """

    graph: Any
    experiment: ExperimentSession
    name: str = "langgraph-run"
    framework: str = "langgraph"

    def invoke(
        self,
        input: Any,
        *,
        task_id: str,
        config: Mapping[str, Any] | None = None,
        passed: bool | None = None,
        quality_score: float | None = None,
        evaluator: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        record_task_result: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Invoke a LangGraph graph and optionally record task quality."""

        with trace_run(
            task_id=task_id,
            name=self.name,
            metadata={"framework": self.framework, **dict(metadata or {})},
        ):
            result = self.graph.invoke(input, config=dict(config or {}), **kwargs)
        if record_task_result:
            self.experiment.record_task_result(
                task_id=task_id,
                passed=passed,
                quality_score=quality_score,
                evaluator=evaluator,
                status="COMPLETE" if passed is not False else "FAILED",
                metadata={"framework": self.framework, **dict(metadata or {})},
            )
        return result

    async def ainvoke(
        self,
        input: Any,
        *,
        task_id: str,
        config: Mapping[str, Any] | None = None,
        passed: bool | None = None,
        quality_score: float | None = None,
        evaluator: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        record_task_result: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Invoke a LangGraph graph asynchronously and optionally record quality."""

        ainvoke = getattr(self.graph, "ainvoke", None)
        if ainvoke is None:
            raise LangGraphIntegrationError("LangGraph graph does not expose ainvoke")
        with trace_run(
            task_id=task_id,
            name=self.name,
            metadata={"framework": self.framework, **dict(metadata or {})},
        ):
            result = await ainvoke(input, config=dict(config or {}), **kwargs)
        if record_task_result:
            self.experiment.record_task_result(
                task_id=task_id,
                passed=passed,
                quality_score=quality_score,
                evaluator=evaluator,
                status="COMPLETE" if passed is not False else "FAILED",
                metadata={"framework": self.framework, **dict(metadata or {})},
            )
        return result


def instrument(
    graph: Any,
    *,
    experiment: ExperimentSession,
    name: str = "langgraph-run",
) -> AgentPerfLangGraph:
    """Wrap a LangGraph graph with AgentPerf run/task instrumentation.

    Install the optional dependency with ``pip install "agentperf[langgraph]"``.
    Exact LLM/tool visibility depends on what the graph nodes expose or record.
    """

    _require_langgraph()
    return AgentPerfLangGraph(graph=graph, experiment=experiment, name=name)


def _require_langgraph() -> None:
    if importlib.util.find_spec("langgraph") is None:
        raise LangGraphIntegrationError(
            "LangGraph integration requires the optional 'langgraph' extra.\n"
            'Install with: pip install "agentperf[langgraph]"'
        )
