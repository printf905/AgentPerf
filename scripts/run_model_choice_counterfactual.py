#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentperf.model_choice import analyze_model_choice_data  # noqa: E402
from agentperf.reporters.terminal import render_model_choice_report  # noqa: E402
from scripts.run_real_agent_context_waste import (  # noqa: E402
    DEFAULT_STRATEGIES,
    LocalSearchTool,
    Question,
    ResearchAgent,
    call_vllm,
    extract_output_text,
    load_questions,
    mock_response,
    run_config,
    summarize_recording,
    write_artifacts,
)

ROLE_PLANNER = "planner"
ROLE_REVIEWER = "evidence_reviewer"
ROLE_SYNTHESIZER = "final_synthesizer"
ROLE_ALIASES = {
    "planner": ROLE_PLANNER,
    "evidence-review": ROLE_REVIEWER,
    "evidence_reviewer": ROLE_REVIEWER,
    "final": ROLE_SYNTHESIZER,
    "final_synthesizer": ROLE_SYNTHESIZER,
}
ROLES = [ROLE_PLANNER, ROLE_REVIEWER, ROLE_SYNTHESIZER]
DEFAULT_QUALITY_MEAN_SCORE_TOLERANCE = 0.05
DEFAULT_QUALITY_PASS_RATE_TOLERANCE = 0.10
MODEL_LADDER = {
    "small": {
        "model": "Qwen/Qwen3-0.6B",
        "parameter_scale": "0.6B-class",
        "dtype": "bfloat16",
        "context_length": "32K advertised by model family; M4 run uses 8192 max_model_len",
        "vllm_compatibility": "Qwen3ForCausalLM supported by vLLM",
        "relative_cost_weight": 0.6,
    },
    "medium": {
        "model": "Qwen/Qwen3-1.7B",
        "parameter_scale": "1.7B-class",
        "dtype": "bfloat16",
        "context_length": "32K advertised by model family; M4 run uses 8192 max_model_len",
        "vllm_compatibility": "Qwen3ForCausalLM supported by vLLM",
        "relative_cost_weight": 1.7,
    },
    "strong": {
        "model": "Qwen/Qwen3-4B",
        "parameter_scale": "4B-class",
        "dtype": "bfloat16",
        "context_length": "32K advertised by model family; M4 run uses 8192 max_model_len",
        "vllm_compatibility": "Qwen3ForCausalLM supported by vLLM",
        "relative_cost_weight": 4.0,
    },
}


@dataclass(frozen=True)
class ModelEndpoint:
    tier: str
    base_url: str
    served_model: str
    relative_cost_weight: float


class RoutedResearchAgent(ResearchAgent):
    def __init__(
        self,
        *,
        endpoints: dict[str, ModelEndpoint],
        role_routing: dict[str, str],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.endpoints = endpoints
        self.role_routing = role_routing

    def _llm_step(
        self,
        *,
        step_id: str,
        llm_call_id: str,
        role: str,
        components: list[dict[str, Any]],
        max_tokens: int = 96,
    ) -> str:
        semantic_role = normalize_role(role)
        tier = self.role_routing[semantic_role]
        endpoint = self.endpoints[tier]
        request_id = f"agentperf-m4-{tier}-{llm_call_id}"
        trace_id = f"{semantic_role.replace('_', '')}{llm_call_id.replace('-', '')}"[:32].ljust(
            32,
            "0",
        )
        started = time.perf_counter()
        response = (
            routed_mock_response(request_id, components, max_tokens, semantic_role, tier)
            if self.mock_llm
            else call_vllm(
                base_url=endpoint.base_url,
                model=endpoint.served_model,
                request_id=request_id,
                trace_id=trace_id,
                components=components,
                max_tokens=max_tokens,
                timeout=self.timeout,
            )
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.records.append(
            {
                "agent_step_id": step_id,
                "llm_call_id": llm_call_id,
                "trace_id": trace_id,
                "client_request_id": request_id,
                "request_id": response.get("id", request_id),
                "model": endpoint.served_model,
                "prompt_components": components,
                "client_elapsed_ms": elapsed_ms,
                "response": response,
                "output_text": extract_output_text(response),
                "semantic_role": semantic_role,
                "metadata": {
                    "role": semantic_role,
                    "semantic_role": semantic_role,
                    "model_tier": tier,
                },
            }
        )
        return extract_output_text(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run model-choice counterfactual replay for the real research agent"
    )
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
        "--endpoint",
        action="append",
        default=[],
        help="tier=base_url,served_model mapping. Example: strong=http://localhost:8003/v1,agentperf-qwen3-4b",
    )
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
    endpoints = parse_endpoints(args.endpoint, args.mock_llm)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    configs = routing_configs()
    recordings: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for config_name, routing in configs.items():
        recording = run_routing_config(
            config_name=config_name,
            routing=routing,
            endpoints=endpoints,
            questions=questions,
            search_tool=search_tool,
            carry_strategy=args.carry_strategy,
            mock_llm=args.mock_llm,
            timeout=args.timeout,
        )
        recordings[config_name] = recording
        write_artifacts(args.output_dir, config_name, recording)
        summary = summarize_recording(recording)
        summary["routing"] = routing
        summary["relative_cost"] = relative_cost(summary, routing, endpoints)
        summaries[config_name] = summary

    comparison: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": collect_environment(args.mock_llm, args.carry_strategy),
        "model_ladder": MODEL_LADDER,
        "baseline_config": "strong_all",
        "selected_mixed_config": "mixed_evidence_backed",
        "quality_constraint": {
            "baseline_strategy": "strong_all",
            "mean_score_tolerance": args.mean_score_tolerance,
            "pass_rate_tolerance": args.pass_rate_tolerance,
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
    comparison_path = args.output_dir / "model_choice_comparison.json"
    comparison_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (args.output_dir / "model_choice_report.txt").write_text(
        render_model_choice_report(report, show_provenance=True),
        encoding="utf-8",
    )
    print(f"Wrote model-choice artifacts to {args.output_dir}")
    return 0


def run_routing_config(
    *,
    config_name: str,
    routing: dict[str, str],
    endpoints: dict[str, ModelEndpoint],
    questions: list[Question],
    search_tool: LocalSearchTool,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
) -> dict[str, Any]:
    if len(set(routing.values())) == 1:
        tier = next(iter(routing.values()))
        return run_config(
            config_name=config_name,
            questions=questions,
            search_tool=search_tool,
            base_url=endpoints[tier].base_url,
            model=endpoints[tier].served_model,
            carry_strategy=carry_strategy,
            mock_llm=mock_llm,
            timeout=timeout,
            environment=collect_environment(mock_llm, carry_strategy),
        )

    agent = RoutedResearchAgent(
        endpoints=endpoints,
        role_routing=routing,
        base_url=endpoints["strong"].base_url,
        model=endpoints["strong"].served_model,
        search_tool=search_tool,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
        timeout=timeout,
    )
    answers = []
    for index, question in enumerate(questions, start=1):
        output = agent.answer(question, index)
        scored = score_question(question, output)
        answers.append({"question_id": question.id, "answer": output, **scored})
    return {
        "schema_version": "agentperf.vllm_recording.v1",
        "backend": "mock" if mock_llm else "vllm",
        "model": "mixed-routing",
        "environment": collect_environment(mock_llm, carry_strategy),
        "config_name": config_name,
        "routing": routing,
        "records": agent.records,
        "tool_calls": agent.tool_calls,
        "answers": answers,
    }


def routing_configs() -> dict[str, dict[str, str]]:
    strong_all = {role: "strong" for role in ROLES}
    return {
        "strong_all": strong_all,
        "planner_small": {**strong_all, ROLE_PLANNER: "small"},
        "planner_medium": {**strong_all, ROLE_PLANNER: "medium"},
        "reviewer_small": {**strong_all, ROLE_REVIEWER: "small"},
        "reviewer_medium": {**strong_all, ROLE_REVIEWER: "medium"},
        "synthesizer_small": {**strong_all, ROLE_SYNTHESIZER: "small"},
        "synthesizer_medium": {**strong_all, ROLE_SYNTHESIZER: "medium"},
        "mixed_evidence_backed": {
            ROLE_PLANNER: "small",
            ROLE_REVIEWER: "medium",
            ROLE_SYNTHESIZER: "strong",
        },
    }


def parse_endpoints(
    endpoint_args: list[str],
    mock_llm: bool,
) -> dict[str, ModelEndpoint]:
    if mock_llm and not endpoint_args:
        return {
            tier: ModelEndpoint(
                tier=tier,
                base_url=f"mock://{tier}",
                served_model=str(data["model"]),
                relative_cost_weight=float(str(data["relative_cost_weight"])),
            )
            for tier, data in MODEL_LADDER.items()
        }
    endpoints: dict[str, ModelEndpoint] = {}
    for value in endpoint_args:
        tier, _, rest = value.partition("=")
        base_url, _, served_model = rest.partition(",")
        if tier not in MODEL_LADDER or not base_url or not served_model:
            raise ValueError(f"invalid endpoint mapping: {value}")
        endpoints[tier] = ModelEndpoint(
            tier=tier,
            base_url=base_url,
            served_model=served_model,
            relative_cost_weight=float(str(MODEL_LADDER[tier]["relative_cost_weight"])),
        )
    missing = sorted(set(MODEL_LADDER) - set(endpoints))
    if missing:
        raise ValueError(f"missing endpoint mapping for tiers: {', '.join(missing)}")
    return endpoints


def relative_cost(
    summary: dict[str, Any],
    routing: dict[str, str],
    endpoints: dict[str, ModelEndpoint],
) -> float:
    role_profiles = summary.get("role_profiles", {})
    total = 0.0
    for role, tier in routing.items():
        profile = role_profiles.get(role) or role_profiles.get(_legacy_role(role)) or {}
        tokens = int(profile.get("input_tokens", 0)) + int(profile.get("output_tokens", 0))
        total += tokens * endpoints[tier].relative_cost_weight
    return total / 1_000_000


def routed_mock_response(
    request_id: str,
    components: list[dict[str, Any]],
    max_tokens: int,
    semantic_role: str,
    tier: str,
) -> dict[str, Any]:
    response = mock_response(request_id, components, max_tokens)
    if tier == "small" and semantic_role == ROLE_SYNTHESIZER:
        text = "No evidence found."
        response["choices"] = [{"text": text, "token_ids": [0, 1, 2]}]
        response["usage"]["completion_tokens"] = 3
    if tier == "small" and semantic_role == ROLE_REVIEWER:
        text = " ".join(extract_output_text(response).split()[:16])
        response["choices"] = [{"text": text, "token_ids": list(range(max(1, len(text.split()))))}]
        response["usage"]["completion_tokens"] = max(1, len(text.split()))
    return response


def normalize_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)


def score_question(question: Question, answer: str) -> dict[str, Any]:
    from scripts.run_real_agent_context_waste import score_answer

    return score_answer(question, answer)


def collect_environment(mock_llm: bool, carry_strategy: str) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "mock" if mock_llm else "vllm",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "gpu": detect_gpu(),
        "agent_architecture": (
            "planner LLM -> local search -> evidence review LLM -> local search -> final LLM"
        ),
        "agent_framework": "none",
        "carry_strategy": carry_strategy,
    }


def detect_gpu() -> str | None:
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


def _legacy_role(role: str) -> str:
    if role == ROLE_REVIEWER:
        return "evidence-review"
    if role == ROLE_SYNTHESIZER:
        return "final"
    return role


if __name__ == "__main__":
    raise SystemExit(main())
