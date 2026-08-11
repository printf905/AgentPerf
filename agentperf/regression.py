from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentperf.schema.comparison import MetricDelta, RunComparison
from agentperf.schema.regression import (
    FindingPolicy,
    PerformanceMetricPolicy,
    QualityMetricPolicy,
    RegressionCheck,
    RegressionPolicy,
    RegressionResult,
    RegressionStatus,
    TaskCoveragePolicy,
)


class RegressionPolicyError(ValueError):
    """Raised when a regression policy cannot be parsed or evaluated."""


COMPONENT_METRIC_ALIASES = {
    "component.total.processed_tokens": "total",
    "component_total_processed_tokens": "total",
    "component.system.processed_tokens": "system",
    "component_system_tokens": "system",
    "component.user.processed_tokens": "user",
    "component_user_tokens": "user",
    "component.history.processed_tokens": "history",
    "component_history_tokens": "history",
    "component.tool_schema.processed_tokens": "tool_schema",
    "component_tool_schema_tokens": "tool_schema",
    "component.tool_result.processed_tokens": "tool_result",
    "component_tool_result_tokens": "tool_result",
    "component.retrieved_context.processed_tokens": "retrieved_context",
    "component_retrieved_context_tokens": "retrieved_context",
    "component.other.processed_tokens": "other",
    "component_other_tokens": "other",
    "tool_result_tokens": "tool_result",
}

PROVIDER_METRIC_ALIASES = {
    "input_tokens": "provider.input_tokens",
    "provider_input_tokens": "provider.input_tokens",
    "provider.input_tokens": "provider.input_tokens",
    "output_tokens": "provider.output_tokens",
    "provider_output_tokens": "provider.output_tokens",
    "provider.output_tokens": "provider.output_tokens",
}

LATENCY_METRICS = {
    "client_latency_p50",
    "client_latency_p95",
    "scheduled_to_first_p50",
    "scheduled_to_first_p95",
}

ALLOWED_PERFORMANCE_METRICS = (
    set(PROVIDER_METRIC_ALIASES)
    | set(COMPONENT_METRIC_ALIASES)
    | LATENCY_METRICS
)


def load_regression_policy(path: Path) -> RegressionPolicy:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegressionPolicyError(str(exc)) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _parse_simple_yaml(text)
    return parse_regression_policy(data)


def parse_regression_policy(data: Any) -> RegressionPolicy:
    root = _mapping(data, "policy")
    schema_version = root.get("schema_version", root.get("version", 1))
    if not isinstance(schema_version, int):
        raise RegressionPolicyError("policy schema_version must be an integer")
    if schema_version != 1:
        raise RegressionPolicyError(
            f"unsupported regression policy schema_version {schema_version}; "
            "this AgentPerf version supports 1"
        )
    return RegressionPolicy(
        schema_version=schema_version,
        quality=_parse_quality(root.get("quality", {})),
        performance=_parse_performance(root.get("performance", {})),
        findings=_parse_findings(root.get("findings", {})),
        task_coverage=_parse_task_coverage(root.get("task_coverage", {})),
        metadata=_mapping(root.get("metadata", {}), "metadata"),
    )


def evaluate_regression_policy(
    comparison: RunComparison,
    policy: RegressionPolicy,
) -> RegressionResult:
    checks: list[RegressionCheck] = []
    checks.extend(_artifact_checks(comparison, policy))
    checks.extend(_task_coverage_checks(comparison, policy))
    checks.extend(_quality_checks(comparison, policy))
    checks.extend(_performance_checks(comparison, policy))
    checks.extend(_finding_checks(comparison, policy))
    status = _overall_status(checks)
    return RegressionResult(
        status=status,
        checks=checks,
        warnings=list(comparison.warnings),
        metadata={
            "baseline_id": comparison.baseline_id,
            "candidate_id": comparison.candidate_id,
            "matched_tasks": len(comparison.matched_tasks),
            "unmatched_baseline_tasks": len(comparison.unmatched_baseline_tasks),
            "unmatched_candidate_tasks": len(comparison.unmatched_candidate_tasks),
            "comparison_verdict": comparison.acceptance_result.verdict,
            "task_quality_changes": comparison.metadata.get("task_quality_changes", []),
        },
    )


def regression_result_to_dict(result: RegressionResult) -> dict[str, Any]:
    return asdict(result)


def regression_result_to_json(result: RegressionResult) -> str:
    return json.dumps(regression_result_to_dict(result), indent=2, sort_keys=True)


def regression_exit_code(result: RegressionResult) -> int:
    if result.status == "PASS":
        return 0
    if result.status == "FAIL":
        return 1
    return 3


def _artifact_checks(
    comparison: RunComparison,
    policy: RegressionPolicy,
) -> list[RegressionCheck]:
    checks: list[RegressionCheck] = []
    for side in ("baseline", "candidate"):
        status = comparison.metadata.get(f"{side}_artifact_status")
        if status is None:
            continue
        result: RegressionStatus = "PASS"
        if status == "FAILED":
            result = "FAIL"
        elif status == "PARTIAL" and not policy.task_coverage.allow_partial:
            result = "INCONCLUSIVE"
        checks.append(
            RegressionCheck(
                category="ARTIFACT",
                metric=f"{side}_artifact_status",
                result=result,
                candidate=str(status),
                allowed=(
                    "COMPLETE"
                    if not policy.task_coverage.allow_partial
                    else "COMPLETE/PARTIAL"
                ),
                evidence={"artifact_status": status},
            )
        )
    return checks


def _task_coverage_checks(
    comparison: RunComparison,
    policy: RegressionPolicy,
) -> list[RegressionCheck]:
    coverage_policy = policy.task_coverage
    checks: list[RegressionCheck] = []
    matched = len(comparison.matched_tasks)
    baseline_total = matched + len(comparison.unmatched_baseline_tasks)
    candidate_total = matched + len(comparison.unmatched_candidate_tasks)
    if coverage_policy.require_same_tasks:
        same_tasks = (
            matched > 0
            and not comparison.unmatched_baseline_tasks
            and not comparison.unmatched_candidate_tasks
        )
        checks.append(
            RegressionCheck(
                category="TASK_COVERAGE",
                metric="same_tasks",
                result="PASS" if same_tasks else "FAIL",
                baseline=baseline_total,
                candidate=candidate_total,
                allowed="same matched task set",
                evidence={
                    "matched_tasks": matched,
                    "unmatched_baseline_tasks": comparison.unmatched_baseline_tasks,
                    "unmatched_candidate_tasks": comparison.unmatched_candidate_tasks,
                },
            )
        )
    if coverage_policy.minimum_task_coverage is not None:
        coverage = matched / baseline_total if baseline_total else None
        result: RegressionStatus
        if coverage is None:
            result = "INCONCLUSIVE"
        elif coverage + 1e-12 >= coverage_policy.minimum_task_coverage:
            result = "PASS"
        else:
            result = "FAIL"
        checks.append(
            RegressionCheck(
                category="TASK_COVERAGE",
                metric="minimum_task_coverage",
                result=result,
                baseline=baseline_total,
                candidate=matched,
                allowed=coverage_policy.minimum_task_coverage,
                actual_delta=coverage,
                evidence={"candidate_total_tasks": candidate_total},
            )
        )
    return checks


def _quality_checks(
    comparison: RunComparison,
    policy: RegressionPolicy,
) -> list[RegressionCheck]:
    checks: list[RegressionCheck] = []
    metric_map = {
        "mean_score": comparison.quality_deltas.mean_score,
        "pass_rate": comparison.quality_deltas.pass_rate,
    }
    for metric, threshold in policy.quality.items():
        delta = metric_map.get(metric)
        if delta is None:
            checks.append(_unsupported_check("QUALITY", metric))
            continue
        checks.append(_quality_check(metric, delta, threshold))
    return checks


def _quality_check(
    metric: str,
    delta: MetricDelta,
    threshold: QualityMetricPolicy,
) -> RegressionCheck:
    if delta.baseline is None or delta.candidate is None:
        return RegressionCheck(
            category="QUALITY",
            metric=metric,
            result="INCONCLUSIVE",
            baseline=delta.baseline,
            candidate=delta.candidate,
            allowed=threshold.max_drop,
            evidence={"reason": "quality metric missing from comparison input"},
        )
    if threshold.max_drop is None:
        return RegressionCheck(
            category="QUALITY",
            metric=metric,
            result="PASS",
            baseline=delta.baseline,
            candidate=delta.candidate,
            allowed="not configured",
            actual_delta=delta.delta,
            actual_percent_delta=delta.percent_delta,
        )
    drop = float(delta.baseline) - float(delta.candidate)
    return RegressionCheck(
        category="QUALITY",
        metric=metric,
        result="PASS" if drop <= threshold.max_drop + 1e-12 else "FAIL",
        baseline=delta.baseline,
        candidate=delta.candidate,
        allowed=threshold.max_drop,
        actual_delta=drop,
        actual_percent_delta=delta.percent_delta,
    )


def _performance_checks(
    comparison: RunComparison,
    policy: RegressionPolicy,
) -> list[RegressionCheck]:
    checks: list[RegressionCheck] = []
    metric_map = {
        "client_latency_p50": comparison.latency_deltas.client_p50_ms,
        "client_latency_p95": comparison.latency_deltas.client_p95_ms,
        "scheduled_to_first_p50": comparison.latency_deltas.scheduled_to_first_p50_ms,
        "scheduled_to_first_p95": comparison.latency_deltas.scheduled_to_first_p95_ms,
    }
    for metric, threshold in policy.performance.items():
        delta = _performance_delta(comparison, metric, metric_map)
        if delta is None:
            checks.append(_unsupported_check("PERFORMANCE", metric))
            continue
        checks.append(_performance_check(comparison, metric, delta, threshold))
    return checks


def _performance_delta(
    comparison: RunComparison,
    metric: str,
    latency_metric_map: dict[str, MetricDelta],
) -> MetricDelta | None:
    provider_metric = PROVIDER_METRIC_ALIASES.get(metric)
    if provider_metric == "provider.input_tokens":
        return comparison.token_deltas.input_tokens
    if provider_metric == "provider.output_tokens":
        return comparison.token_deltas.output_tokens
    component = COMPONENT_METRIC_ALIASES.get(metric)
    if component == "total":
        accounting = comparison.token_deltas.component_accounting
        return accounting.total_processed_tokens if accounting is not None else None
    if component is not None:
        return comparison.token_deltas.component_processed_tokens.get(component)
    return latency_metric_map.get(metric)


def _performance_check(
    comparison: RunComparison,
    metric: str,
    delta: MetricDelta,
    threshold: PerformanceMetricPolicy,
) -> RegressionCheck:
    source = _metric_source(metric)
    if delta.baseline is None or delta.candidate is None or delta.delta is None:
        return RegressionCheck(
            category="PERFORMANCE",
            metric=metric,
            result="INCONCLUSIVE",
            baseline=delta.baseline,
            candidate=delta.candidate,
            evidence={
                "reason": "performance metric missing from comparison input",
                "accounting_source": source,
            },
        )
    attribution_check = _attribution_requirement_check(comparison, metric, threshold)
    if attribution_check is not None:
        return RegressionCheck(
            category="PERFORMANCE",
            metric=metric,
            result="INCONCLUSIVE",
            baseline=delta.baseline,
            candidate=delta.candidate,
            evidence=attribution_check,
        )
    allowed_percent = (
        threshold.max_increase_percent / 100.0
        if threshold.max_increase_percent is not None
        else None
    )
    allowed_absolute = threshold.max_increase_absolute
    percent_ok = (
        True
        if allowed_percent is None
        else (delta.percent_delta or 0.0) <= allowed_percent
    )
    absolute_ok = True if allowed_absolute is None else float(delta.delta) <= allowed_absolute
    allowed = _threshold_label(allowed_percent, allowed_absolute)
    return RegressionCheck(
        category="PERFORMANCE",
        metric=metric,
        result="PASS" if percent_ok and absolute_ok else "FAIL",
        baseline=delta.baseline,
        candidate=delta.candidate,
        allowed=allowed,
        actual_delta=delta.delta,
        actual_percent_delta=delta.percent_delta,
        evidence={"accounting_source": source},
    )


def _attribution_requirement_check(
    comparison: RunComparison,
    metric: str,
    threshold: PerformanceMetricPolicy,
) -> dict[str, Any] | None:
    if metric not in COMPONENT_METRIC_ALIASES:
        return None
    accounting = comparison.token_deltas.component_accounting
    if accounting is None:
        return {
            "reason": "component attribution accounting unavailable",
            "accounting_source": "agentperf_component_attribution",
        }
    if threshold.min_attribution_coverage is not None:
        baseline_coverage = accounting.attribution_coverage_ratio.baseline
        candidate_coverage = accounting.attribution_coverage_ratio.candidate
        if (
            baseline_coverage is None
            or candidate_coverage is None
            or float(baseline_coverage) + 1e-12 < threshold.min_attribution_coverage
            or float(candidate_coverage) + 1e-12 < threshold.min_attribution_coverage
        ):
            return {
                "reason": "component attribution coverage below policy requirement",
                "accounting_source": "agentperf_component_attribution",
                "min_attribution_coverage": threshold.min_attribution_coverage,
                "baseline_coverage": baseline_coverage,
                "candidate_coverage": candidate_coverage,
            }
    if threshold.require_attribution_confidence is not None:
        required = threshold.require_attribution_confidence
        if not (
            _confidence_satisfies(accounting.baseline_confidence, required)
            and _confidence_satisfies(accounting.candidate_confidence, required)
        ):
            return {
                "reason": "component attribution confidence below policy requirement",
                "accounting_source": "agentperf_component_attribution",
                "required_confidence": required,
                "baseline_confidence": accounting.baseline_confidence,
                "candidate_confidence": accounting.candidate_confidence,
            }
    return None


def _confidence_satisfies(actual: str, required: str) -> bool:
    rank = {"UNAVAILABLE": 0, "APPROXIMATE": 1, "STRUCTURED": 2}
    if required not in rank:
        raise RegressionPolicyError(
            "require_attribution_confidence must be STRUCTURED or APPROXIMATE"
        )
    return rank.get(actual, 0) >= rank[required]


def _finding_checks(
    comparison: RunComparison,
    policy: RegressionPolicy,
) -> list[RegressionCheck]:
    checks: list[RegressionCheck] = []
    if policy.findings.fail_on_new_material_findings:
        new_material = [
            change
            for change in comparison.finding_changes
            if change.lifecycle == "NEW"
            and _material_finding(change.candidate_severity, change.candidate_materiality)
        ]
        checks.append(
            RegressionCheck(
                category="FINDINGS",
                metric="new_material_findings",
                result="FAIL" if new_material else "PASS",
                candidate=len(new_material),
                allowed=0,
                evidence={
                    "findings": [
                        {
                            "id": change.finding_id,
                            "severity": change.candidate_severity,
                            "materiality": change.candidate_materiality,
                            "scope": change.scope,
                        }
                        for change in new_material
                    ]
                },
            )
        )
    if policy.findings.fail_on_regressed_material_findings:
        regressed_material = [
            change
            for change in comparison.finding_changes
            if change.lifecycle == "REGRESSED"
            and _material_finding(change.candidate_severity, change.candidate_materiality)
        ]
        checks.append(
            RegressionCheck(
                category="FINDINGS",
                metric="regressed_material_findings",
                result="FAIL" if regressed_material else "PASS",
                candidate=len(regressed_material),
                allowed=0,
                evidence={
                    "findings": [
                        {
                            "id": change.finding_id,
                            "baseline_severity": change.baseline_severity,
                            "candidate_severity": change.candidate_severity,
                            "materiality": change.candidate_materiality,
                            "scope": change.scope,
                        }
                        for change in regressed_material
                    ]
                },
            )
        )
    return checks


def _unsupported_check(category: str, metric: str) -> RegressionCheck:
    return RegressionCheck(
        category=category,  # type: ignore[arg-type]
        metric=metric,
        result="INCONCLUSIVE",
        evidence={"reason": "unsupported regression policy metric"},
    )


def _material_finding(severity: str | None, materiality: str | None) -> bool:
    if materiality in {"MATERIAL", "ACTIONABLE"}:
        return True
    if materiality in {"OBSERVATION", "HEADROOM", "CACHEABILITY_HEADROOM"}:
        return False
    return severity == "HIGH"


def _threshold_label(percent: float | None, absolute: float | None) -> str:
    labels: list[str] = []
    if percent is not None:
        labels.append(f"{percent * 100:g}%")
    if absolute is not None:
        labels.append(f"{absolute:g}")
    return " and ".join(labels) if labels else "not configured"


def _overall_status(checks: list[RegressionCheck]) -> RegressionStatus:
    if any(check.result == "FAIL" for check in checks):
        return "FAIL"
    if any(check.result == "INCONCLUSIVE" for check in checks):
        return "INCONCLUSIVE"
    return "PASS"


def _parse_quality(data: Any) -> dict[str, QualityMetricPolicy]:
    result: dict[str, QualityMetricPolicy] = {}
    for metric, raw in _mapping(data, "quality").items():
        values = _mapping(raw, f"quality.{metric}")
        result[str(metric)] = QualityMetricPolicy(max_drop=_optional_float(values, "max_drop"))
    return result


def _parse_performance(data: Any) -> dict[str, PerformanceMetricPolicy]:
    result: dict[str, PerformanceMetricPolicy] = {}
    for metric, raw in _mapping(data, "performance").items():
        metric_name = str(metric)
        if metric_name not in ALLOWED_PERFORMANCE_METRICS:
            allowed = ", ".join(sorted(ALLOWED_PERFORMANCE_METRICS))
            raise RegressionPolicyError(
                f"unsupported performance metric {metric_name!r}; "
                f"supported metrics: {allowed}"
            )
        values = _mapping(raw, f"performance.{metric}")
        confidence = _optional_str(values, "require_attribution_confidence")
        if confidence is not None and confidence not in {"STRUCTURED", "APPROXIMATE"}:
            raise RegressionPolicyError(
                "require_attribution_confidence must be STRUCTURED or APPROXIMATE"
            )
        result[metric_name] = PerformanceMetricPolicy(
            max_increase_percent=_optional_float(values, "max_increase_percent"),
            max_increase_absolute=_optional_float(values, "max_increase_absolute"),
            min_attribution_coverage=_optional_float(values, "min_attribution_coverage"),
            require_attribution_confidence=confidence,
        )
    return result


def _metric_source(metric: str) -> str:
    if metric in PROVIDER_METRIC_ALIASES:
        return "provider_usage"
    if metric in COMPONENT_METRIC_ALIASES:
        return "agentperf_component_attribution"
    if metric.startswith(("client_latency", "scheduled_to_first")):
        return "latency"
    return "unknown"


def _parse_findings(data: Any) -> FindingPolicy:
    values = _mapping(data, "findings")
    return FindingPolicy(
        fail_on_new_material_findings=_bool(values.get("fail_on_new_material_findings"), False),
        fail_on_regressed_material_findings=_bool(
            values.get("fail_on_regressed_material_findings"),
            False,
        ),
    )


def _parse_task_coverage(data: Any) -> TaskCoveragePolicy:
    values = _mapping(data, "task_coverage")
    return TaskCoveragePolicy(
        require_same_tasks=_bool(values.get("require_same_tasks"), False),
        minimum_task_coverage=_optional_float(values, "minimum_task_coverage"),
        allow_partial=_bool(values.get("allow_partial"), False),
    )


def _mapping(data: Any, name: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RegressionPolicyError(f"{name} must be a mapping")
    return {str(key): value for key, value in data.items()}


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise RegressionPolicyError(f"{key} must be numeric")
    return float(value)


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegressionPolicyError(f"{key} must be a string")
    return value


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise RegressionPolicyError("boolean policy values must be true or false")
    return value


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            raise RegressionPolicyError(f"invalid policy line {line_number}: {raw_line}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise RegressionPolicyError(f"empty policy key on line {line_number}")
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        value_text = raw_value.strip()
        if not value_text:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value_text)
    return root


def _parse_scalar(value: str) -> str | int | float | bool | None:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
