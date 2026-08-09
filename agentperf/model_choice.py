from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentperf.schema.findings import Finding, FindingProvenance

QUALITY_EPSILON = 1e-9


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
    findings = _findings(sensitivities, baseline, quality_constraint)
    pareto = _pareto(configs, quality_constraint)
    selected = _selected_mixed_config(data, configs, quality_constraint)
    return ModelChoiceReport(
        environment=_as_dict(data.get("environment")),
        model_ladder=_as_dict(data.get("model_ladder")),
        quality_constraint=quality_constraint,
        baseline=baseline,
        configurations=configs,
        role_sensitivity=sensitivities,
        findings=findings,
        selected_mixed_config=selected,
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
            )
        )
    return rows


def _findings(
    sensitivities: list[RoleSensitivity],
    baseline: ModelChoiceConfig,
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
        findings.append(
            Finding(
                id="MODEL_CHOICE_HEADROOM",
                severity="MEDIUM",
                title="Model-choice headroom",
                summary=(
                    f"Counterfactual replay shows role {row.role} can use "
                    f"{row.candidate_model} within the configured quality tolerance."
                ),
                evidence={
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
                    f"Evaluate routing {row.role} calls to {row.candidate_model} "
                    f"while retaining stronger models for roles that failed replay."
                ),
                confidence="MEDIUM",
                validation_plan=[
                    "Replay the full mixed-routing agent configuration.",
                    "Compare mean quality, pass rate, latency, and relative cost.",
                    "Inspect failures for role-specific quality regressions.",
                ],
                provenance=FindingProvenance(
                    derived_metrics={
                        "config_name": row.config_name,
                        "quality_preserving": row.quality_preserving,
                    },
                    notes=[
                        (
                            "Finding is based on counterfactual replay evidence, "
                            "not model-size heuristics."
                        ),
                    ],
                ),
            )
        )
    return findings


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
