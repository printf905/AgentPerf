from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from agentperf.correlation.correlator import CorrelationResult, TraceCorrelator
from agentperf.detectors.base import Detector, DetectorContext
from agentperf.detectors.context_duplication import ContextDuplicationDetector
from agentperf.detectors.prefill import PrefillBottleneckDetector
from agentperf.detectors.prefix_cache import PrefixCacheOpportunityDetector
from agentperf.detectors.tool_output_bloat import ToolOutputBloatDetector
from agentperf.investigations import Investigation, build_investigations
from agentperf.metric_provenance import MetricProvenance, metric_provenance_rows
from agentperf.metrics.attribution import (
    ComponentTokenAttribution,
    ContextGrowthRow,
    ToolReinjection,
    component_token_attribution,
    context_growth_rows,
    tool_reinjections,
)
from agentperf.schema.findings import Finding
from agentperf.schema.trace import AgentRun, TraceParseError, parse_agentperf_trace


@dataclass(frozen=True)
class AnalysisReport:
    run: AgentRun
    correlation: CorrelationResult
    findings: list[Finding] = field(default_factory=list)
    token_attribution: ComponentTokenAttribution | None = None
    context_growth: list[ContextGrowthRow] = field(default_factory=list)
    tool_reinjections: list[ToolReinjection] = field(default_factory=list)
    metric_provenance: list[MetricProvenance] = field(default_factory=list)
    investigations: list[Investigation] = field(default_factory=list)


def analyze_path(path: Path) -> AnalysisReport:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TraceParseError(f"invalid JSON: {exc}") from exc
    run = parse_agentperf_trace(data)
    return analyze_run(run)


def analyze_run(run: AgentRun) -> AnalysisReport:
    correlation = TraceCorrelator().correlate(run)
    context = DetectorContext(run=run, correlation=correlation)
    detectors: list[Detector] = [
        ContextDuplicationDetector(),
        ToolOutputBloatDetector(),
        PrefixCacheOpportunityDetector(),
        PrefillBottleneckDetector(),
    ]
    findings: list[Finding] = []
    for detector in detectors:
        findings.extend(detector.detect(context))
    attribution = component_token_attribution(run)
    growth = context_growth_rows(run)
    return AnalysisReport(
        run=run,
        correlation=correlation,
        findings=findings,
        token_attribution=attribution,
        context_growth=growth,
        tool_reinjections=tool_reinjections(run),
        metric_provenance=metric_provenance_rows(
            run,
            attribution=attribution,
            context_growth=growth,
            findings=findings,
        ),
        investigations=build_investigations(findings),
    )
