from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from agentperf.analyzer import analyze_path, analyze_run
from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.integrations.openai_agents import agent_run_from_openai_agents_export
from agentperf.model_choice import analyze_model_choice_path
from agentperf.reporters.terminal import render_model_choice_report, render_report
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
    return 2
