from __future__ import annotations

from pathlib import Path

from agentperf.analyzer import analyze_path
from agentperf.cli import main
from agentperf.reporters.terminal import render_report

ROOT = Path(__file__).resolve().parents[1]


def test_terminal_report_includes_synthetic_label_and_findings() -> None:
    report = analyze_path(ROOT / "examples/traces/multi_problem_agent.json")
    output = render_report(report)

    assert "Data: synthetic trace fixture, not benchmark results" in output
    assert "[LOW] CACHEABILITY_HEADROOM" in output
    assert "Validation:" in output


def test_cli_analyze_success(capsys) -> None:  # type: ignore[no-untyped-def]
    code = main(["analyze", str(ROOT / "examples/traces/healthy_agent.json")])

    captured = capsys.readouterr()
    assert code == 0
    assert "AgentPerf Report" in captured.out
    assert "No high-confidence MVP findings." in captured.out


def test_cli_reports_malformed_trace(tmp_path, capsys) -> None:  # type: ignore[no-untyped-def]
    trace = tmp_path / "bad.json"
    trace.write_text('{"agent_run": {"steps": []}}', encoding="utf-8")

    code = main(["analyze", str(trace)])

    captured = capsys.readouterr()
    assert code == 2
    assert "missing required field" in captured.err
