from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any, cast

from agentperf.analyzer import analyze_run
from agentperf.experiments import ExperimentSession
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.openai_agents import (
    AgentPerfModelWrapper,
    OpenAIAgentsTraceProcessor,
)
from agentperf.reporters.terminal import render_report
from agentperf.schema.artifacts import QualityMetric

try:
    from agents import Agent, Model, ModelResponse, Runner, Usage, function_tool
    from agents.tracing import set_trace_processors
    from openai.types.responses import (
        ResponseFunctionToolCall,
        ResponseOutputMessage,
        ResponseOutputText,
    )
except ImportError as exc:  # pragma: no cover - exercised by users without the optional extra
    raise SystemExit(
        "Install the optional integration dependency first: "
        'pip install -e ".[openai-agents]"'
    ) from exc


POLICY_CORPUS = {
    "refund": (
        "POLICY-REFUND-2026: Refunds are available within 30 days when the "
        "customer provides an order ID and the license has not been transferred."
    ),
    "security": (
        "POLICY-SECURITY-2026: Account takeover reports must be escalated to "
        "Security Operations and require password reset plus active-session revocation."
    ),
    "billing": (
        "POLICY-BILLING-2026: Duplicate charges should be routed to Billing "
        "Operations with invoice ID, charge date, and last four payment digits."
    ),
    "integration": (
        "POLICY-INTEGRATION-2026: API rate-limit increases require the workspace "
        "ID, current quota, target quota, and a recent traffic sample."
    ),
}

TASKS: list[dict[str, str]] = [
    {
        "id": "task-refund-1",
        "text": "Customer asks for a refund for order A-100 within 20 days.",
        "expected_policy": "POLICY-REFUND-2026",
        "expected_route": "refund",
    },
    {
        "id": "task-security-1",
        "text": "Customer says their account was taken over and sessions are suspicious.",
        "expected_policy": "POLICY-SECURITY-2026",
        "expected_route": "security",
    },
    {
        "id": "task-billing-1",
        "text": "Customer reports two charges for the same invoice this morning.",
        "expected_policy": "POLICY-BILLING-2026",
        "expected_route": "billing",
    },
    {
        "id": "task-integration-1",
        "text": "Customer wants a higher API rate limit for workspace ws_123.",
        "expected_policy": "POLICY-INTEGRATION-2026",
        "expected_route": "integration",
    },
    {
        "id": "task-refund-2",
        "text": "A license was purchased 12 days ago and the buyer requests money back.",
        "expected_policy": "POLICY-REFUND-2026",
        "expected_route": "refund",
    },
    {
        "id": "task-security-2",
        "text": "User cannot explain recent login activity and asks to secure the account.",
        "expected_policy": "POLICY-SECURITY-2026",
        "expected_route": "security",
    },
    {
        "id": "task-billing-2",
        "text": "The same card appears to have been charged twice for invoice INV-77.",
        "expected_policy": "POLICY-BILLING-2026",
        "expected_route": "billing",
    },
    {
        "id": "task-integration-2",
        "text": "Partner integration is hitting the API quota and asks for an increase.",
        "expected_policy": "POLICY-INTEGRATION-2026",
        "expected_route": "integration",
    },
    {
        "id": "task-refund-3",
        "text": "Order B-901 is 18 days old and the customer asks whether refund is possible.",
        "expected_policy": "POLICY-REFUND-2026",
        "expected_route": "refund",
    },
    {
        "id": "task-security-3",
        "text": "Customer reports password changed by someone else and active sessions remain.",
        "expected_policy": "POLICY-SECURITY-2026",
        "expected_route": "security",
    },
]

STANDARD_INSTRUCTIONS = (
    "Classify the support request. Use lookup_policy before answering. "
    "Final answer format: ROUTE=<route>; POLICY=<policy id>; ACTION=<short action>."
)

COMPACT_INSTRUCTIONS = (
    "Use lookup_policy, then answer: ROUTE=<route>; POLICY=<policy id>; ACTION=<short action>."
)


@function_tool
def lookup_policy(query: str) -> str:
    """Look up deterministic support policy passages by query text."""
    lowered = query.lower()
    for key, passage in POLICY_CORPUS.items():
        if key in lowered:
            return passage
    return "\n".join(POLICY_CORPUS.values())


class ScriptedSupportModel(Model):
    def __init__(self) -> None:
        self.calls = 0

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        self.calls += 1
        prompt_text = _flatten_input(input)
        tool_output = _latest_tool_output(input)
        if tool_output is None:
            route = _route_for(prompt_text)
            call_id = f"call_{self.calls}_{route}"
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        id=f"fc_{self.calls}",
                        type="function_call",
                        call_id=call_id,
                        name="lookup_policy",
                        arguments=json.dumps({"query": route}),
                        status="completed",
                    )
                ],
                usage=Usage(
                    input_tokens=_approx_tokens(prompt_text) + 40,
                    output_tokens=8,
                    total_tokens=_approx_tokens(prompt_text) + 48,
                ),
                response_id=f"resp_{self.calls}",
                request_id=f"scripted-req-{self.calls}",
            )
        answer = _answer_from_policy(tool_output)
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    id=f"msg_{self.calls}",
                    type="message",
                    role="assistant",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            type="output_text",
                            text=answer,
                            annotations=[],
                        )
                    ],
                )
            ],
            usage=Usage(
                input_tokens=_approx_tokens(prompt_text) + _approx_tokens(tool_output) + 60,
                output_tokens=_approx_tokens(answer),
                total_tokens=_approx_tokens(prompt_text) + _approx_tokens(tool_output) + 60,
            ),
            response_id=f"resp_{self.calls}",
            request_id=f"scripted-req-{self.calls}",
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("The deterministic M5 example uses non-streaming runs.")


async def run(output_dir: Path, *, instruction_style: str = "standard") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    instructions = _instructions_for_style(instruction_style)
    recorder = TraceRecorder(
        agent_run_id=f"m5-openai-agents-support-triage-{instruction_style}",
        name="OpenAI Agents SDK support triage",
        metadata={
            "framework": "openai-agents-python",
            "workload": "deterministic support triage",
            "task_count": len(TASKS),
            "serving_telemetry": "unavailable",
            "instruction_style": instruction_style,
        },
    )
    processor = OpenAIAgentsTraceProcessor(recorder, capture_function_spans=False)
    set_trace_processors([cast(Any, processor)])
    model = AgentPerfModelWrapper(
        ScriptedSupportModel(),
        recorder,
        model_name="scripted-support-model",
    )
    agent = Agent(
        name="Support Triage Agent",
        instructions=instructions,
        tools=[lookup_policy],
        model=model,
    )
    results: list[dict[str, Any]] = []
    experiment = ExperimentSession(
        output_path=output_dir / "agentperf_artifact",
        artifact_id=f"m5-openai-agents-support-triage-{instruction_style}",
        workload_id="m5-openai-agents-support-triage",
        expected_task_count=len(TASKS),
        framework="openai-agents-python",
        agent_name="Support Triage Agent",
        backend="scripted",
        model="scripted-support-model",
        recorder=recorder,
        environment={
            "framework": "openai-agents-python",
            "backend": "scripted",
            "serving_telemetry": False,
            "instruction_style": instruction_style,
        },
    )
    with experiment:
        for task in TASKS:
            started = time.perf_counter()
            result = await Runner.run(agent, task["text"])
            final = str(result.final_output)
            score = score_answer(final, task)
            passed = score == 1.0
            task_result = {
                "task_id": task["id"],
                "input": task["text"],
                "expected_policy": task["expected_policy"],
                "expected_route": task["expected_route"],
                "answer": final,
                "score": score,
                "passed": passed,
            }
            results.append(task_result)
            experiment.record_task_result(
                task_id=task["id"],
                passed=passed,
                quality_score=score,
                quality_metrics=[QualityMetric(name="answer_score", value=score)],
                evaluator="deterministic-policy-coverage",
                client_latency_ms=(time.perf_counter() - started) * 1000,
                status="COMPLETE",
                metadata={
                    "expected_policy": task["expected_policy"],
                    "expected_route": task["expected_route"],
                },
            )
    artifact = experiment.finalize()
    run_data = artifact.runs[0]
    report = analyze_run(run_data)
    processor.write_export(output_dir / "openai_agents_export.json")
    recorder.write_json(output_dir / "agentperf_trace.json")
    (output_dir / "agentperf_report.txt").write_text(render_report(report), encoding="utf-8")
    mean_score = sum(float(item["score"]) for item in results) / len(results)
    pass_rate = sum(1 for item in results if item["passed"]) / len(results)
    summary = {
        "framework": "openai-agents-python",
        "agent": "Support Triage Agent",
        "instruction_style": instruction_style,
        "tasks": len(TASKS),
        "llm_calls": len(run_data.llm_calls),
        "tool_calls": len(run_data.tool_calls),
        "mean_score": mean_score,
        "pass_rate": pass_rate,
        "findings": [finding.id for finding in report.findings],
        "task_results": results,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(render_report(report))
    print(json.dumps(summary, indent=2))


def score_answer(answer: str, task: dict[str, str]) -> float:
    normalized = answer.lower()
    policy = task["expected_policy"].lower()
    route = task["expected_route"].lower()
    score = 0.0
    if policy in normalized:
        score += 0.5
    if f"route={route}" in normalized or route in normalized:
        score += 0.5
    return score


def _instructions_for_style(style: str) -> str:
    if style == "standard":
        return STANDARD_INSTRUCTIONS
    if style == "compact":
        return COMPACT_INSTRUCTIONS
    raise ValueError(f"unsupported instruction style: {style}")


def _route_for(text: str) -> str:
    lowered = text.lower()
    if "refund" in lowered or "money back" in lowered:
        return "refund"
    if "account" in lowered or "session" in lowered or "password" in lowered:
        return "security"
    if "charge" in lowered or "invoice" in lowered:
        return "billing"
    if "api" in lowered or "quota" in lowered or "rate limit" in lowered:
        return "integration"
    return "refund"


def _answer_from_policy(policy_text: str) -> str:
    if "POLICY-REFUND-2026" in policy_text:
        return "ROUTE=refund; POLICY=POLICY-REFUND-2026; ACTION=verify order ID and refund window."
    if "POLICY-SECURITY-2026" in policy_text:
        return (
            "ROUTE=security; POLICY=POLICY-SECURITY-2026; "
            "ACTION=escalate and revoke active sessions."
        )
    if "POLICY-BILLING-2026" in policy_text:
        return (
            "ROUTE=billing; POLICY=POLICY-BILLING-2026; "
            "ACTION=collect invoice and charge details."
        )
    if "POLICY-INTEGRATION-2026" in policy_text:
        return (
            "ROUTE=integration; POLICY=POLICY-INTEGRATION-2026; "
            "ACTION=collect workspace and quota details."
        )
    return "ROUTE=refund; POLICY=POLICY-REFUND-2026; ACTION=verify order details."


def _latest_tool_output(input_value: str | list[Any]) -> str | None:
    if not isinstance(input_value, list):
        return None
    for item in reversed(input_value):
        data = item.model_dump() if hasattr(item, "model_dump") else item
        if isinstance(data, dict) and data.get("type") == "function_call_output":
            return str(data.get("output") or "")
    return None


def _flatten_input(input_value: str | list[Any]) -> str:
    if isinstance(input_value, str):
        return input_value
    parts: list[str] = []
    for item in input_value:
        data = item.model_dump() if hasattr(item, "model_dump") else item
        if not isinstance(data, dict):
            parts.append(str(data))
            continue
        if data.get("output"):
            parts.append(str(data["output"]))
        content = data.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                block_data = block.model_dump() if hasattr(block, "model_dump") else block
                if isinstance(block_data, dict):
                    text = block_data.get("text") or block_data.get("input_text")
                    if text:
                        parts.append(str(text))
    return "\n".join(parts)


def _approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a deterministic OpenAI Agents SDK support triage workload."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/agentperf_openai_agents_support_triage"),
    )
    parser.add_argument(
        "--instruction-style",
        choices=["standard", "compact"],
        default="standard",
    )
    args = parser.parse_args()
    asyncio.run(run(args.output_dir, instruction_style=args.instruction_style))


if __name__ == "__main__":
    main()
