from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from agentperf.schema.comparison import FindingChange, MetricDelta, RunComparison
from agentperf.schema.findings import (
    ExpectedMetricChange,
    Finding,
    RecommendationContract,
)

VerificationStatus = Literal[
    "VERIFIED",
    "PARTIALLY_VERIFIED",
    "NOT_VERIFIED",
    "QUALITY_REGRESSION",
    "INCONCLUSIVE",
]
MetricCheckStatus = Literal["PASSED", "FAILED", "UNAVAILABLE", "NOT_APPLICABLE"]


@dataclass(frozen=True)
class RecommendationMetricCheck:
    metric: str
    direction: str
    required: bool
    status: MetricCheckStatus
    baseline: float | int | None = None
    candidate: float | int | None = None
    delta: float | int | None = None
    observed: str | None = None
    rationale: str = ""


@dataclass(frozen=True)
class RecommendationVerification:
    finding_id: str
    status: VerificationStatus
    quality_status: str
    metric_checks: list[RecommendationMetricCheck]
    reason: str


def enrich_finding_recommendation(finding: Finding) -> Finding:
    if finding.recommendation_contract is not None:
        return finding
    contract = recommendation_contract_for_finding(finding)
    if contract is None:
        return finding
    return replace(finding, recommendation_contract=contract)


def enrich_finding_recommendations(findings: list[Finding]) -> list[Finding]:
    return [enrich_finding_recommendation(finding) for finding in findings]


def recommendation_contract_for_finding(finding: Finding) -> RecommendationContract | None:
    if finding.recommendation_contract is not None:
        return finding.recommendation_contract
    return recommendation_contract_for_id(
        finding.id,
        severity=finding.severity,
        materiality=_materiality(finding),
    )


def recommendation_contract_for_id(
    finding_id: str,
    *,
    severity: str | None = None,
    materiality: str | None = None,
) -> RecommendationContract | None:
    if finding_id == "TOOL_OUTPUT_BLOAT":
        return RecommendationContract(
            objective="Reduce cumulative downstream processing of tool-result content.",
            applicability="ACTIONABLE",
            interventions=[
                "Carry forward only the tool-result fields needed by later LLM calls.",
                "Avoid reinjecting identical tool results into multiple later prompts.",
                "Compact or summarize tool results before reinjection when quality permits.",
                "Store large tool results out-of-band and retrieve details on demand.",
            ],
            expected_metric_changes=[
                ExpectedMetricChange(
                    metric="component.tool_result.processed_tokens",
                    direction="DECREASE",
                    rationale="The detector is based on cumulative processed tool-result tokens.",
                ),
                ExpectedMetricChange(
                    metric=f"finding.{finding_id}.lifecycle",
                    direction="RESOLVE_OR_IMPROVE_FINDING",
                    required=False,
                    rationale=(
                        "The finding should resolve or improve if the replay removes "
                        "the signal."
                    ),
                ),
            ],
            risks=[
                "Necessary evidence may be removed from downstream prompts.",
                "Compaction may omit details needed for task correctness.",
            ],
            verification_requirements=[
                "Replay the same task set.",
                "Require task quality to remain within configured tolerance.",
                "Confirm tool-result processed tokens decrease.",
            ],
            evidence_level="HIGH",
        )
    if finding_id == "CONTEXT_DUPLICATION":
        observation_only = severity == "LOW" or materiality == "OBSERVATION"
        return RecommendationContract(
            objective=(
                "Inspect repeated within-run context and determine whether any repeated "
                "content is safely reducible."
            ),
            applicability="OBSERVATION_ONLY" if observation_only else "INVESTIGATE",
            interventions=[
                "Separate semantically required repeated context from accidental carry-forward.",
                "Deduplicate or selectively carry forward repeated content only where safe.",
                "Preserve system, policy, and task context required by downstream calls.",
            ],
            expected_metric_changes=[] if observation_only else [
                ExpectedMetricChange(
                    metric="component.total.processed_tokens",
                    direction="DECREASE",
                    required=False,
                    rationale="Safe reduction should reduce component-attributed processing.",
                ),
                ExpectedMetricChange(
                    metric=f"finding.{finding_id}.lifecycle",
                    direction="RESOLVE_OR_IMPROVE_FINDING",
                    required=False,
                    rationale="The finding may improve if repeated context is actually reducible.",
                ),
            ],
            risks=[
                "Repeated context may be semantically required for model behavior.",
                "Removing shared instructions or evidence can cause quality regressions.",
            ],
            verification_requirements=[
                "Replay the same tasks after any prompt-structure change.",
                "Require quality to remain within configured tolerance.",
                "Treat unchanged or regressed quality as failed validation.",
            ],
            evidence_level="MEDIUM",
        )
    if finding_id == "CROSS_RUN_SHARED_SCAFFOLD":
        return RecommendationContract(
            objective=(
                "Record repeated scaffold across independent executions without treating "
                "it as removable task context."
            ),
            applicability="OBSERVATION_ONLY",
            interventions=[],
            expected_metric_changes=[],
            risks=[
                "Independent tasks may require the same system or policy scaffold.",
                "Removing scaffold solely because it repeats across tasks is unsafe.",
            ],
            verification_requirements=[
                (
                    "Do not optimize this finding unless independent serving evidence "
                    "shows material cost."
                ),
                (
                    "If serving cache behavior is relevant, replay and compare cache "
                    "evidence without removing required instructions."
                ),
            ],
            quality_requirement=None,
            evidence_level="MEDIUM",
        )
    if finding_id in {"CACHEABILITY_HEADROOM", "MATERIAL_PREFIX_CACHE_OPPORTUNITY"}:
        actionable = finding_id == "MATERIAL_PREFIX_CACHE_OPPORTUNITY"
        return RecommendationContract(
            objective=(
                "Increase reusable prompt-prefix structure where serving telemetry "
                "supports it."
            ),
            applicability="ACTIONABLE" if actionable else "CONDITIONAL",
            interventions=[
                (
                    "Place stable instructions, tool schemas, and reusable context "
                    "earlier in the prompt."
                ),
                "Reduce unnecessary dynamic content before stable prefix material.",
                "Replay with the same backend to compare compatible cache telemetry.",
            ],
            expected_metric_changes=[
                ExpectedMetricChange(
                    metric="cache.cached_token_ratio",
                    direction="INCREASE",
                    required=actionable,
                    rationale=(
                        "Reusable prefix changes should increase observed cache reuse "
                        "when telemetry is available."
                    ),
                ),
                ExpectedMetricChange(
                    metric="cache.cache_miss_tokens",
                    direction="DECREASE",
                    required=False,
                    rationale="Effective cache reuse may reduce uncached prompt work.",
                ),
                ExpectedMetricChange(
                    metric="latency.scheduled_to_first_p95_ms",
                    direction="DECREASE",
                    required=False,
                    rationale=(
                        "Latency may improve, but token/cache evidence is the primary "
                        "expectation."
                    ),
                ),
            ],
            risks=[
                "Prompt restructuring can change model behavior.",
                "Serving cache telemetry may be unavailable or backend-specific.",
                "Headroom does not imply an urgent or material bottleneck.",
            ],
            verification_requirements=[
                "Replay on comparable backend/hardware.",
                "Require quality to remain within configured tolerance.",
                (
                    "Use backend-compatible cache metrics; otherwise treat cache "
                    "verification as inconclusive."
                ),
            ],
            evidence_level="HIGH",
        )
    if finding_id in {"PREFILL_PATH_DOMINANCE", "MATERIAL_PREFILL_BOTTLENECK"}:
        actionable = finding_id == "MATERIAL_PREFILL_BOTTLENECK"
        return RecommendationContract(
            objective=(
                "Reduce serving-side first-token path pressure when materiality gates support it."
            ),
            applicability="ACTIONABLE" if actionable else "CONDITIONAL",
            interventions=[
                "Reduce uncached prompt volume only where task semantics allow.",
                "Improve prefix reuse if compatible cache telemetry indicates misses.",
                "Preserve quality and compare serving first-token telemetry after replay.",
            ],
            expected_metric_changes=[
                ExpectedMetricChange(
                    metric="latency.scheduled_to_first_p95_ms",
                    direction="DECREASE",
                    required=actionable,
                    rationale=(
                        "Scheduled-to-first is the available first-token path metric; "
                        "it is not pure GPU prefill-kernel latency."
                    ),
                ),
                ExpectedMetricChange(
                    metric="cache.cache_miss_tokens",
                    direction="DECREASE",
                    required=False,
                    rationale=(
                        "Lower uncached prompt volume supports the detector hypothesis "
                        "when telemetry exists."
                    ),
                ),
            ],
            risks=[
                "Prompt shortening can remove information needed for correctness.",
                "Serving first-token metrics vary by backend and telemetry capability.",
                "Dominant prefill-path attribution is not automatically material.",
            ],
            verification_requirements=[
                "Replay on comparable backend/hardware.",
                "Require quality to remain within configured tolerance.",
                "Compare scheduled-to-first and uncached-token evidence with metric provenance.",
            ],
            evidence_level="HIGH" if actionable else "MEDIUM",
        )
    if finding_id == "MODEL_CHOICE_HEADROOM":
        return RecommendationContract(
            objective=(
                "Reduce unnecessary model capacity for a specific role only when "
                "counterfactual replay and full routing replay preserve task quality."
            ),
            applicability="CONDITIONAL",
            interventions=[
                "Route the tested role to the replayed smaller or cheaper model.",
                (
                    "Combine multiple role substitutions only as a candidate routing "
                    "that must be replayed end to end."
                ),
                "Keep stronger models for roles whose counterfactual replay failed quality.",
            ],
            expected_metric_changes=[
                ExpectedMetricChange(
                    metric="model.relative_cost_proxy",
                    direction="DECREASE",
                    rationale=(
                        "M25 uses an explicit relative token-weighted model-capacity "
                        "proxy unless user-supplied price data is available."
                    ),
                ),
                ExpectedMetricChange(
                    metric="latency.client_p95_ms",
                    direction="DECREASE",
                    required=False,
                    rationale=(
                        "Latency may improve, but model-capacity headroom is not "
                        "defined by latency alone."
                    ),
                ),
            ],
            risks=[
                "The role may need the stronger model for tasks outside the replay set.",
                "Independent role substitutions may interact badly when combined.",
                "Relative cost proxy is not commercial pricing.",
            ],
            verification_requirements=[
                "Replay one role substitution at a time to estimate local sensitivity.",
                "Construct candidate routing only from quality-preserving substitutions.",
                "Replay the full mixed routing end to end before accepting it.",
                "Require quality to remain within configured tolerance.",
            ],
            evidence_level="MEDIUM",
        )
    return None


def verify_recommendation(
    comparison: RunComparison,
    contract: RecommendationContract,
    *,
    finding_id: str,
    finding_change: FindingChange | None = None,
) -> RecommendationVerification:
    metric_checks = [
        _check_expected_metric(comparison, expected, finding_change=finding_change)
        for expected in contract.expected_metric_changes
    ]
    quality_status = _quality_status(comparison, contract)
    if quality_status == "FAILED":
        return RecommendationVerification(
            finding_id=finding_id,
            status="QUALITY_REGRESSION",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason=(
                "Expected performance evidence may have moved, but task quality violated "
                "the configured requirement."
            ),
        )
    if not metric_checks:
        return RecommendationVerification(
            finding_id=finding_id,
            status="INCONCLUSIVE",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason="No machine-checkable metric expectation is attached to this recommendation.",
        )
    required_checks = [check for check in metric_checks if check.required]
    failed_required = [check for check in required_checks if check.status == "FAILED"]
    unavailable_required = [
        check for check in required_checks if check.status == "UNAVAILABLE"
    ]
    passed_required = [check for check in required_checks if check.status == "PASSED"]
    passed_optional = [
        check for check in metric_checks if not check.required and check.status == "PASSED"
    ]
    if failed_required:
        return RecommendationVerification(
            finding_id=finding_id,
            status="NOT_VERIFIED",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason="A required recommendation expectation did not move as predicted.",
        )
    if unavailable_required:
        return RecommendationVerification(
            finding_id=finding_id,
            status="INCONCLUSIVE",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason="Required evidence for recommendation verification is unavailable.",
        )
    if passed_required:
        return RecommendationVerification(
            finding_id=finding_id,
            status="VERIFIED" if quality_status != "UNAVAILABLE" else "PARTIALLY_VERIFIED",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason="Required recommendation expectations moved in the predicted direction.",
        )
    if passed_optional:
        return RecommendationVerification(
            finding_id=finding_id,
            status="PARTIALLY_VERIFIED",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason="Optional recommendation evidence moved in the predicted direction.",
        )
    if any(check.status == "FAILED" for check in metric_checks):
        return RecommendationVerification(
            finding_id=finding_id,
            status="NOT_VERIFIED",
            quality_status=quality_status,
            metric_checks=metric_checks,
            reason="Recommendation expectations did not move as predicted.",
        )
    return RecommendationVerification(
        finding_id=finding_id,
        status="INCONCLUSIVE",
        quality_status=quality_status,
        metric_checks=metric_checks,
        reason="Recommendation evidence is unavailable or not applicable.",
    )


def recommendation_verifications(comparison: RunComparison) -> list[RecommendationVerification]:
    results: list[RecommendationVerification] = []
    for change in comparison.finding_changes:
        contract = recommendation_contract_for_id(
            change.finding_id,
            severity=change.baseline_severity or change.candidate_severity,
            materiality=change.baseline_materiality or change.candidate_materiality,
        )
        if contract is None:
            continue
        results.append(
            verify_recommendation(
                comparison,
                contract,
                finding_id=change.finding_id,
                finding_change=change,
            )
        )
    return results


def recommendation_verification_to_dict(
    verification: RecommendationVerification,
) -> dict[str, Any]:
    return asdict(verification)


def recommendation_contract_to_dict(contract: RecommendationContract) -> dict[str, Any]:
    return asdict(contract)


def _check_expected_metric(
    comparison: RunComparison,
    expected: ExpectedMetricChange,
    *,
    finding_change: FindingChange | None,
) -> RecommendationMetricCheck:
    if expected.direction == "RESOLVE_OR_IMPROVE_FINDING":
        if finding_change is None:
            status: MetricCheckStatus = "UNAVAILABLE"
        else:
            status = (
                "PASSED"
                if finding_change.lifecycle in {"RESOLVED", "IMPROVED"}
                else "FAILED"
            )
        return RecommendationMetricCheck(
            metric=expected.metric,
            direction=expected.direction,
            required=expected.required,
            status=status,
            observed=finding_change.lifecycle if finding_change is not None else None,
            rationale=expected.rationale,
        )
    delta = _metric_delta(comparison, expected.metric)
    if delta is None or delta.baseline is None or delta.candidate is None or delta.delta is None:
        return RecommendationMetricCheck(
            metric=expected.metric,
            direction=expected.direction,
            required=expected.required,
            status="UNAVAILABLE",
            rationale=expected.rationale,
        )
    status = _direction_status(delta, expected.direction)
    return RecommendationMetricCheck(
        metric=expected.metric,
        direction=expected.direction,
        required=expected.required,
        status=status,
        baseline=delta.baseline,
        candidate=delta.candidate,
        delta=delta.delta,
        rationale=expected.rationale,
    )


def _direction_status(delta: MetricDelta, direction: str) -> MetricCheckStatus:
    if delta.delta is None:
        return "UNAVAILABLE"
    value = float(delta.delta)
    if direction == "DECREASE":
        return "PASSED" if value < 0 else "FAILED"
    if direction == "INCREASE":
        return "PASSED" if value > 0 else "FAILED"
    if direction == "NO_REGRESSION":
        return "PASSED" if value <= 0 else "FAILED"
    return "UNAVAILABLE"


def _metric_delta(comparison: RunComparison, metric: str) -> MetricDelta | None:
    metadata_deltas = comparison.metadata.get("metric_deltas")
    if isinstance(metadata_deltas, dict) and isinstance(metadata_deltas.get(metric), dict):
        raw = metadata_deltas[metric]
        return MetricDelta(
            baseline=raw.get("baseline"),
            candidate=raw.get("candidate"),
            delta=raw.get("delta"),
            percent_delta=raw.get("percent_delta"),
            measurement_quality=str(raw.get("measurement_quality", "DERIVED")),
        )
    if metric == "provider.input_tokens":
        return comparison.token_deltas.input_tokens
    if metric == "provider.output_tokens":
        return comparison.token_deltas.output_tokens
    if metric == "component.total.processed_tokens":
        accounting = comparison.token_deltas.component_accounting
        return accounting.total_processed_tokens if accounting else None
    if metric.startswith("component.") and metric.endswith(".processed_tokens"):
        component = metric.removeprefix("component.").removesuffix(".processed_tokens")
        return comparison.token_deltas.component_processed_tokens.get(component)
    if metric == "latency.client_p95_ms":
        return comparison.latency_deltas.client_p95_ms
    if metric == "latency.scheduled_to_first_p95_ms":
        return comparison.latency_deltas.scheduled_to_first_p95_ms
    if metric == "cache.cached_token_ratio":
        return comparison.cache_deltas.cached_token_ratio
    if metric == "cache.cache_miss_tokens":
        return comparison.cache_deltas.cache_miss_tokens
    return None


def _quality_status(
    comparison: RunComparison,
    contract: RecommendationContract,
) -> str:
    if contract.quality_requirement is None:
        return "NOT_APPLICABLE"
    if comparison.quality_deltas.passed is True:
        return "PASSED"
    if comparison.quality_deltas.passed is False:
        return "FAILED"
    return "UNAVAILABLE"


def _materiality(finding: Finding) -> str | None:
    value = finding.evidence.get("materiality")
    if value is not None:
        return str(value)
    value = finding.provenance.derived_metrics.get("materiality")
    if value is not None:
        return str(value)
    return None
