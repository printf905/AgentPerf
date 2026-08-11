from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from agentperf.analyzer import analyze_path, analyze_run
from agentperf.artifacts import ArtifactError, analyze_artifact, inspect_artifact, is_artifact_path
from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.benchmark_suites import (
    SuiteError,
    baseline_proposal_to_dict,
    check_all_suites,
    check_suite,
    propose_baseline,
    render_baseline_proposal,
    render_check_all,
    render_suite_check,
    render_suite_validation,
    suite_check_to_dict,
    suite_collection_to_dict,
    suite_result_exit_code,
    suite_validation_to_dict,
    validate_suite,
)
from agentperf.comparison import ComparisonError, compare_paths, comparison_to_json
from agentperf.integrations.openai_agents import agent_run_from_openai_agents_export
from agentperf.model_choice import analyze_model_choice_path
from agentperf.regression import (
    RegressionPolicyError,
    evaluate_regression_policy,
    load_regression_policy,
    regression_exit_code,
    regression_result_to_json,
)
from agentperf.reporters.html import write_html_report
from agentperf.reporters.terminal import (
    render_comparison_report,
    render_model_choice_report,
    render_regression_markdown,
    render_regression_report,
    render_report,
)
from agentperf.schema.trace import TraceParseError

LOGGER = logging.getLogger("agentperf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentperf")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser(
        "analyze",
        help="Analyze a normalized AgentPerf trace JSON file or artifact directory",
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
        help="Compare a baseline AgentPerf trace/artifact with a replay candidate",
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
    check = subparsers.add_parser(
        "check",
        help="Evaluate a regression policy against two AgentPerf artifacts/traces",
    )
    check.add_argument("baseline_path", type=Path)
    check.add_argument("candidate_path", type=Path)
    check.add_argument(
        "--policy",
        required=True,
        type=Path,
        help="Path to agentperf-regression.yaml/json",
    )
    check.add_argument(
        "--format",
        choices=["terminal", "json", "markdown"],
        default="terminal",
        help="Output format",
    )
    check.add_argument("--output", type=Path, help="Write check output to a file")
    check.add_argument(
        "--min-material-improvement",
        type=float,
        default=0.05,
        help="Minimum relative improvement used by the underlying replay comparison",
    )
    check.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    inspect = subparsers.add_parser(
        "inspect",
        help="Inspect an AgentPerf artifact bundle",
    )
    inspect.add_argument("artifact_path", type=Path)
    inspect.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    html_report = subparsers.add_parser(
        "report",
        help="Generate a standalone local HTML profiler report from an artifact or trace",
    )
    html_report.add_argument("input_path", type=Path)
    html_report.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Write the self-contained HTML report to this path",
    )
    html_report.add_argument("--title", help="Optional report title")
    html_report.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    suite = subparsers.add_parser(
        "suite",
        help="Validate and check AgentPerf benchmark suites",
    )
    suite_subparsers = suite.add_subparsers(dest="suite_command", required=True)
    suite_validate = suite_subparsers.add_parser(
        "validate",
        help="Validate a benchmark suite manifest, baseline, and policy",
    )
    suite_validate.add_argument("suite_path", type=Path)
    suite_validate.add_argument(
        "--format",
        choices=["terminal", "json", "markdown"],
        default="terminal",
    )
    suite_validate.add_argument("--output", type=Path)
    suite_validate.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    suite_check = suite_subparsers.add_parser(
        "check",
        help="Check one candidate artifact against a benchmark suite",
    )
    suite_check.add_argument("suite_path", type=Path)
    suite_check.add_argument("candidate_path", type=Path)
    suite_check.add_argument(
        "--format",
        choices=["terminal", "json", "markdown"],
        default="terminal",
    )
    suite_check.add_argument("--output", type=Path)
    suite_check.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    suite_check_all = suite_subparsers.add_parser(
        "check-all",
        help="Check all suites below a suites root against candidate artifacts",
    )
    suite_check_all.add_argument("suites_root", type=Path)
    suite_check_all.add_argument("candidates_root", type=Path)
    suite_check_all.add_argument(
        "--format",
        choices=["terminal", "json", "markdown"],
        default="terminal",
    )
    suite_check_all.add_argument("--output", type=Path)
    suite_check_all.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    suite_propose = suite_subparsers.add_parser(
        "propose-baseline",
        help="Generate a reviewable baseline update proposal without replacing files",
    )
    suite_propose.add_argument("suite_path", type=Path)
    suite_propose.add_argument("candidate_path", type=Path)
    suite_propose.add_argument(
        "--format",
        choices=["markdown", "terminal", "json"],
        default="markdown",
    )
    suite_propose.add_argument("--output", type=Path)
    suite_propose.add_argument(
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
            if is_artifact_path(args.trace_path):
                reports = analyze_artifact(args.trace_path)
            else:
                reports = [analyze_path(args.trace_path)]
        except (OSError, ArtifactError, TraceParseError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        for index, report in enumerate(reports):
            if index:
                sys.stdout.write("\n\n")
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
    if args.command == "check":
        try:
            policy = load_regression_policy(args.policy)
            mean_score_policy = policy.quality.get("mean_score")
            pass_rate_policy = policy.quality.get("pass_rate")
            comparison = compare_paths(
                args.baseline_path,
                args.candidate_path,
                mean_score_tolerance=(
                    mean_score_policy.max_drop if mean_score_policy else None
                ),
                pass_rate_tolerance=(
                    pass_rate_policy.max_drop if pass_rate_policy else None
                ),
                min_material_improvement=args.min_material_improvement,
            )
            result = evaluate_regression_policy(comparison, policy)
        except (OSError, ComparisonError, RegressionPolicyError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        if args.format == "json":
            output = regression_result_to_json(result)
        elif args.format == "markdown":
            output = render_regression_markdown(result)
        else:
            output = render_regression_report(result)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            sys.stdout.write(output)
            sys.stdout.write("\n")
        return regression_exit_code(result)
    if args.command == "inspect":
        try:
            output = inspect_artifact(args.artifact_path)
        except (OSError, ArtifactError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write(output)
        sys.stdout.write("\n")
        return 0
    if args.command == "report":
        try:
            write_html_report(args.input_path, args.output, title=args.title)
        except (OSError, ArtifactError, TraceParseError, ValueError, json.JSONDecodeError) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
        sys.stdout.write(f"Wrote AgentPerf HTML report: {args.output}\n")
        return 0
    if args.command == "suite":
        try:
            if args.suite_command == "validate":
                validation_result = validate_suite(args.suite_path)
                if args.format == "json":
                    output = json.dumps(
                        suite_validation_to_dict(validation_result),
                        indent=2,
                        sort_keys=True,
                    )
                else:
                    output = render_suite_validation(
                        validation_result,
                        markdown=args.format == "markdown",
                    )
                _write_or_print(output, args.output)
                return suite_result_exit_code(validation_result.status)
            if args.suite_command == "check":
                check_result = check_suite(args.suite_path, args.candidate_path)
                if args.format == "json":
                    output = json.dumps(
                        suite_check_to_dict(check_result),
                        indent=2,
                        sort_keys=True,
                    )
                else:
                    output = render_suite_check(
                        check_result,
                        markdown=args.format == "markdown",
                    )
                _write_or_print(output, args.output)
                return suite_result_exit_code(check_result.status)
            if args.suite_command == "check-all":
                collection_result = check_all_suites(args.suites_root, args.candidates_root)
                if args.format == "json":
                    output = json.dumps(
                        suite_collection_to_dict(collection_result),
                        indent=2,
                        sort_keys=True,
                    )
                else:
                    output = render_check_all(
                        collection_result,
                        markdown=args.format == "markdown",
                    )
                _write_or_print(output, args.output)
                return suite_result_exit_code(collection_result.status)
            if args.suite_command == "propose-baseline":
                proposal = propose_baseline(args.suite_path, args.candidate_path)
                if args.format == "json":
                    output = json.dumps(
                        baseline_proposal_to_dict(proposal),
                        indent=2,
                        sort_keys=True,
                    )
                else:
                    output = render_baseline_proposal(
                        proposal,
                        markdown=args.format == "markdown",
                    )
                _write_or_print(output, args.output)
                return suite_result_exit_code(proposal.regression.status)
        except (
            OSError,
            ArtifactError,
            ComparisonError,
            RegressionPolicyError,
            SuiteError,
        ) as exc:
            LOGGER.error("%s", exc)
            sys.stderr.write(f"{exc}\n")
            return 2
    return 2


def _write_or_print(output: str, path: Path | None) -> None:
    if path:
        path.write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output)
        sys.stdout.write("\n")
