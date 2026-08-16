from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from agentperf.recommendations import (
    RecommendationVerification,
    recommendation_contract_for_finding,
    verify_recommendation,
)
from agentperf.schema.comparison import (
    AcceptanceResult,
    CacheDelta,
    ComponentAccountingSummary,
    ContextGrowthDelta,
    FindingChange,
    LatencyDelta,
    MetricDelta,
    QualityDelta,
    RunComparison,
    TokenDelta,
)
from agentperf.schema.findings import Finding, FindingProvenance
from agentperf.schema.trace import AgentRun, LLMCall

QUALITY_EPSILON = 1e-9
RoleCounterfactualStatus = Literal[
    "SAFE_WITHIN_TOLERANCE",
    "QUALITY_REGRESSION",
    "NO_MATERIAL_BENEFIT",
    "INCONCLUSIVE",
]
RoutingVerificationStatus = Literal[
    "VERIFIED",
    "REJECTED_QUALITY_REGRESSION",
    "NO_MATERIAL_BENEFIT",
    "CANDIDATE_TO_VERIFY",
    "INCONCLUSIVE",
]


@dataclass(frozen=True)
class RoleExecution:
    role_id: str
    model: str
    backend: str | None = None
    llm_call_ids: list[str] = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ModelRouting:
    assignments: list[RoleExecution]
    source: str = "trace"

    def as_role_map(self) -> dict[str, str]:
        return {assignment.role_id: assignment.model for assignment in self.assignments}


@dataclass(frozen=True)
class CandidateRouting:
    routing: dict[str, str]
    source: str
    status: RoutingVerificationStatus
    rationale: str


@dataclass(frozen=True)
class RoleCounterfactualResult:
    role: str
    baseline_model: str
    candidate_model: str
    config_name: str
    mean_quality_delta: float
    pass_rate_delta: float
    client_latency_p95_delta_ms: float | None
    relative_cost_delta: float
    quality_preserving: bool
    status: RoleCounterfactualStatus


@dataclass(frozen=True)
class RoutingVerification:
    config_name: str | None
    status: RoutingVerificationStatus
    quality_preserving: bool | None
    relative_cost_delta: float | None
    client_latency_p95_delta_ms: float | None
    changed_roles: list[dict[str, str]]
    recommendation_verification: RecommendationVerification | None
    reason: str


@dataclass(frozen=True)
class ModelChoiceConfig:
    name: str
    routing: dict[str, str]
    mean_score: float
    pass_rate: float
    input_tokens: int
    output_tokens: int
    ttft_p95_ms: float | None
    client_latency_p95_ms: float | None
    relative_cost: float
    role_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class RoleSensitivity:
    role: str
    baseline_model: str
    candidate_model: str
    config_name: str
    mean_quality_delta: float
    pass_rate_delta: float
    client_latency_p95_delta_ms: float | None
    relative_cost_delta: float
    quality_preserving: bool
    status: RoleCounterfactualStatus


@dataclass(frozen=True)
class ModelChoiceReport:
    environment: dict[str, Any]
    model_ladder: dict[str, dict[str, Any]]
    quality_constraint: dict[str, Any]
    baseline: ModelChoiceConfig
    configurations: list[ModelChoiceConfig]
    role_sensitivity: list[RoleSensitivity]
    findings: list[Finding]
    selected_mixed_config: str | None
    candidate_routing: CandidateRouting | None
    routing_verification: RoutingVerification
    pareto: list[dict[str, Any]]


def analyze_model_choice_path(path: Path) -> ModelChoiceReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    return analyze_model_choice_data(data)


def analyze_model_choice_data(data: dict[str, Any]) -> ModelChoiceReport:
    configs = [
        _parse_config(name, value)
        for name, value in data.get("configurations", {}).items()
        if isinstance(value, dict)
    ]
    baseline_name = str(data.get("baseline_config", "strong_all"))
    baseline = next((config for config in configs if config.name == baseline_name), None)
    if baseline is None:
        raise ValueError(f"missing model-choice baseline config: {baseline_name}")
    quality_constraint = _quality_constraint(data, baseline)
    sensitivities = _role_sensitivity(configs, baseline, quality_constraint)
    findings = _findings(sensitivities, baseline, configs, quality_constraint)
    pareto = _pareto(configs, quality_constraint)
    selected = _selected_mixed_config(data, configs, quality_constraint)
    candidate = _candidate_routing(sensitivities, baseline)
    routing_verification = _routing_verification(
        configs,
        baseline,
        quality_constraint,
        selected_mixed_config=selected,
        findings=findings,
    )
    return ModelChoiceReport(
        environment=_as_dict(data.get("environment")),
        model_ladder=_as_dict(data.get("model_ladder")),
        quality_constraint=quality_constraint,
        baseline=baseline,
        configurations=configs,
        role_sensitivity=sensitivities,
        findings=findings,
        selected_mixed_config=selected,
        candidate_routing=candidate,
        routing_verification=routing_verification,
        pareto=pareto,
    )


def _parse_config(name: str, data: dict[str, Any]) -> ModelChoiceConfig:
    correctness = _as_dict(data.get("correctness"))
    return ModelChoiceConfig(
        name=name,
        routing={str(k): str(v) for k, v in _as_dict(data.get("routing")).items()},
        mean_score=float(correctness.get("mean_score", data.get("mean_score", 0.0))),
        pass_rate=float(correctness.get("pass_rate", data.get("pass_rate", 0.0))),
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        ttft_p95_ms=_optional_float(data.get("ttft_p95_ms")),
        client_latency_p95_ms=_optional_float(data.get("client_latency_p95_ms")),
        relative_cost=float(data.get("relative_cost", 0.0)),
        role_profiles=_as_dict(data.get("role_profiles")),
    )


def _quality_constraint(
    data: dict[str, Any],
    baseline: ModelChoiceConfig,
) -> dict[str, Any]:
    raw = _as_dict(data.get("quality_constraint"))
    mean_tolerance = float(raw.get("mean_score_tolerance", 0.05))
    pass_tolerance = float(raw.get("pass_rate_tolerance", 0.10))
    return {
        "baseline_config": baseline.name,
        "mean_score_tolerance": mean_tolerance,
        "pass_rate_tolerance": pass_tolerance,
        "minimum_mean_score": baseline.mean_score - mean_tolerance,
        "minimum_pass_rate": baseline.pass_rate - pass_tolerance,
        "objective": raw.get(
            "objective",
            "minimize relative cost or latency subject to quality tolerance",
        ),
    }


def _role_sensitivity(
    configs: list[ModelChoiceConfig],
    baseline: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
) -> list[RoleSensitivity]:
    rows: list[RoleSensitivity] = []
    for config in configs:
        changed_roles = [
            role
            for role, model in config.routing.items()
            if baseline.routing.get(role) != model
        ]
        if len(changed_roles) != 1:
            continue
        role = changed_roles[0]
        rows.append(
            RoleSensitivity(
                role=role,
                baseline_model=baseline.routing[role],
                candidate_model=config.routing[role],
                config_name=config.name,
                mean_quality_delta=config.mean_score - baseline.mean_score,
                pass_rate_delta=config.pass_rate - baseline.pass_rate,
                client_latency_p95_delta_ms=_delta(
                    config.client_latency_p95_ms,
                    baseline.client_latency_p95_ms,
                ),
                relative_cost_delta=config.relative_cost - baseline.relative_cost,
                quality_preserving=_quality_preserving(config, quality_constraint),
                status=_role_counterfactual_status(config, baseline, quality_constraint),
            )
        )
    return rows


def _findings(
    sensitivities: list[RoleSensitivity],
    baseline: ModelChoiceConfig,
    configs: list[ModelChoiceConfig],
    quality_constraint: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    for row in sensitivities:
        if not row.quality_preserving:
            continue
        latency_delta = row.client_latency_p95_delta_ms
        latency_improved = latency_delta is not None and latency_delta < 0
        cost_improved = row.relative_cost_delta < 0
        if not latency_improved and not cost_improved:
            continue
        finding = Finding(
                id="MODEL_CHOICE_HEADROOM",
                severity="MEDIUM",
                title="Model-choice headroom",
                summary=(
                    f"Counterfactual replay shows role {row.role} can use "
                    f"{row.candidate_model} within the configured quality tolerance. "
                    "This is local role headroom, not a verified mixed-routing policy."
                ),
                evidence={
                    "evidence_source": "COUNTERFACTUAL_ROLE_REPLAY",
                    "headroom_scope": "LOCAL_ROLE_HEADROOM",
                    "role": row.role,
                    "baseline_model": row.baseline_model,
                    "candidate_model": row.candidate_model,
                    "baseline_mean_score": baseline.mean_score,
                    "candidate_mean_score": baseline.mean_score + row.mean_quality_delta,
                    "mean_quality_delta": row.mean_quality_delta,
                    "baseline_pass_rate": baseline.pass_rate,
                    "candidate_pass_rate": baseline.pass_rate + row.pass_rate_delta,
                    "pass_rate_delta": row.pass_rate_delta,
                    "quality_minimum_mean_score": quality_constraint[
                        "minimum_mean_score"
                    ],
                    "quality_minimum_pass_rate": quality_constraint[
                        "minimum_pass_rate"
                    ],
                    "client_latency_p95_delta_ms": latency_delta,
                    "relative_cost_delta": row.relative_cost_delta,
                },
                affected_spans=[row.role],
                recommendation=(
                    f"Treat routing {row.role} calls to {row.candidate_model} as a "
                    "candidate to verify. Replay the full routing before accepting "
                    "any deployment change."
                ),
                confidence="MEDIUM",
                validation_plan=[
                    "Construct a candidate routing from quality-preserving role substitutions.",
                    "Replay the full mixed-routing agent configuration end to end.",
                    "Compare mean quality, pass rate, latency, and relative cost.",
                    "Inspect failures for role-specific quality regressions.",
                ],
                provenance=FindingProvenance(
                    derived_metrics={
                        "config_name": row.config_name,
                        "quality_preserving": row.quality_preserving,
                        "role_counterfactual_status": row.status,
                        "validation_status": "LOCAL_ROLE_HEADROOM_CANDIDATE_TO_VERIFY",
                    },
                    notes=[
                        (
                            "Finding is based on counterfactual replay evidence, "
                            "not model-size heuristics. It does not verify a mixed "
                            "routing configuration by itself."
                        ),
                    ],
                ),
            )
        contract = recommendation_contract_for_finding(finding)
        findings.append(
            replace(finding, recommendation_contract=contract)
            if contract is not None
            else finding
        )
    findings.extend(_mixed_findings(configs, baseline, quality_constraint))
    return findings


def _mixed_findings(
    configs: list[ModelChoiceConfig],
    baseline: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
) -> list[Finding]:
    findings: list[Finding] = []
    for config in configs:
        if not config.name.startswith("mixed"):
            continue
        if not _quality_preserving(config, quality_constraint):
            continue
        latency_delta = _delta(config.client_latency_p95_ms, baseline.client_latency_p95_ms)
        ttft_delta = _delta(config.ttft_p95_ms, baseline.ttft_p95_ms)
        cost_delta = config.relative_cost - baseline.relative_cost
        if cost_delta >= 0 and (latency_delta is None or latency_delta >= 0):
            continue
        changed_roles = [
            {
                "role": role,
                "baseline_model": baseline.routing[role],
                "selected_model": selected_model,
            }
            for role, selected_model in config.routing.items()
            if baseline.routing.get(role) != selected_model
        ]
        finding = Finding(
                id="MODEL_CHOICE_HEADROOM",
                severity="HIGH",
                title="End-to-end validated model-choice headroom",
                summary=(
                    f"End-to-end replay shows {config.name} stays within the "
                    "configured quality tolerance while reducing model-capacity cost "
                    "or latency."
                ),
                evidence={
                    "evidence_source": "END_TO_END_VALIDATED",
                    "headroom_scope": "GLOBAL_ROUTING_VERIFIED",
                    "role": "mixed_routing",
                    "config_name": config.name,
                    "changed_roles": changed_roles,
                    "replay_task_count": config.role_profiles.get(
                        "final_synthesizer", {}
                    ).get("calls", 0),
                    "baseline_mean_score": baseline.mean_score,
                    "candidate_mean_score": config.mean_score,
                    "mean_quality_delta": config.mean_score - baseline.mean_score,
                    "baseline_pass_rate": baseline.pass_rate,
                    "candidate_pass_rate": config.pass_rate,
                    "pass_rate_delta": config.pass_rate - baseline.pass_rate,
                    "quality_minimum_mean_score": quality_constraint[
                        "minimum_mean_score"
                    ],
                    "quality_minimum_pass_rate": quality_constraint[
                        "minimum_pass_rate"
                    ],
                    "client_latency_p95_delta_ms": latency_delta,
                    "ttft_p95_delta_ms": ttft_delta,
                    "relative_cost_delta": cost_delta,
                },
                affected_spans=[
                    str(item["role"]) for item in changed_roles if "role" in item
                ],
                recommendation=(
                    f"Evaluate {config.name} as a mixed model-routing configuration "
                    "and monitor task quality on a broader workload."
                ),
                confidence="MEDIUM",
                validation_plan=[
                    "Replay more tasks with the same routing policy.",
                    "Inspect per-task regressions and role outputs.",
                    "Compare provider-specific cost only after supplying price inputs.",
                ],
                provenance=FindingProvenance(
                    derived_metrics={
                        "config_name": config.name,
                        "quality_preserving": True,
                        "validation_status": "END_TO_END_VALIDATED",
                    },
                    notes=[
                        (
                            "Finding is based on a full mixed-agent replay where "
                            "role outputs feed downstream roles."
                        ),
                    ],
                ),
            )
        contract = recommendation_contract_for_finding(finding)
        findings.append(
            replace(finding, recommendation_contract=contract)
            if contract is not None
            else finding
        )
    return findings


def routing_from_run(run: AgentRun) -> ModelRouting:
    grouped: dict[tuple[str, str, str | None], list[LLMCall]] = {}
    for call in run.llm_calls:
        role = call.semantic_role or _metadata_role(call)
        if role is None or call.model is None:
            continue
        grouped.setdefault((role, call.model, call.backend), []).append(call)
    assignments = [
        RoleExecution(
            role_id=role,
            model=model,
            backend=backend,
            llm_call_ids=[call.llm_call_id for call in calls],
            calls=len(calls),
            input_tokens=sum(int(call.input_tokens or 0) for call in calls),
            output_tokens=sum(int(call.output_tokens or 0) for call in calls),
        )
        for (role, model, backend), calls in sorted(grouped.items())
    ]
    return ModelRouting(assignments=assignments)


def routing_summary_from_run(run: AgentRun) -> dict[str, Any]:
    routing = routing_from_run(run)
    if not routing.assignments:
        return {"available": False, "reason": "missing role/model metadata"}
    return {
        "available": True,
        "source": routing.source,
        "assignments": [asdict(assignment) for assignment in routing.assignments],
        "role_model_map": routing.as_role_map(),
    }


def routing_summary_from_runs(runs: list[AgentRun]) -> dict[str, Any]:
    assignments: dict[tuple[str, str, str | None], RoleExecution] = {}
    for run in runs:
        for assignment in routing_from_run(run).assignments:
            key = (assignment.role_id, assignment.model, assignment.backend)
            existing = assignments.get(key)
            if existing is None:
                assignments[key] = assignment
            else:
                assignments[key] = RoleExecution(
                    role_id=assignment.role_id,
                    model=assignment.model,
                    backend=assignment.backend,
                    llm_call_ids=[*existing.llm_call_ids, *assignment.llm_call_ids],
                    calls=existing.calls + assignment.calls,
                    input_tokens=existing.input_tokens + assignment.input_tokens,
                    output_tokens=existing.output_tokens + assignment.output_tokens,
                )
    if not assignments:
        return {"available": False, "reason": "missing role/model metadata"}
    ordered = [assignments[key] for key in sorted(assignments)]
    return {
        "available": True,
        "source": "trace",
        "assignments": [asdict(assignment) for assignment in ordered],
        "role_model_map": {
            assignment.role_id: assignment.model
            for assignment in ordered
            if _single_model_for_role(assignment.role_id, ordered)
        },
    }


def _single_model_for_role(role: str, assignments: list[RoleExecution]) -> bool:
    return len({assignment.model for assignment in assignments if assignment.role_id == role}) == 1


def _metadata_role(call: LLMCall) -> str | None:
    role = call.metadata.get("semantic_role") or call.metadata.get("role")
    return str(role) if role is not None else None


def _role_counterfactual_status(
    config: ModelChoiceConfig,
    baseline: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
) -> RoleCounterfactualStatus:
    if not _quality_preserving(config, quality_constraint):
        return "QUALITY_REGRESSION"
    latency_delta = _delta(config.client_latency_p95_ms, baseline.client_latency_p95_ms)
    latency_improved = latency_delta is not None and latency_delta < 0
    cost_improved = config.relative_cost < baseline.relative_cost
    if latency_improved or cost_improved:
        return "SAFE_WITHIN_TOLERANCE"
    if config.client_latency_p95_ms is None and baseline.client_latency_p95_ms is None:
        return "INCONCLUSIVE"
    return "NO_MATERIAL_BENEFIT"


def _candidate_routing(
    sensitivities: list[RoleSensitivity],
    baseline: ModelChoiceConfig,
) -> CandidateRouting | None:
    selected: dict[str, RoleSensitivity] = {}
    for row in sensitivities:
        if row.status != "SAFE_WITHIN_TOLERANCE":
            continue
        current = selected.get(row.role)
        if current is None or _candidate_sort_key(row) < _candidate_sort_key(current):
            selected[row.role] = row
    if not selected:
        return None
    routing = dict(baseline.routing)
    for role, row in selected.items():
        routing[role] = row.candidate_model
    changed = ", ".join(
        f"{role}: {baseline.routing.get(role)} -> {routing[role]}"
        for role in sorted(selected)
    )
    return CandidateRouting(
        routing=routing,
        source="one_role_counterfactuals",
        status="CANDIDATE_TO_VERIFY",
        rationale=(
            "Candidate routing is assembled from quality-preserving one-role "
            f"substitutions and still requires full replay: {changed}."
        ),
    )


def _candidate_sort_key(row: RoleSensitivity) -> tuple[float, float, float, float]:
    # Prefer substitutions with more quality headroom before chasing cost.
    latency_delta = (
        row.client_latency_p95_delta_ms
        if row.client_latency_p95_delta_ms is not None
        else float("inf")
    )
    return (
        -row.mean_quality_delta,
        -row.pass_rate_delta,
        row.relative_cost_delta,
        latency_delta,
    )


def _routing_verification(
    configs: list[ModelChoiceConfig],
    baseline: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
    *,
    selected_mixed_config: str | None,
    findings: list[Finding],
) -> RoutingVerification:
    if selected_mixed_config is None:
        return RoutingVerification(
            config_name=None,
            status="CANDIDATE_TO_VERIFY",
            quality_preserving=None,
            relative_cost_delta=None,
            client_latency_p95_delta_ms=None,
            changed_roles=[],
            recommendation_verification=None,
            reason=(
                "Role-level headroom may exist, but no full mixed-routing replay "
                "configuration is available."
            ),
        )
    config = next((item for item in configs if item.name == selected_mixed_config), None)
    if config is None:
        return RoutingVerification(
            config_name=selected_mixed_config,
            status="INCONCLUSIVE",
            quality_preserving=None,
            relative_cost_delta=None,
            client_latency_p95_delta_ms=None,
            changed_roles=[],
            recommendation_verification=None,
            reason="Selected mixed-routing config is not present in the result data.",
        )
    changed_roles = _changed_roles(baseline, config)
    quality_preserving = _quality_preserving(config, quality_constraint)
    latency_delta = _delta(config.client_latency_p95_ms, baseline.client_latency_p95_ms)
    cost_delta = config.relative_cost - baseline.relative_cost
    verification = _verify_model_choice_contract(
        baseline,
        config,
        quality_constraint,
        finding=next(
            (
                finding
                for finding in findings
                if finding.id == "MODEL_CHOICE_HEADROOM"
                and finding.evidence.get("config_name") == config.name
            ),
            None,
        ),
    )
    if not quality_preserving:
        status: RoutingVerificationStatus = "REJECTED_QUALITY_REGRESSION"
        reason = "Full mixed-routing replay violated the configured quality tolerance."
    elif cost_delta < 0 or (latency_delta is not None and latency_delta < 0):
        status = "VERIFIED"
        reason = (
            "Full mixed-routing replay preserved quality and improved relative "
            "model-capacity cost or latency evidence."
        )
    else:
        status = "NO_MATERIAL_BENEFIT"
        reason = (
            "Full mixed-routing replay preserved quality but did not improve available "
            "efficiency evidence."
        )
    return RoutingVerification(
        config_name=config.name,
        status=status,
        quality_preserving=quality_preserving,
        relative_cost_delta=cost_delta,
        client_latency_p95_delta_ms=latency_delta,
        changed_roles=changed_roles,
        recommendation_verification=verification,
        reason=reason,
    )


def _changed_roles(
    baseline: ModelChoiceConfig,
    config: ModelChoiceConfig,
) -> list[dict[str, str]]:
    return [
        {
            "role": role,
            "baseline_model": baseline_model,
            "candidate_model": config.routing[role],
        }
        for role, baseline_model in sorted(baseline.routing.items())
        if config.routing.get(role) != baseline_model
    ]


def _verify_model_choice_contract(
    baseline: ModelChoiceConfig,
    candidate: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
    *,
    finding: Finding | None,
) -> RecommendationVerification | None:
    contract = recommendation_contract_for_finding(finding) if finding is not None else None
    if contract is None:
        return None
    comparison = _model_choice_run_comparison(baseline, candidate, quality_constraint)
    return verify_recommendation(
        comparison,
        contract,
        finding_id="MODEL_CHOICE_HEADROOM",
    )


def _model_choice_run_comparison(
    baseline: ModelChoiceConfig,
    candidate: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
) -> RunComparison:
    cost_delta = _metric_delta(baseline.relative_cost, candidate.relative_cost)
    return RunComparison(
        baseline_id=baseline.name,
        candidate_id=candidate.name,
        matched_tasks=[],
        unmatched_baseline_tasks=[],
        unmatched_candidate_tasks=[],
        token_deltas=TokenDelta(
            input_tokens=_metric_delta(baseline.input_tokens, candidate.input_tokens),
            output_tokens=_metric_delta(baseline.output_tokens, candidate.output_tokens),
            component_accounting=ComponentAccountingSummary(
                total_processed_tokens=_empty_delta(),
                total_unique_tokens=_empty_delta(),
                other_processed_tokens=_empty_delta(),
                attribution_coverage_ratio=_empty_delta(),
            ),
        ),
        context_growth_delta=ContextGrowthDelta(
            final_step_input_tokens=_empty_delta(),
            max_step_input_tokens=_empty_delta(),
            growth_slope_tokens_per_step=_empty_delta(),
            baseline_steps=0,
            candidate_steps=0,
        ),
        latency_deltas=LatencyDelta(
            tool_latency_ms=_empty_delta(),
            queue_p50_ms=_empty_delta(),
            queue_p95_ms=_empty_delta(),
            scheduled_to_first_p50_ms=_empty_delta(),
            scheduled_to_first_p95_ms=_metric_delta(
                baseline.ttft_p95_ms,
                candidate.ttft_p95_ms,
            ),
            generation_p50_ms=_empty_delta(),
            generation_p95_ms=_empty_delta(),
            client_p50_ms=_empty_delta(),
            client_p95_ms=_metric_delta(
                baseline.client_latency_p95_ms,
                candidate.client_latency_p95_ms,
            ),
        ),
        cache_deltas=CacheDelta(
            cached_tokens=_empty_delta(),
            cache_miss_tokens=_empty_delta(),
            cached_token_ratio=_empty_delta(),
        ),
        quality_deltas=QualityDelta(
            mean_score=_metric_delta(baseline.mean_score, candidate.mean_score),
            pass_rate=_metric_delta(baseline.pass_rate, candidate.pass_rate),
            baseline_tasks_with_quality=0,
            candidate_tasks_with_quality=0,
            mean_score_tolerance=float(quality_constraint["mean_score_tolerance"]),
            pass_rate_tolerance=float(quality_constraint["pass_rate_tolerance"]),
            passed=_quality_preserving(candidate, quality_constraint),
        ),
        finding_changes=[
            FindingChange(
                finding_id="MODEL_CHOICE_HEADROOM",
                lifecycle="IMPROVED",
                baseline_severity=None,
                candidate_severity="HIGH",
                scope="model_routing",
            )
        ],
        acceptance_result=AcceptanceResult(
            verdict="ACCEPT"
            if _quality_preserving(candidate, quality_constraint)
            else "REJECT_QUALITY_REGRESSION",
            reason="Model-choice contract verification input.",
            performance_improved=cost_delta.delta is not None and cost_delta.delta < 0,
            quality_passed=_quality_preserving(candidate, quality_constraint),
            material_regression=False,
        ),
        metadata={"metric_deltas": {"model.relative_cost_proxy": asdict(cost_delta)}},
    )


def _metric_delta(
    baseline: float | int | None,
    candidate: float | int | None,
) -> MetricDelta:
    if baseline is None or candidate is None:
        return _empty_delta()
    delta = candidate - baseline
    percent = (delta / baseline) if baseline else None
    return MetricDelta(
        baseline=baseline,
        candidate=candidate,
        delta=delta,
        percent_delta=percent,
    )


def _empty_delta() -> MetricDelta:
    return MetricDelta(baseline=None, candidate=None, delta=None, percent_delta=None)


def _pareto(
    configs: list[ModelChoiceConfig],
    quality_constraint: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "config": config.name,
            "mean_score": config.mean_score,
            "pass_rate": config.pass_rate,
            "relative_cost": config.relative_cost,
            "client_latency_p95_ms": config.client_latency_p95_ms,
            "quality_preserving": _quality_preserving(config, quality_constraint),
            "dominated": False,
        }
        for config in configs
    ]
    for row in rows:
        for other in rows:
            if other is row:
                continue
            if (
                float(other["mean_score"]) >= float(row["mean_score"])
                and float(other["pass_rate"]) >= float(row["pass_rate"])
                and float(other["relative_cost"]) <= float(row["relative_cost"])
                and _latency_value(other) <= _latency_value(row)
                and (
                    float(other["mean_score"]) > float(row["mean_score"])
                    or float(other["pass_rate"]) > float(row["pass_rate"])
                    or float(other["relative_cost"]) < float(row["relative_cost"])
                    or _latency_value(other) < _latency_value(row)
                )
            ):
                row["dominated"] = True
                break
    return rows


def _selected_mixed_config(
    data: dict[str, Any],
    configs: list[ModelChoiceConfig],
    quality_constraint: dict[str, Any],
) -> str | None:
    requested = data.get("selected_mixed_config")
    if requested:
        return str(requested)
    mixed = [
        config
        for config in configs
        if config.name.startswith("mixed") and _quality_preserving(config, quality_constraint)
    ]
    if not mixed:
        return None
    return min(
        mixed,
        key=lambda config: (config.relative_cost, _latency_value_config(config)),
    ).name


def _quality_preserving(
    config: ModelChoiceConfig,
    quality_constraint: dict[str, Any],
) -> bool:
    return (
        config.mean_score + QUALITY_EPSILON
        >= float(quality_constraint["minimum_mean_score"])
        and config.pass_rate + QUALITY_EPSILON
        >= float(quality_constraint["minimum_pass_rate"])
    )


def _latency_value(row: dict[str, Any]) -> float:
    value = row.get("client_latency_p95_ms")
    if value is None:
        return float("inf")
    return float(value)


def _latency_value_config(config: ModelChoiceConfig) -> float:
    if config.client_latency_p95_ms is None:
        return float("inf")
    return config.client_latency_p95_ms


def _delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}
