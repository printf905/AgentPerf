from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from agentperf.artifacts import ArtifactError, ExperimentArtifact, load_artifact
from agentperf.comparison import compare_paths
from agentperf.regression import (
    RegressionPolicyError,
    evaluate_regression_policy,
    load_regression_policy,
    regression_result_to_dict,
)
from agentperf.schema.regression import RegressionCheck, RegressionResult
from agentperf.schema.suites import (
    SUITE_SCHEMA_VERSION,
    SuiteEnvironmentPolicy,
    SuiteManifest,
    SuiteStatus,
    TaskSetSpec,
)


class SuiteError(ValueError):
    """Raised when a benchmark suite cannot be loaded or evaluated."""


@dataclass(frozen=True)
class BenchmarkSuite:
    path: Path
    manifest: SuiteManifest
    baseline_path: Path
    policy_path: Path
    root: Path


@dataclass(frozen=True)
class SuiteValidationResult:
    status: SuiteStatus
    suite_id: str | None
    checks: list[RegressionCheck]
    warnings: list[str]


@dataclass(frozen=True)
class SuiteCheckResult:
    suite: BenchmarkSuite
    regression: RegressionResult
    comparison: dict[str, Any]

    @property
    def status(self) -> SuiteStatus:
        return self.regression.status


@dataclass(frozen=True)
class SuiteCollectionResult:
    status: SuiteStatus
    results: list[SuiteCheckResult]
    missing_candidates: list[str]


@dataclass(frozen=True)
class BaselineProposal:
    suite: BenchmarkSuite
    candidate_path: Path
    regression: RegressionResult
    comparison: dict[str, Any]


def load_suite(path: Path) -> BenchmarkSuite:
    suite_dir = path if path.is_dir() else path.parent
    manifest_path = suite_dir / "suite.yaml" if path.is_dir() else path
    root = _discover_root(suite_dir)
    raw = _load_mapping(manifest_path)
    manifest = parse_suite_manifest(raw)
    baseline_path = _safe_path(suite_dir, manifest.baseline_artifact, root)
    policy_path = _safe_path(suite_dir, manifest.regression_policy, root)
    return BenchmarkSuite(
        path=suite_dir,
        manifest=manifest,
        baseline_path=baseline_path,
        policy_path=policy_path,
        root=root,
    )


def parse_suite_manifest(data: Any) -> SuiteManifest:
    root = _mapping(data, "suite manifest")
    schema_version = root.get("schema_version", root.get("version", 1))
    if not isinstance(schema_version, int):
        raise SuiteError("suite schema_version must be an integer")
    if schema_version != SUITE_SCHEMA_VERSION:
        raise SuiteError(
            f"unsupported suite schema_version {schema_version}; "
            f"this AgentPerf version supports {SUITE_SCHEMA_VERSION}"
        )
    suite_id = _required_str(root, "suite_id")
    suite_version = root.get("suite_version", 1)
    if not isinstance(suite_version, int):
        raise SuiteError("suite_version must be an integer")
    quality_metrics = [
        key for key, enabled in _mapping(root.get("quality_metrics", {}), "quality_metrics").items()
        if _bool(enabled, True)
    ]
    return SuiteManifest(
        schema_version=schema_version,
        suite_id=suite_id,
        suite_version=suite_version,
        description=_optional_str(root, "description"),
        agent=_optional_str(root, "agent"),
        framework=_optional_str(root, "framework"),
        task_set=_parse_task_set(root.get("task_set", {})),
        baseline_artifact=_required_str(root, "baseline_artifact"),
        regression_policy=_required_str(root, "regression_policy"),
        expected_task_count=_optional_int(root, "expected_task_count"),
        quality_metrics=quality_metrics,
        environment=_parse_environment_policy(root.get("environment", {})),
        metadata=_mapping(root.get("metadata", {}), "metadata"),
    )


def validate_suite(path: Path) -> SuiteValidationResult:
    try:
        suite = load_suite(path)
    except (OSError, SuiteError) as exc:
        return SuiteValidationResult(
            status="FAIL",
            suite_id=None,
            checks=[
                RegressionCheck(
                    category="ARTIFACT",
                    metric="suite_manifest",
                    result="FAIL",
                    evidence={"error": str(exc)},
                )
            ],
            warnings=[],
        )
    checks: list[RegressionCheck] = []
    warnings: list[str] = []
    baseline: ExperimentArtifact | None = None
    policy_quality_metrics: set[str] = set()
    checks.append(
        RegressionCheck(
            category="ARTIFACT",
            metric="suite_manifest",
            result="PASS",
            evidence={"suite_id": suite.manifest.suite_id},
        )
    )
    try:
        baseline = load_artifact(suite.baseline_path)
        checks.extend(_baseline_checks(suite, baseline))
    except (OSError, ArtifactError) as exc:
        checks.append(
            RegressionCheck(
                category="ARTIFACT",
                metric="baseline_artifact",
                result="FAIL",
                evidence={"path": str(suite.baseline_path), "error": str(exc)},
            )
        )
    try:
        policy = load_regression_policy(suite.policy_path)
        policy_quality_metrics = set(policy.quality)
        checks.append(
            RegressionCheck(
                category="ARTIFACT",
                metric="regression_policy",
                result="PASS",
                evidence={"path": _relative_display(suite.policy_path, suite.root)},
            )
        )
    except (OSError, RegressionPolicyError) as exc:
        checks.append(
            RegressionCheck(
                category="ARTIFACT",
                metric="regression_policy",
                result="FAIL",
                evidence={"path": str(suite.policy_path), "error": str(exc)},
            )
        )
    if baseline is not None and policy_quality_metrics:
        available = {metric.name for metric in baseline.quality_metrics}
        missing = sorted(policy_quality_metrics - available)
        checks.append(
            RegressionCheck(
                category="QUALITY",
                metric="policy_quality_metrics_present",
                result="PASS" if not missing else "FAIL",
                evidence={"missing": missing, "available": sorted(available)},
            )
        )
    return SuiteValidationResult(
        status=_status_from_checks(checks),
        suite_id=suite.manifest.suite_id,
        checks=checks,
        warnings=warnings,
    )


def check_suite(path: Path, candidate_path: Path) -> SuiteCheckResult:
    suite = load_suite(path)
    policy = load_regression_policy(suite.policy_path)
    mean_score_policy = policy.quality.get("mean_score")
    pass_rate_policy = policy.quality.get("pass_rate")
    comparison = compare_paths(
        suite.baseline_path,
        candidate_path,
        mean_score_tolerance=mean_score_policy.max_drop if mean_score_policy else None,
        pass_rate_tolerance=pass_rate_policy.max_drop if pass_rate_policy else None,
    )
    regression = evaluate_regression_policy(comparison, policy)
    regression = _with_suite_checks(
        regression,
        suite,
        suite.baseline_path,
        candidate_path,
        latency_policy_configured=any(
            metric.startswith(("client_latency", "scheduled_to_first"))
            for metric in policy.performance
        ),
    )
    return SuiteCheckResult(
        suite=suite,
        regression=regression,
        comparison=regression_result_to_dict(regression)["metadata"]
        | {"comparison_verdict": comparison.acceptance_result.verdict},
    )


def check_all_suites(suites_root: Path, candidates_root: Path) -> SuiteCollectionResult:
    suite_paths = sorted(suites_root.rglob("suite.yaml"))
    results: list[SuiteCheckResult] = []
    missing: list[str] = []
    for suite_path in suite_paths:
        suite = load_suite(suite_path)
        candidate = _candidate_for_suite(suite, candidates_root)
        if candidate is None:
            missing.append(suite.manifest.suite_id)
            continue
        results.append(check_suite(suite.path, candidate))
    status: SuiteStatus
    if any(result.status == "FAIL" for result in results) or missing:
        status = "FAIL"
    elif any(result.status == "INCONCLUSIVE" for result in results):
        status = "INCONCLUSIVE"
    else:
        status = "PASS"
    return SuiteCollectionResult(status=status, results=results, missing_candidates=missing)


def propose_baseline(path: Path, candidate_path: Path) -> BaselineProposal:
    result = check_suite(path, candidate_path)
    return BaselineProposal(
        suite=result.suite,
        candidate_path=candidate_path,
        regression=result.regression,
        comparison=result.comparison,
    )


def suite_result_exit_code(status: SuiteStatus) -> int:
    if status == "PASS":
        return 0
    if status == "FAIL":
        return 1
    return 3


def render_suite_validation(result: SuiteValidationResult, *, markdown: bool = False) -> str:
    if markdown:
        return _render_checks_markdown("AgentPerf Suite Validation", result.status, result.checks)
    return _render_checks_terminal(
        "AgentPerf Suite Validation",
        result.status,
        result.checks,
        suite_id=result.suite_id,
    )


def render_suite_check(result: SuiteCheckResult, *, markdown: bool = False) -> str:
    if markdown:
        return _render_checks_markdown(
            f"AgentPerf Suite Check: {result.suite.manifest.suite_id}",
            result.status,
            result.regression.checks,
        )
    return _render_checks_terminal(
        "AgentPerf Suite Check",
        result.status,
        result.regression.checks,
        suite_id=result.suite.manifest.suite_id,
    )


def render_check_all(result: SuiteCollectionResult, *, markdown: bool = False) -> str:
    if markdown:
        lines = ["## AgentPerf Benchmark Suites", "", f"**Overall:** {result.status}", ""]
        if result.status != "PASS":
            lines.extend(["### Triage", ""])
            for item in result.results:
                if item.status != "PASS":
                    reason = _suite_reason(item.regression.checks)
                    lines.append(
                        f"- `{item.suite.manifest.suite_id}`: {item.status}; {reason}"
                    )
            for suite_id in result.missing_candidates:
                lines.append(f"- `{suite_id}`: FAIL; missing candidate artifact")
            lines.append("")
        lines.extend(["| Suite | Result |", "| --- | --- |"])
        for item in result.results:
            lines.append(f"| `{item.suite.manifest.suite_id}` | {item.status} |")
        for suite_id in result.missing_candidates:
            lines.append(f"| `{suite_id}` | FAIL: missing candidate |")
        return "\n".join(lines)
    lines = [
        "=" * 60,
        "AgentPerf Benchmark Suites",
        "=" * 60,
    ]
    for item in result.results:
        lines.append(f"{item.suite.manifest.suite_id:<34} {item.status}")
    for suite_id in result.missing_candidates:
        lines.append(f"{suite_id:<34} FAIL missing candidate")
    lines.extend(["", f"Overall: {result.status}"])
    if result.status != "PASS":
        lines.extend(["", "Failed/Inconclusive Suites", "-" * 60])
        for item in result.results:
            if item.status != "PASS":
                reason = _suite_reason(item.regression.checks)
                lines.append(f"{item.suite.manifest.suite_id:<34} {reason}")
        for suite_id in result.missing_candidates:
            lines.append(f"{suite_id:<34} missing candidate artifact")
    return "\n".join(lines)


def render_baseline_proposal(proposal: BaselineProposal, *, markdown: bool = True) -> str:
    suite = proposal.suite
    old_baseline = load_artifact(suite.baseline_path)
    candidate = load_artifact(proposal.candidate_path)
    if markdown:
        lines = [
            "## AgentPerf Baseline Update Proposal",
            "",
            f"**Suite:** `{suite.manifest.suite_id}`",
            f"**Suite version:** `{suite.manifest.suite_version}`",
            "",
            "### Baselines",
            "",
            f"- Current: `{old_baseline.manifest.artifact_id}`",
            f"- Candidate: `{candidate.manifest.artifact_id}`",
            "",
            "### Regression Checks",
            "",
            "| Check | Result | Evidence |",
            "| --- | --- | --- |",
        ]
        for check in proposal.regression.checks:
            lines.append(
                f"| {check.category}: `{check.metric}` | {check.result} | "
                f"{_check_evidence(check)} |"
            )
        lines.extend(
            [
                "",
                "### Recommendation",
                "",
                _proposal_recommendation(proposal.regression.status),
                "",
                (
                    "This command does not replace the baseline. Commit any suite "
                    "manifest or artifact change explicitly for review."
                ),
            ]
        )
        return "\n".join(lines)
    return _render_checks_terminal(
        "AgentPerf Baseline Update Proposal",
        proposal.regression.status,
        proposal.regression.checks,
        suite_id=suite.manifest.suite_id,
    )


def suite_validation_to_dict(result: SuiteValidationResult) -> dict[str, Any]:
    return asdict(result)


def suite_check_to_dict(result: SuiteCheckResult) -> dict[str, Any]:
    return {
        "suite": asdict(result.suite.manifest),
        "status": result.status,
        "regression": regression_result_to_dict(result.regression),
    }


def suite_collection_to_dict(result: SuiteCollectionResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "results": [suite_check_to_dict(item) for item in result.results],
        "missing_candidates": result.missing_candidates,
    }


def baseline_proposal_to_dict(proposal: BaselineProposal) -> dict[str, Any]:
    return {
        "suite": asdict(proposal.suite.manifest),
        "candidate_path": str(proposal.candidate_path),
        "regression": regression_result_to_dict(proposal.regression),
    }


def _baseline_checks(
    suite: BenchmarkSuite,
    artifact: ExperimentArtifact,
) -> list[RegressionCheck]:
    checks = [
        RegressionCheck(
            category="ARTIFACT",
            metric="baseline_artifact",
            result="PASS",
            evidence={
                "path": _relative_display(suite.baseline_path, suite.root),
                "artifact_id": artifact.manifest.artifact_id,
                "agentperf_version": artifact.manifest.agentperf_version,
                "created_at": artifact.manifest.created_at,
                "task_count": artifact.manifest.task_count,
            },
        ),
        RegressionCheck(
            category="ARTIFACT",
            metric="baseline_complete",
            result="PASS" if artifact.manifest.status == "COMPLETE" else "FAIL",
            candidate=artifact.manifest.status,
            allowed="COMPLETE",
        ),
    ]
    if suite.manifest.expected_task_count is not None:
        actual = artifact.manifest.task_count
        checks.append(
            RegressionCheck(
                category="TASK_COVERAGE",
                metric="expected_task_count",
                result="PASS" if actual == suite.manifest.expected_task_count else "FAIL",
                baseline=suite.manifest.expected_task_count,
                candidate=actual,
            )
        )
    fingerprint = task_set_fingerprint(artifact)
    if suite.manifest.task_set.fingerprint and fingerprint:
        checks.append(
            RegressionCheck(
                category="TASK_COVERAGE",
                metric="task_set_fingerprint",
                result="PASS" if fingerprint == suite.manifest.task_set.fingerprint else "FAIL",
                baseline=suite.manifest.task_set.fingerprint,
                candidate=fingerprint,
            )
        )
    return checks


def _with_suite_checks(
    regression: RegressionResult,
    suite: BenchmarkSuite,
    baseline_path: Path,
    candidate_path: Path,
    *,
    latency_policy_configured: bool,
) -> RegressionResult:
    checks = list(regression.checks)
    warnings = list(regression.warnings)
    try:
        baseline = load_artifact(baseline_path)
        candidate = load_artifact(candidate_path)
    except ArtifactError:
        return regression
    checks.extend(_task_set_checks(suite, baseline, candidate))
    if latency_policy_configured:
        env_check = _environment_check(suite, baseline, candidate)
        if env_check:
            checks.append(env_check)
            if env_check.result != "PASS":
                warnings.append(
                    "Latency policy configured, but suite environment compatibility "
                    "was not established."
                )
    status = _status_from_checks(checks)
    return replace(regression, status=status, checks=checks, warnings=warnings)


def _task_set_checks(
    suite: BenchmarkSuite,
    baseline: ExperimentArtifact,
    candidate: ExperimentArtifact,
) -> list[RegressionCheck]:
    checks: list[RegressionCheck] = []
    baseline_fingerprint = task_set_fingerprint(baseline)
    candidate_fingerprint = task_set_fingerprint(candidate)
    expected = suite.manifest.task_set.fingerprint
    if expected and baseline_fingerprint:
        checks.append(
            RegressionCheck(
                category="TASK_COVERAGE",
                metric="baseline_task_set_fingerprint",
                result="PASS" if baseline_fingerprint == expected else "FAIL",
                baseline=expected,
                candidate=baseline_fingerprint,
            )
        )
    if baseline_fingerprint and candidate_fingerprint:
        checks.append(
            RegressionCheck(
                category="TASK_COVERAGE",
                metric="candidate_task_set_fingerprint",
                result="PASS" if baseline_fingerprint == candidate_fingerprint else "FAIL",
                baseline=baseline_fingerprint,
                candidate=candidate_fingerprint,
            )
        )
    return checks


def _environment_check(
    suite: BenchmarkSuite,
    baseline: ExperimentArtifact,
    candidate: ExperimentArtifact,
) -> RegressionCheck | None:
    if not suite.manifest.environment.latency_requires_compatible:
        return None
    fields = {
        "backend": (baseline.manifest.backend, candidate.manifest.backend),
        "model": (baseline.manifest.model, candidate.manifest.model),
        "gpu": (baseline.environment.get("gpu"), candidate.environment.get("gpu")),
    }
    mismatches = {
        key: {"baseline": left, "candidate": right}
        for key, (left, right) in fields.items()
        if left is not None and right is not None and left != right
    }
    if not mismatches:
        return RegressionCheck(
            category="ENVIRONMENT",
            metric="latency_environment_compatible",
            result="PASS",
            evidence={"checked_fields": sorted(fields)},
        )
    result: SuiteStatus = (
        "PASS" if suite.manifest.environment.allow_environment_mismatch else "INCONCLUSIVE"
    )
    return RegressionCheck(
        category="ENVIRONMENT",
        metric="latency_environment_compatible",
        result=result,
        evidence={"mismatches": mismatches},
    )


def task_set_fingerprint(artifact: ExperimentArtifact) -> str | None:
    if not artifact.task_results:
        return None
    task_ids = sorted(task.task_id for task in artifact.task_results)
    joined = "\n".join(task_ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _candidate_for_suite(suite: BenchmarkSuite, candidates_root: Path) -> Path | None:
    for name in (suite.manifest.suite_id, suite.path.name):
        candidate = candidates_root / name
        if candidate.exists():
            return candidate
    return None


def _status_from_checks(checks: list[RegressionCheck]) -> SuiteStatus:
    if any(check.result == "FAIL" for check in checks):
        return "FAIL"
    if any(check.result == "INCONCLUSIVE" for check in checks):
        return "INCONCLUSIVE"
    return "PASS"


def _render_checks_terminal(
    title: str,
    status: str,
    checks: list[RegressionCheck],
    *,
    suite_id: str | None = None,
) -> str:
    lines = ["=" * 60, title, "=" * 60]
    if suite_id:
        lines.append(f"{'Suite':<34} {suite_id}")
    lines.append(f"{'Result':<34} {status}")
    lines.extend(["", "Summary", "-" * 60])
    lines.extend(_suite_summary_lines(checks))
    lines.extend(["", "Detailed Checks", "-" * 60])
    for check in checks:
        lines.append(
            f"{check.category + ':' + check.metric:<34} {check.result} {_check_evidence(check)}"
        )
    return "\n".join(lines)


def _render_checks_markdown(title: str, status: str, checks: list[RegressionCheck]) -> str:
    lines = [f"## {title}", "", f"**Result:** {status}", "", "### Summary", ""]
    lines.extend(f"- {line}" for line in _suite_summary_lines(checks, markdown=True))
    lines.extend(["", "### Detailed Checks", "", "| Check | Result | Evidence |"])
    lines.append("| --- | --- | --- |")
    for check in checks:
        lines.append(
            f"| {check.category}: `{check.metric}` | {check.result} | "
            f"{_check_evidence(check)} |"
        )
    return "\n".join(lines)


def _check_evidence(check: RegressionCheck) -> str:
    parts: list[str] = []
    if check.baseline is not None and check.candidate is not None:
        parts.append(f"{check.baseline} -> {check.candidate}")
    elif check.baseline is not None:
        parts.append(str(check.baseline))
    elif check.candidate is not None:
        parts.append(str(check.candidate))
    if check.allowed is not None:
        parts.append(f"allowed {check.allowed}")
    if check.actual_delta is not None:
        parts.append(f"delta {check.actual_delta}")
    if check.evidence:
        parts.append("; ".join(f"{key}={value}" for key, value in check.evidence.items()))
    return "; ".join(parts)


def _suite_summary_lines(
    checks: list[RegressionCheck],
    *,
    markdown: bool = False,
) -> list[str]:
    lines: list[str] = []
    quality = [check for check in checks if check.category == "QUALITY"]
    failed_quality = [check for check in quality if check.result == "FAIL"]
    if failed_quality:
        lines.append(
            "QUALITY REGRESSION: "
            + "; ".join(_check_summary(check) for check in failed_quality)
        )
    elif quality:
        lines.append("Quality: " + "; ".join(_check_summary(check) for check in quality))
    coverage = next(
        (
            check
            for check in checks
            if check.category == "TASK_COVERAGE" and check.metric == "same_tasks"
        ),
        None,
    )
    if coverage is not None:
        matched = coverage.evidence.get("matched_tasks")
        lines.append(f"Task coverage: {matched} matched ({coverage.result})")
    failures = [check for check in checks if check.result == "FAIL"]
    if failures and not failed_quality:
        lines.append("Primary failure: " + _check_summary(failures[0]))
    perf = [check for check in checks if check.category == "PERFORMANCE"]
    improvements = sorted(
        [check for check in perf if check.actual_delta is not None and check.actual_delta < 0],
        key=lambda check: check.actual_percent_delta
        if check.actual_percent_delta is not None
        else -abs(float(check.actual_delta or 0)),
    )
    perf_failures = [check for check in perf if check.result == "FAIL"]
    if improvements:
        lines.append(
            "Biggest improvements: "
            + "; ".join(_check_summary(check) for check in improvements[:3])
        )
    lines.append(
        "Biggest regressions: "
        + (
            "; ".join(_check_summary(check) for check in perf_failures)
            if perf_failures
            else "none above configured thresholds"
        )
    )
    accounting_note = _suite_accounting_note(perf)
    if accounting_note:
        lines.append(accounting_note)
    findings = [check for check in checks if check.category == "FINDINGS"]
    if findings:
        lines.append(
            "Findings: "
            + "; ".join(_finding_summary(check) for check in findings)
        )
    if markdown:
        return [line.replace("|", "\\|") for line in lines]
    return lines or ["No summary checks available."]


def _check_summary(check: RegressionCheck) -> str:
    values: list[str] = []
    if check.baseline is not None and check.candidate is not None:
        values.append(f"{check.baseline} -> {check.candidate}")
    if check.actual_percent_delta is not None:
        values.append(f"{check.actual_percent_delta * 100:+.1f}%")
    elif check.actual_delta is not None:
        values.append(f"delta {check.actual_delta}")
    if check.result == "FAIL" and check.allowed is not None:
        values.append(f"allowed {check.allowed}")
    value = ", ".join(values) if values else _check_evidence(check)
    return f"{check.metric}: {value} ({check.result})"


def _finding_summary(check: RegressionCheck) -> str:
    value = check.candidate if check.candidate is not None else check.result
    return f"{check.metric}={value}"


def _suite_accounting_note(checks: list[RegressionCheck]) -> str | None:
    provider_flat = any(
        check.evidence.get("accounting_source") == "provider_usage"
        and check.actual_percent_delta is not None
        and abs(check.actual_percent_delta) < 0.01
        for check in checks
    )
    component_moved = any(
        check.evidence.get("accounting_source") == "agentperf_component_attribution"
        and check.actual_percent_delta is not None
        and abs(check.actual_percent_delta) >= 0.05
        for check in checks
    )
    if provider_flat and component_moved:
        return (
            "Accounting note: provider-reported usage is unchanged, but "
            "AgentPerf observed component-level context movement."
        )
    return None


def _suite_reason(checks: list[RegressionCheck]) -> str:
    for category in ("QUALITY", "TASK_COVERAGE", "PERFORMANCE", "FINDINGS", "ARTIFACT"):
        for check in checks:
            if check.category == category and check.result == "FAIL":
                return _check_summary(check)
    for check in checks:
        if check.result == "INCONCLUSIVE":
            return _check_summary(check)
    return "no failing detail"


def _proposal_recommendation(status: str) -> str:
    if status == "PASS":
        return "SAFE TO REVIEW: policy checks pass, but baseline replacement still needs review."
    if status == "FAIL":
        return "REVIEW CAREFULLY: the candidate fails at least one configured policy check."
    return "INCONCLUSIVE: required evidence is missing or not comparable."


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteError(str(exc)) from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _parse_simple_yaml(text)
    return _mapping(data, "suite manifest")


def _parse_task_set(data: Any) -> TaskSetSpec:
    values = _mapping(data, "task_set")
    return TaskSetSpec(
        task_set_id=_optional_str(values, "id") or _optional_str(values, "task_set_id"),
        fingerprint=_optional_str(values, "fingerprint"),
    )


def _parse_environment_policy(data: Any) -> SuiteEnvironmentPolicy:
    values = _mapping(data, "environment")
    return SuiteEnvironmentPolicy(
        latency_requires_compatible=_bool(values.get("latency_requires_compatible"), True),
        allow_environment_mismatch=_bool(values.get("allow_environment_mismatch"), False),
    )


def _safe_path(suite_dir: Path, value: str, root: Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        raise SuiteError(f"suite path must be relative: {value}")
    resolved = (suite_dir / raw).resolve()
    if root != resolved and root not in resolved.parents:
        raise SuiteError(f"suite path escapes repository root: {value}")
    return resolved


def _discover_root(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return resolved.parent


def _relative_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _mapping(data: Any, name: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SuiteError(f"{name} must be a mapping")
    return {str(key): value for key, value in data.items()}


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SuiteError(f"{key} must be a non-empty string")
    return value


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise SuiteError(f"{key} must be an integer")
    return value


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SuiteError("boolean suite values must be true or false")
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
            raise SuiteError(f"invalid suite manifest line {line_number}: {raw_line}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
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
