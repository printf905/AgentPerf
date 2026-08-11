from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agentperf.analyzer import analyze_run
from agentperf.artifacts import ExperimentArtifact
from agentperf.instrumentation import TraceRecorder
from agentperf.integrations.mini_swe_agent import (
    AgentPerfMiniSweEnvironmentWrapper,
    AgentPerfMiniSweModelWrapper,
)
from agentperf.reporters.terminal import render_report
from agentperf.schema.artifacts import QualityMetric, TaskResult

try:
    import yaml
    from minisweagent import package_dir
    from minisweagent.agents.default import DefaultAgent
    from minisweagent.environments.local import LocalEnvironment
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.models.test_models import DeterministicModel, make_output
except ImportError as exc:  # pragma: no cover - optional dependency boundary
    raise SystemExit(
        "Install the optional external-agent dependency first: "
        'pip install -e ".[mini-swe-agent]"'
    ) from exc


TASKS = [
    {
        "id": "calc-add",
        "instruction": "Fix the failing calculator addition behavior. Do not change tests.",
        "files": {
            "calculator.py": "def add(a: int, b: int) -> int:\n    return a - b\n",
            "test_calculator.py": (
                "from calculator import add\n\n"
                "def test_add_positive_numbers():\n"
                "    assert add(2, 3) == 5\n"
            ),
        },
        "patch_command": (
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "path = Path('calculator.py')\n"
            "path.write_text('def add(a: int, b: int) -> int:\\n    return a + b\\n')\n"
            "PY"
        ),
    },
    {
        "id": "strings-slug",
        "instruction": "Fix slugify so the included tests pass. Do not change tests.",
        "files": {
            "strings.py": (
                "def slugify(value: str) -> str:\n"
                "    return value.strip().replace(' ', '_').lower()\n"
            ),
            "test_strings.py": (
                "from strings import slugify\n\n"
                "def test_slugify_uses_hyphens():\n"
                "    assert slugify('Hello Agent Perf') == 'hello-agent-perf'\n"
            ),
        },
        "patch_command": (
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "path = Path('strings.py')\n"
            "path.write_text(\"def slugify(value: str) -> str:\\n"
            "    return '-'.join(value.strip().lower().split())\\n\")\n"
            "PY"
        ),
    },
    {
        "id": "inventory-total",
        "instruction": "Fix total_quantity so it returns the sum of item quantities.",
        "files": {
            "inventory.py": (
                "def total_quantity(items: list[dict[str, int]]) -> int:\n"
                "    return len(items)\n"
            ),
            "test_inventory.py": (
                "from inventory import total_quantity\n\n"
                "def test_total_quantity_sums_quantities():\n"
                "    assert total_quantity([{'qty': 2}, {'qty': 5}]) == 7\n"
            ),
        },
        "patch_command": (
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "path = Path('inventory.py')\n"
            "path.write_text(\"def total_quantity(items: list[dict[str, int]]) -> int:\\n"
            "    return sum(item.get('qty', 0) for item in items)\\n\")\n"
            "PY"
        ),
    },
    {
        "id": "dates-window",
        "instruction": "Fix is_within_window so inclusive boundary dates pass.",
        "files": {
            "dates.py": (
                "from datetime import date\n\n"
                "def is_within_window(day: date, start: date, end: date) -> bool:\n"
                "    return start < day < end\n"
            ),
            "test_dates.py": (
                "from datetime import date\n"
                "from dates import is_within_window\n\n"
                "def test_window_is_inclusive():\n"
                "    assert is_within_window(\n"
                "        date(2026, 8, 10), date(2026, 8, 10), date(2026, 8, 12)\n"
                "    )\n"
            ),
        },
        "patch_command": (
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "path = Path('dates.py')\n"
            "path.write_text(\"from datetime import date\\n\\n"
            "def is_within_window(day: date, start: date, end: date) -> bool:\\n"
            "    return start <= day <= end\\n\")\n"
            "PY"
        ),
    },
    {
        "id": "parser-empty",
        "instruction": "Fix parse_tags so empty fields are ignored.",
        "files": {
            "parser.py": (
                "def parse_tags(value: str) -> list[str]:\n"
                "    return [part.strip() for part in value.split(',')]\n"
            ),
            "test_parser.py": (
                "from parser import parse_tags\n\n"
                "def test_parse_tags_ignores_empty_fields():\n"
                "    assert parse_tags('alpha, , beta,,') == ['alpha', 'beta']\n"
            ),
        },
        "patch_command": (
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "path = Path('parser.py')\n"
            "path.write_text(\"def parse_tags(value: str) -> list[str]:\\n"
            "    return [part.strip() for part in value.split(',') if part.strip()]\\n\")\n"
            "PY"
        ),
    },
]


def run(output_dir: Path, *, mode: str, model_name: str | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    tasks_root = output_dir / "repos"
    if tasks_root.exists():
        shutil.rmtree(tasks_root)
    tasks_root.mkdir()
    results: list[dict[str, Any]] = []
    recorder = TraceRecorder(
        agent_run_id=f"m7-mini-swe-agent-{mode}",
        name="mini-SWE-agent repository repair",
        metadata={
            "framework": "mini-swe-agent",
            "workload": "small repository repair",
            "task_count": len(TASKS),
            "mode": mode,
        },
    )

    with recorder.as_current():
        for task in TASKS:
            task_dir = tasks_root / str(task["id"])
            _write_task_repo(task_dir, task)
            with recorder.step(f"task-{task['id']}", metadata={"task_id": task["id"]}):
                result = _run_one_task(
                    task,
                    task_dir,
                    recorder,
                    mode=mode,
                    model_name=model_name,
                )
            results.append(result)

    run_data = recorder.finish()
    report = analyze_run(run_data)
    recorder.write_json(output_dir / "agentperf_trace.json")
    (output_dir / "agentperf_report.txt").write_text(render_report(report), encoding="utf-8")
    pass_rate = sum(1 for item in results if item["passed"]) / len(results)
    summary = {
        "agent": "mini-SWE-agent DefaultAgent",
        "mode": mode,
        "tasks": len(TASKS),
        "llm_calls": len(run_data.llm_calls),
        "tool_calls": len(run_data.tool_calls),
        "passed": sum(1 for item in results if item["passed"]),
        "pass_rate": pass_rate,
        "input_tokens": sum(call.input_tokens or 0 for call in run_data.llm_calls),
        "output_tokens": sum(call.output_tokens or 0 for call in run_data.llm_calls),
        "findings": [finding.id for finding in report.findings],
        "task_results": results,
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    ExperimentArtifact.from_analysis(
        report,
        artifact_id=f"m7-mini-swe-agent-{mode}",
        workload_id=f"m7-mini-swe-agent-{mode}",
        task_results=[
            TaskResult(
                task_id=str(item["task_id"]),
                passed=bool(item["passed"]),
                quality_score=1.0 if item["passed"] else 0.0,
                evaluator="local-tests-pass",
                agent_run_ids=[run_data.agent_run_id],
                metadata={"mode": mode},
            )
            for item in results
        ],
        quality_metrics=[
            QualityMetric(
                name="pass_rate",
                value=pass_rate,
                aggregation="rate",
            ),
            QualityMetric(
                name="mean_score",
                value=pass_rate,
                aggregation="mean_pass_indicator",
            ),
        ],
        environment={
            "framework": "mini-swe-agent",
            "backend": "deterministic" if mode == "deterministic" else "configured-model",
            "serving_telemetry": False,
        },
        summary=summary,
        framework="mini-swe-agent",
        agent_name="mini-SWE-agent DefaultAgent",
        backend="deterministic" if mode == "deterministic" else "configured-model",
        model=model_name or mode,
        serving_telemetry=False,
    ).save(output_dir / "agentperf_artifact")
    print(render_report(report))


def _run_one_task(
    task: dict[str, Any],
    task_dir: Path,
    recorder: TraceRecorder,
    *,
    mode: str,
    model_name: str | None,
) -> dict[str, Any]:
    env = AgentPerfMiniSweEnvironmentWrapper(
        LocalEnvironment(cwd=str(task_dir), timeout=30),
        recorder,
        tool_call_id_prefix=f"mini-swe-{task['id']}-tool",
    )
    model = AgentPerfMiniSweModelWrapper(
        _build_model(task, mode=mode, model_name=model_name),
        recorder,
        tool_output_lookup=env.tool_call_ids_for_observation,
        call_id_prefix=f"mini-swe-{task['id']}-llm",
    )
    agent_config = yaml.safe_load(Path(package_dir / "config" / "default.yaml").read_text())[
        "agent"
    ]
    agent_config = {
        **agent_config,
        "step_limit": 8,
        "cost_limit": 0,
        "output_path": task_dir / "mini_swe_trajectory.json",
    }
    agent = DefaultAgent(model, env, **agent_config)
    exit_info = agent.run(str(task["instruction"]))
    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=task_dir,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    return {
        "task_id": task["id"],
        "exit_status": exit_info.get("exit_status"),
        "submission": exit_info.get("submission", ""),
        "passed": test_result.returncode == 0,
        "test_output": test_result.stdout,
    }


def _build_model(task: dict[str, Any], *, mode: str, model_name: str | None) -> Any:
    if mode == "litellm":
        if model_name is None:
            raise SystemExit("--model-name is required with --mode litellm")
        return LitellmModel(
            model_name=model_name,
            cost_tracking="ignore_errors",
            model_kwargs={"temperature": 0, "max_tokens": 512},
        )
    return DeterministicModel(outputs=_deterministic_outputs(task))


def _deterministic_outputs(task: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        make_output("Inspect the repository.", [{"command": "ls -la"}], cost=0.0),
        make_output("Read the failing test.", [{"command": "sed -n '1,220p' test_*.py"}], cost=0.0),
        make_output("Read the implementation.", [{"command": "sed -n '1,220p' *.py"}], cost=0.0),
        make_output(
            "Apply the minimal fix.",
            [{"command": _with_active_python(str(task["patch_command"]))}],
            cost=0.0,
        ),
        make_output(
            "Run the test suite.",
            [{"command": f"{sys.executable} -m pytest -q"}],
            cost=0.0,
        ),
        make_output(
            "Submit final result.",
            [{"command": "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\nfixed\\n'"}],
            cost=0.0,
        ),
    ]


def _write_task_repo(task_dir: Path, task: dict[str, Any]) -> None:
    task_dir.mkdir(parents=True)
    for relative_path, content in task["files"].items():
        path = task_dir / str(relative_path)
        path.write_text(str(content), encoding="utf-8")


def _with_active_python(command: str) -> str:
    return command.replace("python - <<'PY'", f"{sys.executable} - <<'PY'", 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["deterministic", "litellm"], default="deterministic")
    parser.add_argument("--model-name")
    args = parser.parse_args(argv)
    run(args.output_dir, mode=args.mode, model_name=args.model_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
