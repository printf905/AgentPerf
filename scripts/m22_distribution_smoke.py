from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import venv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SmokeResult:
    command: list[str]
    returncode: int
    stdout_preview: str = ""
    stderr_preview: str = ""


@dataclass
class SmokeSummary:
    wheel: str
    workdir: str
    venv: str
    results: list[SmokeResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "wheel": self.wheel,
            "workdir": self.workdir,
            "venv": self.venv,
            "results": [
                {
                    "command": result.command,
                    "returncode": result.returncode,
                    "stdout_preview": result.stdout_preview,
                    "stderr_preview": result.stderr_preview,
                }
                for result in self.results
            ],
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test a built AgentPerf wheel from outside the source checkout."
    )
    parser.add_argument("--wheel", type=Path, default=None, help="Path to built AgentPerf wheel")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON summary path")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the temporary virtualenv and working directory for inspection",
    )
    args = parser.parse_args()

    wheel = args.wheel or _latest_wheel(Path("dist"))
    if not wheel.exists():
        raise SystemExit(f"wheel not found: {wheel}")

    temp_root = Path(tempfile.mkdtemp(prefix="agentperf-m22-smoke-"))
    venv_path = temp_root / "venv"
    workdir = temp_root / "work"
    workdir.mkdir()
    summary = SmokeSummary(wheel=str(wheel.resolve()), workdir=str(workdir), venv=str(venv_path))
    try:
        venv.EnvBuilder(with_pip=True).create(venv_path)
        python = _venv_bin(venv_path, "python")
        agentperf = _venv_bin(venv_path, "agentperf")
        _run(summary, [python, "-m", "pip", "install", str(wheel.resolve())], cwd=workdir)
        _run(summary, [agentperf, "--help"], cwd=workdir)
        _run(summary, [agentperf, "demo", "--output", "demo", "--force"], cwd=workdir)
        _run(summary, [agentperf, "doctor", "demo/baseline"], cwd=workdir)
        _run(
            summary,
            [agentperf, "report", "demo/baseline", "--output", "demo/report.html"],
            cwd=workdir,
        )
        _run(summary, [agentperf, "compare", "demo/baseline", "demo/candidate"], cwd=workdir)
        _run(
            summary,
            [
                agentperf,
                "check",
                "demo/baseline",
                "demo/candidate",
                "--policy",
                "demo/agentperf-regression.yaml",
            ],
            cwd=workdir,
        )
    finally:
        if args.output is not None:
            args.output.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
        if not args.keep:
            shutil.rmtree(temp_root)

    print("AgentPerf M22 distribution smoke passed")
    return 0


def _run(summary: SmokeSummary, command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    summary.results.append(
        SmokeResult(
            command=command,
            returncode=completed.returncode,
            stdout_preview=completed.stdout[:1000],
            stderr_preview=completed.stderr[:1000],
        )
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}\n"
            f"{completed.stderr}"
        )


def _latest_wheel(dist_dir: Path) -> Path:
    wheels = sorted(dist_dir.glob("agentperf-*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        raise SystemExit("no AgentPerf wheel found under dist/")
    return wheels[-1]


def _venv_bin(venv_path: Path, command: str) -> str:
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    return str(venv_path / bin_dir / command)


if __name__ == "__main__":
    raise SystemExit(main())
