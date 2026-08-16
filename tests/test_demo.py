from __future__ import annotations

import json
from pathlib import Path

from agentperf.artifacts import load_artifact
from agentperf.cli import main
from agentperf.comparison import compare_paths
from agentperf.demo import run_demo


def test_demo_creates_real_artifacts_report_policy_and_accepts_replay(tmp_path: Path) -> None:
    result = run_demo(tmp_path / "demo")

    assert result.baseline_path.exists()
    assert result.candidate_path.exists()
    assert result.report_path.exists()
    assert result.comparison_report_path.exists()
    assert result.policy_path.exists()
    assert result.comparison.acceptance_result.verdict == "ACCEPT"
    assert result.regression_status == "PASS"

    baseline = load_artifact(result.baseline_path)
    candidate = load_artifact(result.candidate_path)

    assert baseline.manifest.status == "COMPLETE"
    assert candidate.manifest.status == "COMPLETE"
    assert len(baseline.task_results) == 3
    assert all(task.quality_score == 1.0 for task in baseline.task_results)
    assert baseline.summary["llm_calls"] == 9
    assert baseline.summary["tool_calls"] == 3
    assert "TOOL_OUTPUT_BLOAT" in baseline.summary["findings"]
    assert "TOOL_OUTPUT_BLOAT" not in candidate.summary["findings"]


def test_demo_cli_runs_from_non_repo_cwd(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)

    code = main(["demo", "--output", "demo"])
    output = capsys.readouterr().out

    assert code == 0
    assert "AgentPerf Demo" in output
    assert "comparison verdict             ACCEPT" in output
    assert (tmp_path / "demo" / "baseline").exists()
    assert (tmp_path / "demo" / "candidate").exists()
    assert (tmp_path / "demo" / "baseline-report.html").exists()
    assert (tmp_path / "demo" / "comparison.html").exists()


def test_demo_cli_json_output_is_machine_readable(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["demo", "--output", str(tmp_path / "demo"), "--format", "json"])
    data = json.loads(capsys.readouterr().out)

    assert code == 0
    assert data["comparison_verdict"] == "ACCEPT"
    assert data["regression_status"] == "PASS"
    assert data["token_deltas"]["component_tool_result_processed_tokens"]["candidate"] < (
        data["token_deltas"]["component_tool_result_processed_tokens"]["baseline"]
    )


def test_demo_refuses_to_overwrite_non_empty_directory_without_force(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    output.mkdir()
    (output / "user-file.txt").write_text("do not replace", encoding="utf-8")

    try:
        run_demo(output)
    except FileExistsError as exc:
        assert "Use --force" in str(exc)
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("demo should refuse to overwrite a non-empty directory")


def test_demo_force_replaces_previous_demo_output(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    output.mkdir()
    (output / "old.txt").write_text("replace me", encoding="utf-8")

    result = run_demo(output, force=True)

    assert result.baseline_path.exists()
    assert not (output / "old.txt").exists()


def test_demo_artifacts_remain_comparable_after_load(tmp_path: Path) -> None:
    result = run_demo(tmp_path / "demo")
    comparison = compare_paths(result.baseline_path, result.candidate_path)

    assert comparison.acceptance_result.verdict == "ACCEPT"
    assert any(change.finding_id == "TOOL_OUTPUT_BLOAT" for change in comparison.finding_changes)
