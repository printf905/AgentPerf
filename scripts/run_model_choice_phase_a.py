#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

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
    relative_cost,
    routed_mock_response,
)
from scripts.run_real_agent_context_waste import (  # noqa: E402
    DEFAULT_STRATEGIES,
    FINAL_MAX_TOKENS,
    PLANNER_MAX_TOKENS,
    REVIEW_MAX_TOKENS,
    LocalSearchTool,
    Question,
    ToolResultRecord,
    call_vllm,
    compact_carried_component,
    component,
    dedup_carried_components,
    extract_output_text,
    load_questions,
    ranked_carried_components,
    raw_carried_component,
    score_answer,
    summarize_recording,
    write_artifacts,
)

STATE_VERSION = "agentperf.m4.phase_a.v1"
DEFAULT_PORT = 18000


@dataclass(frozen=True)
class StageEndpoint:
    tier: str
    base_url: str
    served_model: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run staged M4 role-sensitivity replay with one model loaded at a time."
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=[
            "strong-baseline",
            "candidate-tier",
            "strong-continuations",
            "assemble",
        ],
    )
    parser.add_argument("--tier", choices=["small", "medium", "strong"])
    parser.add_argument("--base-url", default=f"http://localhost:{DEFAULT_PORT}/v1")
    parser.add_argument("--served-model")
    parser.add_argument("--corpus-dir", type=Path, default=Path("docs/corpus"))
    parser.add_argument(
        "--questions-path",
        type=Path,
        default=Path("docs/corpus/questions.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/model_choice_m4"))
    parser.add_argument("--carry-strategy", default="dedup_only", choices=DEFAULT_STRATEGIES)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--mock-llm", action="store_true")
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

    if args.stage == "strong-baseline":
        endpoint = _endpoint(args, required_tier="strong")
        recording = run_strong_baseline(
            endpoint=endpoint,
            questions=questions,
            search_tool=search_tool,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            timeout=args.timeout,
        )
        _write_recording(args.output_dir, "strong_all", recording)
        _write_state(args.output_dir, "strong_baseline.json", recording)
        assemble_comparison(
            output_dir=args.output_dir,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            mean_score_tolerance=args.mean_score_tolerance,
            pass_rate_tolerance=args.pass_rate_tolerance,
        )
        return 0

    if args.stage == "candidate-tier":
        if args.tier not in {"small", "medium"}:
            raise ValueError("--stage candidate-tier requires --tier small or medium")
        endpoint = _endpoint(args, required_tier=args.tier)
        baseline = _read_state(args.output_dir, "strong_baseline.json")
        candidates = run_candidate_tier(
            tier=args.tier,
            endpoint=endpoint,
            baseline=baseline,
            questions=questions,
            search_tool=search_tool,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            timeout=args.timeout,
        )
        _write_state(args.output_dir, f"candidate_{args.tier}.json", candidates)
        synth_recording = assemble_synthesizer_recording(
            tier=args.tier,
            baseline=baseline,
            candidates=candidates,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
        )
        _write_recording(args.output_dir, f"synthesizer_{args.tier}", synth_recording)
        assemble_comparison(
            output_dir=args.output_dir,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            mean_score_tolerance=args.mean_score_tolerance,
            pass_rate_tolerance=args.pass_rate_tolerance,
        )
        return 0

    if args.stage == "strong-continuations":
        endpoint = _endpoint(args, required_tier="strong")
        baseline = _read_state(args.output_dir, "strong_baseline.json")
        for tier in ("medium", "small"):
            candidate_path = _state_path(args.output_dir, f"candidate_{tier}.json")
            if not candidate_path.exists():
                continue
            candidates = _read_state(args.output_dir, f"candidate_{tier}.json")
            planner_recording = assemble_planner_recording(
                tier=tier,
                strong_endpoint=endpoint,
                baseline=baseline,
                candidates=candidates,
                questions=questions,
                search_tool=search_tool,
                carry_strategy=args.carry_strategy,
                mock_llm=args.mock_llm,
                timeout=args.timeout,
            )
            reviewer_recording = assemble_reviewer_recording(
                tier=tier,
                strong_endpoint=endpoint,
                baseline=baseline,
                candidates=candidates,
                questions=questions,
                search_tool=search_tool,
                carry_strategy=args.carry_strategy,
                mock_llm=args.mock_llm,
                timeout=args.timeout,
            )
            _write_recording(args.output_dir, f"planner_{tier}", planner_recording)
            _write_recording(args.output_dir, f"reviewer_{tier}", reviewer_recording)
        assemble_comparison(
            output_dir=args.output_dir,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            mean_score_tolerance=args.mean_score_tolerance,
            pass_rate_tolerance=args.pass_rate_tolerance,
        )
        return 0

    assemble_comparison(
        output_dir=args.output_dir,
        carry_strategy=args.carry_strategy,
        mock_llm=args.mock_llm,
        mean_score_tolerance=args.mean_score_tolerance,
        pass_rate_tolerance=args.pass_rate_tolerance,
    )
    return 0


def run_strong_baseline(
    *,
    endpoint: StageEndpoint,
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    answers: list[dict[str, Any]] = []
    checkpoints: dict[str, Any] = {}
    for question_index, question in enumerate(questions, start=1):
        planner_components = planner_prompt(question)
        planner = run_llm(
            endpoint=endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_PLANNER,
            components=planner_components,
            max_tokens=PLANNER_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage="strong_baseline",
        )

        first_tool, second_tool = tool_records(question, search_tool)
        tool_calls.extend(tool_call_json(first_tool, f"q{question_index:02d}-step-2"))
        review_components = review_prompt(
            planner_output=planner["output_text"],
            first_tool=first_tool,
            carry_strategy=carry_strategy,
        )
        reviewer = run_llm(
            endpoint=endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_REVIEWER,
            components=review_components,
            max_tokens=REVIEW_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage="strong_baseline",
        )

        tool_calls.extend(tool_call_json(second_tool, f"q{question_index:02d}-step-4"))
        final_components = final_prompt(
            question=question,
            planner_output=planner["output_text"],
            reviewer_output=reviewer["output_text"],
            first_tool=first_tool,
            second_tool=second_tool,
            carry_strategy=carry_strategy,
        )
        final = run_llm(
            endpoint=endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_SYNTHESIZER,
            components=final_components,
            max_tokens=FINAL_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage="strong_baseline",
        )
        score = score_answer(question, final["output_text"])
        answers.append(score)
        records.extend([planner["record"], reviewer["record"], final["record"]])
        checkpoints[question.id] = {
            "question": asdict(question),
            "planner": planner,
            "reviewer": reviewer,
            "final": final,
            "tool_calls": [
                *tool_call_json(first_tool, f"q{question_index:02d}-step-2"),
                *tool_call_json(second_tool, f"q{question_index:02d}-step-4"),
            ],
            "answer": score,
        }
    return recording(
        config_name="strong_all",
        model=endpoint.served_model,
        routing={role: "strong" for role in ROLES},
        records=records,
        tool_calls=tool_calls,
        answers=answers,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
        extra={"checkpoints": checkpoints},
    )


def run_candidate_tier(
    *,
    tier: str,
    endpoint: StageEndpoint,
    baseline: dict[str, Any],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    results: dict[str, Any] = {
        "state_version": STATE_VERSION,
        "tier": tier,
        "model": endpoint.served_model,
        "created_at": datetime.now(UTC).isoformat(),
        "tasks": {},
    }
    checkpoints = _checkpoints(baseline)
    for question_index, question in enumerate(questions, start=1):
        baseline_task = checkpoints[question.id]
        first_tool, second_tool = tool_records(question, search_tool)
        planner = run_llm(
            endpoint=endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_PLANNER,
            components=planner_prompt(question),
            max_tokens=PLANNER_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"{tier}_planner_candidate",
        )
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
            max_tokens=REVIEW_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"{tier}_reviewer_candidate",
        )
        synthesizer = run_llm(
            endpoint=endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_SYNTHESIZER,
            components=baseline_task["final"]["record"]["prompt_components"],
            max_tokens=FINAL_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"{tier}_synthesizer_candidate",
        )
        results["tasks"][question.id] = {
            "planner": planner,
            "reviewer": reviewer,
            "synthesizer": synthesizer,
            "synthesizer_answer": score_answer(question, synthesizer["output_text"]),
            "tool_calls": [
                *tool_call_json(first_tool, f"q{question_index:02d}-step-2"),
                *tool_call_json(second_tool, f"q{question_index:02d}-step-4"),
            ],
        }
    return results


def assemble_synthesizer_recording(
    *,
    tier: str,
    baseline: dict[str, Any],
    candidates: dict[str, Any],
    carry_strategy: str,
    mock_llm: bool,
) -> dict[str, Any]:
    records = []
    tool_calls = []
    answers = []
    checkpoints = _checkpoints(baseline)
    for question_id, baseline_task in checkpoints.items():
        candidate_task = candidates["tasks"][question_id]
        records.extend(
            [
                baseline_task["planner"]["record"],
                baseline_task["reviewer"]["record"],
                candidate_task["synthesizer"]["record"],
            ]
        )
        tool_calls.extend(baseline_task["tool_calls"])
        answers.append(candidate_task["synthesizer_answer"])
    strong = {role: "strong" for role in ROLES}
    return recording(
        config_name=f"synthesizer_{tier}",
        model=f"synthesizer={tier}",
        routing={**strong, ROLE_SYNTHESIZER: tier},
        records=records,
        tool_calls=tool_calls,
        answers=answers,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
    )


def assemble_planner_recording(
    *,
    tier: str,
    strong_endpoint: StageEndpoint,
    baseline: dict[str, Any],
    candidates: dict[str, Any],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    records = []
    tool_calls = []
    answers = []
    candidate_tasks = candidates["tasks"]
    for question_index, question in enumerate(questions, start=1):
        planner = candidate_tasks[question.id]["planner"]
        first_tool, second_tool = tool_records(question, search_tool)
        review = run_llm(
            endpoint=strong_endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_REVIEWER,
            components=review_prompt(
                planner_output=planner["output_text"],
                first_tool=first_tool,
                carry_strategy=carry_strategy,
            ),
            max_tokens=REVIEW_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"{tier}_planner_strong_review_continuation",
        )
        final = run_llm(
            endpoint=strong_endpoint,
            question=question,
            question_index=question_index,
            role=ROLE_SYNTHESIZER,
            components=final_prompt(
                question=question,
                planner_output=planner["output_text"],
                reviewer_output=review["output_text"],
                first_tool=first_tool,
                second_tool=second_tool,
                carry_strategy=carry_strategy,
            ),
            max_tokens=FINAL_MAX_TOKENS,
            mock_llm=mock_llm,
            timeout=timeout,
            replay_stage=f"{tier}_planner_strong_final_continuation",
        )
        records.extend([planner["record"], review["record"], final["record"]])
        tool_calls.extend(
            [
                *tool_call_json(first_tool, f"q{question_index:02d}-step-2"),
                *tool_call_json(second_tool, f"q{question_index:02d}-step-4"),
            ]
        )
        answers.append(score_answer(question, final["output_text"]))
    strong = {role: "strong" for role in ROLES}
    return recording(
        config_name=f"planner_{tier}",
        model=f"planner={tier}",
        routing={**strong, ROLE_PLANNER: tier},
        records=records,
        tool_calls=tool_calls,
        answers=answers,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
    )


def assemble_reviewer_recording(
    *,
    tier: str,
    strong_endpoint: StageEndpoint,
    baseline: dict[str, Any],
    candidates: dict[str, Any],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    records = []
    tool_calls = []
    answers = []
    checkpoints = _checkpoints(baseline)
    candidate_tasks = candidates["tasks"]
    for question_index, question in enumerate(questions, start=1):
        baseline_task = checkpoints[question.id]
        reviewer = candidate_tasks[question.id]["reviewer"]
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
            replay_stage=f"{tier}_reviewer_strong_final_continuation",
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
        config_name=f"reviewer_{tier}",
        model=f"reviewer={tier}",
        routing={**strong, ROLE_REVIEWER: tier},
        records=records,
        tool_calls=tool_calls,
        answers=answers,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
    )


def run_llm(
    *,
    endpoint: StageEndpoint,
    question: Question,
    question_index: int,
    role: str,
    components: list[dict[str, Any]],
    max_tokens: int,
    mock_llm: bool,
    timeout: float,
    replay_stage: str,
) -> dict[str, Any]:
    request_id = f"agentperf-m4-{endpoint.tier}-{question.id}-{role}-{uuid4().hex[:8]}"
    trace_id = uuid4().hex
    llm_call_id = f"{question.id}-{role}"
    step_id = {
        ROLE_PLANNER: f"q{question_index:02d}-step-1",
        ROLE_REVIEWER: f"q{question_index:02d}-step-3",
        ROLE_SYNTHESIZER: f"q{question_index:02d}-step-5",
    }[role]
    started = time.perf_counter()
    response = (
        routed_mock_response(request_id, components, max_tokens, role, endpoint.tier)
        if mock_llm
        else call_vllm(
            base_url=endpoint.base_url,
            model=endpoint.served_model,
            request_id=request_id,
            trace_id=trace_id,
            components=components,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    output_text = extract_output_text(response)
    record = {
        "agent_step_id": step_id,
        "llm_call_id": llm_call_id,
        "trace_id": trace_id,
        "client_request_id": request_id,
        "request_id": response.get("id", request_id),
        "model": endpoint.served_model,
        "prompt_components": components,
        "client_elapsed_ms": elapsed_ms,
        "response": response,
        "output_text": output_text,
        "semantic_role": role,
        "metadata": {
            "role": role,
            "semantic_role": role,
            "model_tier": endpoint.tier,
            "replay_stage": replay_stage,
        },
    }
    return {"output_text": output_text, "record": record}


def planner_prompt(question: Question) -> list[dict[str, Any]]:
    return [
        component("system", _system_instructions()),
        component("tool_schemas", _tool_schema()),
        component(
            "user",
            (
                "Plan only. Do not answer the question. Return exactly two "
                "search query lines for the local search tool.\n"
                f"Question: {question.question}"
            ),
        ),
    ]


def review_prompt(
    *,
    planner_output: str,
    first_tool: ToolResultRecord,
    carry_strategy: str,
) -> list[dict[str, Any]]:
    return [
        component("system", _system_instructions()),
        component("tool_schemas", _tool_schema()),
        component("history", f"Planner output:\n{planner_output}"),
        *tool_components([first_tool], carry_strategy),
        component(
            "user",
            (
                "Copy only relevant DOC_ID, ANSWER_FACT, and CITATION lines "
                "from the tool results. Do not add facts not present in those lines."
            ),
        ),
    ]


def final_prompt(
    *,
    question: Question,
    planner_output: str,
    reviewer_output: str,
    first_tool: ToolResultRecord,
    second_tool: ToolResultRecord,
    carry_strategy: str,
) -> list[dict[str, Any]]:
    return [
        component("system", _system_instructions()),
        component("tool_schemas", _tool_schema()),
        component(
            "history",
            f"Planner output:\n{planner_output}\n\nEvidence review output:\n{reviewer_output}",
        ),
        *tool_components([first_tool, second_tool], carry_strategy),
        component(
            "user",
            (
                "Answer the original question using only supplied evidence. "
                "Do not continue the prompt. Do not invent document IDs. "
                "Use this exact format:\n"
                "DOC_ID: <source doc id>\n"
                "CAUSE: <cause or reason>\n"
                "MITIGATION: <first mitigation or action>\n"
                "OWNER: <owning team if available>\n"
                "WHY_NOT: <why the rejected action is not first, if asked>\n"
                f"Original question: {question.question}"
            ),
        ),
    ]


def tool_components(
    records: list[ToolResultRecord],
    carry_strategy: str,
) -> list[dict[str, Any]]:
    if carry_strategy == "raw_full":
        carried = [raw_carried_component(record, carry_strategy) for record in records]
    elif carry_strategy == "aggressive_compact":
        carried = [compact_carried_component(record, carry_strategy) for record in records]
    elif carry_strategy == "dedup_only":
        carried = dedup_carried_components(records, carry_strategy)
    elif carry_strategy.startswith("top_k_"):
        top_k = int(carry_strategy.rsplit("_", 1)[1])
        carried = ranked_carried_components(
            records,
            carry_strategy,
            top_k=top_k,
            token_budget=None,
        )
    elif carry_strategy.startswith("budget_"):
        budget = int(carry_strategy.rsplit("_", 1)[1])
        carried = ranked_carried_components(
            records,
            carry_strategy,
            top_k=None,
            token_budget=budget,
        )
    else:
        raise ValueError(f"unknown carry strategy: {carry_strategy}")
    return [
        component(
            "tool_results",
            item.text,
            source_tool_call_ids=[item.tool_call_id],
            metadata=item.metadata,
        )
        for item in carried
    ]


def tool_records(
    question: Question,
    search_tool: LocalSearchTool,
) -> tuple[ToolResultRecord, ToolResultRecord]:
    return (
        search_tool.search(question.queries[0], tool_call_id=f"{question.id}-search-1"),
        search_tool.search(question.queries[1], tool_call_id=f"{question.id}-search-2"),
    )


def tool_call_json(record: ToolResultRecord, step_id: str) -> list[dict[str, Any]]:
    return [
        {
            "agent_step_id": step_id,
            "tool_call_id": record.tool_call_id,
            "name": "search",
            "input": {"query": record.query},
            "output": record.raw_text,
            "latency_ms": 0.0,
            "metadata": {
                "retrieved_doc_ids": [hit.doc_id for hit in record.hits],
                "raw_output_tokens_approx": sum(hit.original_tokens for hit in record.hits),
                "evidence_items": [
                    {
                        "source_document_id": hit.doc_id,
                        "tool_call_id": hit.tool_call_id,
                        "passage_id": hit.passage_id,
                        "retrieval_rank": hit.rank,
                        "retrieval_score": hit.score,
                        "original_token_count": hit.original_tokens,
                    }
                    for hit in record.hits
                ],
            },
        }
    ]


def recording(
    *,
    config_name: str,
    model: str,
    routing: dict[str, str],
    records: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    answers: list[dict[str, Any]],
    carry_strategy: str,
    mock_llm: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "state_version": STATE_VERSION,
        "agent_run_id": config_name,
        "name": config_name,
        "backend": "mock" if mock_llm else "vllm",
        "model": model,
        "config_name": config_name,
        "routing": routing,
        "environment": environment(mock_llm, carry_strategy),
        "records": records,
        "tool_calls": tool_calls,
        "answers": answers,
    }
    if extra:
        data.update(extra)
    return data


def assemble_comparison(
    *,
    output_dir: Path,
    carry_strategy: str,
    mock_llm: bool,
    mean_score_tolerance: float,
    pass_rate_tolerance: float,
) -> dict[str, Any]:
    summaries: dict[str, dict[str, Any]] = {}
    endpoints = default_endpoints()
    for config_name in phase_a_config_names():
        recording_path = output_dir / config_name / "raw" / "recording.json"
        if not recording_path.exists():
            continue
        data = json.loads(recording_path.read_text(encoding="utf-8"))
        summary = summarize_recording(data)
        routing = data.get("routing", {})
        if isinstance(routing, dict):
            summary["routing"] = {str(key): str(value) for key, value in routing.items()}
        summary["relative_cost"] = relative_cost(summary, summary["routing"], endpoints)
        summaries[config_name] = summary
    if "strong_all" not in summaries:
        return {}
    comparison: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": {
            **environment(mock_llm, carry_strategy),
            "execution_strategy": "sequential_one_model_at_a_time",
            "counterfactual_semantics": (
                "Unchanged strong role records are reused from the strong baseline. "
                "Changed role calls are regenerated with the candidate model. "
                "Downstream strong calls are regenerated when upstream output changes."
            ),
        },
        "model_ladder": MODEL_LADDER,
        "baseline_config": "strong_all",
        "quality_constraint": {
            "baseline_strategy": "strong_all",
            "mean_score_tolerance": mean_score_tolerance,
            "pass_rate_tolerance": pass_rate_tolerance,
            "objective": (
                "minimize relative model cost/latency subject to mean score and "
                "pass-rate tolerance"
            ),
        },
        "configurations": summaries,
    }
    report = analyze_model_choice_data(comparison)
    comparison["model_choice_findings"] = [
        {
            "id": finding.id,
            "severity": finding.severity,
            "evidence": finding.evidence,
            "recommendation": finding.recommendation,
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
    (output_dir / "model_choice_comparison.json").write_text(
        json.dumps(comparison, indent=2),
        encoding="utf-8",
    )
    (output_dir / "model_choice_report.txt").write_text(
        render_model_choice_report(report, show_provenance=True),
        encoding="utf-8",
    )
    return comparison


def phase_a_config_names() -> list[str]:
    return [
        "strong_all",
        "planner_medium",
        "reviewer_medium",
        "synthesizer_medium",
        "planner_small",
        "reviewer_small",
        "synthesizer_small",
    ]


def default_endpoints() -> dict[str, ModelEndpoint]:
    return {
        tier: ModelEndpoint(
            tier=tier,
            base_url="sequential://single-active-server",
            served_model=str(data["model"]),
            relative_cost_weight=float(str(data["relative_cost_weight"])),
        )
        for tier, data in MODEL_LADDER.items()
    }


def _write_recording(output_dir: Path, name: str, data: dict[str, Any]) -> None:
    write_artifacts(output_dir, name, data)


def _write_state(output_dir: Path, name: str, data: dict[str, Any]) -> None:
    state_dir = output_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_state(output_dir: Path, name: str) -> dict[str, Any]:
    path = _state_path(output_dir, name)
    if not path.exists():
        raise FileNotFoundError(f"missing replay state: {path}")
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _state_path(output_dir: Path, name: str) -> Path:
    return output_dir / "state" / name


def _checkpoints(baseline: dict[str, Any]) -> dict[str, Any]:
    checkpoints = baseline.get("checkpoints")
    if not isinstance(checkpoints, dict):
        raise ValueError("strong baseline state is missing checkpoints")
    return checkpoints


def _endpoint(args: argparse.Namespace, *, required_tier: str) -> StageEndpoint:
    tier = args.tier or required_tier
    if tier != required_tier:
        raise ValueError(f"stage requires tier {required_tier}, got {tier}")
    served_model = args.served_model or str(MODEL_LADDER[tier]["model"])
    return StageEndpoint(tier=tier, base_url=args.base_url, served_model=served_model)


def environment(mock_llm: bool, carry_strategy: str) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "mock" if mock_llm else "vllm",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "carry_strategy": carry_strategy,
        "agent_architecture": (
            "planner LLM -> local search -> evidence review LLM -> local search -> final LLM"
        ),
        "agent_framework": "none",
    }


def _system_instructions() -> str:
    from scripts.run_real_agent_context_waste import SYSTEM_INSTRUCTIONS

    return SYSTEM_INSTRUCTIONS


def _tool_schema() -> str:
    from scripts.run_real_agent_context_waste import TOOL_SCHEMA

    return TOOL_SCHEMA


if __name__ == "__main__":
    raise SystemExit(main())
