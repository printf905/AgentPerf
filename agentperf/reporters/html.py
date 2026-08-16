from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from agentperf.analyzer import AnalysisReport, analyze_run
from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.completeness import CompletenessReport, assess_runs
from agentperf.metrics.attribution import (
    ComponentTokenAttribution,
    ContextGrowthRow,
    component_token_attribution,
)
from agentperf.metrics.components import COMPONENT_ORDER, component_kind
from agentperf.metrics.tokens import call_input_tokens, token_count
from agentperf.recommendations import recommendation_contract_for_finding
from agentperf.schema.artifacts import QualityMetric, TaskResult
from agentperf.schema.findings import Finding
from agentperf.schema.trace import (
    AgentRun,
    AgentStep,
    LLMCall,
    ServingRequest,
    ToolCall,
    parse_agentperf_trace,
    parse_datetime,
)


@dataclass(frozen=True)
class HtmlReportInput:
    title: str
    source_type: str
    source_path: str
    runs: list[AgentRun]
    reports: list[AnalysisReport]
    tasks: list[TaskResult]
    quality_metrics: list[QualityMetric]
    findings: list[Finding]
    environment: dict[str, Any]
    manifest: dict[str, Any]
    summary: dict[str, Any]
    completeness: CompletenessReport


def load_html_report_input(path: Path, *, title: str | None = None) -> HtmlReportInput:
    if path.is_dir():
        artifact = load_artifact(path)
        return _from_artifact(artifact, path, title=title)
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = _parse_raw_runs(data)
    reports = [analyze_run(run) for run in runs]
    completeness = assess_runs(
        reports,
        task_results=[],
        manifest=None,
        source_type="raw_trace",
        source_path=str(path),
    )
    return HtmlReportInput(
        title=title or _default_title(path),
        source_type="raw trace",
        source_path=str(path),
        runs=runs,
        reports=reports,
        tasks=[],
        quality_metrics=[],
        findings=[finding for report in reports for finding in report.findings],
        environment={},
        manifest={},
        summary={},
        completeness=completeness,
    )


def render_html_report(report_input: HtmlReportInput) -> str:
    aggregate = _aggregate(report_input)
    payload = json.dumps(
        {
            "title": report_input.title,
            "source_type": report_input.source_type,
            "source_path": report_input.source_path,
            "runs": len(report_input.runs),
            "tasks": len(report_input.tasks),
            "llm_calls": aggregate["llm_calls"],
            "tool_calls": aggregate["tool_calls"],
            "findings": len(report_input.findings),
        },
        sort_keys=True,
    )
    sections = [
        _overview(report_input, aggregate),
        _instrumentation(report_input),
        _tasks(report_input),
        _timeline(report_input),
        _token_attribution(report_input),
        _context_growth(report_input),
        _tool_reinjections(report_input),
        _metric_provenance(report_input),
        _investigations(report_input),
        _findings(report_input),
        _serving(report_input),
        _environment(report_input),
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
            f'<script type="application/json" id="agentperf-report-data">{_h(payload)}</script>',
            '<main class="page">',
            _hero(report_input),
            *sections,
            "</main>",
            "<script>",
            _JS,
            "</script>",
            "</body>",
            "</html>",
        ]
    )


def write_html_report(input_path: Path, output_path: Path, *, title: str | None = None) -> None:
    report_input = load_html_report_input(input_path, title=title)
    output_path.write_text(render_html_report(report_input), encoding="utf-8")


def _from_artifact(
    artifact: ExperimentArtifact,
    path: Path,
    *,
    title: str | None,
) -> HtmlReportInput:
    runs = artifact.runs_for_comparison()
    reports = [analyze_run(run) for run in runs]
    completeness = assess_runs(
        reports,
        task_results=artifact.task_results,
        manifest=artifact.manifest,
        source_type="artifact",
        source_path=str(path),
    )
    persisted_findings = artifact.findings or [
        finding for report in reports for finding in report.findings
    ]
    manifest = {
        "artifact_id": artifact.manifest.artifact_id,
        "schema_version": artifact.manifest.artifact_schema_version,
        "created_at": artifact.manifest.created_at,
        "agentperf_version": artifact.manifest.agentperf_version,
        "workload_id": artifact.manifest.workload_id,
        "framework": artifact.manifest.framework,
        "agent_name": artifact.manifest.agent_name,
        "backend": artifact.manifest.backend,
        "model": artifact.manifest.model,
        "task_count": artifact.manifest.task_count,
        "serving_telemetry": artifact.manifest.serving_telemetry,
        "status": artifact.manifest.status,
        "metadata": artifact.manifest.metadata,
    }
    return HtmlReportInput(
        title=title or artifact.manifest.workload_id or artifact.manifest.artifact_id,
        source_type="artifact",
        source_path=str(path),
        runs=runs,
        reports=reports,
        tasks=artifact.task_results,
        quality_metrics=artifact.quality_metrics,
        findings=persisted_findings,
        environment=artifact.environment,
        manifest=manifest,
        summary=artifact.summary,
        completeness=completeness,
    )


def _parse_raw_runs(data: Any) -> list[AgentRun]:
    if isinstance(data, dict) and isinstance(data.get("runs"), list):
        return [parse_agentperf_trace(item) for item in data["runs"]]
    if isinstance(data, list):
        return [parse_agentperf_trace(item) for item in data]
    if isinstance(data, dict):
        return [parse_agentperf_trace(data)]
    raise ValueError("report input must be an artifact directory or normalized trace JSON")


def _default_title(path: Path) -> str:
    return f"AgentPerf report: {path.name}"


def _hero(report_input: HtmlReportInput) -> str:
    return (
        '<header class="hero">'
        '<div>'
        '<p class="eyebrow">AgentPerf Local Profiler Report</p>'
        f"<h1>{_h(report_input.title)}</h1>"
        f'<p class="muted">Source: {_h(report_input.source_type)} · '
        f"{_h(report_input.source_path)}</p>"
        "</div>"
        '<p class="security-note">Raw prompt and tool payloads are redacted by default. '
        "This report shows IDs, token counts, bounded metadata, and provenance.</p>"
        "</header>"
    )


def _overview(report_input: HtmlReportInput, aggregate: dict[str, Any]) -> str:
    manifest = report_input.manifest
    cards = [
        ("Status", str(manifest.get("status") or "unknown")),
        ("Framework", str(manifest.get("framework") or "unknown")),
        ("Backend", str(manifest.get("backend") or "none")),
        ("Model", str(manifest.get("model") or "unknown")),
        ("Tasks", _fmt_int(len(report_input.tasks) or manifest.get("task_count"))),
        ("Runs", _fmt_int(len(report_input.runs))),
        ("LLM calls", _fmt_int(aggregate["llm_calls"])),
        ("Tool calls", _fmt_int(aggregate["tool_calls"])),
        ("Provider input tokens", _fmt_int(aggregate["provider_input_tokens"])),
        ("Provider output tokens", _fmt_int(aggregate["provider_output_tokens"])),
        ("Component processed tokens", _fmt_int(aggregate["component_processed_tokens"])),
        ("Quality", _quality_brief(report_input.quality_metrics)),
        ("Client duration", _duration_brief(report_input, aggregate)),
        ("Material findings", _fmt_int(aggregate["material_findings"])),
    ]
    return _section(
        "Overview",
        '<div class="metric-grid">' + "".join(_metric_card(label, value) for label, value in cards)
        + "</div>",
    )


def _tasks(report_input: HtmlReportInput) -> str:
    if not report_input.tasks:
        return _section("Tasks", '<p class="empty">No task-level results recorded.</p>')
    rows = []
    for task in report_input.tasks:
        rows.append(
            "<tr>"
            f"<td>{_h(task.task_id)}</td>"
            f"<td>{_h(task.status or 'unknown')}</td>"
            f"<td>{_pass_badge(task.passed)}</td>"
            f"<td>{_h(_fmt_float(task.quality_score))}</td>"
            f"<td>{_h(_fmt_int(task.input_tokens))}</td>"
            f"<td>{_h(_fmt_ms(task.client_latency_ms or task.duration_ms))}</td>"
            f"<td>{_h(', '.join(task.agent_run_ids) or 'unlinked')}</td>"
            "</tr>"
        )
    return _section(
        "Tasks",
        _table(
            ["Task", "Status", "Pass", "Quality", "Input tokens", "Latency", "Agent runs"],
            rows,
        ),
    )


def _instrumentation(report_input: HtmlReportInput) -> str:
    report = report_input.completeness
    cards = [
        ("Agent profiling", report.agent_profiling_readiness),
        ("Cross-layer", report.cross_layer_readiness),
        (
            "LLM usage",
            _ratio(report.llm_calls_with_provider_usage, report.llm_calls_observed),
        ),
        (
            "Component attribution",
            _ratio(report.llm_calls_with_component_attribution, report.llm_calls_observed),
        ),
        (
            "Request IDs",
            _ratio(report.llm_calls_with_request_ids, report.llm_calls_observed),
        ),
        (
            "Serving correlations",
            (
                _ratio(report.exact_serving_correlations, report.eligible_serving_correlations)
                if report.cross_layer_readiness != "NOT_APPLICABLE"
                else "not applicable"
            ),
        ),
    ]
    rows = [
        "<tr>"
        f"<td>{_h(metric.name.replace('_', ' '))}</td>"
        f"<td>{_h(metric.status)}</td>"
        f"<td>{_h(_ratio(metric.covered, metric.eligible))}</td>"
        f"<td>{_h(metric.detail)}</td>"
        "</tr>"
        for metric in report.metrics
    ]
    limitations = "".join(f"<li>{_h(item)}</li>" for item in report.limitations)
    body = (
        '<p class="note">Profiling conclusions are only as strong as instrumentation '
        "coverage. Missing evidence is reported as unavailable or partial, not as a "
        "negative result.</p>"
        '<div class="metric-grid compact">'
        + "".join(_metric_card(label, value) for label, value in cards)
        + "</div>"
        + _table(["Metric", "Status", "Coverage", "Meaning"], rows)
    )
    if limitations:
        body += f"<details><summary>Limitations</summary><ul>{limitations}</ul></details>"
    return _section("Instrumentation Completeness", body)


def _timeline(report_input: HtmlReportInput) -> str:
    blocks = []
    tasks_by_run = _tasks_by_run(report_input.tasks)
    max_duration = _max_step_duration(report_input.runs)
    for run_index, run in enumerate(report_input.runs, start=1):
        task = tasks_by_run.get(run.agent_run_id)
        title = task.task_id if task else run.name or run.agent_run_id
        rows = []
        for step_index, step in enumerate(run.steps, start=1):
            rows.extend(_step_rows(step, run, step_index, max_duration))
        body = "".join(rows) or '<p class="empty">No LLM/tool steps recorded.</p>'
        blocks.append(
            '<details class="run" open>'
            f"<summary>Run {run_index}: {_h(title)} "
            f"<span>{_h(run.agent_run_id)} · {len(run.llm_calls)} LLM · "
            f"{len(run.tool_calls)} tools</span></summary>"
            f'<div class="timeline">{body}</div>'
            "</details>"
        )
    return _section("Execution Timeline", "".join(blocks))


def _step_rows(
    step: AgentStep,
    run: AgentRun,
    step_index: int,
    max_duration: float,
) -> list[str]:
    rows: list[str] = []
    for call in step.llm_calls:
        duration = _llm_duration(call, run)
        rows.append(
            _timeline_item(
                kind="LLM",
                title=f"{call.llm_call_id}",
                subtitle=f"step {step_index} · model {_unknown(call.model)}",
                duration_ms=duration,
                max_duration=max_duration,
                detail=_llm_detail(call, run),
                anchor=call.llm_call_id,
            )
        )
    for tool_call in step.tool_calls:
        rows.append(
            _timeline_item(
                kind="Tool",
                title=f"{tool_call.name}",
                subtitle=f"step {step_index} · {tool_call.tool_call_id}",
                duration_ms=_tool_duration(tool_call),
                max_duration=max_duration,
                detail=_tool_detail(tool_call),
                anchor=tool_call.tool_call_id,
            )
        )
    return rows


def _timeline_item(
    *,
    kind: str,
    title: str,
    subtitle: str,
    duration_ms: float | None,
    max_duration: float,
    detail: str,
    anchor: str,
) -> str:
    width = 0.0
    if duration_ms is not None and max_duration > 0:
        width = max(4.0, min(100.0, duration_ms / max_duration * 100.0))
    bar = (
        f'<span class="bar" style="width:{width:.1f}%"></span>'
        if duration_ms is not None
        else '<span class="bar missing"></span>'
    )
    return (
        f'<details class="timeline-item" id="{_attr(anchor)}">'
        f"<summary><span class=\"pill\">{_h(kind)}</span><strong>{_h(title)}</strong>"
        f"<span>{_h(subtitle)}</span><em>{_h(_fmt_ms(duration_ms))}</em></summary>"
        f'<div class="duration">{bar}</div>'
        f'<div class="drilldown">{detail}</div>'
        "</details>"
    )


def _llm_detail(call: LLMCall, run: AgentRun) -> str:
    serving = _serving_for_call(call, run)
    component_rows = []
    for component in call.prompt_components:
        kind = component_kind(component.name)
        tokens = token_count(component.text)
        component_rows.append(
            "<tr>"
            f"<td>{_h(kind)}</td>"
            f"<td>{_h(component.name)}</td>"
            f"<td>{_h(_fmt_int(tokens))}</td>"
            f"<td>{_h(_safe_metadata(component.metadata))}</td>"
            "</tr>"
        )
    serving_html = (
        _serving_detail(serving)
        if serving
        else '<p class="empty">No exact serving correlation recorded.</p>'
    )
    provider_usage = (
        f"input {_h(_fmt_int(call.input_tokens))}, "
        f"output {_h(_fmt_int(call.output_tokens))}"
    )
    return (
        '<div class="two-col">'
        '<div>'
        "<h4>LLM Call</h4>"
        f"<p>ID: <code>{_h(call.llm_call_id)}</code></p>"
        f"<p>Request ID: <code>{_h(call.llm_request_id or 'missing')}</code></p>"
        f"<p>Provider usage: {provider_usage}</p>"
        f"<p>Tokenization: {_h(call.tokenization_mode)}</p>"
        "</div>"
        '<div>'
        "<h4>Serving Correlation</h4>"
        f"{serving_html}"
        "</div>"
        "</div>"
        "<h4>Prompt Component Attribution</h4>"
        + _table(["Kind", "Component", "Tokens", "Metadata"], component_rows)
    )


def _tool_detail(call: ToolCall) -> str:
    output_tokens = token_count(str(call.output)) if call.output is not None else 0
    rows = [
        ("Tool call ID", call.tool_call_id),
        ("Span ID", call.span_id or "missing"),
        ("Duration", _fmt_ms(_tool_duration(call))),
        ("Output token estimate", _fmt_int(output_tokens)),
        ("Metadata", _safe_metadata(call.metadata)),
    ]
    return (
        _key_values(rows)
        + '<p class="empty">Raw tool input/output payloads are redacted by default.</p>'
    )


def _token_attribution(report_input: HtmlReportInput) -> str:
    aggregate = _aggregate_attribution(report_input.runs)
    rows = []
    total = aggregate.total_processed_tokens
    for component in COMPONENT_ORDER:
        processed = aggregate.processed_tokens_by_component.get(component, 0)
        unique = aggregate.unique_tokens_by_component.get(component, 0)
        if not processed and not unique:
            continue
        share = processed / total if total else 0.0
        rows.append(
            "<tr>"
            f"<td>{_h(component)}</td>"
            f"<td>{_h(_fmt_int(processed))}</td>"
            f"<td>{_h(_fmt_int(unique))}</td>"
            f"<td>{share:.1%}</td>"
            "</tr>"
        )
    coverage = _coverage(aggregate)
    confidence = "APPROXIMATE" if aggregate.approximate else "EXACT/STRUCTURED"
    note = (
        '<p class="note"><strong>MODEL-PROVIDER USAGE</strong> is reported by the '
        "backend/client. "
        "<strong>AGENTPERF COMPONENT ATTRIBUTION</strong> estimates which agent context "
        "components caused processing. These quantities can differ.</p>"
    )
    summary = (
        '<div class="metric-grid compact">'
        + _metric_card("Provider input tokens", _fmt_int(aggregate.trace_input_tokens))
        + _metric_card("Attributed processed tokens", _fmt_int(total))
        + _metric_card("Attribution coverage", f"{coverage:.1%}")
        + _metric_card("Confidence", confidence)
        + "</div>"
    )
    return _section(
        "Token Attribution",
        note + summary + _table(["Component", "Processed", "Unique", "Share"], rows),
    )


def _context_growth(report_input: HtmlReportInput) -> str:
    rows = []
    max_tokens = 0
    all_rows: list[ContextGrowthRow] = []
    for report in report_input.reports:
        all_rows.extend(report.context_growth)
    for row in all_rows:
        max_tokens = max(max_tokens, row.input_tokens)
    for row in all_rows:
        width = row.input_tokens / max_tokens * 100 if max_tokens else 0
        rows.append(
            "<tr>"
            f"<td>{row.step_index}</td>"
            f"<td><a href=\"#{_attr(row.llm_call_id)}\">{_h(row.llm_call_id)}</a></td>"
            f"<td>{_h(_fmt_int(row.input_tokens))}"
            f'<div class="mini-bar"><span style="width:{width:.1f}%"></span></div></td>'
            f"<td>{_h(_fmt_int(row.history_tokens))}</td>"
            f"<td>{_h(_fmt_int(row.tool_result_tokens))}</td>"
            f"<td>{_h(_fmt_int(row.retrieved_context_tokens))}</td>"
            "</tr>"
        )
    body = _table(
        ["Step", "LLM call", "Input tokens", "History", "Tool result", "Retrieved"],
        rows,
    ) if rows else '<p class="empty">No LLM context-growth rows recorded.</p>'
    return _section("Context Growth", body)


def _tool_reinjections(report_input: HtmlReportInput) -> str:
    reinjections = [item for report in report_input.reports for item in report.tool_reinjections]
    reinjections = sorted(
        reinjections,
        key=lambda item: item.cumulative_processed_tokens,
        reverse=True,
    )
    rows = []
    for item in reinjections:
        if not item.raw_output_tokens and not item.cumulative_processed_tokens:
            continue
        links = ", ".join(
            f'<a href="#{_attr(call_id)}">{_h(call_id)}</a>' for call_id in item.reinjected_calls
        )
        rows.append(
            "<tr>"
            f"<td><a href=\"#{_attr(item.tool_call_id)}\">{_h(item.tool_name)}</a></td>"
            f"<td>{_h(_fmt_int(item.raw_output_tokens))}</td>"
            f"<td>{_h(_fmt_int(item.cumulative_processed_tokens))}</td>"
            f"<td>{len(item.reinjected_calls)}</td>"
            f"<td>{links or 'none'}</td>"
            "</tr>"
        )
    intro = (
        '<p class="note">Unique tool output and cumulative downstream processing are separate. '
        "A 4K-token tool result carried into three later LLM calls can contribute about 12K "
        "processed tokens.</p>"
    )
    body = _table(
        ["Tool", "Unique output tokens", "Processed downstream", "Reinjections", "LLM calls"],
        rows,
    ) if rows else '<p class="empty">No tool-output carry-forward evidence recorded.</p>'
    return _section("Tool-Output Carry-Forward", intro + body)


def _metric_provenance(report_input: HtmlReportInput) -> str:
    rows = []
    for report in report_input.reports:
        for item in report.metric_provenance:
            rows.append(
                "<tr>"
                f"<td>{_h(item.name.replace('_', ' '))}</td>"
                f"<td>{_h(_safe_value(item.value))}</td>"
                f"<td>{_h(item.unit)}</td>"
                f"<td>{_h(item.source_layer)}</td>"
                f"<td>{_h(item.source_field)}</td>"
                f"<td>{_h(item.aggregation)}</td>"
                f"<td>{_h(item.semantic_meaning)}</td>"
                f"<td>{_h(item.availability)}</td>"
                "</tr>"
            )
    if not rows:
        return _section("Metric Provenance", '<p class="empty">No metric provenance recorded.</p>')
    intro = (
        '<p class="note">These rows explain which layer produced commonly confused '
        "numbers. Agent trace tokens, component attribution, provider usage, and "
        "serving telemetry may legitimately differ.</p>"
    )
    return _section(
        "Metric Provenance",
        intro
        + _table(
            [
                "Metric",
                "Value",
                "Unit",
                "Source layer",
                "Source field",
                "Aggregation",
                "Meaning",
                "Availability",
            ],
            rows,
        ),
    )


def _investigations(report_input: HtmlReportInput) -> str:
    investigations = [
        investigation
        for report in report_input.reports
        for investigation in report.investigations
    ]
    if not investigations:
        return _section(
            "Investigations",
            '<p class="empty">No related finding investigation chains recorded.</p>',
        )
    cards = []
    for investigation in investigations:
        facts = "".join(
            "<tr>"
            f"<td>{_h(fact.relationship)}</td>"
            f"<td>{_h(fact.label)}</td>"
            f"<td>{_h(fact.value)}</td>"
            f"<td>{_h(fact.strength)}</td>"
            "</tr>"
            for fact in investigation.facts
        )
        interpretation = "".join(
            f"<li>{_h(item)}</li>" for item in investigation.interpretation
        )
        experiment = "".join(
            f"<li>{_h(item)}</li>" for item in investigation.recommended_experiment
        )
        related = ", ".join(investigation.related_finding_ids)
        cards.append(
            '<article class="investigation">'
            f"<h3>{_h(investigation.title)}</h3>"
            f"<p>{_h(investigation.summary)}</p>"
            f"<p><strong>Related findings:</strong> {_h(related)}</p>"
            "<h4>Facts</h4>"
            + _table(["Relationship", "Evidence", "Value", "Strength"], [facts] if facts else [])
            + "<h4>Interpretation</h4>"
            f"<ul>{interpretation}</ul>"
            "<h4>Assessment</h4>"
            f"<p>{_h(investigation.assessment)}</p>"
            "<h4>Recommended experiment</h4>"
            f"<ul>{experiment}</ul>"
            "</article>"
        )
    note = (
        '<p class="note">Investigation chains group related evidence. They do not claim '
        "causality unless the individual findings and replay evidence support it.</p>"
    )
    return _section("Investigations", note + "".join(cards))


def _findings(report_input: HtmlReportInput) -> str:
    if not report_input.findings:
        return _section("Findings", '<p class="empty">No AgentPerf findings recorded.</p>')
    findings = sorted(report_input.findings, key=_finding_sort_key)
    cards = []
    for finding in findings:
        provenance_links = _provenance_links(finding)
        evidence = _safe_metadata(
            {
                key: value
                for key, value in finding.evidence.items()
                if key != "materiality_evaluation"
            }
        )
        materiality = _finding_materiality_evaluation(finding)
        validation = "".join(f"<li>{_h(item)}</li>" for item in finding.validation_plan)
        contract = _recommendation_contract_html(finding)
        cards.append(
            '<article class="finding">'
            f'<div><span class="severity {finding.severity.lower()}">'
            f"{_h(finding.severity)}</span> "
            f'<span class="materiality">{_h(_finding_materiality(finding))}</span></div>'
            f"<h3>{_h(finding.id)} · {_h(finding.title)}</h3>"
            f"<p>{_h(finding.summary)}</p>"
            f"<p><strong>Scope:</strong> {_h(str(finding.evidence.get('scope', 'trace')))}</p>"
            f"<p><strong>Affected:</strong> {_affected_html(finding, provenance_links)}</p>"
            f"<p><strong>Evidence:</strong> <code>{_h(evidence)}</code></p>"
            f"{materiality}"
            f"<p><strong>Recommendation:</strong> {_h(finding.recommendation)}</p>"
            f"{contract}"
            "<details><summary>Validation plan</summary>"
            f"<ul>{validation or '<li>none recorded</li>'}</ul></details>"
            "</article>"
        )
    note = (
        '<p class="note">Findings are ordered by materiality and severity. Dominant does not '
        "necessarily mean material; repeated does not automatically mean removable.</p>"
    )
    return _section("Findings", note + "".join(cards))


def _recommendation_contract_html(finding: Finding) -> str:
    contract = recommendation_contract_for_finding(finding)
    if contract is None:
        return ""
    interventions = "".join(f"<li>{_h(item)}</li>" for item in contract.interventions)
    expected = "".join(
        "<li>"
        f"<code>{_h(change.metric)}</code> {_h(change.direction.lower())}"
        f" ({'required' if change.required else 'supporting'})"
        "</li>"
        for change in contract.expected_metric_changes
    )
    risks = "".join(f"<li>{_h(item)}</li>" for item in contract.risks)
    verification = "".join(
        f"<li>{_h(item)}</li>" for item in contract.verification_requirements
    )
    if not expected:
        expected = "<li>No optimization metric required.</li>"
    if not interventions:
        interventions = "<li>No intervention recommended from this observation alone.</li>"
    return (
        '<details class="recommendation-contract">'
        "<summary>Recommendation contract</summary>"
        f"<p><strong>Objective:</strong> {_h(contract.objective)}</p>"
        f"<p><strong>Applicability:</strong> {_h(contract.applicability)}</p>"
        "<h4>Possible interventions</h4>"
        f"<ul>{interventions}</ul>"
        "<h4>Expected metric movement</h4>"
        f"<ul>{expected}</ul>"
        "<h4>Risk</h4>"
        f"<ul>{risks or '<li>none recorded</li>'}</ul>"
        "<h4>How to verify</h4>"
        f"<ul>{verification or '<li>none recorded</li>'}</ul>"
        "</details>"
    )


def _serving(report_input: HtmlReportInput) -> str:
    requests = [request for run in report_input.runs for request in run.serving_requests]
    if not requests:
        return _section("Serving Telemetry", '<p class="empty">No serving telemetry recorded.</p>')
    rows = []
    for request in requests:
        cached = request.prefix_cache_hit_tokens or 0
        miss = request.prefix_cache_miss_tokens or 0
        total_cache = cached + miss
        cache_ratio = cached / total_cache if total_cache else None
        rows.append(
            "<tr>"
            f"<td>{_h(request.serving_request_id)}</td>"
            f"<td>{_h(request.llm_request_id or 'missing')}</td>"
            f"<td>{_h(_unknown(request.backend))}</td>"
            f"<td>{_h(_unknown(request.model))}</td>"
            f"<td>{_h(_fmt_ms(request.queue_latency_ms))}</td>"
            f"<td>{_h(_fmt_ms(_first_token_evidence_ms(request)))}</td>"
            f"<td>{_h(_fmt_ms(request.decode_latency_ms))}</td>"
            f"<td>{_h(_fmt_int(cached))}</td>"
            f"<td>{_h(_fmt_int(miss))}</td>"
            f"<td>{_h(_fmt_percent(cache_ratio))}</td>"
            "</tr>"
        )
    intro = (
        '<p class="note">First-token evidence preserves backend provenance. For vLLM, '
        "scheduled-to-first is end-to-end serving path evidence, not pure GPU prefill "
        "kernel time. For SGLang, client TTFT is client-observed unless server trace "
        "stages are recorded. Correlation uses explicit request IDs when present.</p>"
    )
    return _section(
        "Serving Telemetry",
        intro
        + _table(
            [
                "Serving request",
                "LLM request",
                "Backend",
                "Model",
                "Queue",
                "First-token evidence",
                "Generation",
                "Cached",
                "Miss",
                "Cache ratio",
            ],
            rows,
        ),
    )


def _environment(report_input: HtmlReportInput) -> str:
    rows = []
    for key, value in sorted(report_input.manifest.items()):
        if key == "metadata":
            continue
        rows.append((key, _safe_value(value)))
    for key, value in sorted(report_input.environment.items()):
        rows.append((f"environment.{key}", _safe_value(value)))
    if report_input.summary:
        rows.append(("summary", _safe_metadata(report_input.summary)))
    if not rows:
        return _section("Environment", '<p class="empty">No environment metadata recorded.</p>')
    return _section(
        "Environment",
        "<details><summary>Reproducibility metadata</summary>"
        + _key_values(rows)
        + "</details>",
    )


def _aggregate(report_input: HtmlReportInput) -> dict[str, Any]:
    provider_input = sum(
        call_input_tokens(call) for run in report_input.runs for call in run.llm_calls
    )
    provider_output = sum(
        call.output_tokens or 0 for run in report_input.runs for call in run.llm_calls
    )
    attribution = _aggregate_attribution(report_input.runs)
    material_findings = sum(1 for finding in report_input.findings if _is_material(finding))
    task_duration = sum(
        task.client_latency_ms or task.duration_ms or 0 for task in report_input.tasks
    )
    return {
        "llm_calls": sum(len(run.llm_calls) for run in report_input.runs),
        "tool_calls": sum(len(run.tool_calls) for run in report_input.runs),
        "provider_input_tokens": provider_input,
        "provider_output_tokens": provider_output,
        "component_processed_tokens": attribution.total_processed_tokens,
        "material_findings": material_findings,
        "task_duration_ms": task_duration or None,
    }


def _aggregate_attribution(runs: list[AgentRun]) -> ComponentTokenAttribution:
    processed: dict[str, int] = {}
    unique: dict[str, int] = {}
    total_input = 0
    approximate = False
    for run in runs:
        attribution = component_token_attribution(run)
        total_input += attribution.trace_input_tokens
        approximate = approximate or attribution.approximate
        for key, value in attribution.processed_tokens_by_component.items():
            processed[key] = processed.get(key, 0) + value
        for key, value in attribution.unique_tokens_by_component.items():
            unique[key] = unique.get(key, 0) + value
    return ComponentTokenAttribution(
        processed_tokens_by_component={
            key: processed[key] for key in COMPONENT_ORDER if processed.get(key)
        },
        unique_tokens_by_component={
            key: unique[key] for key in COMPONENT_ORDER if unique.get(key)
        },
        total_processed_tokens=sum(processed.values()),
        total_unique_tokens=sum(unique.values()),
        trace_input_tokens=total_input,
        approximate=approximate,
    )


def _coverage(attribution: ComponentTokenAttribution) -> float:
    total = attribution.total_processed_tokens
    if not total:
        return 0.0
    other = attribution.processed_tokens_by_component.get("other", 0)
    return (total - other) / total


def _ratio(covered: int, eligible: int) -> str:
    if eligible <= 0:
        return f"{covered} / n/a"
    return f"{covered} / {eligible}"


def _tasks_by_run(tasks: list[TaskResult]) -> dict[str, TaskResult]:
    result: dict[str, TaskResult] = {}
    for task in tasks:
        for run_id in task.agent_run_ids:
            result[run_id] = task
    return result


def _max_step_duration(runs: list[AgentRun]) -> float:
    values = []
    for run in runs:
        for call in run.llm_calls:
            duration = _llm_duration(call, run)
            if duration is not None:
                values.append(duration)
        for tool_call in run.tool_calls:
            duration = _tool_duration(tool_call)
            if duration is not None:
                values.append(duration)
    return max(values, default=0.0)


def _llm_duration(call: LLMCall, run: AgentRun) -> float | None:
    serving = _serving_for_call(call, run)
    if serving and serving.total_model_latency_ms is not None:
        return serving.total_model_latency_ms
    if call.started_at and call.ended_at:
        start = parse_datetime(call.started_at)
        end = parse_datetime(call.ended_at)
        if start and end:
            return (end - start).total_seconds() * 1000
    return call.ttft_ms


def _tool_duration(call: ToolCall) -> float | None:
    if call.latency_ms is not None:
        return call.latency_ms
    if call.started_at and call.ended_at:
        start = parse_datetime(call.started_at)
        end = parse_datetime(call.ended_at)
        if start and end:
            return (end - start).total_seconds() * 1000
    return None


def _serving_for_call(call: LLMCall, run: AgentRun) -> ServingRequest | None:
    for request in run.serving_requests:
        if call.serving_request_id and request.serving_request_id == call.serving_request_id:
            return request
        if call.llm_request_id and request.llm_request_id == call.llm_request_id:
            return request
    return None


def _serving_detail(request: ServingRequest) -> str:
    return _key_values(
        [
            ("Serving request", request.serving_request_id),
            ("Backend", request.backend or "unknown"),
            ("Model", request.model or "unknown"),
            ("Queue", _fmt_ms(request.queue_latency_ms)),
            (_first_token_label(request), _fmt_ms(_first_token_evidence_ms(request))),
            ("Generation", _fmt_ms(request.decode_latency_ms)),
            ("Cached prompt tokens", _fmt_int(request.prefix_cache_hit_tokens)),
            ("Cache-miss prompt tokens", _fmt_int(request.prefix_cache_miss_tokens)),
        ]
    )


def _first_token_evidence_ms(request: ServingRequest) -> float | None:
    return request.prefill_path_latency_ms or request.prefill_latency_ms or request.ttft_ms


def _first_token_label(request: ServingRequest) -> str:
    semantics = (
        request.metadata.get("metric_reliability", {})
        .get("measurement_semantics", {})
        .get("ttft_ms")
    )
    if semantics == "client_time_to_first_token":
        return "Client TTFT"
    return "Scheduled->first"


def _quality_brief(metrics: list[QualityMetric]) -> str:
    if not metrics:
        return "not recorded"
    parts = []
    for metric in metrics:
        if metric.name in {"mean_score", "pass_rate", "task_success_rate", "task_success"}:
            parts.append(f"{metric.name}={_fmt_metric(metric.value)}")
    if not parts:
        metric = metrics[0]
        parts.append(f"{metric.name}={_fmt_metric(metric.value)}")
    return ", ".join(parts)


def _duration_brief(report_input: HtmlReportInput, aggregate: dict[str, Any]) -> str:
    task_duration = aggregate.get("task_duration_ms")
    if task_duration is not None:
        return _fmt_ms(float(task_duration))
    durations = [run.duration_ms for run in report_input.runs if run.duration_ms is not None]
    if durations:
        return _fmt_ms(sum(durations))
    return "not recorded"


def _pass_badge(value: bool | None) -> str:
    if value is None:
        return '<span class="badge unknown">unknown</span>'
    if value:
        return '<span class="badge pass">pass</span>'
    return '<span class="badge fail">fail</span>'


def _provenance_links(finding: Finding) -> str:
    links = []
    for call_id in finding.provenance.llm_call_ids:
        links.append(f'<a href="#{_attr(call_id)}">{_h(call_id)}</a>')
    for request_id in finding.provenance.serving_request_ids:
        links.append(_h(request_id))
    for span_id in finding.provenance.agent_span_ids:
        links.append(_h(span_id))
    return ", ".join(links)


def _finding_sort_key(finding: Finding) -> tuple[int, int, str]:
    return (
        0 if _is_material(finding) else 1,
        {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(finding.severity, 3),
        finding.id,
    )


def _is_material(finding: Finding) -> bool:
    materiality = str(finding.evidence.get("materiality", "")).upper()
    return materiality in {"MATERIAL", "ACTIONABLE"} or (
        finding.severity == "HIGH" and materiality not in {"OBSERVATION", "HEADROOM"}
    )


def _finding_materiality(finding: Finding) -> str:
    return str(finding.evidence.get("materiality", "unspecified"))


def _affected_html(finding: Finding, provenance_links: str) -> str:
    if provenance_links:
        return provenance_links
    return _h(", ".join(finding.affected_spans) or "none recorded")


def _finding_materiality_evaluation(finding: Finding) -> str:
    value = finding.evidence.get("materiality_evaluation")
    if not isinstance(value, dict):
        return ""
    rows = []
    gates = value.get("gates")
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            rows.append(
                "<tr>"
                f"<td>{_h(gate.get('name', 'gate'))}</td>"
                f"<td>{_h(gate.get('observed', 'unknown'))} {_h(gate.get('unit', ''))}</td>"
                f"<td>{_h(gate.get('threshold', 'unknown'))} {_h(gate.get('unit', ''))}</td>"
                f"<td>{_h(gate.get('result', 'unknown'))}</td>"
                f"<td>{_h(gate.get('source_layer', 'unknown'))}</td>"
                "</tr>"
            )
    reason = value.get("reason", "")
    rule = value.get("rule", "")
    overall = value.get("overall", "")
    return (
        "<details class=\"materiality-detail\" open>"
        "<summary>Materiality evaluation</summary>"
        f"<p><strong>Overall:</strong> {_h(overall)}</p>"
        f"<p><strong>Rule:</strong> {_h(rule)}</p>"
        + _table(["Gate", "Observed", "Threshold", "Result", "Source"], rows)
        + f"<p><strong>Reason:</strong> {_h(reason)}</p>"
        "</details>"
    )


def _metric_card(label: str, value: str) -> str:
    return (
        '<div class="metric">'
        f"<span>{_h(label)}</span><strong>{_h(value)}</strong>"
        "</div>"
    )


def _table(headers: list[str], rows: list[str]) -> str:
    if not rows:
        return '<p class="empty">No rows recorded.</p>'
    header_html = "".join(f"<th>{_h(header)}</th>" for header in headers)
    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"{header_html}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def _key_values(rows: list[tuple[str, Any]]) -> str:
    items = "".join(
        f"<dt>{_h(label)}</dt><dd>{_h(str(value))}</dd>" for label, value in rows
    )
    return f'<dl class="kv">{items}</dl>'


def _section(title: str, body: str) -> str:
    return f'<section class="panel"><h2>{_h(title)}</h2>{body}</section>'


def _safe_metadata(data: dict[str, Any]) -> str:
    redacted = {str(key): _safe_metadata_value(str(key), value) for key, value in data.items()}
    return json.dumps(redacted, sort_keys=True, ensure_ascii=False)


def _safe_metadata_value(key: str, value: Any) -> Any:
    if _secretish_key(key):
        return "[redacted]"
    if isinstance(value, str) and _secretish_value(value):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key): _safe_metadata_value(str(child_key), child_value)
            for child_key, child_value in list(value.items())[:20]
        }
    if isinstance(value, list):
        items = [_safe_metadata_value(key, item) for item in value[:5]]
        if len(value) > 5:
            items.append(f"... {len(value) - 5} more")
        return items
    if isinstance(value, str) and len(value) > 160:
        return value[:157] + "..."
    return value


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


def _secretish_value(value: str) -> bool:
    lower = value.lower()
    if any(
        marker in lower
        for marker in (
            "openai_api_key=",
            "hf_token=",
            "runpod_api_key=",
            "authorization:",
            "bearer ",
            "password=",
            "private_key=",
        )
    ):
        return True
    if re.search(r"\bsk-[a-z0-9_-]{8,}\b", value, flags=re.IGNORECASE):
        return True
    return bool(re.search(r"(/users/|/user/|/private/tmp/)", value, flags=re.IGNORECASE))


def _safe_value(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, dict):
        return _safe_metadata(value)
    if isinstance(value, list):
        return json.dumps(value[:20], sort_keys=True, ensure_ascii=False)
    text = str(value)
    return text if len(text) <= 200 else text[:197] + "..."


def _fmt_int(value: Any) -> str:
    if value is None:
        return "not recorded"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_float(value: float | None) -> str:
    if value is None:
        return "not recorded"
    return f"{value:.3f}"


def _fmt_metric(value: float | bool | str) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int | float):
        return f"{float(value):.3f}"
    return str(value)


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "not recorded"
    if value >= 1000:
        return f"{value / 1000:.2f}s"
    return f"{value:.2f} ms"


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "not recorded"
    return f"{value:.1%}"


def _unknown(value: str | None) -> str:
    return value or "unknown"


def _h(value: Any) -> str:
    return escape(str(value), quote=False)


def _attr(value: str) -> str:
    return escape(value, quote=True)


_CSS = """
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --ink: #17202a;
  --muted: #667085;
  --line: #d8dde6;
  --accent: #265fdb;
  --good: #087443;
  --bad: #b42318;
  --warn: #b54708;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}
.page { max-width: 1180px; margin: 0 auto; padding: 28px; }
.hero {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  align-items: flex-end;
  margin-bottom: 22px;
}
.eyebrow { color: var(--accent); font-weight: 700; margin: 0 0 6px; }
h1 { margin: 0; font-size: 28px; line-height: 1.15; }
h2 { margin: 0 0 14px; font-size: 18px; }
h3 { margin: 8px 0 6px; font-size: 15px; }
h4 {
  margin: 12px 0 6px;
  font-size: 13px;
  color: var(--muted);
  text-transform: uppercase;
}
.muted, .empty, .note, .security-note { color: var(--muted); }
.security-note { max-width: 390px; margin: 0; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 18px;
  margin: 16px 0;
}
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 10px;
}
.metric {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  min-height: 70px;
}
.metric span { display: block; color: var(--muted); font-size: 12px; }
.metric strong {
  display: block;
  margin-top: 6px;
  font-size: 16px;
  overflow-wrap: anywhere;
}
.compact .metric { min-height: 58px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td {
  border-bottom: 1px solid var(--line);
  padding: 8px 7px;
  text-align: left;
  vertical-align: top;
}
th { color: var(--muted); font-size: 12px; text-transform: uppercase; }
code { background: #eef2f7; border-radius: 4px; padding: 1px 4px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.run {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 10px 12px;
  margin: 10px 0;
}
.run > summary { cursor: pointer; font-weight: 700; }
.run > summary span { color: var(--muted); font-weight: 500; margin-left: 8px; }
.timeline { margin-top: 10px; }
.timeline-item {
  border-left: 3px solid var(--accent);
  background: #fbfcfe;
  border-radius: 6px;
  margin: 9px 0;
  padding: 8px 10px;
}
.timeline-item > summary {
  display: grid;
  grid-template-columns: 58px minmax(130px, 1fr) minmax(160px, 2fr) 92px;
  gap: 10px;
  align-items: center;
  cursor: pointer;
}
.timeline-item em { color: var(--muted); font-style: normal; text-align: right; }
.pill, .badge, .severity, .materiality {
  display: inline-block;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 12px;
  font-weight: 700;
}
.pill { background: #e9efff; color: var(--accent); }
.badge.pass { background: #ecfdf3; color: var(--good); }
.badge.fail { background: #fef3f2; color: var(--bad); }
.badge.unknown { background: #f2f4f7; color: var(--muted); }
.severity.high { background: #fef3f2; color: var(--bad); }
.severity.medium { background: #fff7ed; color: var(--warn); }
.severity.low { background: #eef2f7; color: var(--muted); }
.materiality { background: #f2f4f7; color: var(--muted); }
.duration, .mini-bar {
  height: 8px;
  background: #eef2f7;
  border-radius: 999px;
  overflow: hidden;
  margin-top: 8px;
}
.duration .bar, .mini-bar span {
  display: block;
  height: 100%;
  background: var(--accent);
}
.duration .missing { width: 0; }
.drilldown {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
}
.two-col {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
}
.kv {
  display: grid;
  grid-template-columns: minmax(170px, 0.35fr) minmax(0, 1fr);
  gap: 6px 12px;
}
.kv dt { color: var(--muted); }
.kv dd { margin: 0; overflow-wrap: anywhere; }
.finding {
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 12px;
  margin: 10px 0;
}
@media (max-width: 760px) {
  .page { padding: 16px; }
  .hero { display: block; }
  .timeline-item > summary { grid-template-columns: 1fr; }
  .timeline-item em { text-align: left; }
  .two-col { grid-template-columns: 1fr; }
}
"""


_JS = """
document.querySelectorAll('a[href^="#"]').forEach((link) => {
  link.addEventListener('click', () => {
    const id = link.getAttribute('href').slice(1);
    const target = document.getElementById(id);
    if (target && target.tagName.toLowerCase() === 'details') {
      target.open = true;
    }
  });
});
"""
