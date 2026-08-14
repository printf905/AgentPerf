from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from agentperf import ExperimentSession, trace_llm, trace_tool
from agentperf.integrations.langgraph import LangGraphIntegrationError, instrument
from agentperf.metrics.tokens import token_count
from agentperf.schema.trace import PromptComponent

try:
    from langgraph.graph import END, START, StateGraph
except ModuleNotFoundError as exc:  # pragma: no cover - exercised in clean install smoke
    raise SystemExit(
        "The LangGraph example requires the optional AgentPerf LangGraph extra.\n"
        'Install with: pip install "agentperf[langgraph]"'
    ) from exc


SYSTEM_PROMPT = (
    "You are a policy-routing graph. Plan the lookup, inspect policy evidence, "
    "review the result, and produce the correct support route."
)

TASKS = [
    {
        "task_id": "langgraph-refund-001",
        "query": "Route a damaged-delivery refund request.",
        "topic": "refund",
        "expected": "refund",
    },
    {
        "task_id": "langgraph-billing-002",
        "query": "Route a duplicate invoice charge request.",
        "topic": "billing",
        "expected": "billing",
    },
    {
        "task_id": "langgraph-security-003",
        "query": "Route an account takeover request.",
        "topic": "security",
        "expected": "security",
    },
]

POLICIES = {
    "refund": (
        "REFUND GRAPH POLICY: damaged delivery refund routing requires order ID, "
        "photo evidence, a report within 30 days, and refunds queue assignment. "
    )
    * 24,
    "billing": (
        "BILLING GRAPH POLICY: duplicate invoice routing requires invoice ID, "
        "processor event ID, last four card digits, and billing operations review. "
    )
    * 24,
    "security": (
        "SECURITY GRAPH POLICY: account takeover routing requires session revoke, "
        "password reset, device review, and security operations escalation. "
    )
    * 24,
}

COMPACT_POLICIES = {
    "refund": "refund route evidence: order ID, photo, within 30 days",
    "billing": "billing route evidence: duplicate invoice and processor event",
    "security": "security route evidence: revoke sessions and escalate account takeover",
}


class GraphState(TypedDict, total=False):
    task_id: str
    query: str
    topic: str
    plan: str
    policy: str
    review: str
    answer: str


@dataclass(frozen=True)
class FakeResponse:
    text: str
    input_tokens: int
    output_tokens: int
    request_id: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a deterministic local LangGraph workload instrumented by AgentPerf."
    )
    parser.add_argument("--variant", choices=["raw", "optimized"], required=True)
    parser.add_argument("--output-root", type=Path, default=Path("/tmp/agentperf-langgraph"))
    args = parser.parse_args()

    output_path = args.output_root / args.variant
    graph = build_graph(variant=args.variant)
    with ExperimentSession(
        output_path=output_path,
        artifact_id=f"langgraph-policy-{args.variant}",
        workload_id="langgraph-policy-agent",
        expected_task_count=len(TASKS),
        framework="langgraph",
        agent_name="langgraph-policy-router",
        backend="deterministic-local",
        model="fake-langgraph-model",
        mean_score_tolerance=0.0,
        pass_rate_tolerance=0.0,
        environment={"framework": "langgraph", "serving_telemetry": False},
    ) as experiment:
        runner = instrument(graph, experiment=experiment, name="policy graph")
        for task in TASKS:
            result = runner.invoke(
                {
                    "task_id": task["task_id"],
                    "query": task["query"],
                    "topic": task["topic"],
                },
                task_id=task["task_id"],
                metadata={"variant": args.variant, "topic": task["topic"]},
            )
            answer = str(result.get("answer", ""))
            passed = task["expected"] in answer.lower()
            experiment.record_task_result(
                task_id=task["task_id"],
                passed=passed,
                quality_score=1.0 if passed else 0.0,
                evaluator="deterministic-route-match@1",
                status="COMPLETE",
                metadata={"variant": args.variant, "topic": task["topic"]},
            )

    print(f"Wrote AgentPerf LangGraph artifact: {output_path}")
    return 0


def build_graph(*, variant: str) -> Any:
    graph = StateGraph(GraphState)

    def plan_node(state: GraphState) -> GraphState:
        components = {"system": SYSTEM_PROMPT, "user": state["query"]}
        with trace_llm(
            model="fake-langgraph-model",
            provider="deterministic-local",
            semantic_role="planner",
            components=components,
        ) as call:
            response = fake_model(
                components,
                request_id=f"{state['task_id']}-planner",
                answer=f"Plan lookup for {state['topic']} route.",
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )
        return {"plan": response.text}

    def lookup_node(state: GraphState) -> GraphState:
        with trace_tool(
            "lookup_policy",
            tool_call_id=f"{state['task_id']}-policy",
            input={"topic": state["topic"]},
        ) as tool:
            raw_policy = POLICIES[state["topic"]]
            tool.record_output(raw_policy)
        policy = raw_policy if variant == "raw" else COMPACT_POLICIES[state["topic"]]
        return {"policy": policy}

    def review_node(state: GraphState) -> GraphState:
        components = evidence_components(state)
        with trace_llm(
            model="fake-langgraph-model",
            provider="deterministic-local",
            semantic_role="reviewer",
            components=components,
        ) as call:
            response = fake_model(
                components,
                request_id=f"{state['task_id']}-reviewer",
                answer=f"Reviewed {state['topic']} policy evidence.",
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )
        return {"review": response.text}

    def final_node(state: GraphState) -> GraphState:
        components = evidence_components(state)
        with trace_llm(
            model="fake-langgraph-model",
            provider="deterministic-local",
            semantic_role="final",
            components=components,
        ) as call:
            answer = final_answer(state["topic"])
            response = fake_model(
                components,
                request_id=f"{state['task_id']}-final",
                answer=answer,
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )
        return {"answer": response.text}

    graph.add_node("plan", plan_node)
    graph.add_node("lookup_policy", lookup_node)
    graph.add_node("review", review_node)
    graph.add_node("final", final_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "lookup_policy")
    graph.add_edge("lookup_policy", "review")
    graph.add_edge("review", "final")
    graph.add_edge("final", END)
    return graph.compile()


def evidence_components(state: GraphState) -> list[PromptComponent]:
    return [
        PromptComponent(name="system", text=SYSTEM_PROMPT),
        PromptComponent(name="user", text=state["query"]),
        PromptComponent(name="history", text=state.get("plan", "")),
        PromptComponent(
            name="tool_result",
            text=state["policy"],
            metadata={"source_tool_call_ids": [f"{state['task_id']}-policy"]},
        ),
    ]


def fake_model(
    components: Mapping[str, object] | list[PromptComponent],
    *,
    request_id: str,
    answer: str,
) -> FakeResponse:
    if isinstance(components, list):
        input_text = "\n".join(component.text for component in components)
    else:
        input_text = "\n".join(str(value) for value in components.values())
    return FakeResponse(
        text=answer,
        input_tokens=token_count(input_text),
        output_tokens=token_count(answer),
        request_id=request_id,
    )


def final_answer(topic: str) -> str:
    if topic == "refund":
        return "ROUTE=refund; collect damaged-delivery evidence and route to refunds."
    if topic == "billing":
        return "ROUTE=billing; collect invoice and payment evidence for billing review."
    return "ROUTE=security; revoke sessions and escalate account takeover."


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LangGraphIntegrationError as exc:
        raise SystemExit(str(exc)) from exc
