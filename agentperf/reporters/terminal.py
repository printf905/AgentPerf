from __future__ import annotations

from agentperf.analyzer import AnalysisReport
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import percentile, total_tool_latency_ms
from agentperf.metrics.tokens import call_input_tokens, call_output_tokens


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
    prefill_ms = sum(request.prefill_latency_ms or 0 for request in serving)
    decode_ms = sum(request.decode_latency_ms or 0 for request in serving)
    tool_ms = total_tool_latency_ms(run)
    lines.extend(
        [
            "Latency",
            "-" * 60,
            _row("Queue", _format_seconds(queue_ms)),
            _row("Prefill", _format_seconds(prefill_ms)),
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
            "Findings",
            "-" * 60,
        ]
    )

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
