from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool
from agentperf.metrics.tokens import token_count
from agentperf.schema.trace import PromptComponent

TASKS = [
    {
        "task_id": "ticket-refund-001",
        "user": "Customer asks whether a damaged order can be refunded.",
        "policy_key": "refund",
        "expected": "refund eligible",
    },
    {
        "task_id": "ticket-shipping-002",
        "user": "Customer asks whether expedited shipping can be waived.",
        "policy_key": "shipping",
        "expected": "shipping waiver",
    },
    {
        "task_id": "ticket-warranty-003",
        "user": "Customer asks whether a device is covered after purchase.",
        "policy_key": "warranty",
        "expected": "warranty coverage",
    },
]

POLICIES = {
    "refund": (
        "POLICY REFUND 2026: refund eligible when damage is reported within "
        "30 days, the order ID is present, and the user can provide a photo. "
        "Support must explain the evidence needed, avoid promising instant "
        "payment, and route exceptions to the refunds queue. "
    )
    * 18,
    "shipping": (
        "POLICY SHIPPING 2026: shipping waiver can be offered when expedited "
        "delivery missed the promised date and the order was not delayed by "
        "weather or address changes. Capture order ID and promised date. "
    )
    * 18,
    "warranty": (
        "POLICY WARRANTY 2026: warranty coverage applies for covered device "
        "failures within one year when there is no evidence of misuse. Ask for "
        "serial number, purchase date, and failure description. "
    )
    * 18,
}

COMPACT_POLICIES = {
    "refund": "refund eligible: damaged order within 30 days with order ID and photo",
    "shipping": "shipping waiver: missed expedited promise without weather/address exception",
    "warranty": "warranty coverage: device failure within one year without misuse",
}


@dataclass(frozen=True)
class FakeResponse:
    text: str
    input_tokens: int
    output_tokens: int
    request_id: str


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["raw", "optimized"], required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path(__file__).parent / "runs",
    )
    args = parser.parse_args()
    output_path = args.output_root / args.variant

    with ExperimentSession(
        output_path=output_path,
        artifact_id=f"byoa-support-{args.variant}",
        workload_id="byoa-support-agent",
        expected_task_count=len(TASKS),
        framework="framework-free",
        agent_name="byoa-support-policy-agent",
        backend="deterministic-local",
        model="fake-support-model",
        mean_score_tolerance=0.0,
        pass_rate_tolerance=0.0,
    ) as experiment:
        for task in TASKS:
            result = run_task(task, variant=args.variant)
            experiment.record_task_result(
                task_id=task["task_id"],
                passed=task["expected"] in result.lower(),
                quality_score=1.0 if task["expected"] in result.lower() else 0.0,
                evaluator="deterministic-string-match@1",
                status="COMPLETE",
            )

    print(f"Wrote AgentPerf artifact: {output_path}")
    return 0


def run_task(task: dict[str, str], *, variant: str) -> str:
    system = (
        "You are a support policy assistant. Use policy evidence before finalizing "
        "a concise answer."
    )
    with trace_run(task_id=task["task_id"], name="support ticket"):
        planner_components = {
            "system": system,
            "user": task["user"],
        }
        with trace_llm(
            model="fake-support-model",
            provider="deterministic-local",
            semantic_role="planner",
            components=planner_components,
        ) as call:
            planner = fake_model(
                planner_components,
                request_id=f"{task['task_id']}-planner",
                answer="Need policy lookup before final response.",
            )
            call.record_response(
                output=planner.text,
                input_tokens=planner.input_tokens,
                output_tokens=planner.output_tokens,
                request_id=planner.request_id,
            )

        tool_id = f"{task['task_id']}-policy"
        with trace_tool(
            "lookup_policy",
            tool_call_id=tool_id,
            input={"policy_key": task["policy_key"]},
        ) as tool:
            policy = lookup_policy(task["policy_key"])
            tool.record_output(policy)

        policy_context = policy if variant == "raw" else COMPACT_POLICIES[task["policy_key"]]
        reviewer_components = [
            PromptComponent(name="system", text=system),
            PromptComponent(name="user", text=task["user"]),
            PromptComponent(
                name="tool_result",
                text=policy_context,
                metadata={"source_tool_call_ids": [tool_id]},
            ),
        ]
        with trace_llm(
            model="fake-support-model",
            provider="deterministic-local",
            semantic_role="reviewer",
            components=reviewer_components,
        ) as call:
            reviewer = fake_model(
                reviewer_components,
                request_id=f"{task['task_id']}-reviewer",
                answer="Policy evidence is sufficient for a concise answer.",
            )
            call.record_response(
                output=reviewer.text,
                input_tokens=reviewer.input_tokens,
                output_tokens=reviewer.output_tokens,
                request_id=reviewer.request_id,
            )

        final_components = [
            PromptComponent(name="system", text=system),
            PromptComponent(name="user", text=task["user"]),
            PromptComponent(
                name="tool_result",
                text=policy_context,
                metadata={"source_tool_call_ids": [tool_id]},
            ),
        ]
        with trace_llm(
            model="fake-support-model",
            provider="deterministic-local",
            semantic_role="final",
            components=final_components,
        ) as call:
            response_text = final_answer(task["policy_key"])
            response = fake_model(
                final_components,
                request_id=f"{task['task_id']}-final",
                answer=response_text,
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )
            return response.text


def lookup_policy(policy_key: str) -> str:
    return POLICIES[policy_key]


def final_answer(policy_key: str) -> str:
    if policy_key == "refund":
        return "Refund eligible if the customer provides the order ID and damage photo."
    if policy_key == "shipping":
        return "Shipping waiver may apply when the expedited promise was missed."
    return "Warranty coverage may apply for a covered failure within one year."


def fake_model(
    components: dict[str, object] | list[PromptComponent],
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
