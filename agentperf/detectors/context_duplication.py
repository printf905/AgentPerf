from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.components import component_kind
from agentperf.metrics.tokens import DuplicationMetrics, compute_duplication_metrics, token_count
from agentperf.schema.findings import Finding, FindingProvenance, Severity
from agentperf.schema.trace import AgentRun, LLMCall


@dataclass(frozen=True)
class ContextDuplicationConfig:
    min_affected_calls: int = 3
    min_repeated_tokens: int = 50
    min_repeated_ratio: float = 0.25
    min_material_repeated_tokens: int = 5000
    min_cross_run_repeated_tokens: int = 500


@dataclass(frozen=True)
class CrossRunScaffoldMetrics:
    scope_count: int
    repeated_tokens: int
    repeated_tokens_by_component: dict[str, int]
    affected_call_ids: list[str]


class ContextDuplicationDetector:
    def __init__(self, config: ContextDuplicationConfig | None = None) -> None:
        self.config = config or ContextDuplicationConfig()

    def detect(self, context: DetectorContext) -> list[Finding]:
        scopes = _execution_scopes(context.run)
        findings: list[Finding] = []
        within_scope_findings = [
            self._within_run_finding(scope_id, calls)
            for scope_id, calls in scopes.items()
        ]
        findings.extend(
            finding
            for finding in within_scope_findings
            if finding is not None and (len(scopes) == 1 or finding.severity != "LOW")
        )

        if len(scopes) > 1:
            cross_run = _cross_run_shared_scaffold(scopes)
            if (
                cross_run.repeated_tokens >= self.config.min_cross_run_repeated_tokens
                and cross_run.scope_count >= 2
            ):
                findings.append(self._cross_run_finding(cross_run, context))

        return findings

    def _within_run_finding(self, scope_id: str, calls: list[LLMCall]) -> Finding | None:
        metrics = compute_duplication_metrics(calls)
        if len(metrics.affected_call_ids) < self.config.min_affected_calls:
            return None
        if metrics.repeated_context_tokens < self.config.min_repeated_tokens:
            return None
        if metrics.repeated_context_ratio < self.config.min_repeated_ratio:
            return None

        if metrics.repeated_context_tokens < self.config.min_material_repeated_tokens:
            severity: Severity = "LOW"
            materiality = "OBSERVATION"
        elif metrics.repeated_context_ratio >= 0.5:
            severity = "HIGH"
            materiality = "MATERIAL"
        else:
            severity = "MEDIUM"
            materiality = "HEADROOM"

        return _context_duplication_finding(
            scope_id=scope_id,
            metrics=metrics,
            severity=severity,
            materiality=materiality,
        )

    def _cross_run_finding(
        self,
        cross_run: CrossRunScaffoldMetrics,
        context: DetectorContext,
    ) -> Finding:
        has_serving = bool(context.run.serving_requests)
        materiality = "CACHEABILITY_HEADROOM" if has_serving else "OBSERVATION"
        recommendation = (
            "No context-removal recommendation. This repeated scaffold occurs across "
            "independent execution scopes; evaluate static prompt or prefix caching only "
            "if the serving backend supports it and telemetry shows material latency."
        )
        validation_plan = [
            "If serving telemetry is available, compare prefix-cache reuse for these scopes.",
            "Do not remove shared instructions solely because they repeat across tasks.",
        ]
        return Finding(
            id="CROSS_RUN_SHARED_SCAFFOLD",
            severity="LOW",
            title="Shared static scaffold across independent executions",
            summary=(
                "The same prompt scaffold appears across independent execution scopes. "
                "This is not evidence that the content is unnecessary within a task."
            ),
            evidence={
                "scope": "cross_run_shared_scaffold",
                "scope_count": cross_run.scope_count,
                "llm_calls_affected": len(cross_run.affected_call_ids),
                "repeated_context_tokens": cross_run.repeated_tokens,
                "repeated_tokens_by_component": cross_run.repeated_tokens_by_component,
                "materiality": materiality,
                "serving_telemetry_present": has_serving,
            },
            affected_spans=cross_run.affected_call_ids,
            recommendation=recommendation,
            confidence="MEDIUM",
            validation_plan=validation_plan,
            provenance=FindingProvenance(
                llm_call_ids=cross_run.affected_call_ids,
                derived_metrics={
                    "scope_count": cross_run.scope_count,
                    "repeated_context_tokens": cross_run.repeated_tokens,
                    "materiality": materiality,
                },
                notes=[
                    "Cross-run repetition is measured once per execution scope.",
                    "Repetition across independent tasks is not treated as removable context.",
                ],
            ),
        )


def _context_duplication_finding(
    *,
    scope_id: str,
    metrics: DuplicationMetrics,
    severity: Severity,
    materiality: str,
) -> Finding:
    return Finding(
        id="CONTEXT_DUPLICATION",
        severity=severity,
        title="Repeated prompt context within one execution scope",
        summary=(
            "Multiple LLM calls in the same execution scope contain exact repeated "
            "prompt components. Repeated content may be necessary, but it is a cost "
            "and latency signal."
        ),
        evidence={
            "scope": "within_run_duplication",
            "execution_scope_id": scope_id,
            "llm_calls_affected": len(metrics.affected_call_ids),
            "total_input_tokens": metrics.total_input_tokens,
            "repeated_context_tokens": metrics.repeated_context_tokens,
            "repeated_context_ratio": round(metrics.repeated_context_ratio, 4),
            "largest_common_prefix_tokens": metrics.largest_common_prefix_tokens,
            "largest_common_prefix_ratio": round(metrics.largest_common_prefix_ratio, 4),
            "repeated_non_prefix_tokens": metrics.repeated_non_prefix_tokens,
            "repeated_tokens_by_component": metrics.repeated_tokens_by_component,
            "materiality": materiality,
            "tokenization": "approximate" if metrics.approximate else "trace-provided totals",
        },
        affected_spans=metrics.affected_call_ids,
        recommendation=(
            "Inspect whether repeated within-run context can be cached, summarized, "
            "deduplicated, or carried forward more selectively."
        ),
        confidence="MEDIUM",
        validation_plan=[
            "Replay the same execution after any prompt-structure change.",
            "Compare input tokens, task quality, and end-to-end latency.",
        ],
        provenance=FindingProvenance(
            llm_call_ids=metrics.affected_call_ids,
            derived_metrics={
                "scope": "within_run_duplication",
                "execution_scope_id": scope_id,
                "total_input_tokens": metrics.total_input_tokens,
                "repeated_context_tokens": metrics.repeated_context_tokens,
                "repeated_context_ratio": metrics.repeated_context_ratio,
                "largest_common_prefix_tokens": metrics.largest_common_prefix_tokens,
                "repeated_tokens_by_component": metrics.repeated_tokens_by_component,
                "materiality": materiality,
            },
            notes=[
                "Repeated content is measured from normalized prompt components.",
                "The detector does not infer that repeated content is unnecessary.",
                "Low absolute repeated-token volume is treated as an observation.",
            ],
        ),
    )


def _execution_scopes(run: AgentRun) -> dict[str, list[LLMCall]]:
    scope_by_step_id: dict[str, str] = {}
    scoped_steps = 0
    for step in run.steps:
        scope_id = _step_scope_id(step.metadata)
        if scope_id is not None:
            scoped_steps += 1
            scope_by_step_id[step.agent_step_id] = scope_id

    if scoped_steps < 2 and _declared_task_count(run) > 1:
        return {
            f"step:{step.agent_step_id}": list(step.llm_calls)
            for step in run.steps
            if step.llm_calls
        }

    if scoped_steps < 2:
        return {run.agent_run_id: run.llm_calls}

    scopes: defaultdict[str, list[LLMCall]] = defaultdict(list)
    for step in run.steps:
        scope_id = scope_by_step_id.get(step.agent_step_id)
        if scope_id is None:
            scope_id = f"{run.agent_run_id}:unscoped"
        scopes[scope_id].extend(step.llm_calls)
    return dict(scopes)


def _step_scope_id(metadata: dict[str, object]) -> str | None:
    for key in ("task_id", "execution_id", "workload_item_id", "run_id"):
        value = metadata.get(key)
        if value is not None:
            return f"{key}:{value}"
    return None


def _declared_task_count(run: AgentRun) -> int:
    value = run.metadata.get("task_count")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 1


def _cross_run_shared_scaffold(scopes: dict[str, list[LLMCall]]) -> CrossRunScaffoldMetrics:
    scope_counts: Counter[str] = Counter()
    component_tokens: dict[str, int] = {}
    component_kinds: dict[str, str] = {}
    affected: defaultdict[str, set[str]] = defaultdict(set)

    for calls in scopes.values():
        seen_texts: set[str] = set()
        for call in calls:
            for component in call.prompt_components:
                text = component.text
                if not text or text in seen_texts:
                    continue
                seen_texts.add(text)
                component_tokens[text] = token_count(text)
                component_kinds[text] = component_kind(component.name)
                affected[text].add(call.llm_call_id)
        for text in seen_texts:
            scope_counts[text] += 1

    repeated_by_component: defaultdict[str, int] = defaultdict(int)
    affected_call_ids: set[str] = set()
    repeated_tokens = 0
    for text, count in scope_counts.items():
        if count <= 1:
            continue
        tokens = component_tokens[text] * (count - 1)
        repeated_tokens += tokens
        repeated_by_component[component_kinds[text]] += tokens
        affected_call_ids.update(affected[text])

    return CrossRunScaffoldMetrics(
        scope_count=len(scopes),
        repeated_tokens=repeated_tokens,
        repeated_tokens_by_component=dict(sorted(repeated_by_component.items())),
        affected_call_ids=sorted(affected_call_ids),
    )
