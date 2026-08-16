from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agentperf import ExperimentSession, trace_llm, trace_run, trace_tool
from agentperf.comparison import compare_paths
from agentperf.metrics.tokens import token_count
from agentperf.regression import evaluate_regression_policy, load_regression_policy
from agentperf.reporters.comparison_html import write_comparison_html
from agentperf.reporters.html import write_html_report
from agentperf.schema.comparison import RunComparison
from agentperf.schema.trace import PromptComponent

DemoFormat = Literal["terminal", "json"]

SYSTEM_PROMPT = (
    "You are a support policy agent. Use retrieved evidence before answering, "
    "separate policy facts from unknowns, and keep the final response concise."
)

TASKS: list[dict[str, str]] = [
    {
        "task_id": "demo-refund-001",
        "query": "Can a customer get a refund for a damaged order?",
        "topic": "refund",
        "expected": "refund",
    },
    {
        "task_id": "demo-shipping-002",
        "query": "Can expedited shipping be waived after a missed delivery promise?",
        "topic": "shipping",
        "expected": "shipping",
    },
    {
        "task_id": "demo-warranty-003",
        "query": "Is a device failure covered under the standard warranty?",
        "topic": "warranty",
        "expected": "warranty",
    },
]

POLICIES = {
    "refund": (
        "REFUND POLICY: damaged delivery is refund eligible when reported within "
        "30 days with an order ID and photo evidence. Support must collect the "
        "order ID, explain that payment timing depends on review, and route "
        "exceptions to the refunds queue. "
    )
    * 22,
    "shipping": (
        "SHIPPING POLICY: expedited shipping may be waived when delivery missed "
        "the promised date and the delay was not caused by weather, address "
        "changes, or customer rescheduling. Capture order ID and promised date. "
    )
    * 22,
    "warranty": (
        "WARRANTY POLICY: standard coverage applies to covered device failures "
        "within one year when there is no evidence of misuse. Ask for serial "
        "number, purchase date, and failure description before routing. "
    )
    * 22,
}

COMPACT_POLICIES = {
    "refund": "refund evidence: damaged order, order ID, photo, within 30 days",
    "shipping": "shipping evidence: missed expedited promise without excluded delay",
    "warranty": "warranty evidence: covered failure within one year without misuse",
}


@dataclass(frozen=True)
class FakeResponse:
    text: str
    input_tokens: int
    output_tokens: int
    request_id: str


@dataclass(frozen=True)
class DemoResult:
    output_dir: Path
    baseline_path: Path
    candidate_path: Path
    report_path: Path
    comparison_report_path: Path
    policy_path: Path
    comparison: RunComparison
    regression_status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": str(self.output_dir),
            "baseline_path": str(self.baseline_path),
            "candidate_path": str(self.candidate_path),
            "report_path": str(self.report_path),
            "comparison_report_path": str(self.comparison_report_path),
            "policy_path": str(self.policy_path),
            "comparison_verdict": self.comparison.acceptance_result.verdict,
            "regression_status": self.regression_status,
            "matched_tasks": self.comparison.matched_tasks,
            "token_deltas": {
                "provider_input_tokens": _metric_delta(self.comparison.token_deltas.input_tokens),
                "component_total_processed_tokens": _metric_delta(
                    self.comparison.token_deltas.component_accounting.total_processed_tokens
                    if self.comparison.token_deltas.component_accounting
                    else _empty_delta()
                ),
                "component_tool_result_processed_tokens": _metric_delta(
                    self.comparison.token_deltas.component_processed_tokens["tool_result"]
                ),
            },
        }


def run_demo(output_dir: Path, *, force: bool = False) -> DemoResult:
    """Run a deterministic local AgentPerf demo using only public instrumentation APIs."""

    _prepare_output_dir(output_dir, force=force)
    baseline_path = output_dir / "baseline"
    candidate_path = output_dir / "candidate"
    report_path = output_dir / "baseline-report.html"
    comparison_report_path = output_dir / "comparison.html"
    policy_path = output_dir / "agentperf-regression.yaml"

    _run_workload(baseline_path, variant="raw")
    _run_workload(candidate_path, variant="optimized")
    write_html_report(baseline_path, report_path, title="AgentPerf Demo Baseline")
    _write_policy(policy_path)
    comparison = compare_paths(baseline_path, candidate_path)
    regression = evaluate_regression_policy(comparison, load_regression_policy(policy_path))
    write_comparison_html(
        baseline_path,
        candidate_path,
        comparison_report_path,
        regression_result=regression,
        title="AgentPerf Demo Replay Verification",
    )
    return DemoResult(
        output_dir=output_dir,
        baseline_path=baseline_path,
        candidate_path=candidate_path,
        report_path=report_path,
        comparison_report_path=comparison_report_path,
        policy_path=policy_path,
        comparison=comparison,
        regression_status=regression.status,
    )


def render_demo_result(result: DemoResult, *, output_format: DemoFormat = "terminal") -> str:
    if output_format == "json":
        return json.dumps(result.to_dict(), indent=2, sort_keys=True)
    comparison = result.comparison
    finding_ids = [
        change.finding_id
        for change in comparison.finding_changes
        if change.lifecycle in {"RESOLVED", "PERSISTENT"}
    ]
    lines = [
        "AgentPerf Demo",
        "",
        "Baseline artifact",
        f"  {result.baseline_path}",
        "Candidate artifact",
        f"  {result.candidate_path}",
        "",
        "What happened",
        f"  matched tasks                  {len(comparison.matched_tasks)}",
        f"  finding signal                 {', '.join(finding_ids) if finding_ids else 'none'}",
        f"  comparison verdict             {comparison.acceptance_result.verdict}",
        f"  regression policy              {result.regression_status}",
        "",
        "Key deltas",
        _format_delta(
            "provider input tokens",
            comparison.token_deltas.input_tokens.baseline,
            comparison.token_deltas.input_tokens.candidate,
            comparison.token_deltas.input_tokens.percent_delta,
        ),
        _format_delta(
            "component processed tokens",
            _component_total_delta(comparison).baseline,
            _component_total_delta(comparison).candidate,
            _component_total_delta(comparison).percent_delta,
        ),
        _format_delta(
            "tool-result processed tokens",
            _component_delta(comparison, "tool_result").baseline,
            _component_delta(comparison, "tool_result").candidate,
            _component_delta(comparison, "tool_result").percent_delta,
        ),
        _format_delta(
            "mean quality",
            comparison.quality_deltas.mean_score.baseline
            if comparison.quality_deltas.mean_score
            else None,
            comparison.quality_deltas.mean_score.candidate
            if comparison.quality_deltas.mean_score
            else None,
            comparison.quality_deltas.mean_score.percent_delta
            if comparison.quality_deltas.mean_score
            else None,
        ),
        "",
        f"Profiler report: {result.report_path}",
        f"Comparison report: {result.comparison_report_path}",
        "",
        "Next:",
        f"  agentperf doctor {result.baseline_path}",
        f"  agentperf report {result.baseline_path} --output {result.output_dir / 'report.html'}",
        f"  agentperf compare {result.baseline_path} {result.candidate_path}",
        (
            f"  agentperf check {result.baseline_path} {result.candidate_path} "
            f"--policy {result.policy_path}"
        ),
    ]
    return "\n".join(lines)


def _run_workload(output_path: Path, *, variant: Literal["raw", "optimized"]) -> None:
    with ExperimentSession(
        output_path=output_path,
        artifact_id=f"agentperf-demo-{variant}",
        workload_id="agentperf-demo-support-agent",
        expected_task_count=len(TASKS),
        framework="framework-free",
        agent_name="demo-support-policy-agent",
        backend="deterministic-local",
        model="fake-demo-model",
        mean_score_tolerance=0.0,
        pass_rate_tolerance=0.0,
        environment={
            "demo": True,
            "serving_telemetry": False,
            "variant": variant,
        },
    ) as experiment:
        for task in TASKS:
            answer = _run_task(task, variant=variant)
            passed = task["expected"] in answer.lower()
            experiment.record_task_result(
                task_id=task["task_id"],
                passed=passed,
                quality_score=1.0 if passed else 0.0,
                evaluator="deterministic-keyword-match@1",
                status="COMPLETE",
                metadata={"topic": task["topic"], "variant": variant},
            )


def _run_task(task: dict[str, str], *, variant: Literal["raw", "optimized"]) -> str:
    with trace_run(task_id=task["task_id"], name="demo support task"):
        planner_components = {"system": SYSTEM_PROMPT, "user": task["query"]}
        with trace_llm(
            model="fake-demo-model",
            provider="deterministic-local",
            semantic_role="planner",
            components=planner_components,
        ) as call:
            response = _fake_model(
                planner_components,
                request_id=f"{task['task_id']}-planner",
                answer=f"Plan: lookup {task['topic']} policy before answering.",
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )

        tool_id = f"{task['task_id']}-policy"
        with trace_tool(
            "lookup_policy",
            tool_call_id=tool_id,
            input={"topic": task["topic"]},
        ) as tool:
            policy = POLICIES[task["topic"]]
            tool.record_output(policy)

        policy_context = policy if variant == "raw" else COMPACT_POLICIES[task["topic"]]
        review_components = _policy_components(task, policy_context, tool_id)
        with trace_llm(
            model="fake-demo-model",
            provider="deterministic-local",
            semantic_role="reviewer",
            components=review_components,
        ) as call:
            response = _fake_model(
                review_components,
                request_id=f"{task['task_id']}-reviewer",
                answer="Policy evidence is sufficient for final response.",
            )
            call.record_response(
                output=response.text,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                request_id=response.request_id,
            )

        final_components = _policy_components(task, policy_context, tool_id)
        with trace_llm(
            model="fake-demo-model",
            provider="deterministic-local",
            semantic_role="final",
            components=final_components,
        ) as call:
            answer = _final_answer(task["topic"])
            response = _fake_model(
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


def _policy_components(
    task: dict[str, str],
    policy_context: str,
    tool_id: str,
) -> list[PromptComponent]:
    return [
        PromptComponent(name="system", text=SYSTEM_PROMPT),
        PromptComponent(name="user", text=task["query"]),
        PromptComponent(
            name="tool_result",
            text=policy_context,
            metadata={"source_tool_call_ids": [tool_id], "topic": task["topic"]},
        ),
    ]


def _fake_model(
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


def _final_answer(topic: str) -> str:
    if topic == "refund":
        return "Refund route: collect order ID and photo for damaged-order refund review."
    if topic == "shipping":
        return "Shipping route: expedited shipping waiver may apply after missed promise."
    return "Warranty route: covered device failure may qualify within one year."


def _write_policy(path: Path) -> None:
    path.write_text(
        """schema_version: 1
quality:
  mean_score:
    max_drop: 0.0
  pass_rate:
    max_drop: 0.0
performance:
  component.total.processed_tokens:
    max_increase_percent: 5
  component.tool_result.processed_tokens:
    max_increase_percent: 5
findings:
  fail_on_new_material_findings: true
task_coverage:
  require_same_tasks: false
  allow_partial: false
""",
        encoding="utf-8",
    )


def _prepare_output_dir(output_dir: Path, *, force: bool) -> None:
    if output_dir.exists():
        if not force and any(output_dir.iterdir()):
            raise FileExistsError(
                f"demo output directory already exists and is not empty: {output_dir}\n"
                "Use --force to replace AgentPerf demo output."
            )
        if force:
            shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _metric_delta(delta: Any) -> dict[str, float | int | None]:
    return {
        "baseline": delta.baseline,
        "candidate": delta.candidate,
        "absolute_delta": delta.delta,
        "percent_delta": delta.percent_delta,
    }


def _component_delta(comparison: RunComparison, component: str) -> Any:
    return comparison.token_deltas.component_processed_tokens[component]


def _component_total_delta(comparison: RunComparison) -> Any:
    if comparison.token_deltas.component_accounting is None:
        return _empty_delta()
    return comparison.token_deltas.component_accounting.total_processed_tokens


def _empty_delta() -> Any:
    class EmptyDelta:
        baseline = None
        candidate = None
        delta = None
        percent_delta = None

    return EmptyDelta()


def _format_delta(
    label: str,
    baseline: int | float | None,
    candidate: int | float | None,
    relative_delta: float | None,
) -> str:
    if baseline is None or candidate is None:
        return f"  {label:<31} unavailable"
    suffix = ""
    if relative_delta is not None:
        suffix = f" ({relative_delta * 100:+.1f}%)"
    return f"  {label:<31} {baseline:g} -> {candidate:g}{suffix}"
