from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import agentperf
from agentperf.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_package_root_import_does_not_require_optional_integrations() -> None:
    assert agentperf.__version__ == "0.4.0"
    assert hasattr(agentperf, "ExperimentSession")
    assert hasattr(agentperf, "trace_llm")


def test_cli_help_lists_demo_command() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "agentperf", "--help"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "demo" in completed.stdout
    assert "doctor" in completed.stdout
    assert "report" in completed.stdout


def test_pyproject_declares_langgraph_as_optional_extra() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional = data["project"]["optional-dependencies"]

    assert "langgraph" in optional
    assert any(requirement.startswith("langgraph") for requirement in optional["langgraph"])
    assert data["project"]["dependencies"] == []


def test_demo_command_rejects_existing_non_empty_output(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    output = tmp_path / "demo"
    output.mkdir()
    (output / "user-file.txt").write_text("keep", encoding="utf-8")

    code = main(["demo", "--output", str(output)])
    captured = capsys.readouterr()

    assert code == 2
    assert "Use --force" in captured.err
