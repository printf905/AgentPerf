from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CorpusCommand:
    name: str
    argv: list[str]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the deterministic no-GPU/no-API AgentPerf release-candidate corpus. "
            "This is a maintainer validation helper, not a product CLI."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/private/tmp/agentperf-release-corpus"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    commands = _commands(args.output_dir)
    failures: list[str] = []
    for command in commands:
        print(f"== {command.name}")
        completed = subprocess.run(
            command.argv,
            cwd=ROOT,
            check=False,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if completed.returncode != 0:
            failures.append(command.name)
            print(completed.stdout)
            print(completed.stderr, file=sys.stderr)
        else:
            print("PASS")
    if failures:
        print(f"FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("Release-candidate corpus PASS")
    return 0


def _commands(output_dir: Path) -> list[CorpusCommand]:
    py = sys.executable
    demo_dir = output_dir / "demo"
    byoa_dir = output_dir / "byoa"
    return [
        CorpusCommand(
            "demo",
            [py, "-m", "agentperf", "demo", "--output", str(demo_dir), "--force"],
        ),
        CorpusCommand(
            "demo doctor",
            [py, "-m", "agentperf", "doctor", str(demo_dir / "baseline")],
        ),
        CorpusCommand(
            "demo report",
            [
                py,
                "-m",
                "agentperf",
                "report",
                str(demo_dir / "baseline"),
                "--output",
                str(output_dir / "demo-report.html"),
            ],
        ),
        CorpusCommand(
            "demo compare",
            [
                py,
                "-m",
                "agentperf",
                "compare",
                str(demo_dir / "baseline"),
                str(demo_dir / "candidate"),
            ],
        ),
        CorpusCommand(
            "demo check",
            [
                py,
                "-m",
                "agentperf",
                "check",
                str(demo_dir / "baseline"),
                str(demo_dir / "candidate"),
                "--policy",
                str(demo_dir / "agentperf-regression.yaml"),
            ],
        ),
        CorpusCommand(
            "M3 compare",
            [
                py,
                "-m",
                "agentperf",
                "compare",
                "examples/artifacts/m3_raw_full",
                "examples/artifacts/m3_dedup_only",
            ],
        ),
        CorpusCommand(
            "M3 check",
            [
                py,
                "-m",
                "agentperf",
                "check",
                "examples/artifacts/m3_raw_full",
                "examples/artifacts/m3_dedup_only",
                "--policy",
                "examples/policies/m3-context-regression.yaml",
            ],
        ),
        CorpusCommand(
            "M3 comparison HTML",
            [
                py,
                "-m",
                "agentperf",
                "compare",
                "examples/artifacts/m3_raw_full",
                "examples/artifacts/m3_dedup_only",
                "--format",
                "html",
                "--output",
                str(output_dir / "m3-comparison.html"),
            ],
        ),
        CorpusCommand(
            "M3 suite validate",
            [py, "-m", "agentperf", "suite", "validate", "examples/benchmark_suites/m3_context"],
        ),
        CorpusCommand(
            "M3 suite check",
            [
                py,
                "-m",
                "agentperf",
                "suite",
                "check",
                "examples/benchmark_suites/m3_context",
                "examples/artifacts/m3_dedup_only",
            ],
        ),
        CorpusCommand(
            "BYOA raw",
            [
                py,
                "examples/bring_your_own_agent/run.py",
                "--variant",
                "raw",
                "--output-root",
                str(byoa_dir),
            ],
        ),
        CorpusCommand(
            "BYOA optimized",
            [
                py,
                "examples/bring_your_own_agent/run.py",
                "--variant",
                "optimized",
                "--output-root",
                str(byoa_dir),
            ],
        ),
        CorpusCommand(
            "BYOA compare",
            [py, "-m", "agentperf", "compare", str(byoa_dir / "raw"), str(byoa_dir / "optimized")],
        ),
        CorpusCommand(
            "M25 model-choice",
            [
                py,
                "-m",
                "agentperf",
                "analyze-model-choice",
                "docs/data/m25_phase_b/model_choice_phase_b_comparison.json",
            ],
        ),
        CorpusCommand(
            "vLLM fixture",
            [
                py,
                "-m",
                "agentperf",
                "analyze-vllm-recording",
                "examples/recorded_telemetry/vllm_openai_response_fixture.json",
            ],
        ),
        CorpusCommand(
            "SGLang fixture",
            [
                py,
                "-m",
                "agentperf",
                "analyze-sglang-recording",
                "examples/recorded_telemetry/sglang_openai_response_fixture.json",
            ],
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
