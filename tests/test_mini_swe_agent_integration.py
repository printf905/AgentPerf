from __future__ import annotations

from typing import Any

from agentperf.analyzer import analyze_run
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.mini_swe_agent import (
    AgentPerfMiniSweEnvironmentWrapper,
    AgentPerfMiniSweModelWrapper,
    prompt_components_from_mini_swe_messages,
)


def test_mini_swe_messages_map_to_prompt_components() -> None:
    components = prompt_components_from_mini_swe_messages(
        [
            {"role": "system", "content": "You are a coding agent."},
            {"role": "user", "content": "Fix the failing test."},
            {"role": "assistant", "content": "I will inspect files."},
            {
                "role": "user",
                "content": "<returncode>0</returncode>\n<output>\nfile contents</output>",
            },
        ],
        tool_output_lookup=lambda text: ["tool-1"] if "file contents" in text else [],
    )

    assert [component.name for component in components] == [
        "system",
        "user",
        "history",
        "tool_result",
    ]
    assert components[-1].metadata["source_tool_call_ids"] == ["tool-1"]


def test_mini_swe_wrappers_capture_llm_and_environment_spans() -> None:
    recorder = TraceRecorder(agent_run_id="mini-swe-fixture")
    environment = AgentPerfMiniSweEnvironmentWrapper(_FakeEnvironment(), recorder)
    model = AgentPerfMiniSweModelWrapper(
        _FakeMiniSweModel(),
        recorder,
        tool_output_lookup=environment.tool_call_ids_for_observation,
    )

    with recorder.as_current():
        action_output = environment.execute({"command": "cat app.py"})
        message = model.query(
            [
                model.format_message(role="system", content="You are a coding agent."),
                model.format_message(role="user", content="Fix the bug."),
                {
                    "role": "user",
                    "content": (
                        "<returncode>0</returncode>\n"
                        f"<output>\n{action_output['output']}</output>"
                    ),
                },
            ]
        )

    run = recorder.finish()
    report = analyze_run(run)

    assert message["role"] == "assistant"
    assert len(run.llm_calls) == 1
    assert len(run.tool_calls) == 1
    assert run.llm_calls[0].llm_request_id == "chatcmpl-fixture"
    assert run.llm_calls[0].input_tokens == 123
    assert run.llm_calls[0].output_tokens == 17
    assert run.llm_calls[0].prompt_components[-1].metadata["source_tool_call_ids"] == [
        "mini-swe-tool-1"
    ]
    assert report.tool_reinjections[0].reinjected_calls == ["mini-swe-llm-1"]


class _FakeMiniSweModel:
    def __init__(self) -> None:
        self.config = type("Config", (), {"model_name": "fake-mini-model"})()

    def query(self, messages: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": "Run tests next.",
            "extra": {
                "actions": [{"command": "pytest"}],
                "response": {
                    "id": "chatcmpl-fixture",
                    "model": "fake-mini-model",
                    "usage": {"prompt_tokens": 123, "completion_tokens": 17},
                },
            },
        }

    def format_message(self, **kwargs: Any) -> dict[str, Any]:
        return dict(kwargs)

    def format_observation_messages(
        self,
        message: dict[str, Any],
        outputs: list[dict[str, Any]],
        template_vars: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": (
                    f"<returncode>{output['returncode']}</returncode>\n"
                    f"<output>\n{output['output']}</output>"
                ),
            }
            for output in outputs
        ]

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def serialize(self) -> dict[str, Any]:
        return {"info": {"config": {"model_type": "fake"}}}


class _FakeEnvironment:
    def execute(
        self,
        action: dict[str, Any],
        cwd: str = "",
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return {
            "output": "def add(a, b):\n    return a - b\n",
            "returncode": 0,
            "exception_info": "",
        }

    def get_template_vars(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def serialize(self) -> dict[str, Any]:
        return {"info": {"config": {"environment_type": "fake"}}}
