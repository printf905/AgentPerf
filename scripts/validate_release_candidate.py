from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ValidationCommand:
    name: str
    argv: list[str]
    timeout: int = 600


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run AgentPerf's deterministic local release-candidate validation corpus. "
            "This helper does not publish, tag, create releases, use GPUs, or call model APIs."
        )
    )
    parser.add_argument("--version", default="0.5.0", help="Expected package version.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/private/tmp/agentperf-release-validation"),
        help="Directory for generated local validation artifacts.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    for command in _commands(args.version, args.output_dir):
        print(f"== {command.name}")
        completed = subprocess.run(
            command.argv,
            cwd=ROOT,
            check=False,
            text=True,
            timeout=command.timeout,
        )
        if completed.returncode != 0:
            failures.append(command.name)
            print(f"FAILED: {command.name}", file=sys.stderr)
            break
        print("PASS")

    if failures:
        print(f"Release validation failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("Release validation PASS")
    return 0


def _commands(expected_version: str, output_dir: Path) -> list[ValidationCommand]:
    py = sys.executable
    commands = [
        ValidationCommand(
            "package version",
            [
                py,
                str(Path("scripts") / "validate_release_candidate.py"),
                "--version-check-only",
                expected_version,
            ],
            timeout=60,
        ),
        ValidationCommand("pytest", [py, "-m", "pytest"], timeout=900),
        ValidationCommand("ruff", [py, "-m", "ruff", "check", "."], timeout=300),
        ValidationCommand("mypy", [py, "-m", "mypy", "agentperf", "tests", "scripts"], timeout=600),
        ValidationCommand("build", [py, "-m", "build"], timeout=600),
        ValidationCommand(
            "twine",
            [py, str(Path("scripts") / "validate_release_candidate.py"), "--twine-check-only"],
            timeout=300,
        ),
        ValidationCommand(
            "deterministic release-candidate corpus",
            [
                py,
                str(Path("scripts") / "release_candidate_corpus.py"),
                "--output-dir",
                str(output_dir / "corpus"),
            ],
            timeout=600,
        ),
    ]
    commands.extend(_langgraph_commands(output_dir))
    return commands


def _dist_files() -> list[Path]:
    files = sorted(str(path) for path in (ROOT / "dist").glob("agentperf-0.5.0*"))
    if not files:
        raise SystemExit("no dist/agentperf-0.5.0* files found after build")
    return [Path(path) for path in files]


def _twine_check() -> int:
    files = [str(path) for path in _dist_files()]
    return subprocess.run(
        [sys.executable, "-m", "twine", "check", *files],
        cwd=ROOT,
        check=False,
        text=True,
    ).returncode


def _langgraph_commands(output_dir: Path) -> list[ValidationCommand]:
    if importlib.util.find_spec("langgraph") is None:
        return [
            ValidationCommand(
                "LangGraph optional extra",
                [sys.executable, "-c", "print('SKIP: langgraph not installed')"],
                timeout=60,
            )
        ]
    py = sys.executable
    langgraph_root = output_dir / "langgraph"
    return [
        ValidationCommand(
            "LangGraph raw",
            [
                py,
                str(Path("examples") / "langgraph_agent" / "run.py"),
                "--variant",
                "raw",
                "--output-root",
                str(langgraph_root),
            ],
            timeout=300,
        ),
        ValidationCommand(
            "LangGraph optimized",
            [
                py,
                str(Path("examples") / "langgraph_agent" / "run.py"),
                "--variant",
                "optimized",
                "--output-root",
                str(langgraph_root),
            ],
            timeout=300,
        ),
        ValidationCommand(
            "LangGraph compare",
            [
                py,
                "-m",
                "agentperf",
                "compare",
                str(langgraph_root / "raw"),
                str(langgraph_root / "optimized"),
            ],
            timeout=300,
        ),
    ]


def _version_check(expected_version: str) -> int:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        pyproject_version = tomllib.load(fh)["project"]["version"]
    import agentperf

    if pyproject_version != expected_version:
        print(
            f"pyproject version {pyproject_version!r} does not match {expected_version!r}",
            file=sys.stderr,
        )
        return 1
    if agentperf.__version__ != expected_version:
        print(
            f"agentperf.__version__ {agentperf.__version__!r} does not match {expected_version!r}",
            file=sys.stderr,
        )
        return 1
    print(f"Package version {expected_version}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--version-check-only":
        raise SystemExit(_version_check(sys.argv[2]))
    if len(sys.argv) == 2 and sys.argv[1] == "--twine-check-only":
        raise SystemExit(_twine_check())
    raise SystemExit(main())
