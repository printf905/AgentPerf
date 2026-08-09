from __future__ import annotations

from agentperf.analyzer import AnalysisReport
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import (
    percentile,
    prefill_or_path_label,
    prefill_or_path_latency_ms,
    total_tool_latency_ms,
)
from agentperf.metrics.tokens import call_input_tokens, call_output_tokens
from agentperf.model_choice import ModelChoiceReport


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
            _row("Input tokens", sum(call_input_tokens(call) for call in llm_calls)),
            _row("Output tokens", sum(call_output_tokens(call) for call in llm_calls)),
            _row("Correlated serving requests", len(report.correlation.llm_to_serving)),
            "",
        ]
    )

    queue_ms = sum(request.queue_latency_ms or 0 for request in serving)
    prefill_ms = sum(prefill_or_path_latency_ms(request) or 0 for request in serving)
    decode_ms = sum(request.decode_latency_ms or 0 for request in serving)
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
                _row("Trace input tokens", attribution.trace_input_tokens),
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
            lines.append(_row(key.replace("_", " "), _format_value(value)))
        lines.extend(["", "Recommendation:", f"  {finding.recommendation}", ""])
        if finding.validation_plan:
            lines.append("Validation:")
            for item in finding.validation_plan:
                lines.append(f"  - {item}")
        if show_provenance:
            lines.extend(["", "Provenance:"])
            provenance = finding.provenance
            if provenance.llm_call_ids:
                lines.append(_row("llm call ids", ", ".join(provenance.llm_call_ids)))
            if provenance.llm_request_ids:
                lines.append(_row("llm request ids", ", ".join(provenance.llm_request_ids)))
            if provenance.serving_request_ids:
                lines.append(
                    _row("serving request ids", ", ".join(provenance.serving_request_ids))
                )
            if provenance.raw_metrics:
                lines.append(_row("raw metrics", _compact_dict(provenance.raw_metrics)))
            if provenance.derived_metrics:
                lines.append(
                    _row("derived metrics", _compact_dict(provenance.derived_metrics))
                )
            for note in provenance.notes:
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
                        f"{row.relative_cost_delta:+.2f}"
                    ),
                )
            )
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
        if show_provenance:
            lines.extend(["", "Provenance:"])
            for key, value in finding.provenance.derived_metrics.items():
                lines.append(_row(key.replace("_", " "), _format_value(value)))
            for note in finding.provenance.notes:
                lines.append(f"  - {note}")
    return "\n".join(lines)


def _row(label: str, value: object) -> str:
    return f"{label:<34} {value}"


def _format_value(value: object) -> str:
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value * 100:.1f}%"
        return f"{value:.1f}"
    return str(value)


def _format_seconds(ms: float | None) -> str:
    if ms is None:
        return "n/a"
    return f"{ms / 1000:.1f} s"


def _format_ms(ms: float | None) -> str:
    if ms is None:
        return "n/a"
    return f"{ms:.0f} ms"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _compact_dict(value: dict[str, object]) -> str:
    return "; ".join(f"{key}={item}" for key, item in value.items())


def _prefill_report_label(label: str) -> str:
    if label == "prefill_path_proxy":
        return "Prefill path proxy"
    return "Prefill"
