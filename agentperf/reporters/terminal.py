from __future__ import annotations

from collections.abc import Iterable

from agentperf.analyzer import AnalysisReport
from agentperf.completeness import CompletenessReport, assess_report
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import (
    percentile,
    prefill_or_path_label,
    prefill_or_path_latency_ms,
    total_tool_latency_ms,
)
from agentperf.metrics.tokens import call_input_tokens, call_output_tokens
from agentperf.model_choice import ModelChoiceReport
from agentperf.recommendations import recommendation_contract_for_finding
from agentperf.schema.comparison import MetricDelta, RunComparison
from agentperf.schema.findings import RecommendationContract
from agentperf.schema.regression import RegressionCheck, RegressionResult


def render_report(report: AnalysisReport, *, show_provenance: bool = False) -> str:
    run = report.run
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("AgentPerf Report")
    lines.append("=" * 60)
    if run.synthetic:
        lines.append("Data: synthetic trace fixture, not benchmark results")
        lines.append("")

    llm_calls = run.llm_calls
    serving = run.serving_requests
    lines.extend(
        [
            "Run",
            "-" * 60,
            _row("Run ID", run.agent_run_id),
            _row("Duration", _format_seconds(run.duration_ms)),
            _row("LLM calls", len(llm_calls)),
            _row("Tool calls", len(run.tool_calls)),
            _row(
                "Agent trace input tokens",
                sum(call_input_tokens(call) for call in llm_calls),
            ),
            _row(
                "Agent trace output tokens",
                sum(call_output_tokens(call) for call in llm_calls),
            ),
            _row("Correlated serving requests", len(report.correlation.llm_to_serving)),
            "",
        ]
    )

    completeness = assess_report(report)
    lines.extend(_instrumentation_lines(completeness))

    queue_ms = _sum_optional(request.queue_latency_ms for request in serving)
    prefill_ms = _sum_optional(prefill_or_path_latency_ms(request) for request in serving)
    decode_ms = _sum_optional(request.decode_latency_ms for request in serving)
    tool_ms = total_tool_latency_ms(run)
    lines.extend(
        [
            "Latency",
            "-" * 60,
            _row("Queue", _format_seconds(queue_ms)),
            _row(
                _prefill_report_label(prefill_or_path_label(serving)),
                _format_seconds(prefill_ms),
            ),
            _row("Decode", _format_seconds(decode_ms)),
            _row("Tools", _format_seconds(tool_ms)),
            "",
        ]
    )

    ttfts = [request.ttft_ms for request in serving if request.ttft_ms is not None]
    cache_hit = prefix_cache_hit_ratio(serving)
    lines.extend(
        [
            "Serving",
            "-" * 60,
            _row("Requests", len(serving)),
            _row("TTFT P50", _format_ms(percentile([float(value) for value in ttfts], 0.50))),
            _row("TTFT P95", _format_ms(percentile([float(value) for value in ttfts], 0.95))),
            _row("Prefix cache hit", _format_ratio(cache_hit)),
            "",
        ]
    )

    if report.token_attribution is not None:
        attribution = report.token_attribution
        lines.extend(
            [
                "Token Attribution",
                "-" * 60,
                _row("Agent trace input tokens", attribution.trace_input_tokens),
                _row("Component processed tokens", attribution.total_processed_tokens),
                _row("Component unique tokens", attribution.total_unique_tokens),
                _row(
                    "Attribution tokenization",
                    "approximate" if attribution.approximate else "exact/trace totals",
                ),
                "",
            ]
        )
        if attribution.processed_tokens_by_component:
            lines.append(_row("Component", "Processed  Unique  Share"))
            for component, processed in attribution.processed_tokens_by_component.items():
                unique = attribution.unique_tokens_by_component.get(component, 0)
                share = (
                    processed / attribution.total_processed_tokens
                    if attribution.total_processed_tokens
                    else 0.0
                )
                lines.append(
                    _row(
                        component.replace("_", " ").title(),
                        f"{processed:>9}  {unique:>6}  {share * 100:>5.1f}%",
                    )
                )
            lines.append("")

    if report.context_growth:
        lines.extend(["Context Growth", "-" * 60])
        lines.append(_row("Step", "Input  History  Tool Results  Retrieved"))
        for row in report.context_growth:
            lines.append(
                _row(
                    f"{row.step_index} {row.llm_call_id}",
                    (
                        f"{row.input_tokens:>5}  {row.history_tokens:>7}  "
                        f"{row.tool_result_tokens:>12}  "
                        f"{row.retrieved_context_tokens:>9}"
                    ),
                )
            )
        lines.append("")

    if report.metric_provenance:
        lines.extend(["Metric Provenance", "-" * 60])
        lines.append(_row("Metric", "Value  Source  Aggregation"))
        for provenance in report.metric_provenance:
            lines.append(
                _row(
                    provenance.name.replace("_", " "),
                    (
                        f"{_format_metric_provenance_value(provenance.value)} "
                        f"{provenance.unit}  {provenance.source_layer}  "
                        f"{provenance.aggregation}"
                    ),
                )
            )
        lines.append("")

    if report.investigations:
        lines.extend(["Investigations", "-" * 60])
        for investigation in report.investigations:
            lines.extend(
                [
                    investigation.title,
                    investigation.summary,
                    "",
                    "Facts:",
                ]
            )
            for fact in investigation.facts:
                lines.append(
                    _row(
                        f"{fact.relationship}: {fact.label}",
                        f"{fact.value} ({fact.strength})",
                    )
                )
            lines.extend(["", "Assessment:", f"  {investigation.assessment}", ""])
            if investigation.recommended_experiment:
                lines.append("Recommended experiment:")
                for item in investigation.recommended_experiment:
                    lines.append(f"  - {item}")
            lines.append("")

    lines.extend(["Findings", "-" * 60])

    if not report.findings:
        lines.append("No high-confidence MVP findings.")
        return "\n".join(lines)

    for finding in report.findings:
        lines.extend(
            [
                "",
                f"[{finding.severity}] {finding.id}",
                "",
                finding.summary,
                "",
                "Evidence:",
            ]
        )
        for key, value in finding.evidence.items():
            if key == "materiality_evaluation" and isinstance(value, dict):
                lines.extend(_materiality_evaluation_lines(value))
            else:
                lines.append(
                    _row(_finding_evidence_label(key), _format_evidence_value(key, value))
                )
        lines.extend(["", "Recommendation:", f"  {finding.recommendation}", ""])
        if finding.validation_plan:
            lines.append("Validation:")
            for item in finding.validation_plan:
                lines.append(f"  - {item}")
        contract = recommendation_contract_for_finding(finding)
        if contract is not None:
            lines.extend(["", "Recommendation contract:"])
            lines.extend(_recommendation_contract_lines(contract))
        if show_provenance:
            lines.extend(["", "Provenance:"])
            finding_provenance = finding.provenance
            if finding_provenance.llm_call_ids:
                lines.append(_row("llm call ids", ", ".join(finding_provenance.llm_call_ids)))
            if finding_provenance.llm_request_ids:
                lines.append(
                    _row("llm request ids", ", ".join(finding_provenance.llm_request_ids))
                )
            if finding_provenance.serving_request_ids:
                lines.append(
                    _row(
                        "serving request ids",
                        ", ".join(finding_provenance.serving_request_ids),
                    )
                )
            if finding_provenance.raw_metrics:
                lines.append(_row("raw metrics", _compact_dict(finding_provenance.raw_metrics)))
            if finding_provenance.derived_metrics:
                lines.append(
                    _row(
                        "derived metrics",
                        _compact_dict(finding_provenance.derived_metrics),
                    )
                )
            for note in finding_provenance.notes:
                lines.append(f"  - {note}")
    return "\n".join(lines)


def render_model_choice_report(
    report: ModelChoiceReport,
    *,
    show_provenance: bool = False,
) -> str:
    lines = [
        "=" * 60,
        "AgentPerf Model-Choice Report",
        "=" * 60,
        "Quality Constraint",
        "-" * 60,
        _row("Baseline config", report.quality_constraint["baseline_config"]),
        _row("Minimum mean score", f"{report.quality_constraint['minimum_mean_score']:.3f}"),
        _row("Minimum pass rate", _format_ratio(report.quality_constraint["minimum_pass_rate"])),
        "",
        "Configurations",
        "-" * 60,
        _row("Config", "Quality  Pass  Cost  Client P95"),
    ]
    for config in report.configurations:
        lines.append(
            _row(
                config.name,
                (
                    f"{config.mean_score:.3f}  "
                    f"{config.pass_rate * 100:>5.1f}%  "
                    f"{config.relative_cost:>5.2f}  "
                    f"{_format_ms(config.client_latency_p95_ms)}"
                ),
            )
        )
    lines.extend(["", "Role Sensitivity", "-" * 60])
    if not report.role_sensitivity:
        lines.append("No one-role counterfactuals found.")
    else:
        lines.append(_row("Role", "Candidate  Quality d  Pass d  Cost d"))
        for row in report.role_sensitivity:
            lines.append(
                _row(
                    row.role,
                    (
                        f"{row.candidate_model}  "
                        f"{row.mean_quality_delta:+.3f}  "
                        f"{row.pass_rate_delta * 100:+.1f}pp  "
                        f"{row.relative_cost_delta:+.2f}  "
                        f"{row.status}"
                    ),
                )
            )
    lines.extend(["", "Candidate Routing", "-" * 60])
    if report.candidate_routing is None:
        lines.append("No quality-preserving role substitutions produced a routing candidate.")
    else:
        for role, model in sorted(report.candidate_routing.routing.items()):
            baseline_model = report.baseline.routing.get(role)
            movement = (
                f"{baseline_model} -> {model}"
                if baseline_model != model
                else str(model)
            )
            lines.append(_row(role, movement))
        lines.append(_row("Status", report.candidate_routing.status))
        lines.append(f"  - {report.candidate_routing.rationale}")
    verification = report.routing_verification
    lines.extend(["", "Full Routing Verification", "-" * 60])
    lines.append(_row("Config", verification.config_name or "not replayed"))
    lines.append(_row("Status", verification.status))
    lines.append(_row("Quality preserving", _format_value(verification.quality_preserving)))
    lines.append(_row("Relative cost delta", _format_value(verification.relative_cost_delta)))
    lines.append(
        _row(
            "Client P95 delta ms",
            _format_value(verification.client_latency_p95_delta_ms),
        )
    )
    lines.append(f"  - {verification.reason}")
    if verification.recommendation_verification is not None:
        rec = verification.recommendation_verification
        lines.append(_row("Recommendation verification", rec.status))
        lines.append(f"  - {rec.reason}")
    lines.extend(["", "Pareto", "-" * 60])
    lines.append(_row("Config", "Quality  Cost  Status"))
    for pareto_row in report.pareto:
        if not pareto_row["quality_preserving"]:
            status = "quality-violating"
        elif pareto_row["dominated"]:
            status = "dominated"
        else:
            status = "pareto"
        lines.append(
            _row(
                str(pareto_row["config"]),
                (
                    f"{float(pareto_row['mean_score']):.3f}  "
                    f"{float(pareto_row['relative_cost']):.2f}  {status}"
                ),
            )
        )
    lines.extend(["", "Findings", "-" * 60])
    if not report.findings:
        lines.append("No model-choice headroom found within the quality constraint.")
        return "\n".join(lines)
    for finding in report.findings:
        lines.extend(
            [
                "",
                f"[{finding.severity}] {finding.id}",
                "",
                finding.summary,
                "",
                "Evidence:",
            ]
        )
        for key, value in finding.evidence.items():
            lines.append(_row(key.replace("_", " "), _format_value(value)))
        lines.extend(["", "Recommendation:", f"  {finding.recommendation}"])
        contract = recommendation_contract_for_finding(finding)
        if contract is not None:
            lines.extend(["", "Recommendation contract:"])
            lines.extend(_recommendation_contract_lines(contract))
        if show_provenance:
            lines.extend(["", "Provenance:"])
            for key, value in finding.provenance.derived_metrics.items():
                lines.append(_row(key.replace("_", " "), _format_value(value)))
            for note in finding.provenance.notes:
                lines.append(f"  - {note}")
    return "\n".join(lines)


def render_comparison_report(comparison: RunComparison, *, show_provenance: bool = False) -> str:
    lines: list[str] = [
        "=" * 60,
        "AgentPerf Replay Comparison",
        "=" * 60,
        _row("Result", comparison.acceptance_result.verdict),
        _row("Quality", _quality_summary(comparison)),
        _row(
            "Task coverage",
            f"{len(comparison.matched_tasks)} matched; "
            f"{len(comparison.unmatched_baseline_tasks)} baseline-only; "
            f"{len(comparison.unmatched_candidate_tasks)} candidate-only",
        ),
        "",
        "Largest Context Changes",
        "-" * 60,
        *_component_change_lines(comparison, limit=3),
        "",
        "Finding Summary",
        "-" * 60,
        *_finding_summary_lines(comparison),
        "",
        "Tasks",
        "-" * 60,
        _row("Baseline", comparison.baseline_id),
        _row("Candidate", comparison.candidate_id),
        _row("Matched tasks", f"{len(comparison.matched_tasks)}"),
        _row("Unmatched baseline", len(comparison.unmatched_baseline_tasks)),
        _row("Unmatched candidate", len(comparison.unmatched_candidate_tasks)),
        "",
        "Performance",
        "-" * 60,
        _row(
            "Provider input tokens",
            _format_delta(comparison.token_deltas.input_tokens, integer=True),
        ),
        _row(
            "Provider output tokens",
            _format_delta(comparison.token_deltas.output_tokens, integer=True),
        ),
    ]
    accounting = comparison.token_deltas.component_accounting
    if accounting is not None:
        lines.extend(
            [
                _row(
                    "Component processed tokens",
                    _format_delta(accounting.total_processed_tokens, integer=True),
                ),
                _row(
                    "Attribution coverage",
                    _format_delta(accounting.attribution_coverage_ratio, ratio=True),
                ),
                _row(
                    "Attribution confidence",
                    f"{accounting.baseline_confidence} -> {accounting.candidate_confidence}",
                ),
            ]
        )
    tool_result_delta = comparison.token_deltas.component_processed_tokens.get("tool_result")
    if tool_result_delta is not None:
        lines.append(_row("Tool-result tokens", _format_delta(tool_result_delta, integer=True)))
    lines.extend(
        [
            _row(
                "Client P95",
                _format_delta(comparison.latency_deltas.client_p95_ms, suffix=" ms"),
            ),
            _row(
                "Scheduled->first P95",
                _format_delta(comparison.latency_deltas.scheduled_to_first_p95_ms, suffix=" ms"),
            ),
            "",
            "Token Components",
            "-" * 60,
        ]
    )
    if comparison.token_deltas.component_processed_tokens:
        lines.append(_row("Component", "Baseline -> Candidate  Delta"))
        for component, delta in _rank_component_deltas(
            comparison.token_deltas.component_processed_tokens,
            include_tiny=True,
        ):
            lines.append(
                _row(
                    component.replace("_", " ").title(),
                    _format_delta(delta, integer=True),
                )
            )
    else:
        lines.append("No component attribution available.")

    lines.extend(
        [
            "",
            "Quality",
            "-" * 60,
            _row("Mean score", _format_delta(comparison.quality_deltas.mean_score)),
            _row("Pass rate", _format_delta(comparison.quality_deltas.pass_rate, ratio=True)),
            _row("Constraint", _quality_status(comparison.quality_deltas.passed)),
            "",
            "Cache",
            "-" * 60,
            _row(
                "Cached tokens",
                _format_delta(comparison.cache_deltas.cached_tokens, integer=True),
            ),
            _row(
                "Cache-miss tokens",
                _format_delta(comparison.cache_deltas.cache_miss_tokens, integer=True),
            ),
            _row(
                "Cached-token ratio",
                _format_delta(comparison.cache_deltas.cached_token_ratio, ratio=True),
            ),
            "",
            "Finding Lifecycle",
            "-" * 60,
        ]
    )
    if not comparison.finding_changes:
        lines.append("No finding changes.")
    else:
        for change in comparison.finding_changes:
            severity = (
                f"{change.baseline_severity or 'absent'} -> "
                f"{change.candidate_severity or 'absent'}"
            )
            lines.append(_row(change.finding_id, f"{severity}  {change.lifecycle}"))
            if show_provenance and change.scope:
                lines.append(_row("scope", change.scope))

    lines.extend(
        [
            "",
            "Verdict",
            "-" * 60,
            _row("Result", comparison.acceptance_result.verdict),
            comparison.acceptance_result.reason,
        ]
    )
    if comparison.warnings:
        lines.extend(["", "Warnings", "-" * 60])
        for warning in comparison.warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def render_regression_report(result: RegressionResult) -> str:
    lines: list[str] = [
        "=" * 60,
        "AgentPerf Regression Check",
        "=" * 60,
        _row("Result", result.status),
        _row("Baseline", result.metadata.get("baseline_id", "unknown")),
        _row("Candidate", result.metadata.get("candidate_id", "unknown")),
        _row("Matched tasks", result.metadata.get("matched_tasks", "unknown")),
        "",
        "Summary",
        "-" * 60,
        *_regression_summary_lines(result),
        "",
    ]
    for category in ("TASK_COVERAGE", "ARTIFACT", "QUALITY", "PERFORMANCE", "FINDINGS"):
        checks = [check for check in result.checks if check.category == category]
        if not checks:
            continue
        lines.extend([category.replace("_", " ").title(), "-" * 60])
        for check in checks:
            lines.append(_row(_check_label(check), _check_value(check)))
        lines.append("")
    if result.warnings:
        lines.extend(["Warnings", "-" * 60])
        for warning in result.warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.extend(["Final Result", "-" * 60, result.status])
    return "\n".join(lines).rstrip()


def render_regression_markdown(result: RegressionResult) -> str:
    lines = [
        "## AgentPerf Regression Check",
        "",
        f"**Result:** {result.status}",
        "",
        "### Summary",
        "",
    ]
    lines.extend(f"- {line}" for line in _regression_summary_lines(result, markdown=True))
    lines.extend(
        [
            "",
            "### Detailed Checks",
            "",
            "| Check | Result | Evidence |",
            "| --- | --- | --- |",
        ]
    )
    for check in result.checks:
        lines.append(
            f"| {check.category}: `{check.metric}` | {check.result} | "
            f"{_markdown_escape(_check_value(check))} |"
        )
    if result.warnings:
        lines.extend(["", "### Warnings", ""])
        for warning in result.warnings:
            lines.append(f"- {_markdown_escape(warning)}")
    return "\n".join(lines)


def _row(label: str, value: object) -> str:
    return f"{label:<34} {value}"


def _format_value(value: object) -> str:
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value * 100:.1f}%"
        return f"{value:.1f}"
    return str(value)


_FINDING_EVIDENCE_LABELS = {
    "total_input_tokens": "agent trace total input tokens",
    "average_input_tokens": "agent trace average input tokens",
    "shared_prefix_tokens": "agent trace shared prefix tokens",
    "shared_prefix_ratio": "agent trace shared prefix ratio",
    "largest_common_prefix_tokens": "agent trace largest common prefix tokens",
    "largest_common_prefix_ratio": "agent trace largest common prefix ratio",
    "repeated_non_prefix_tokens": "agent trace repeated non prefix tokens",
    "repeated_non_prefix_ratio": "agent trace repeated non prefix ratio",
    "actual_prefix_cache_hit_ratio": "serving prefix cache hit ratio",
    "prefill_fraction_of_ttft": "serving prefill fraction of ttft",
    "prefill_fraction_of_ttft_avg": "serving prefill fraction of ttft avg",
    "prefill_path_proxy_fraction_of_ttft": "serving prefill path proxy fraction of ttft",
    "prefill_path_proxy_fraction_of_ttft_avg": (
        "serving prefill path proxy fraction of ttft avg"
    ),
    "latency_semantics": "serving latency semantics",
    "ttft_p50_ms": "serving ttft p50 ms",
    "ttft_p95_ms": "serving ttft p95 ms",
    "p95_input_tokens": "serving request input p95 tokens",
    "uncached_input_p95_tokens": "serving uncached input p95 tokens",
    "p95_uncached_input_tokens": "serving uncached input p95 tokens",
    "prefix_cache_hit_ratio": "serving prefix cache hit ratio",
    "materiality_threshold_ttft_p95_ms": "materiality threshold ttft p95 ms",
    "materiality_threshold_uncached_input_p95_tokens": (
        "materiality threshold serving uncached input p95 tokens"
    ),
    "materiality_ttft_p95_met": "materiality ttft p95 threshold met",
    "materiality_uncached_input_p95_met": (
        "materiality serving uncached input threshold met"
    ),
}


def _finding_evidence_label(key: str) -> str:
    return _FINDING_EVIDENCE_LABELS.get(key, key.replace("_", " "))


def _format_evidence_value(key: str, value: object) -> str:
    if key == "latency_semantics":
        if value == "prefill":
            return "true prefill stage"
        if value == "prefill_path_proxy":
            return "prefill-path proxy"
        if value == "unavailable":
            return "unavailable"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return _format_value(value)


def _materiality_evaluation_lines(value: dict[str, object]) -> list[str]:
    lines = ["", "Materiality evaluation:"]
    overall = value.get("overall")
    rule = value.get("rule")
    reason = value.get("reason")
    if overall is not None:
        lines.append(_row("overall", overall))
    if rule is not None:
        lines.append(_row("rule", rule))
    gates = value.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            name = str(gate.get("name", "gate"))
            observed = gate.get("observed")
            threshold = gate.get("threshold")
            unit = str(gate.get("unit", ""))
            result = gate.get("result")
            source = gate.get("source_layer")
            lines.append(
                _row(
                    name,
                    (
                        f"observed={observed} {unit}; threshold={threshold} {unit}; "
                        f"result={result}; source={source}"
                    ),
                )
            )
    if reason is not None:
        lines.append(_row("reason", reason))
    return lines


def _instrumentation_lines(report: CompletenessReport) -> list[str]:
    lines = [
        "Instrumentation",
        "-" * 60,
        _row(
            "LLM calls with usage",
            _coverage(report.llm_calls_with_provider_usage, report.llm_calls_observed),
        ),
        _row(
            "LLM calls with components",
            _coverage(report.llm_calls_with_component_attribution, report.llm_calls_observed),
        ),
        _row(
            "Stable request IDs",
            _coverage(report.llm_calls_with_request_ids, report.llm_calls_observed),
        ),
        _row(
            "Exact serving correlations",
            _coverage(
                report.exact_serving_correlations,
                report.eligible_serving_correlations,
            )
            if report.cross_layer_readiness != "NOT_APPLICABLE"
            else "not applicable",
        ),
        _row("Agent profiling readiness", report.agent_profiling_readiness),
        _row("Cross-layer readiness", report.cross_layer_readiness),
    ]
    if report.limitations:
        lines.append("Limitations:")
        lines.extend(f"  - {item}" for item in report.limitations[:4])
        if len(report.limitations) > 4:
            lines.append(f"  - ... {len(report.limitations) - 4} more")
    lines.append("")
    return lines


def _coverage(covered: int, eligible: int) -> str:
    if eligible <= 0:
        return "0 / n/a"
    return f"{covered} / {eligible}"


def _format_metric_provenance_value(value: object) -> str:
    if isinstance(value, list):
        return "[" + ", ".join(str(item) for item in value[:8]) + (
            f", ... {len(value) - 8} more]" if len(value) > 8 else "]"
        )
    return _format_value(value)


def _format_seconds(ms: float | None) -> str:
    if ms is None:
        return "n/a"
    return f"{ms / 1000:.1f} s"


def _sum_optional(values: Iterable[float | None]) -> float | None:
    known = [float(value) for value in values if value is not None]
    if not known:
        return None
    return sum(known)


def _format_ms(ms: float | None) -> str:
    if ms is None:
        return "n/a"
    return f"{ms:.0f} ms"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _format_delta(
    delta: MetricDelta,
    *,
    integer: bool = False,
    ratio: bool = False,
    suffix: str = "",
) -> str:
    if delta.baseline is None or delta.candidate is None or delta.delta is None:
        return "n/a"
    if ratio:
        baseline = f"{float(delta.baseline) * 100:.1f}%"
        candidate = f"{float(delta.candidate) * 100:.1f}%"
        change = f"{float(delta.delta) * 100:+.1f}pp"
    elif integer:
        baseline = f"{int(delta.baseline):,}"
        candidate = f"{int(delta.candidate):,}"
        change = f"{int(delta.delta):+,}"
    else:
        baseline = f"{float(delta.baseline):.3f}{suffix}"
        candidate = f"{float(delta.candidate):.3f}{suffix}"
        change = f"{float(delta.delta):+.3f}{suffix}"
    percent = "" if delta.percent_delta is None else f" ({delta.percent_delta * 100:+.1f}%)"
    return f"{baseline} -> {candidate}  {change}{percent}"


def _quality_summary(comparison: RunComparison) -> str:
    status = _quality_status(comparison.quality_deltas.passed)
    mean_score = _format_delta(comparison.quality_deltas.mean_score)
    pass_rate = _format_delta(comparison.quality_deltas.pass_rate, ratio=True)
    return f"{status}; mean {mean_score}; pass {pass_rate}"


def _component_change_lines(comparison: RunComparison, *, limit: int) -> list[str]:
    ranked = _rank_component_deltas(comparison.token_deltas.component_processed_tokens)
    if not ranked:
        return ["No component attribution available."]
    lines = [
        _row(
            component.replace("_", " ").title(),
            _format_delta(delta, integer=True),
        )
        for component, delta in ranked[:limit]
    ]
    if not lines:
        return ["No component changes above presentation threshold."]
    provider = comparison.token_deltas.input_tokens
    component_accounting = comparison.token_deltas.component_accounting
    if (
        provider.percent_delta is not None
        and abs(provider.percent_delta) < 0.01
        and component_accounting is not None
        and component_accounting.total_processed_tokens.percent_delta is not None
        and abs(component_accounting.total_processed_tokens.percent_delta) >= 0.05
    ):
        lines.append(
            "Provider-reported usage is unchanged, but AgentPerf observed "
            "component-level context movement."
        )
    return lines


def _rank_component_deltas(
    deltas: dict[str, MetricDelta],
    *,
    include_tiny: bool = False,
) -> list[tuple[str, MetricDelta]]:
    items = [
        (component, delta)
        for component, delta in deltas.items()
        if delta.delta is not None
        and (include_tiny or _presentation_material(delta))
    ]
    return sorted(
        items,
        key=lambda item: (
            0 if item[1].delta is not None and item[1].delta < 0 else 1,
            -(abs(item[1].percent_delta) if item[1].percent_delta is not None else 0.0),
            item[0],
        ),
    )


def _presentation_material(delta: MetricDelta) -> bool:
    if delta.percent_delta is not None:
        return abs(delta.percent_delta) >= 0.01
    return delta.delta not in {None, 0}


def _finding_summary_lines(comparison: RunComparison) -> list[str]:
    if not comparison.finding_changes:
        return ["No finding changes."]
    counts: dict[str, int] = {}
    new_material = 0
    regressed_material = 0
    for change in comparison.finding_changes:
        counts[change.lifecycle] = counts.get(change.lifecycle, 0) + 1
        if change.lifecycle == "NEW" and _material(
            change.candidate_severity,
            change.candidate_materiality,
        ):
            new_material += 1
        if change.lifecycle == "REGRESSED" and _material(
            change.candidate_severity,
            change.candidate_materiality,
        ):
            regressed_material += 1
    lines = [
        _row("Resolved", counts.get("RESOLVED", 0)),
        _row("Improved", counts.get("IMPROVED", 0)),
        _row("Regressed", counts.get("REGRESSED", 0)),
        _row("New material", new_material),
        _row("Regressed material", regressed_material),
    ]
    return lines


def _regression_summary_lines(
    result: RegressionResult,
    *,
    markdown: bool = False,
) -> list[str]:
    lines: list[str] = []
    quality_checks = [check for check in result.checks if check.category == "QUALITY"]
    failed_quality = [check for check in quality_checks if check.result == "FAIL"]
    if failed_quality:
        lines.append(
            "QUALITY REGRESSION: "
            + "; ".join(_brief_check(check) for check in failed_quality)
        )
    elif quality_checks:
        lines.append("Quality: " + "; ".join(_brief_check(check) for check in quality_checks))
    else:
        lines.append("Quality: not configured")

    coverage = next(
        (
            check
            for check in result.checks
            if check.category == "TASK_COVERAGE" and check.metric == "same_tasks"
        ),
        None,
    )
    if coverage is not None:
        matched = coverage.evidence.get("matched_tasks")
        lines.append(f"Task coverage: {matched} matched ({coverage.result})")
    else:
        lines.append(f"Task coverage: {result.metadata.get('matched_tasks', 'unknown')} matched")

    performance_checks = [check for check in result.checks if check.category == "PERFORMANCE"]
    improvements = sorted(
        [check for check in performance_checks if _negative_delta(check)],
        key=lambda check: check.actual_percent_delta
        if check.actual_percent_delta is not None
        else -abs(float(check.actual_delta or 0)),
    )
    regressions = [check for check in performance_checks if check.result == "FAIL"]
    lines.append("Biggest improvements: " + _brief_check_list(improvements[:3]))
    lines.append(
        "Biggest regressions: "
        + (
            _brief_check_list(regressions)
            if regressions
            else "none above configured thresholds"
        )
    )
    disagreement = _provider_component_disagreement(performance_checks)
    if disagreement:
        lines.append(disagreement)

    finding_checks = [check for check in result.checks if check.category == "FINDINGS"]
    if finding_checks:
        lines.append(
            "Findings: "
            + "; ".join(_brief_finding_check(check) for check in finding_checks)
        )
    task_changes = result.metadata.get("task_quality_changes")
    if isinstance(task_changes, list) and task_changes:
        changed = task_changes[:5]
        lines.append(
            "Task regressions: "
            + "; ".join(_brief_task_change(item) for item in changed if isinstance(item, dict))
        )
    elif failed_quality:
        lines.append("Task regressions: unavailable in comparison metadata")
    return [line.replace("|", "\\|") for line in lines] if markdown else lines


def _brief_check_list(checks: list[RegressionCheck]) -> str:
    if not checks:
        return "none"
    return "; ".join(_brief_check(check) for check in checks)


def _brief_check(check: RegressionCheck) -> str:
    values: list[str] = []
    if check.baseline is not None and check.candidate is not None:
        values.append(
            f"{_format_check_number(check.baseline)} -> "
            f"{_format_check_number(check.candidate)}"
        )
    if check.actual_percent_delta is not None:
        values.append(f"{check.actual_percent_delta * 100:+.1f}%")
    elif check.actual_delta is not None:
        values.append(f"delta {_format_check_number(check.actual_delta)}")
    if check.result == "FAIL" and check.allowed is not None:
        values.append(f"allowed {check.allowed}")
    value = ", ".join(values) if values else check.result
    return f"{check.metric}: {value}"


def _brief_finding_check(check: RegressionCheck) -> str:
    return f"{check.metric}={check.candidate if check.candidate is not None else check.result}"


def _check_delta(check: RegressionCheck) -> float | int | None:
    return check.actual_delta


def _negative_delta(check: RegressionCheck) -> bool:
    delta = _check_delta(check)
    return delta is not None and delta < 0


def _provider_component_disagreement(checks: list[RegressionCheck]) -> str | None:
    provider = [
        check for check in checks
        if check.evidence.get("accounting_source") == "provider_usage"
    ]
    component = [
        check for check in checks
        if check.evidence.get("accounting_source") == "agentperf_component_attribution"
    ]
    provider_flat = any(
        check.actual_percent_delta is not None and abs(check.actual_percent_delta) < 0.01
        for check in provider
    )
    component_moved = [
        check
        for check in component
        if check.actual_percent_delta is not None and abs(check.actual_percent_delta) >= 0.05
    ]
    if provider_flat and component_moved:
        return (
            "Accounting note: provider-reported usage is unchanged, but "
            "AgentPerf observed component-level context movement."
        )
    return None


def _brief_task_change(item: dict[str, object]) -> str:
    task_id = str(item.get("task_id", "unknown"))
    base_pass = item.get("baseline_passed")
    cand_pass = item.get("candidate_passed")
    base_score = item.get("baseline_score")
    cand_score = item.get("candidate_score")
    if base_pass != cand_pass:
        return f"{task_id}: {base_pass} -> {cand_pass}"
    return f"{task_id}: score {base_score} -> {cand_score}"


def _material(severity: str | None, materiality: str | None) -> bool:
    if materiality in {"MATERIAL", "ACTIONABLE"}:
        return True
    if materiality in {"OBSERVATION", "HEADROOM", "CACHEABILITY_HEADROOM"}:
        return False
    return severity == "HIGH"


def _quality_status(value: bool | None) -> str:
    if value is True:
        return "PASS"
    if value is False:
        return "FAIL"
    return "UNVERIFIED"


def _recommendation_contract_lines(contract: RecommendationContract) -> list[str]:
    lines = [
        f"  Objective: {contract.objective}",
        f"  Applicability: {contract.applicability}",
    ]
    if contract.interventions:
        lines.append("  Possible interventions:")
        for item in contract.interventions[:4]:
            lines.append(f"    - {item}")
    if contract.expected_metric_changes:
        lines.append("  Expected evidence:")
        for expected in contract.expected_metric_changes:
            requirement = "required" if expected.required else "supporting"
            lines.append(
                f"    - {expected.metric} {expected.direction.lower()} ({requirement})"
            )
    else:
        lines.append("  Expected evidence: no optimization metric required")
    if contract.risks:
        lines.append("  Risk:")
        for risk in contract.risks[:2]:
            lines.append(f"    - {risk}")
    if contract.verification_requirements:
        lines.append("  Verification:")
        for item in contract.verification_requirements[:3]:
            lines.append(f"    - {item}")
    return lines


def _compact_dict(value: dict[str, object]) -> str:
    return "; ".join(f"{key}={item}" for key, item in value.items())


def _prefill_report_label(label: str) -> str:
    if label == "prefill_path_proxy":
        return "Prefill path proxy"
    if label == "unavailable":
        return "First-token path evidence"
    return "Prefill"


def _check_label(check: RegressionCheck) -> str:
    return check.metric.replace("_", " ").title()


def _check_value(check: RegressionCheck) -> str:
    values: list[str] = []
    if check.baseline is not None and check.candidate is not None:
        values.append(
            f"{_format_check_number(check.baseline)} -> "
            f"{_format_check_number(check.candidate)}"
        )
    elif check.baseline is not None:
        values.append(_format_check_number(check.baseline))
    elif check.candidate is not None:
        values.append(_format_check_number(check.candidate))
    if check.allowed is not None:
        values.append(f"allowed {check.allowed}")
    if check.actual_delta is not None:
        values.append(f"delta {_format_check_number(check.actual_delta)}")
    if check.actual_percent_delta is not None:
        values.append(f"{check.actual_percent_delta * 100:+.1f}%")
    source = check.evidence.get("accounting_source")
    if source is not None:
        values.append(f"source {source}")
    values.append(check.result)
    return "  ".join(values)


def _format_check_number(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _markdown_escape(value: str) -> str:
    return value.replace("|", "\\|")
