from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

from agentperf.benchmark_suites import (
    check_all_suites,
    check_suite,
    load_suite,
    parse_suite_manifest,
    propose_baseline,
    render_baseline_proposal,
    render_check_all,
    task_set_fingerprint,
    validate_suite,
)
from agentperf.cli import main
from agentperf.regression import load_regression_policy


def test_suite_manifest_parsing() -> None:
    manifest = parse_suite_manifest(
        {
            "schema_version": 1,
            "suite_id": "fixture-suite",
            "suite_version": 2,
            "baseline_artifact": "baseline",
            "regression_policy": "policy.yaml",
            "task_set": {"id": "tasks-v1", "fingerprint": "abc"},
            "quality_metrics": {"mean_score": True, "pass_rate": True},
        }
    )

    assert manifest.suite_id == "fixture-suite"
    assert manifest.suite_version == 2
    assert manifest.task_set.task_set_id == "tasks-v1"
    assert manifest.quality_metrics == ["mean_score", "pass_rate"]


def test_invalid_manifest_fails() -> None:
    try:
        parse_suite_manifest({"schema_version": 99})
    except ValueError as exc:
        assert "unsupported suite schema_version" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected manifest error")


def test_validate_real_m3_suite_passes() -> None:
    result = validate_suite(Path("examples/benchmark_suites/m3_context"))

    assert result.status == "PASS"
    assert result.suite_id == "m3-context-waste"


def test_m3_real_artifact_suite_check_passes() -> None:
    result = check_suite(
        Path("examples/benchmark_suites/m3_context"),
        Path("examples/artifacts/m3_dedup_only"),
    )

    assert result.status == "PASS"
    assert result.regression.status == "PASS"


def test_openai_agents_dogfooding_suite_check_passes() -> None:
    validation = validate_suite(Path("benchmarks/openai-agents-support-triage"))
    result = check_suite(
        Path("benchmarks/openai-agents-support-triage"),
        Path("examples/dogfooding/openai_agents_support_triage_compact"),
    )

    assert validation.status == "PASS"
    assert result.status == "PASS"
    assert result.regression.status == "PASS"


def test_synthetic_suite_passes_and_fingerprint_matches() -> None:
    suite = load_suite(Path("examples/benchmark_suites/synthetic_replay"))
    result = check_suite(suite.path, suite.path / "candidate")
    baseline = _load_baseline_artifact(suite.path)

    assert result.status == "PASS"
    assert task_set_fingerprint(baseline) == (
        "7afaa346b4bf92bf9dc21e9ae809887412a86beb766842e99df7fee6573a4781"
    )


def test_missing_baseline_and_policy_are_validation_failures(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "suite.yaml").write_text(
        """
schema_version: 1
suite_id: missing-suite
baseline_artifact: missing-baseline
regression_policy: missing-policy.yaml
""",
        encoding="utf-8",
    )

    result = validate_suite(suite)

    assert result.status == "FAIL"
    assert {
        check.metric
        for check in result.checks
        if check.result == "FAIL"
    } == {"baseline_artifact", "regression_policy"}


def test_path_traversal_is_rejected(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "suite.yaml").write_text(
        """
schema_version: 1
suite_id: escape-suite
baseline_artifact: ../../outside
regression_policy: policy.yaml
""",
        encoding="utf-8",
    )

    result = validate_suite(suite)

    assert result.status == "FAIL"
    assert "escapes" in result.checks[0].evidence["error"]


def test_baseline_incomplete_fails_validation(tmp_path: Path) -> None:
    suite = _copy_synthetic_suite(tmp_path)
    manifest = _read_json(suite / "baseline" / "manifest.json")
    manifest["status"] = "PARTIAL"
    _write_json(suite / "baseline" / "manifest.json", manifest)

    result = validate_suite(suite)

    assert result.status == "FAIL"
    assert any(check.metric == "baseline_complete" for check in result.checks)


def test_task_fingerprint_mismatch_fails_suite_check(tmp_path: Path) -> None:
    suite = _copy_synthetic_suite(tmp_path)
    tasks = _read_json(suite / "candidate" / "tasks.json")
    tasks["tasks"][0]["task_id"] = "task-2"
    _write_json(suite / "candidate" / "tasks.json", tasks)
    trace = _read_json(suite / "candidate" / "trace.json")
    trace["runs"][0]["agent_run"]["metadata"]["task_id"] = "task-2"
    _write_json(suite / "candidate" / "trace.json", trace)

    result = check_suite(suite, suite / "candidate")

    assert result.status == "FAIL"
    assert any(
        check.metric == "candidate_task_set_fingerprint" and check.result == "FAIL"
        for check in result.regression.checks
    )


def test_environment_mismatch_makes_latency_policy_inconclusive(tmp_path: Path) -> None:
    suite = _copy_synthetic_suite(tmp_path)
    policy = _read_json_policy_like(suite / "policy.yaml")
    policy["performance"]["client_latency_p95"] = {"max_increase_percent": 20}
    _write_json(suite / "policy.yaml", policy)
    suite_manifest = _read_json_policy_like(suite / "suite.yaml")
    suite_manifest["environment"] = {
        "latency_requires_compatible": True,
        "allow_environment_mismatch": False,
    }
    _write_json(suite / "suite.yaml", suite_manifest)
    candidate_env = _read_json(suite / "candidate" / "environment.json")
    candidate_env["gpu"] = "different gpu"
    _write_json(suite / "candidate" / "environment.json", candidate_env)
    baseline_env = _read_json(suite / "baseline" / "environment.json")
    baseline_env["gpu"] = "baseline gpu"
    _write_json(suite / "baseline" / "environment.json", baseline_env)

    result = check_suite(suite, suite / "candidate")

    assert result.status == "INCONCLUSIVE"
    assert any(check.category == "ENVIRONMENT" for check in result.regression.checks)


def test_check_all_reports_missing_candidate(tmp_path: Path) -> None:
    suites_root = tmp_path / "suites"
    suite = _copy_synthetic_suite(suites_root, name="synthetic_replay")
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    assert suite.exists()

    result = check_all_suites(suites_root, candidates)

    assert result.status == "FAIL"
    assert result.missing_candidates == ["synthetic-replay"]
    terminal = render_check_all(result)
    markdown = render_check_all(result, markdown=True)
    assert "missing candidate" in terminal
    assert "Failed/Inconclusive Suites" in terminal
    assert "### Triage" in markdown


def test_baseline_proposal_is_review_only(tmp_path: Path) -> None:
    suite = _copy_synthetic_suite(tmp_path)
    before = (suite / "suite.yaml").read_text(encoding="utf-8")

    proposal = propose_baseline(suite, suite / "candidate")
    markdown = render_baseline_proposal(proposal)

    assert "Baseline Update Proposal" in markdown
    assert "does not replace the baseline" in markdown
    assert (suite / "suite.yaml").read_text(encoding="utf-8") == before


def test_cli_suite_exit_codes_and_markdown(tmp_path: Path) -> None:
    suite = _copy_synthetic_suite(tmp_path)
    output = tmp_path / "suite.md"

    validate_code = main(["suite", "validate", str(suite)])
    check_code = main(
        [
            "suite",
            "check",
            str(suite),
            str(suite / "candidate"),
            "--format",
            "markdown",
            "--output",
            str(output),
        ]
    )

    assert validate_code == 0
    assert check_code == 0
    assert "AgentPerf Suite Check" in output.read_text(encoding="utf-8")


def test_cli_suite_json_and_failed_candidate(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    suite = _copy_synthetic_suite(tmp_path)
    manifest = _read_json(suite / "candidate" / "manifest.json")
    manifest["status"] = "FAILED"
    _write_json(suite / "candidate" / "manifest.json", manifest)

    code = main(
        [
            "suite",
            "check",
            str(suite),
            str(suite / "candidate"),
            "--format",
            "json",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 1
    assert output["status"] == "FAIL"


def test_policy_load_still_works_for_suite_policy() -> None:
    policy = load_regression_policy(Path("examples/benchmark_suites/synthetic_replay/policy.yaml"))

    assert "mean_score" in policy.quality


def _copy_synthetic_suite(tmp_path: Path, *, name: str = "suite") -> Path:
    target = tmp_path / name
    shutil.copytree(Path("examples/benchmark_suites/synthetic_replay"), target)
    return target


def _load_baseline_artifact(suite: Path) -> Any:
    from agentperf.artifacts import load_artifact

    return load_artifact(suite / "baseline")


def _read_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json_policy_like(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, value = raw.strip().split(":", 1)
        while indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value.strip():
            scalar: Any
            raw_value = value.strip()
            if raw_value in {"true", "false"}:
                scalar = raw_value == "true"
            else:
                try:
                    scalar = int(raw_value)
                except ValueError:
                    try:
                        scalar = float(raw_value)
                    except ValueError:
                        scalar = raw_value
            parent[key] = scalar
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return result
