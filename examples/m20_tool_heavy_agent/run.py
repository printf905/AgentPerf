from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool
from agentperf.metrics.tokens import token_count
from agentperf.schema.trace import PromptComponent

SYSTEM_PROMPT = (
    "You are a research-support agent. Use retrieved evidence and policy tools, "
    "separate confirmed facts from unknowns, and give a concise route/action."
)


TASKS: list[dict[str, Any]] = [
    {
        "task_id": "research-refund-large-policy",
        "query": "Customer requests refund after damaged delivery with an order ID.",
        "topic": "refund",
        "tools": ["search", "policy", "history"],
        "expected": "refund",
        "evidence_mode": "reducible",
    },
    {
        "task_id": "research-security-audit",
        "query": "Account takeover report mentions several suspicious sessions.",
        "topic": "security",
        "tools": ["search", "policy", "audit"],
        "expected": "security",
        "evidence_mode": "necessary",
    },
    {
        "task_id": "research-integration-quota",
        "query": "Partner workspace asks for a rate-limit increase after quota errors.",
        "topic": "integration",
        "tools": ["search", "policy"],
        "expected": "integration",
        "evidence_mode": "reducible",
    },
    {
        "task_id": "research-billing-duplicate",
        "query": "Customer reports duplicate invoice charges and asks for next steps.",
        "topic": "billing",
        "tools": ["search", "policy", "history"],
        "expected": "billing",
        "evidence_mode": "reducible",
    },
]


SEARCH_CORPUS = {
    "refund": (
        "Refund research note: damaged shipment evidence, order ID, photo record, "
        "fulfillment exception, payment state, support queue routing, and customer "
        "communication requirements. "
    )
    * 35,
    "security": (
        "Security research note: suspicious session timeline, password reset status, "
        "recent device inventory, revoked token list, escalation criteria, and audit "
        "questions for account takeover handling. "
    )
    * 28,
    "integration": (
        "Integration research note: quota history, workspace ID, endpoint traffic, "
        "current limit, desired limit, customer tier, and sample request spikes. "
    )
    * 24,
    "billing": (
        "Billing research note: invoice ID, charge date, last four card digits, "
        "processor event ID, duplicate detection, refund route, and customer notice. "
    )
    * 30,
}


POLICY_CORPUS = {
    "refund": (
        "POLICY REFUND: route refund cases when damaged delivery is reported within "
        "30 days and the order ID plus photo are available. "
    )
    * 18,
    "security": (
        "POLICY SECURITY: route account takeover reports to security operations and "
        "require password reset plus active-session revocation. "
    )
    * 16,
    "integration": (
        "POLICY INTEGRATION: route rate-limit increases to platform operations with "
        "workspace ID, current quota, requested quota, and traffic sample. "
    )
    * 15,
    "billing": (
        "POLICY BILLING: route duplicate charges to billing operations with invoice "
        "ID, charge date, and payment details. "
    )
    * 17,
}


CASE_HISTORY = {
    "refund": (
        "Case history: order opened, delivery damaged, customer uploaded two photos, "
        "agent confirmed order ID, warehouse exception noted. "
    )
    * 12,
    "billing": (
        "Case history: invoice viewed twice, two processor events observed, customer "
        "submitted payment last four and charge timestamp. "
    )
    * 12,
}


AUDIT_LOG = (
    "Audit timeline: login from new country, password reset requested, session token "
    "revocation pending, support agent verified owner, security operations escalation "
    "needed, customer asked for all active sessions to be revoked. "
) * 10


COMPACT_EVIDENCE = {
    "refund": "refund evidence: damaged delivery, order ID, photo, within policy route",
    "integration": "integration evidence: workspace quota errors and requested increase",
    "billing": "billing evidence: duplicate invoice charge with payment details",
}


@dataclass(frozen=True)
class FakeResponse:
    text: str
    input_tokens: int
    output_tokens: int
    request_id: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic M20 tool-heavy AgentPerf validation workload."
    )
    parser.add_argument("--variant", choices=["raw", "optimized"], required=True)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/agentperf-m20-tool-heavy"))
    args = parser.parse_args()
    output_path = args.output_root / args.variant

    with ExperimentSession(
        output_path=output_path,
        artifact_id=f"m20-tool-heavy-{args.variant}",
        workload_id="m20-tool-heavy-agent",
        expected_task_count=len(TASKS),
        framework="framework-free",
        agent_name="m20-research-support-agent",
        backend="deterministic-local",
        model="fake-research-model",
        mean_score_tolerance=0.0,
        pass_rate_tolerance=0.0,
        environment={
            "framework": "framework-free",
            "serving_telemetry": False,
            "workload_class": "tool-heavy multi-step agent",
        },
    ) as experiment:
        for task in TASKS:
            answer = run_task(task, variant=args.variant)
            passed = str(task["expected"]) in answer.lower()
            experiment.record_task_result(
                task_id=str(task["task_id"]),
                passed=passed,
                quality_score=1.0 if passed else 0.0,
                evaluator="deterministic-route-match@1",
                status="COMPLETE",
                metadata={
                    "topic": task["topic"],
                    "evidence_mode": task["evidence_mode"],
                },
            )

    print(f"Wrote AgentPerf artifact: {output_path}")
    return 0


def run_task(task: dict[str, Any], *, variant: str) -> str:
    topic = str(task["topic"])
    with trace_run(task_id=str(task["task_id"]), name="research support task"):
        planner_components = {
            "system": SYSTEM_PROMPT,
            "user": task["query"],
        }
        with trace_llm(
            model="fake-research-model",
            provider="deterministic-local",
            semantic_role="planner",
            components=planner_components,
        ) as call:
            response = fake_model(
                planner_components,
                request_id=f"{task['task_id']}-planner",
                answer=f"Plan: gather {topic} evidence, policy, then synthesize.",
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )

        tool_outputs: dict[str, tuple[str, str]] = {}
        for tool_name in task["tools"]:
            tool_id = f"{task['task_id']}-{tool_name}"
            with trace_tool(
                tool_name,
                tool_call_id=tool_id,
                input={"topic": topic},
            ) as tool:
                output = invoke_tool(tool_name, topic)
                tool.record_output(output)
            tool_outputs[tool_name] = (tool_id, output)

        review_components = _evidence_components(task, tool_outputs, variant=variant)
        with trace_llm(
            model="fake-research-model",
            provider="deterministic-local",
            semantic_role="reviewer",
            components=review_components,
        ) as call:
            response = fake_model(
                review_components,
                request_id=f"{task['task_id']}-reviewer",
                answer="Evidence reviewed; route can be selected.",
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )

        final_components = _evidence_components(task, tool_outputs, variant=variant)
        with trace_llm(
            model="fake-research-model",
            provider="deterministic-local",
            semantic_role="final",
            components=final_components,
        ) as call:
            answer = final_answer(topic)
            response = fake_model(
                final_components,
                request_id=f"{task['task_id']}-final",
                answer=answer,
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )
            return response.text


def invoke_tool(tool_name: str, topic: str) -> str:
    if tool_name == "search":
        return SEARCH_CORPUS[topic]
    if tool_name == "policy":
        return POLICY_CORPUS[topic]
    if tool_name == "history":
        return CASE_HISTORY[topic]
    if tool_name == "audit":
        return AUDIT_LOG
    raise ValueError(f"unsupported tool: {tool_name}")


def _evidence_components(
    task: dict[str, Any],
    tool_outputs: dict[str, tuple[str, str]],
    *,
    variant: str,
) -> list[PromptComponent]:
    topic = str(task["topic"])
    components = [
        PromptComponent(name="system", text=SYSTEM_PROMPT),
        PromptComponent(name="user", text=str(task["query"])),
    ]
    for tool_name, (tool_id, output) in tool_outputs.items():
        component_name = "retrieved_context" if tool_name == "search" else "tool_result"
        text = _component_text(task, tool_name, output, variant=variant)
        components.append(
            PromptComponent(
                name=component_name,
                text=text,
                metadata={
                    "source_tool_call_ids": [tool_id],
                    "topic": topic,
                    "evidence_mode": task["evidence_mode"],
                },
            )
        )
    return components


def _component_text(task: dict[str, Any], tool_name: str, output: str, *, variant: str) -> str:
    if variant == "raw":
        return output
    if task["evidence_mode"] == "necessary" and tool_name == "audit":
        return output
    if tool_name in {"search", "policy", "history"}:
        topic = str(task["topic"])
        return COMPACT_EVIDENCE.get(topic, output[:240])
    return output


def final_answer(topic: str) -> str:
    if topic == "refund":
        return "ROUTE=refund; ACTION=collect order ID and photo before refund routing."
    if topic == "security":
        return "ROUTE=security; ACTION=escalate account takeover and revoke sessions."
    if topic == "integration":
        return "ROUTE=integration; ACTION=collect workspace quota evidence."
    return "ROUTE=billing; ACTION=collect invoice and payment evidence."


def fake_model(
    components: list[PromptComponent] | dict[str, object],
    *,
    request_id: str,
    answer: str,
) -> FakeResponse:
    if isinstance(components, dict):
        input_text = "\n".join(str(value) for value in components.values())
    else:
        input_text = "\n".join(component.text for component in components)
    return FakeResponse(
        text=answer,
        input_tokens=token_count(input_text),
        output_tokens=token_count(answer),
        request_id=request_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
