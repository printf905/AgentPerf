from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact, is_artifact_path, load_artifact
from agentperf.comparison import (
    LoadedWorkload,
    compare_paths,
    comparison_to_dict,
    load_workload,
)
from agentperf.metrics.components import COMPONENT_ORDER
from agentperf.metrics.tokens import call_input_tokens
from agentperf.recommendations import (
    recommendation_contract_for_id,
    verify_recommendation,
)
from agentperf.regression import regression_result_to_dict
from agentperf.schema.comparison import FindingChange, MetricDelta, RunComparison
from agentperf.schema.regression import RegressionResult
from agentperf.schema.trace import AgentRun, LLMCall, ServingRequest


@dataclass(frozen=True)
class ComparisonHtmlInput:
    comparison: RunComparison
    baseline_path: str
    candidate_path: str
    baseline: LoadedWorkload
    candidate: LoadedWorkload
    regression_result: RegressionResult | None = None
    title: str = "AgentPerf Replay Verification"


def load_comparison_html_input(
    baseline_path: Path,
    candidate_path: Path,
    *,
    mean_score_tolerance: float | None = None,
    pass_rate_tolerance: float | None = None,
    min_material_improvement: float = 0.05,
    regression_result: RegressionResult | None = None,
    title: str | None = None,
) -> ComparisonHtmlInput:
    comparison = compare_paths(
        baseline_path,
        candidate_path,
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
        min_material_improvement=min_material_improvement,
    )
    return build_comparison_html_input(
        comparison,
        baseline_path,
        candidate_path,
        regression_result=regression_result,
        title=title,
    )


def build_comparison_html_input(
    comparison: RunComparison,
    baseline_path: Path,
    candidate_path: Path,
    *,
    regression_result: RegressionResult | None = None,
    title: str | None = None,
) -> ComparisonHtmlInput:
    return ComparisonHtmlInput(
        comparison=comparison,
        baseline_path=str(baseline_path),
        candidate_path=str(candidate_path),
        baseline=load_workload(baseline_path),
        candidate=load_workload(candidate_path),
        regression_result=regression_result,
        title=title or "AgentPerf Replay Verification",
    )


def write_comparison_html(
    baseline_path: Path,
    candidate_path: Path,
    output_path: Path,
    *,
    mean_score_tolerance: float | None = None,
    pass_rate_tolerance: float | None = None,
    min_material_improvement: float = 0.05,
    regression_result: RegressionResult | None = None,
    title: str | None = None,
) -> None:
    report_input = load_comparison_html_input(
        baseline_path,
        candidate_path,
        mean_score_tolerance=mean_score_tolerance,
        pass_rate_tolerance=pass_rate_tolerance,
        min_material_improvement=min_material_improvement,
        regression_result=regression_result,
        title=title,
    )
    output_path.write_text(render_comparison_html(report_input), encoding="utf-8")


def render_comparison_html(report_input: ComparisonHtmlInput) -> str:
    comparison = report_input.comparison
    payload = {
        "comparison": comparison_to_dict(comparison),
        "policy_result": (
            regression_result_to_dict(report_input.regression_result)
            if report_input.regression_result
            else None
        ),
        "baseline_path": report_input.baseline_path,
        "candidate_path": report_input.candidate_path,
    }
    sections = [
        _verdict(report_input),
        _overview(comparison),
        _quality(comparison),
        _task_coverage(comparison, report_input),
        _token_accounting(comparison),
        _finding_lifecycle(comparison),
        _context_growth(comparison, report_input),
        _tool_output_carry_forward(report_input),
        _model_routing(comparison),
        _multi_agent(comparison),
        _latency(comparison),
        _cache(comparison),
        _serving(report_input),
        _environment(report_input),
        _policy(report_input.regression_result),
        _warnings(comparison),
    ]
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{_h(report_input.title)}</title>",
            "<style>",
            _CSS,
            "</style>",
            "</head>",
            "<body>",
            (
                '<script type="application/json" id="agentperf-comparison-data">'
                f"{_h(json.dumps(_redact_payload(payload), sort_keys=True))}</script>"
            ),
            '<main class="page">',
            _hero(report_input),
            *sections,
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def _hero(report_input: ComparisonHtmlInput) -> str:
    comparison = report_input.comparison
    return (
        '<section class="hero">'
        "<div>"
        "<p class=\"eyebrow\">Replay Verification</p>"
        f"<h1>{_h(report_input.title)}</h1>"
        f"<p>{_h(comparison.acceptance_result.reason)}</p>"
        "</div>"
        f'<div class="verdict-card {comparison.acceptance_result.verdict.lower()}">'
        "<span>Verdict</span>"
        f"<strong>{_h(_verdict_label(comparison.acceptance_result.verdict))}</strong>"
        "</div>"
        "</section>"
    )


def _verdict(report_input: ComparisonHtmlInput) -> str:
    result = report_input.comparison.acceptance_result
    quality_note = ""
    if result.verdict == "REJECT_QUALITY_REGRESSION":
        quality_note = (
            '<p class="callout bad"><strong>Quality regression dominates.</strong> '
            "Performance improvements are not accepted when configured quality "
            "constraints fail.</p>"
        )
    elif result.quality_passed is None:
        quality_note = (
            '<p class="callout warn"><strong>Quality verification unavailable.</strong> '
            "Performance improvement cannot be fully accepted without task quality "
            "evidence.</p>"
        )
    return _section(
        "Top-Level Verdict",
        '<div class="metric-grid compact">'
        + _metric("Verdict", _verdict_label(result.verdict))
        + _metric("Performance improved", _bool_status(result.performance_improved))
        + _metric("Quality gate", _quality_gate(result.quality_passed))
        + _metric("Material regression", _bool_status(result.material_regression))
        + "</div>"
        + f"<p>{_h(result.reason)}</p>"
        + quality_note,
    )


def _overview(comparison: RunComparison) -> str:
    rows = [
        ("Tasks", _counts(len(comparison.matched_tasks), len(comparison.matched_tasks))),
        ("Mean quality", _delta_text(comparison.quality_deltas.mean_score)),
        ("Pass rate", _delta_text(comparison.quality_deltas.pass_rate, ratio=True)),
        ("Provider input tokens", _delta_text(comparison.token_deltas.input_tokens, integer=True)),
        (
            "Provider output tokens",
            _delta_text(comparison.token_deltas.output_tokens, integer=True),
        ),
        (
            "Component processed tokens",
            _delta_text(
                comparison.token_deltas.component_accounting.total_processed_tokens
                if comparison.token_deltas.component_accounting
                else _empty_delta(),
                integer=True,
            ),
        ),
        (
            "Client P95",
            _delta_text(comparison.latency_deltas.client_p95_ms, suffix=" ms"),
        ),
        (
            "Scheduled-to-first P95",
            _delta_text(
                comparison.latency_deltas.scheduled_to_first_p95_ms,
                suffix=" ms",
            ),
        ),
    ]
    return _section(
        "Baseline vs Candidate Overview",
        _metric_table(
            ["Metric", "Baseline -> Candidate", "Delta"],
            [
                [
                    label,
                    _baseline_candidate(value),
                    _delta_only(value),
                ]
                for label, value in rows
            ],
        )
        + (
            '<p class="note">Only available metrics are compared. Missing evidence is '
            'shown as unavailable, not zero.</p>'
        ),
    )


def _quality(comparison: RunComparison) -> str:
    q = comparison.quality_deltas
    changes = comparison.metadata.get("task_quality_changes", [])
    body = (
        '<div class="metric-grid compact">'
        + _metric("Mean score", _delta_text(q.mean_score))
        + _metric("Pass rate", _delta_text(q.pass_rate, ratio=True))
        + _metric("Mean-score tolerance", _fmt_optional(q.mean_score_tolerance))
        + _metric("Pass-rate tolerance", _fmt_optional(q.pass_rate_tolerance, ratio=True))
        + _metric("Quality gate", _quality_gate(q.passed))
        + "</div>"
    )
    if q.passed is None:
        body += (
            '<p class="callout warn">Quality verification unavailable. Performance '
            "improvement cannot be fully accepted.</p>"
        )
    if isinstance(changes, list) and changes:
        rows = [
            [
                _safe_text(item.get("task_id", "unknown")),
                _pass_text(item.get("baseline_passed")),
                _pass_text(item.get("candidate_passed")),
                _fmt_optional(item.get("baseline_score")),
                _fmt_optional(item.get("candidate_score")),
            ]
            for item in changes
            if isinstance(item, dict)
        ]
        body += "<h3>Task regressions / quality changes</h3>"
        body += _metric_table(
            ["Task", "Baseline", "Candidate", "Baseline score", "Candidate score"],
            rows,
        )
    else:
        body += '<p class="empty">No task-level quality changes recorded.</p>'
    return _section("Quality Verification", body)


def _task_coverage(comparison: RunComparison, report_input: ComparisonHtmlInput) -> str:
    rows = [
        ["Matched tasks", str(len(comparison.matched_tasks))],
        ["Unmatched baseline tasks", str(len(comparison.unmatched_baseline_tasks))],
        ["Unmatched candidate tasks", str(len(comparison.unmatched_candidate_tasks))],
        [
            "Coverage",
            _coverage_text(
                len(comparison.matched_tasks),
                len(comparison.matched_tasks) + len(comparison.unmatched_baseline_tasks),
            ),
        ],
    ]
    details = ""
    if comparison.unmatched_baseline_tasks or comparison.unmatched_candidate_tasks:
        details += (
            '<p class="callout warn">Task sets differ. Treat performance deltas as '
            "inconclusive until coverage is reviewed.</p>"
        )
    details += _task_drilldown(report_input)
    return _section(
        "Task Matching and Execution Drill-Down",
        _metric_table(["Coverage item", "Value"], rows) + details,
    )


def _token_accounting(comparison: RunComparison) -> str:
    components = comparison.token_deltas.component_processed_tokens
    ranked = sorted(
        components.items(),
        key=lambda item: abs(float(item[1].delta or 0)),
        reverse=True,
    )
    ordered = [
        (component, components[component])
        for component in COMPONENT_ORDER
        if component in components
    ]
    ordered.extend((name, delta) for name, delta in ranked if name not in COMPONENT_ORDER)
    largest_rows = [
        [
            _component_label(name),
            _baseline_candidate(_delta_text(delta, integer=True)),
            _delta_only(_delta_text(delta, integer=True)),
        ]
        for name, delta in ranked[:5]
    ]
    component_rows = [
        [
            _component_label(name),
            _fmt_optional(delta.baseline, integer=True),
            _fmt_optional(delta.candidate, integer=True),
            _fmt_optional(delta.delta, integer=True, signed=True),
            _fmt_percent(delta.percent_delta, signed=True),
        ]
        for name, delta in ordered
    ]
    body = (
        "<h3>Model / Provider Usage</h3>"
        + _metric_table(
            ["Metric", "Baseline", "Candidate", "Delta", "%"],
            [
                _delta_row(
                    "Provider input tokens",
                    comparison.token_deltas.input_tokens,
                    integer=True,
                ),
                _delta_row(
                    "Provider output tokens",
                    comparison.token_deltas.output_tokens,
                    integer=True,
                ),
            ],
        )
        + '<p class="note">Provider usage is reported by the model/provider layer.</p>'
        + "<h3>Agent Context Attribution</h3>"
    )
    if comparison.token_deltas.component_accounting is not None:
        accounting = comparison.token_deltas.component_accounting
        body += _metric_table(
            ["Metric", "Baseline", "Candidate", "Delta", "%"],
            [
                _delta_row(
                    "Total processed tokens",
                    accounting.total_processed_tokens,
                    integer=True,
                ),
                _delta_row("Total unique tokens", accounting.total_unique_tokens, integer=True),
                _delta_row(
                    "Other processed tokens",
                    accounting.other_processed_tokens,
                    integer=True,
                ),
                _delta_row(
                    "Attribution coverage",
                    accounting.attribution_coverage_ratio,
                    ratio=True,
                ),
            ],
        )
        body += (
            f'<p class="note">Attribution confidence: '
            f"{_h(accounting.baseline_confidence)} -> "
            f"{_h(accounting.candidate_confidence)}.</p>"
        )
    if largest_rows:
        body += "<h3>Largest context changes</h3>"
        body += _metric_table(["Component", "Baseline -> Candidate", "Delta"], largest_rows)
    if component_rows:
        body += "<h3>Component processed-token deltas</h3>"
        body += _metric_table(["Component", "Baseline", "Candidate", "Delta", "%"], component_rows)
    else:
        body += '<p class="empty">Component attribution unavailable.</p>'
    return _section("Token Accounting", body)


def _finding_lifecycle(comparison: RunComparison) -> str:
    if not comparison.finding_changes:
        return _section("Finding Lifecycle", '<p class="empty">No finding changes.</p>')
    rows = []
    for change in sorted(comparison.finding_changes, key=_finding_sort_key):
        rows.append(
            [
                change.finding_id,
                change.lifecycle,
                _severity(change.baseline_severity, change.baseline_materiality),
                _severity(change.candidate_severity, change.candidate_materiality),
                change.scope or "trace",
            ]
        )
    details = ""
    for change in sorted(comparison.finding_changes, key=_finding_sort_key):
        baseline_severity = _severity(change.baseline_severity, change.baseline_materiality)
        candidate_severity = _severity(change.candidate_severity, change.candidate_materiality)
        verification = _recommendation_verification_html(comparison, change)
        details += (
            '<details class="finding">'
            f"<summary>{_h(change.finding_id)} · {_h(change.lifecycle)}</summary>"
            f"<p><strong>Baseline:</strong> {_h(baseline_severity)}</p>"
            f"<p><strong>Candidate:</strong> {_h(candidate_severity)}</p>"
            f"<p><strong>Scope:</strong> {_h(change.scope or 'trace')}</p>"
            f"<p><strong>Baseline evidence:</strong> {_h(change.baseline_summary or 'absent')}</p>"
            f"<p><strong>Candidate evidence:</strong> "
            f"{_h(change.candidate_summary or 'absent')}</p>"
            f"{verification}"
            "</details>"
        )
    return _section(
        "Finding Lifecycle",
        _metric_table(
            ["Finding", "Lifecycle", "Baseline", "Candidate", "Scope"],
            rows,
        )
        + details,
    )


def _recommendation_verification_html(
    comparison: RunComparison,
    change: FindingChange,
) -> str:
    contract = recommendation_contract_for_id(
        change.finding_id,
        severity=change.baseline_severity or change.candidate_severity,
        materiality=change.baseline_materiality or change.candidate_materiality,
    )
    if contract is None:
        return ""
    verification = verify_recommendation(
        comparison,
        contract,
        finding_id=change.finding_id,
        finding_change=change,
    )
    rows = [
        [
            check.metric,
            check.direction,
            "required" if check.required else "supporting",
            check.observed
            or _metric_observed(check.baseline, check.candidate, check.delta),
            check.status,
        ]
        for check in verification.metric_checks
    ]
    body = (
        "<h4>Recommendation verification</h4>"
        f"<p><strong>Status:</strong> {_h(verification.status)}</p>"
        f"<p><strong>Quality requirement:</strong> {_h(verification.quality_status)}</p>"
        f"<p>{_h(verification.reason)}</p>"
        f"<p><strong>Objective:</strong> {_h(contract.objective)}</p>"
        f"<p><strong>Applicability:</strong> {_h(contract.applicability)}</p>"
    )
    if rows:
        body += _metric_table(
            ["Metric", "Expected", "Requirement", "Observed", "Result"],
            rows,
        )
    else:
        body += '<p class="empty">No machine-checkable metric expectation.</p>'
    return body


def _metric_observed(
    baseline: float | int | None,
    candidate: float | int | None,
    delta: float | int | None,
) -> str:
    if baseline is None or candidate is None:
        return "Unavailable"
    text = f"{_fmt_optional(baseline)} -> {_fmt_optional(candidate)}"
    if delta is not None:
        text += f" ({_fmt_optional(delta, signed=True)})"
    return text


def _context_growth(comparison: RunComparison, report_input: ComparisonHtmlInput) -> str:
    delta = comparison.context_growth_delta
    rows = [
        _delta_row("Final step input tokens", delta.final_step_input_tokens, integer=True),
        _delta_row("Max step input tokens", delta.max_step_input_tokens, integer=True),
        _delta_row("Growth slope tokens/step", delta.growth_slope_tokens_per_step),
        ["LLM steps", str(delta.baseline_steps), str(delta.candidate_steps), "", ""],
    ]
    return _section(
        "Context-Growth Comparison",
        _metric_table(["Metric", "Baseline", "Candidate", "Delta", "%"], rows)
        + _context_task_tables(report_input),
    )


def _tool_output_carry_forward(report_input: ComparisonHtmlInput) -> str:
    baseline = _tool_reinjection_summary(report_input.baseline.runs)
    candidate = _tool_reinjection_summary(report_input.candidate.runs)
    rows = [
        [
            "Tool-result unique content",
            _fmt_optional(baseline["raw_output_tokens"], integer=True),
            _fmt_optional(candidate["raw_output_tokens"], integer=True),
            _fmt_optional(
                candidate["raw_output_tokens"] - baseline["raw_output_tokens"],
                integer=True,
                signed=True,
            ),
        ],
        [
            "Cumulative downstream processing",
            _fmt_optional(baseline["cumulative_processed_tokens"], integer=True),
            _fmt_optional(candidate["cumulative_processed_tokens"], integer=True),
            _fmt_optional(
                candidate["cumulative_processed_tokens"]
                - baseline["cumulative_processed_tokens"],
                integer=True,
                signed=True,
            ),
        ],
        [
            "Reinjected LLM calls",
            _fmt_optional(baseline["reinjected_calls"], integer=True),
            _fmt_optional(candidate["reinjected_calls"], integer=True),
            _fmt_optional(
                candidate["reinjected_calls"] - baseline["reinjected_calls"],
                integer=True,
                signed=True,
            ),
        ],
    ]
    return _section(
        "Tool-Output Carry-Forward",
        _metric_table(["Evidence", "Baseline", "Candidate", "Delta"], rows)
        + (
            '<p class="note">Unique content is counted from tool outputs. '
            "Cumulative downstream processing counts repeated prompt-component "
            "processing caused by carry-forward.</p>"
        ),
    )


def _model_routing(comparison: RunComparison) -> str:
    baseline = comparison.metadata.get("baseline_model_routing")
    candidate = comparison.metadata.get("candidate_model_routing")
    if not isinstance(baseline, dict) or not isinstance(candidate, dict):
        return _section("Model Routing", '<p class="empty">Model-role metadata unavailable.</p>')
    if not baseline.get("available") and not candidate.get("available"):
        return _section("Model Routing", '<p class="empty">Model-role metadata unavailable.</p>')
    baseline_map = _routing_role_map(baseline)
    candidate_map = _routing_role_map(candidate)
    roles = sorted(set(baseline_map) | set(candidate_map))
    rows = [
        [
            role,
            baseline_map.get(role, "Unavailable"),
            candidate_map.get(role, "Unavailable"),
            _routing_delta(baseline_map.get(role), candidate_map.get(role)),
        ]
        for role in roles
    ]
    return _section(
        "Model Routing",
        _metric_table(["Role", "Baseline model", "Candidate model", "Change"], rows)
        + (
            '<p class="note">Role/model assignments come from trace metadata. '
            "They describe the replay configuration; model-capacity acceptance still "
            "requires quality-aware comparison evidence.</p>"
        ),
    )


def _routing_role_map(summary: dict[str, object]) -> dict[str, str]:
    raw_map = summary.get("role_model_map")
    if isinstance(raw_map, dict):
        return {str(role): str(model) for role, model in raw_map.items()}
    assignments = summary.get("assignments")
    result: dict[str, str] = {}
    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, dict):
                continue
            role = item.get("role_id")
            model = item.get("model")
            if role is None or model is None:
                continue
            role_key = str(role)
            model_value = str(model)
            if role_key in result and result[role_key] != model_value:
                result[role_key] = "Mixed"
            else:
                result[role_key] = model_value
    return result


def _routing_delta(baseline: str | None, candidate: str | None) -> str:
    if baseline is None or candidate is None:
        return "Unavailable"
    if baseline == candidate:
        return "unchanged"
    return f"{baseline} -> {candidate}"


def _multi_agent(comparison: RunComparison) -> str:
    data = comparison.metadata.get("multi_agent_comparison")
    if not isinstance(data, dict) or not data.get("has_metadata"):
        return ""
    rows = []
    deltas = data.get("agent_deltas")
    if isinstance(deltas, list):
        for item in deltas:
            if not isinstance(item, dict):
                continue
            rows.append(
                [
                    str(item.get("agent_id") or "unknown"),
                    _fmt_optional(item.get("baseline_provider_input_tokens"), integer=True),
                    _fmt_optional(item.get("candidate_provider_input_tokens"), integer=True),
                    _fmt_optional(
                        item.get("provider_input_token_delta"),
                        integer=True,
                        signed=True,
                    ),
                    _fmt_optional(item.get("baseline_component_processed_tokens"), integer=True),
                    _fmt_optional(item.get("candidate_component_processed_tokens"), integer=True),
                    _fmt_optional(
                        item.get("component_processed_token_delta"),
                        integer=True,
                        signed=True,
                    ),
                    _fmt_optional(item.get("llm_call_delta"), integer=True, signed=True),
                    _fmt_optional(item.get("tool_call_delta"), integer=True, signed=True),
                ]
            )
    summary = (
        '<div class="metric-grid compact">'
        + _metric("Added agents", _list_value(data.get("added_agents")))
        + _metric("Removed agents", _list_value(data.get("removed_agents")))
        + _metric("Added branches", _list_value(data.get("added_branches")))
        + _metric("Removed branches", _list_value(data.get("removed_branches")))
        + _metric(
            "Branch count",
            f"{_fmt_optional(data.get('baseline_branch_count'), integer=True)} -> "
            f"{_fmt_optional(data.get('candidate_branch_count'), integer=True)}",
        )
        + _metric(
            "Handoff count",
            f"{_fmt_optional(data.get('baseline_handoff_count'), integer=True)} -> "
            f"{_fmt_optional(data.get('candidate_handoff_count'), integer=True)}",
        )
        + "</div>"
    )
    return _section(
        "Multi-Agent Comparison",
        summary
        + _metric_table(
            [
                "Agent",
                "Baseline input",
                "Candidate input",
                "Input delta",
                "Baseline component",
                "Candidate component",
                "Component delta",
                "LLM delta",
                "Tool delta",
            ],
            rows,
        )
        + (
            '<p class="note">Agent and branch comparison uses explicit stable IDs. '
            "Changed identities are reported as added or removed instead of inferred "
            "through graph matching.</p>"
        ),
    )


def _list_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    return "none"


def _latency(comparison: RunComparison) -> str:
    rows = [
        _delta_row("Client P50", comparison.latency_deltas.client_p50_ms, suffix=" ms"),
        _delta_row("Client P95", comparison.latency_deltas.client_p95_ms, suffix=" ms"),
        _delta_row("Queue P50", comparison.latency_deltas.queue_p50_ms, suffix=" ms"),
        _delta_row("Queue P95", comparison.latency_deltas.queue_p95_ms, suffix=" ms"),
        _delta_row(
            "Scheduled-to-first P50",
            comparison.latency_deltas.scheduled_to_first_p50_ms,
            suffix=" ms",
        ),
        _delta_row(
            "Scheduled-to-first P95",
            comparison.latency_deltas.scheduled_to_first_p95_ms,
            suffix=" ms",
        ),
        _delta_row(
            "Generation/decode P50",
            comparison.latency_deltas.generation_p50_ms,
            suffix=" ms",
        ),
        _delta_row(
            "Generation/decode P95",
            comparison.latency_deltas.generation_p95_ms,
            suffix=" ms",
        ),
        _delta_row("Tool latency total", comparison.latency_deltas.tool_latency_ms, suffix=" ms"),
    ]
    return _section(
        "Latency",
        _metric_table(["Metric", "Baseline", "Candidate", "Delta", "%"], rows)
        + (
            '<p class="note">Scheduled-to-first is the server/client first-token path '
            "available in telemetry; it is not pure GPU prefill kernel latency.</p>"
        ),
    )


def _cache(comparison: RunComparison) -> str:
    rows = [
        _delta_row("Cached tokens", comparison.cache_deltas.cached_tokens, integer=True),
        _delta_row(
            "Uncached / miss tokens",
            comparison.cache_deltas.cache_miss_tokens,
            integer=True,
        ),
        _delta_row("Cache ratio", comparison.cache_deltas.cached_token_ratio, ratio=True),
    ]
    unavailable = all(row[1] == "Unavailable" and row[2] == "Unavailable" for row in rows)
    note = (
        '<p class="empty">Cache comparison unavailable or telemetry is incompatible.</p>'
        if unavailable
        else (
            '<p class="note">Cache evidence is compared only where compatible telemetry '
            "exists.</p>"
        )
    )
    return _section(
        "Cache Evidence",
        _metric_table(["Metric", "Baseline", "Candidate", "Delta", "%"], rows) + note,
    )


def _serving(report_input: ComparisonHtmlInput) -> str:
    baseline = _serving_summary(report_input.baseline.runs)
    candidate = _serving_summary(report_input.candidate.runs)
    rows = [
        ["Serving requests", str(baseline["requests"]), str(candidate["requests"])],
        [
            "LLM calls with request IDs",
            str(baseline["llm_request_ids"]),
            str(candidate["llm_request_ids"]),
        ],
        ["Exact correlations", str(baseline["exact"]), str(candidate["exact"])],
    ]
    examples = _serving_examples(report_input.baseline.runs, "Baseline")
    examples += _serving_examples(report_input.candidate.runs, "Candidate")
    return _section(
        "Cross-Layer Serving Correlation",
        _metric_table(["Evidence", "Baseline", "Candidate"], rows)
        + (
            examples
            or (
                '<p class="empty">No serving telemetry recorded. Agent-only artifacts '
                "remain valid.</p>"
            )
        ),
    )


def _environment(report_input: ComparisonHtmlInput) -> str:
    base = _environment_summary(report_input.baseline_path, report_input.baseline.artifact)
    cand = _environment_summary(report_input.candidate_path, report_input.candidate.artifact)
    rows = [
        [key, str(base.get(key, "Unavailable")), str(cand.get(key, "Unavailable"))]
        for key in sorted(set(base) | set(cand))
    ]
    mismatch = any(row[1] != row[2] for row in rows)
    note = (
        '<p class="callout warn">Environment differs. Latency may not be directly comparable; '
        "token and quality evidence can still be useful.</p>"
        if mismatch
        else (
            '<p class="note">No compared environment differences detected in artifact '
            "metadata.</p>"
        )
    )
    return _section(
        "Environment Compatibility",
        _metric_table(["Field", "Baseline", "Candidate"], rows) + note,
    )


def _policy(result: RegressionResult | None) -> str:
    if result is None:
        return _section("Regression Policy", '<p class="empty">No policy result embedded.</p>')
    rows = [
        [
            check.category.replace("_", " ").title(),
            check.metric,
            _fmt_optional(check.allowed),
            _fmt_optional(
                check.actual_delta if check.actual_delta is not None else check.candidate
            ),
            check.result,
        ]
        for check in result.checks
    ]
    return _section(
        "Regression Policy",
        '<div class="metric-grid compact">'
        + _metric("Policy result", result.status)
        + _metric("Comparison verdict", str(result.metadata.get("comparison_verdict", "unknown")))
        + "</div>"
        + _metric_table(["Check", "Metric", "Allowed", "Actual", "Result"], rows),
    )


def _warnings(comparison: RunComparison) -> str:
    if not comparison.warnings:
        return _section("Warnings", '<p class="empty">No comparison warnings.</p>')
    return _section(
        "Warnings",
        "<ul>" + "".join(f"<li>{_h(warning)}</li>" for warning in comparison.warnings) + "</ul>",
    )


def _task_drilldown(report_input: ComparisonHtmlInput) -> str:
    baseline_by_task = _runs_by_task_id(report_input.baseline.runs)
    candidate_by_task = _runs_by_task_id(report_input.candidate.runs)
    matched = _matched_run_keys(report_input)
    if not matched:
        return '<p class="empty">No matched task execution details available.</p>'
    body = "<h3>Matched task execution</h3>"
    for task_id in matched[:10]:
        base = baseline_by_task.get(task_id)
        cand = candidate_by_task.get(task_id)
        if base is None or cand is None:
            continue
        summary = (
            f"{len(base.llm_calls)} -> {len(cand.llm_calls)} LLM calls; "
            f"{len(base.tool_calls)} -> {len(cand.tool_calls)} tool calls"
        )
        body += (
            '<details class="run">'
            f"<summary>{_h(_safe_text(task_id))} <span>{_h(summary)}</span></summary>"
            '<div class="two-col">'
            + _run_steps("Baseline", base)
            + _run_steps("Candidate", cand)
            + "</div></details>"
        )
    if len(matched) > 10:
        body += f'<p class="note">Showing 10 of {len(matched)} matched tasks.</p>'
    return body


def _context_task_tables(report_input: ComparisonHtmlInput) -> str:
    baseline_by_task = _runs_by_task_id(report_input.baseline.runs)
    candidate_by_task = _runs_by_task_id(report_input.candidate.runs)
    matched = _matched_run_keys(report_input)
    body = ""
    for task_id in matched[:5]:
        base = baseline_by_task.get(task_id)
        cand = candidate_by_task.get(task_id)
        if base is None or cand is None:
            continue
        base_rows = analyze_run(base).context_growth
        cand_rows = analyze_run(cand).context_growth
        max_rows = max(len(base_rows), len(cand_rows))
        if not max_rows:
            continue
        rows = []
        for index in range(max_rows):
            base_value = base_rows[index].input_tokens if index < len(base_rows) else None
            cand_value = cand_rows[index].input_tokens if index < len(cand_rows) else None
            rows.append(
                [
                    str(index + 1),
                    _fmt_optional(base_value, integer=True),
                    _fmt_optional(cand_value, integer=True),
                    _fmt_optional(
                        (cand_value - base_value)
                        if base_value is not None and cand_value is not None
                        else None,
                        integer=True,
                        signed=True,
                    ),
                ]
            )
        body += (
            f"<h3>Context growth: {_h(_safe_text(task_id))}</h3>"
            + _metric_table(["Step", "Baseline input", "Candidate input", "Delta"], rows)
        )
    return body


def _run_steps(label: str, run: AgentRun) -> str:
    rows = []
    for index, call in enumerate(run.llm_calls, start=1):
        rows.append(
            [
                f"LLM #{index}",
                call.llm_call_id,
                _fmt_optional(call_input_tokens(call), integer=True),
            ]
        )
    for index, tool in enumerate(run.tool_calls, start=1):
        rows.append(
            [
                f"Tool #{index}",
                tool.tool_call_id,
                _fmt_optional(tool.latency_ms, suffix=" ms"),
            ]
        )
    return (
        "<div>"
        f"<h4>{_h(label)}</h4>"
        + _metric_table(["Step", "ID", "Tokens / latency"], rows)
        + "</div>"
    )


def _tool_reinjection_summary(runs: list[AgentRun]) -> dict[str, int]:
    raw_output_tokens = 0
    cumulative_processed_tokens = 0
    reinjected_calls = 0
    for run in runs:
        report = analyze_run(run)
        for item in report.tool_reinjections:
            raw_output_tokens += item.raw_output_tokens
            cumulative_processed_tokens += item.cumulative_processed_tokens
            reinjected_calls += len(item.reinjected_calls)
    return {
        "raw_output_tokens": raw_output_tokens,
        "cumulative_processed_tokens": cumulative_processed_tokens,
        "reinjected_calls": reinjected_calls,
    }


def _serving_summary(runs: list[AgentRun]) -> dict[str, int]:
    request_ids = {
        request.llm_request_id
        for run in runs
        for request in run.serving_requests
        if request.llm_request_id
    }
    llm_request_ids = [
        call.llm_request_id for run in runs for call in run.llm_calls if call.llm_request_id
    ]
    return {
        "requests": sum(len(run.serving_requests) for run in runs),
        "llm_request_ids": len(llm_request_ids),
        "exact": sum(1 for request_id in llm_request_ids if request_id in request_ids),
    }


def _serving_examples(runs: list[AgentRun], label: str) -> str:
    rows: list[list[str]] = []
    requests: dict[str, ServingRequest] = {
        request.llm_request_id: request
        for run in runs
        for request in run.serving_requests
        if request.llm_request_id
    }
    calls: list[LLMCall] = [call for run in runs for call in run.llm_calls if call.llm_request_id]
    for call in calls[:5]:
        request = requests.get(call.llm_request_id or "")
        rows.append(
            [
                label,
                call.llm_call_id,
                request.serving_request_id if request else call.llm_request_id or "Unavailable",
                "exact" if request else "missing",
                _fmt_optional(request.ttft_ms if request else None, suffix=" ms"),
            ]
        )
    if not rows:
        return ""
    return "<h3>Correlation examples</h3>" + _metric_table(
        ["Side", "LLM call", "Serving request ID", "Correlation", "TTFT"],
        rows,
    )


def _environment_summary(path: str, artifact: ExperimentArtifact | None) -> dict[str, str]:
    if artifact is None and is_artifact_path(Path(path)):
        artifact = load_artifact(Path(path))
    if artifact is None:
        return {"source": path}
    data = {
        "artifact_id": artifact.manifest.artifact_id,
        "workload_id": artifact.manifest.workload_id,
        "framework": artifact.manifest.framework,
        "backend": artifact.manifest.backend,
        "model": artifact.manifest.model,
        "serving_telemetry": str(artifact.manifest.serving_telemetry),
        "status": artifact.manifest.status,
    }
    return {key: _safe_text(value) for key, value in data.items() if value is not None}


def _runs_by_task_id(runs: list[AgentRun]) -> dict[str, AgentRun]:
    result: dict[str, AgentRun] = {}
    counts: dict[str, int] = {}
    for run in runs:
        raw_key = _task_id(run)
        count = counts.get(raw_key, 0) + 1
        counts[raw_key] = count
        result[raw_key if count == 1 else f"{raw_key}#{count}"] = run
    return result


def _task_id(run: AgentRun) -> str:
    for key in ("workload_item_id", "task_id", "execution_id", "run_id"):
        value = run.metadata.get(key)
        if value is not None:
            return str(value)
    return run.agent_run_id


def _matched_run_keys(report_input: ComparisonHtmlInput) -> list[str]:
    raw = report_input.comparison.metadata.get("matched_run_keys")
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return list(raw)
    return list(report_input.comparison.matched_tasks)


def _section(title: str, body: str) -> str:
    return f'<section class="section"><h2>{_h(title)}</h2>{body}</section>'


def _metric(label: str, value: str) -> str:
    return f'<div class="metric"><span>{_h(label)}</span><strong>{_h(value)}</strong></div>'


def _metric_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{_h(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_h(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _delta_row(
    label: str,
    delta: MetricDelta,
    *,
    integer: bool = False,
    ratio: bool = False,
    suffix: str = "",
) -> list[str]:
    return [
        label,
        _fmt_optional(delta.baseline, integer=integer, ratio=ratio, suffix=suffix),
        _fmt_optional(delta.candidate, integer=integer, ratio=ratio, suffix=suffix),
        _fmt_optional(delta.delta, integer=integer, ratio=ratio, suffix=suffix, signed=True),
        _fmt_percent(delta.percent_delta, signed=True),
    ]


def _delta_text(
    delta: MetricDelta,
    *,
    integer: bool = False,
    ratio: bool = False,
    suffix: str = "",
) -> str:
    return (
        f"{_fmt_optional(delta.baseline, integer=integer, ratio=ratio, suffix=suffix)} -> "
        f"{_fmt_optional(delta.candidate, integer=integer, ratio=ratio, suffix=suffix)} "
        f"({_fmt_optional(delta.delta, integer=integer, ratio=ratio, suffix=suffix, signed=True)}, "
        f"{_fmt_percent(delta.percent_delta, signed=True)})"
    )


def _baseline_candidate(text: str) -> str:
    return text.split(" (", 1)[0]


def _delta_only(text: str) -> str:
    if "(" not in text:
        return ""
    return text.split("(", 1)[1].rstrip(")")


def _empty_delta() -> MetricDelta:
    return MetricDelta(None, None, None, None, measurement_quality="UNAVAILABLE")


def _fmt_optional(
    value: object,
    *,
    integer: bool = False,
    ratio: bool = False,
    suffix: str = "",
    signed: bool = False,
) -> str:
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        if ratio:
            return _fmt_percent(float(value), signed=signed)
        if integer:
            formatted = f"{int(round(float(value))):,}"
        else:
            formatted = f"{float(value):.3f}".rstrip("0").rstrip(".")
        if signed and float(value) > 0:
            formatted = f"+{formatted}"
        return f"{formatted}{suffix}"
    return str(value)


def _fmt_percent(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "Unavailable"
    formatted = f"{value * 100:.1f}%"
    if signed and value > 0:
        formatted = f"+{formatted}"
    return formatted


def _component_label(value: str) -> str:
    return value.upper()


def _verdict_label(value: str) -> str:
    return value.replace("_", " ")


def _bool_status(value: bool) -> str:
    return "yes" if value else "no"


def _quality_gate(value: bool | None) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "UNAVAILABLE"


def _pass_text(value: object) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "Unavailable"


def _counts(baseline: int, candidate: int) -> str:
    return f"{baseline:,} -> {candidate:,}"


def _coverage_text(matched: int, baseline_total: int) -> str:
    if baseline_total <= 0:
        return "Unavailable"
    return f"{matched}/{baseline_total} ({matched / baseline_total * 100:.1f}%)"


def _severity(severity: str | None, materiality: str | None) -> str:
    if severity is None:
        return "absent"
    if materiality:
        return f"{severity} / {materiality}"
    return severity


def _finding_sort_key(change: FindingChange) -> tuple[int, str]:
    priority = {"NEW": 0, "REGRESSED": 1, "RESOLVED": 2, "IMPROVED": 3, "PERSISTENT": 4}
    return (priority.get(change.lifecycle, 5), change.finding_id)


def _safe_text(value: object) -> str:
    text = str(value)
    if _secretish_text(text):
        return "[redacted]"
    if len(text) > 160:
        return text[:157] + "..."
    return text


def _redact_payload(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                "[redacted]"
                if _secretish_key(str(key))
                else _redact_payload(child_value)
            )
            for key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str) and _secretish_text(value):
        return "[redacted]"
    return value


def _secretish_text(text: str) -> bool:
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in (
            "secret",
            "api_key",
            "apikey",
            "private_key",
            "authorization:",
            "bearer ",
            "password=",
            "runpod_api_key=",
            "hf_token=",
        )
    ):
        return True
    if re.search(r"\bsk-[a-z0-9_-]{8,}\b", text, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"(/users/|/user/|/private/tmp/)", text, flags=re.IGNORECASE))


def _secretish_key(key: str) -> bool:
    lower = key.lower()
    if any(
        marker in lower
        for marker in (
            "password",
            "secret",
            "credential",
            "private_key",
            "api_key",
            "apikey",
            "access_key",
            "authorization",
            "bearer",
        )
    ):
        return True
    if lower in {"api_key", "apikey", "access_key", "bearer_token", "auth_token"}:
        return True
    return lower.endswith("_token") and not lower.endswith("_tokens")


def _h(value: object) -> str:
    return escape(str(value), quote=True)


_CSS = """
:root {
  color-scheme: light;
  --bg: #f7f8fb;
  --panel: #ffffff;
  --text: #172033;
  --muted: #667085;
  --line: #d8dee9;
  --accent: #245bd6;
  --good: #067647;
  --warn: #b54708;
  --bad: #b42318;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.page { max-width: 1180px; margin: 0 auto; padding: 24px; }
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 18px;
  align-items: stretch;
  margin-bottom: 18px;
}
.hero, .section, .verdict-card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
}
.eyebrow { color: var(--accent); font-weight: 700; margin: 0 0 6px; }
h1, h2, h3, h4 { margin: 0 0 10px; letter-spacing: 0; }
p { line-height: 1.45; }
.verdict-card span, .metric span { display: block; color: var(--muted); font-size: 12px; }
.verdict-card strong { display: block; margin-top: 10px; font-size: 24px; }
.verdict-card.accept strong { color: var(--good); }
.verdict-card.reject_quality_regression strong,
.verdict-card.regression strong { color: var(--bad); }
.section { margin: 14px 0; }
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin: 12px 0;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  min-height: 68px;
}
.metric strong { display: block; margin-top: 6px; overflow-wrap: anywhere; }
.compact .metric { min-height: 58px; }
.table-wrap { overflow-x: auto; margin: 10px 0; }
table { width: 100%; border-collapse: collapse; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 8px 7px;
  text-align: left;
  vertical-align: top;
}
th { color: var(--muted); font-size: 12px; text-transform: uppercase; }
.note, .empty { color: var(--muted); }
.callout {
  border-left: 4px solid var(--accent);
  background: #f3f6ff;
  border-radius: 6px;
  padding: 10px 12px;
}
.callout.warn { border-color: var(--warn); background: #fff7ed; }
.callout.bad { border-color: var(--bad); background: #fef3f2; }
.run, .finding {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 10px 12px;
  margin: 10px 0;
  background: #fbfcfe;
}
.run > summary, .finding > summary { cursor: pointer; font-weight: 700; }
.run > summary span { color: var(--muted); font-weight: 500; margin-left: 8px; }
.two-col {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
@media (max-width: 760px) {
  .page { padding: 16px; }
  .hero, .two-col { grid-template-columns: 1fr; }
}
"""
