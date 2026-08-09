#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentperf.model_choice import analyze_model_choice_data  # noqa: E402
from agentperf.reporters.terminal import render_model_choice_report  # noqa: E402
from scripts.run_model_choice_counterfactual import (  # noqa: E402
    DEFAULT_QUALITY_MEAN_SCORE_TOLERANCE,
    DEFAULT_QUALITY_PASS_RATE_TOLERANCE,
    MODEL_LADDER,
    ROLE_PLANNER,
    ROLE_REVIEWER,
    ROLE_SYNTHESIZER,
    ROLES,
    ModelEndpoint,
    RoutedResearchAgent,
    relative_cost,
)
from scripts.run_model_choice_phase_a import (  # noqa: E402
    StageEndpoint,
    final_prompt,
    recording,
    review_prompt,
    run_llm,
    run_strong_baseline,
    tool_call_json,
    tool_records,
)
from scripts.run_real_agent_context_waste import (  # noqa: E402
    DEFAULT_STRATEGIES,
    FINAL_MAX_TOKENS,
    LocalSearchTool,
    Question,
    load_questions,
    score_answer,
    summarize_recording,
    write_artifacts,
)

DEFAULT_OUTPUT_DIR = Path("artifacts/model_choice_m4_phase_b")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run M4 Phase B mixed-routing validation stages."
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=[
            "strong-control",
            "reviewer-candidates",
            "reviewer-continuations",
            "mixed-end-to-end",
            "assemble",
        ],
    )
    parser.add_argument("--tier", choices=["small", "medium", "strong"])
    parser.add_argument("--base-url", default="http://localhost:18000/v1")
    parser.add_argument("--served-model")
    parser.add_argument("--small-base-url", default="http://localhost:18001/v1")
    parser.add_argument("--medium-base-url", default="http://localhost:18002/v1")
    parser.add_argument("--small-served-model", default="agentperf-qwen3-0.6b")
    parser.add_argument("--medium-served-model", default="agentperf-qwen3-1.7b")
    parser.add_argument("--strong-served-model", default="agentperf-qwen3-4b")
    parser.add_argument("--corpus-dir", type=Path, default=Path("docs/corpus"))
    parser.add_argument(
        "--questions-path",
        type=Path,
        default=Path("docs/corpus/questions.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--carry-strategy", default="dedup_only", choices=DEFAULT_STRATEGIES)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--mock-llm", action="store_true")
    parser.add_argument("--repeat-count", type=int, default=3)
    parser.add_argument(
        "--mean-score-tolerance",
        type=float,
        default=DEFAULT_QUALITY_MEAN_SCORE_TOLERANCE,
    )
    parser.add_argument(
        "--pass-rate-tolerance",
        type=float,
        default=DEFAULT_QUALITY_PASS_RATE_TOLERANCE,
    )
    args = parser.parse_args(argv)

    questions = load_questions(args.questions_path)
    search_tool = LocalSearchTool(args.corpus_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.stage == "strong-control":
        endpoint = _stage_endpoint(args, tier="strong")
        data = run_strong_baseline(
            endpoint=endpoint,
            questions=questions,
            search_tool=search_tool,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            timeout=args.timeout,
        )
        _rename_recording(data, "strong_control")
        write_artifacts(args.output_dir, "strong_control", data)
        _write_json(args.output_dir / "state" / "strong_control.json", data)
        assemble(
            output_dir=args.output_dir,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            mean_score_tolerance=args.mean_score_tolerance,
            pass_rate_tolerance=args.pass_rate_tolerance,
        )
        return 0

    if args.stage == "reviewer-candidates":
        if args.tier not in {"small", "medium"}:
            raise ValueError("--stage reviewer-candidates requires --tier")
        endpoint = _stage_endpoint(args, tier=args.tier)
        baseline = _read_json(args.output_dir / "state" / "strong_control.json")
        for repeat_index in range(1, args.repeat_count + 1):
            candidates = run_reviewer_candidate_repeat(
                tier=args.tier,
                repeat_index=repeat_index,
                endpoint=endpoint,
                baseline=baseline,
                questions=questions,
                search_tool=search_tool,
                carry_strategy=args.carry_strategy,
                mock_llm=args.mock_llm,
                timeout=args.timeout,
            )
            _write_json(
                args.output_dir
                / "state"
                / f"reviewer_{args.tier}_repeat_{repeat_index}.json",
                candidates,
            )
        return 0

    if args.stage == "reviewer-continuations":
        endpoint = _stage_endpoint(args, tier="strong")
        baseline = _read_json(args.output_dir / "state" / "strong_control.json")
        for tier in ("medium", "small"):
            for repeat_index in range(1, args.repeat_count + 1):
                path = (
                    args.output_dir
                    / "state"
                    / f"reviewer_{tier}_repeat_{repeat_index}.json"
                )
                if not path.exists():
                    continue
                candidates = _read_json(path)
                data = assemble_reviewer_repeat_recording(
                    tier=tier,
                    repeat_index=repeat_index,
                    strong_endpoint=endpoint,
                    baseline=baseline,
                    candidates=candidates,
                    questions=questions,
                    search_tool=search_tool,
                    carry_strategy=args.carry_strategy,
                    mock_llm=args.mock_llm,
                    timeout=args.timeout,
                )
                write_artifacts(
                    args.output_dir,
                    f"reviewer_{tier}_repeat_{repeat_index}",
                    data,
                )
        write_reviewer_repeatability(args.output_dir)
        return 0

    if args.stage == "mixed-end-to-end":
        endpoints = _mixed_endpoints(args)
        routing = {
            ROLE_PLANNER: "medium",
            ROLE_REVIEWER: "small",
            ROLE_SYNTHESIZER: "small",
        }
        data = run_mixed_evidence_backed(
            endpoints=endpoints,
            routing=routing,
            questions=questions,
            search_tool=search_tool,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            timeout=args.timeout,
        )
        write_artifacts(args.output_dir, "mixed_evidence_backed", data)
        assemble(
            output_dir=args.output_dir,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            mean_score_tolerance=args.mean_score_tolerance,
            pass_rate_tolerance=args.pass_rate_tolerance,
        )
        return 0

    assemble(
        output_dir=args.output_dir,
        carry_strategy=args.carry_strategy,
        mock_llm=args.mock_llm,
        mean_score_tolerance=args.mean_score_tolerance,
        pass_rate_tolerance=args.pass_rate_tolerance,
    )
    return 0


def run_reviewer_candidate_repeat(
    *,
    tier: str,
    repeat_index: int,
    endpoint: StageEndpoint,
    baseline: dict[str, Any],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    checkpoints = _checkpoints(baseline)
    tasks: dict[str, Any] = {}
    for question_index, question in enumerate(questions, start=1):
        first_tool, _ = tool_records(question, search_tool)
        baseline_task = checkpoints[question.id]
        reviewer = run_llm(
            endpoint=endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_REVIEWER,
            components=review_prompt(
                planner_output=baseline_task["planner"]["output_text"],
                first_tool=first_tool,
                carry_strategy=carry_strategy,
            ),
            max_tokens=FINAL_MAX_TOKENS // 2,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"phase_b_reviewer_{tier}_repeat_{repeat_index}",
        )
        tasks[question.id] = {
            "question": asdict(question),
            "reviewer": reviewer,
            "tool_calls": tool_call_json(first_tool, f"q{question_index:02d}-step-2"),
        }
    return {
        "state_version": "agentperf.m4.phase_b.reviewer_candidates.v1",
        "tier": tier,
        "repeat_index": repeat_index,
        "model": endpoint.served_model,
        "created_at": datetime.now(UTC).isoformat(),
        "tasks": tasks,
    }


def assemble_reviewer_repeat_recording(
    *,
    tier: str,
    repeat_index: int,
    strong_endpoint: StageEndpoint,
    baseline: dict[str, Any],
    candidates: dict[str, Any],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    checkpoints = _checkpoints(baseline)
    records: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    for question_index, question in enumerate(questions, start=1):
        baseline_task = checkpoints[question.id]
        candidate_task = candidates["tasks"][question.id]
        reviewer = candidate_task["reviewer"]
        first_tool, second_tool = tool_records(question, search_tool)
        final = run_llm(
            endpoint=strong_endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_SYNTHESIZER,
            components=final_prompt(
                question=question,
                planner_output=baseline_task["planner"]["output_text"],
                reviewer_output=reviewer["output_text"],
                first_tool=first_tool,
                second_tool=second_tool,
                carry_strategy=carry_strategy,
            ),
            max_tokens=FINAL_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"phase_b_reviewer_{tier}_repeat_{repeat_index}_strong_final",
        )
        records.extend(
            [
                baseline_task["planner"]["record"],
                reviewer["record"],
                final["record"],
            ]
        )
        tool_calls.extend(
            [
                *tool_call_json(first_tool, f"q{question_index:02d}-step-2"),
                *tool_call_json(second_tool, f"q{question_index:02d}-step-4"),
            ]
        )
        answers.append(score_answer(question, final["output_text"]))
    strong = {role: "strong" for role in ROLES}
    return recording(
        config_name=f"reviewer_{tier}_repeat_{repeat_index}",
        model=f"reviewer={tier};final=strong",
        routing={**strong, ROLE_REVIEWER: tier},
        records=records,
        tool_calls=tool_calls,
        answers=answers,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
    )


def run_mixed_evidence_backed(
    *,
    endpoints: dict[str, ModelEndpoint],
    routing: dict[str, str],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    agent = RoutedResearchAgent(
        endpoints=endpoints,
        role_routing=routing,
        base_url=endpoints["small"].base_url,
        model=endpoints["small"].served_model,
        search_tool=search_tool,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
        timeout=timeout,
    )
    answers = []
    for question_index, question in enumerate(questions, start=1):
        output = agent.answer(question, question_index)
        answers.append(
            {
                "question_id": question.id,
                "answer": output,
                **score_answer(question, output),
            }
        )
    return {
        "schema_version": "agentperf.vllm_recording.v1",
        "agent_run_id": "mixed_evidence_backed",
        "name": "mixed_evidence_backed",
        "backend": "mock" if mock_llm else "vllm",
        "model": "mixed-routing",
        "environment": _environment(mock_llm, carry_strategy),
        "config_name": "mixed_evidence_backed",
        "routing": routing,
        "records": agent.records,
        "tool_calls": agent.tool_calls,
        "answers": answers,
    }


def write_reviewer_repeatability(output_dir: Path) -> dict[str, Any]:
    repeats: dict[str, list[dict[str, Any]]] = {"medium": [], "small": []}
    for tier in repeats:
        for path in sorted(output_dir.glob(f"reviewer_{tier}_repeat_*/raw/recording.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            summary = summarize_recording(data)
            repeats[tier].append(
                {
                    "config": data.get("config_name", path.parts[-3]),
                    "mean_score": summary["correctness"]["mean_score"],
                    "pass_rate": summary["correctness"]["pass_rate"],
                    "client_latency_p95_ms": summary["client_latency_p95_ms"],
                    "ttft_p95_ms": summary["ttft_p95_ms"],
                }
            )
    aggregate = {
        tier: {
            "runs": rows,
            "mean_score_values": [row["mean_score"] for row in rows],
            "pass_rate_values": [row["pass_rate"] for row in rows],
            "all_quality_preserving": all(
                row["mean_score"] >= 0.0 and row["pass_rate"] >= 0.0 for row in rows
            ),
        }
        for tier, rows in repeats.items()
    }
    path = output_dir / "reviewer_repeatability.json"
    path.write_text(json.dumps(aggregate, indent=2), encoding="utf-8")
    return aggregate


def assemble(
    *,
    output_dir: Path,
    carry_strategy: str,
    mock_llm: bool,
    mean_score_tolerance: float,
    pass_rate_tolerance: float,
) -> dict[str, Any]:
    endpoints = _default_endpoints()
    summaries: dict[str, dict[str, Any]] = {}
    for config_name in ("strong_control", "mixed_evidence_backed"):
        path = output_dir / config_name / "raw" / "recording.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = summarize_recording(data)
        routing = data.get("routing", {})
        if isinstance(routing, dict):
            summary["routing"] = {str(key): str(value) for key, value in routing.items()}
            summary["relative_cost"] = relative_cost(summary, summary["routing"], endpoints)
        summaries[config_name] = summary
    if "strong_control" not in summaries:
        return {}
    comparison: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": {
            **_environment(mock_llm, carry_strategy),
            "execution_strategy": "phase_b_end_to_end_mixed_replay",
            "counterfactual_semantics": (
                "Phase B strong_control and mixed_evidence_backed are full agent "
                "executions. Mixed routing role outputs feed downstream roles."
            ),
        },
        "model_ladder": MODEL_LADDER,
        "baseline_config": "strong_control",
        "selected_mixed_config": "mixed_evidence_backed",
        "quality_constraint": {
            "baseline_strategy": "strong_control",
            "mean_score_tolerance": mean_score_tolerance,
            "pass_rate_tolerance": pass_rate_tolerance,
            "objective": (
                "minimize relative model cost/latency subject to mean score and "
                "pass-rate tolerance"
            ),
        },
        "configurations": summaries,
    }
    repeatability_path = output_dir / "reviewer_repeatability.json"
    if repeatability_path.exists():
        comparison["reviewer_repeatability"] = json.loads(
            repeatability_path.read_text(encoding="utf-8")
        )
    report = analyze_model_choice_data(comparison)
    comparison["model_choice_findings"] = [
        {
            "id": finding.id,
            "severity": finding.severity,
            "evidence": finding.evidence,
            "recommendation": finding.recommendation,
            "provenance": {
                "derived_metrics": finding.provenance.derived_metrics,
                "notes": finding.provenance.notes,
            },
        }
        for finding in report.findings
    ]
    comparison["pareto"] = report.pareto
    comparison["role_sensitivity"] = [
        {
            "role": row.role,
            "baseline_model": row.baseline_model,
            "candidate_model": row.candidate_model,
            "config_name": row.config_name,
            "mean_quality_delta": row.mean_quality_delta,
            "pass_rate_delta": row.pass_rate_delta,
            "client_latency_p95_delta_ms": row.client_latency_p95_delta_ms,
            "relative_cost_delta": row.relative_cost_delta,
            "quality_preserving": row.quality_preserving,
        }
        for row in report.role_sensitivity
    ]
    (output_dir / "model_choice_phase_b_comparison.json").write_text(
        json.dumps(comparison, indent=2),
        encoding="utf-8",
    )
    (output_dir / "model_choice_phase_b_report.txt").write_text(
        render_model_choice_report(report, show_provenance=True),
        encoding="utf-8",
    )
    return comparison


def _stage_endpoint(args: argparse.Namespace, *, tier: str) -> StageEndpoint:
    served_model = args.served_model or {
        "strong": args.strong_served_model,
        "medium": args.medium_served_model,
        "small": args.small_served_model,
    }[tier]
    return StageEndpoint(tier=tier, base_url=args.base_url, served_model=served_model)


def _mixed_endpoints(args: argparse.Namespace) -> dict[str, ModelEndpoint]:
    endpoints = {
        "small": ModelEndpoint(
            tier="small",
            base_url="mock://small" if args.mock_llm else args.small_base_url,
            served_model=str(MODEL_LADDER["small"]["model"])
            if args.mock_llm
            else args.small_served_model,
            relative_cost_weight=float(str(MODEL_LADDER["small"]["relative_cost_weight"])),
        ),
        "medium": ModelEndpoint(
            tier="medium",
            base_url="mock://medium" if args.mock_llm else args.medium_base_url,
            served_model=str(MODEL_LADDER["medium"]["model"])
            if args.mock_llm
            else args.medium_served_model,
            relative_cost_weight=float(str(MODEL_LADDER["medium"]["relative_cost_weight"])),
        ),
    }
    endpoints["strong"] = ModelEndpoint(
        tier="strong",
        base_url=endpoints["small"].base_url,
        served_model=str(MODEL_LADDER["strong"]["model"])
        if args.mock_llm
        else args.strong_served_model,
        relative_cost_weight=float(str(MODEL_LADDER["strong"]["relative_cost_weight"])),
    )
    return endpoints


def _default_endpoints() -> dict[str, ModelEndpoint]:
    return {
        tier: ModelEndpoint(
            tier=tier,
            base_url=f"phase-b://{tier}",
            served_model=str(data["model"]),
            relative_cost_weight=float(str(data["relative_cost_weight"])),
        )
        for tier, data in MODEL_LADDER.items()
    }


def _rename_recording(data: dict[str, Any], name: str) -> None:
    data["agent_run_id"] = name
    data["name"] = name
    data["config_name"] = name


def _checkpoints(baseline: dict[str, Any]) -> dict[str, Any]:
    checkpoints = baseline.get("checkpoints")
    if not isinstance(checkpoints, dict):
        raise ValueError("strong control state is missing checkpoints")
    return checkpoints


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing file: {path}")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _environment(mock_llm: bool, carry_strategy: str) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "mock" if mock_llm else "vllm",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "gpu": _detect_gpu(),
        "carry_strategy": carry_strategy,
        "agent_architecture": (
            "planner LLM -> local search -> evidence review LLM -> local search -> final LLM"
        ),
        "agent_framework": "none",
    }


def _detect_gpu() -> str | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().splitlines()[0]
    return None


if __name__ == "__main__":
    raise SystemExit(main())
