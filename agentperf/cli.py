from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from agentperf.analyzer import analyze_path, analyze_run
from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.comparison import ComparisonError, compare_paths, comparison_to_json
from agentperf.integrations.openai_agents import agent_run_from_openai_agents_export
from agentperf.model_choice import analyze_model_choice_path
from agentperf.reporters.terminal import (
    render_comparison_report,
    render_model_choice_report,
    render_report,
)
from agentperf.schema.trace import TraceParseError

LOGGER = logging.getLogger("agentperf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentperf")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze a normalized AgentPerf trace JSON file",
    )
    analyze.add_argument("trace_path", type=Path)
    analyze.add_argument(
        "--show-provenance",
        action="store_true",
        help="Include raw and derived metric provenance for each finding",
    )
    analyze.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    vllm = subparsers.add_parser(
        "analyze-vllm-recording",
        help="Analyze a recorded vLLM OpenAI-compatible response bundle",
    )
    vllm.add_argument("recording_path", type=Path)
    vllm.add_argument(
        "--show-provenance",
        action="store_true",
        help="Include raw and derived metric provenance for each finding",
    )
    vllm.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    openai_agents = subparsers.add_parser(
        "analyze-openai-agents-export",
        help="Analyze an OpenAI Agents SDK trace export normalized by AgentPerf",
    )
    openai_agents.add_argument("export_path", type=Path)
    openai_agents.add_argument(
        "--show-provenance",
        action="store_true",
        help="Include raw and derived metric provenance for each finding",
    )
    openai_agents.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    model_choice = subparsers.add_parser(
        "analyze-model-choice",
        help="Analyze model-choice counterfactual replay results",
    )
    model_choice.add_argument("comparison_path", type=Path)
    model_choice.add_argument(
        "--show-provenance",
        action="store_true",
        help="Include derived metric provenance for each finding",
    )
    model_choice.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    compare = subparsers.add_parser(
        "compare",
        help="Compare a baseline AgentPerf trace/workload with a replay candidate",
    )
    compare.add_argument("baseline_path", type=Path)
    compare.add_argument("candidate_path", type=Path)
    compare.add_argument(
        "--quality-tolerance",
        type=float,
        default=None,
        help="Allowed mean-score drop, for example 0.05",
    )
    compare.add_argument(
        "--pass-rate-tolerance",
        type=float,
        default=None,
        help="Allowed pass-rate drop, for example 0.10",
    )
    compare.add_argument(
        "--min-material-improvement",
        type=float,
        default=0.05,
        help="Minimum relative token/client-latency improvement for ACCEPT",
    )
    compare.add_argument(
        "--format",
        choices=["terminal", "json"],
        default="terminal",
        help="Output format",
    )
    compare.add_argument("--output", type=Path, help="Write comparison output to a file")
    compare.add_argument(
        "--show-provenance",
        action="store_true",
        help="Include finding scope/provenance details in terminal output",
    )
    compare.add_argument(
        "--fail-on-quality-regression",
        action="store_true",
        help="Return a nonzero exit code when the candidate violates quality constraints",
    )
    compare.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.command == "analyze":
        try:
            report = analyze_path(args.trace_path)
        except (OSError, TraceParseError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write(render_report(report, show_provenance=args.show_provenance))
        sys.stdout.write("\n")
        return 0
    if args.command == "analyze-vllm-recording":
        try:
            data = json.loads(args.recording_path.read_text(encoding="utf-8"))
            run = VLLMTelemetryProvider().build_run(data)
            report = analyze_run(run)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write(render_report(report, show_provenance=args.show_provenance))
        sys.stdout.write("\n")
        return 0
    if args.command == "analyze-openai-agents-export":
        try:
            data = json.loads(args.export_path.read_text(encoding="utf-8"))
            run = agent_run_from_openai_agents_export(data)
            report = analyze_run(run)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write(render_report(report, show_provenance=args.show_provenance))
        sys.stdout.write("\n")
        return 0
    if args.command == "analyze-model-choice":
        try:
            model_choice_report = analyze_model_choice_path(args.comparison_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write(
            render_model_choice_report(
                model_choice_report,
                show_provenance=args.show_provenance,
            )
        )
        sys.stdout.write("\n")
        return 0
    if args.command == "compare":
        try:
            comparison = compare_paths(
                args.baseline_path,
                args.candidate_path,
                mean_score_tolerance=args.quality_tolerance,
                pass_rate_tolerance=args.pass_rate_tolerance,
                min_material_improvement=args.min_material_improvement,
            )
        except (OSError, ComparisonError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        output = (
            comparison_to_json(comparison)
            if args.format == "json"
            else render_comparison_report(comparison, show_provenance=args.show_provenance)
        )
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            sys.stdout.write(output)
            sys.stdout.write("\n")
        if (
            args.fail_on_quality_regression
            and comparison.acceptance_result.verdict == "REJECT_QUALITY_REGRESSION"
        ):
            return 1
        return 0
    return 2
