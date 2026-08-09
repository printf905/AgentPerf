#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from agentperf.analyzer import analyze_run
from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.metrics.attribution import component_token_attribution
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import percentile, prefill_or_path_latency_ms
from agentperf.metrics.tokens import token_count
from agentperf.reporters.terminal import render_report
from agentperf.schema.trace import AgentRun

SYSTEM_INSTRUCTIONS = """You are a careful incident research agent.
Use only the local evidence passages supplied by tools.
Return concise answers with document IDs in brackets.
Preserve the cause, first mitigation, and owning team when available."""

TOOL_SCHEMA = """Tool: search(query: string) -> passages.
The search tool returns local corpus passages. Each passage may include DOC_ID,
ANSWER_FACT, and CITATION lines. Treat DOC_ID and ANSWER_FACT lines as primary
evidence. Do not invent facts that are not in the retrieved passages."""

RAW_RESULT_APPENDIX = """Operational appendix:
Check deployment history, queue depth, database saturation, cache evictions,
upstream provider health, regional routing, authentication cache state, and
owner escalation path. Prefer reversible mitigation before root-cause certainty.
Record the evidence source and avoid broad infrastructure changes when a narrow
rollback or cache flush is available."""

DEFAULT_STRATEGIES = [
    "raw_full",
    "dedup_only",
    "top_k_2",
    "budget_1200",
    "aggressive_compact",
]
QUALITY_MEAN_SCORE_TOLERANCE = 0.05
QUALITY_PASS_RATE_TOLERANCE = 0.10
QUALITY_COMPARISON_EPSILON = 1e-9
FINAL_MAX_TOKENS = 320
REVIEW_MAX_TOKENS = 160
PLANNER_MAX_TOKENS = 64


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    queries: list[str]
    required_facts: list[str]
    required_doc_ids: list[str]


@dataclass(frozen=True)
class Document:
    doc_id: str
    path: Path
    text: str


@dataclass(frozen=True)
class SearchHit:
    tool_call_id: str
    doc_id: str
    passage_id: str
    rank: int
    score: int
    text: str

    @property
    def original_tokens(self) -> int:
        return token_count(self.text)


@dataclass(frozen=True)
class ToolResultRecord:
    tool_call_id: str
    query: str
    raw_text: str
    hits: list[SearchHit]


@dataclass(frozen=True)
class CarriedComponent:
    tool_call_id: str
    text: str
    metadata: dict[str, Any]


@dataclass
class AgentExecution:
    records: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    answers: list[dict[str, Any]]


class LocalSearchTool:
    def __init__(self, corpus_dir: Path) -> None:
        self.documents = load_documents(corpus_dir)

    def search(self, query: str, *, tool_call_id: str) -> ToolResultRecord:
        terms = {term.lower() for term in query.replace("-", " ").split() if len(term) > 2}
        ranked_documents = sorted(
            self.documents,
            key=lambda doc: sum(term in doc.text.lower() for term in terms),
            reverse=True,
        )
        selected = ranked_documents[:3]
        hits = [
            SearchHit(
                tool_call_id=tool_call_id,
                doc_id=document.doc_id,
                passage_id=f"{document.doc_id}:full",
                rank=rank,
                score=sum(term in document.text.lower() for term in terms),
                text=document.text,
            )
            for rank, document in enumerate(selected, start=1)
        ]
        return ToolResultRecord(
            tool_call_id=tool_call_id,
            query=query,
            raw_text=self._raw_result(query, hits),
            hits=hits,
        )

    def _raw_result(self, query: str, hits: list[SearchHit]) -> str:
        sections = [f"QUERY: {query}", "MODE: full raw result"]
        for hit in hits:
            sections.extend(
                [
                    f"RESULT_RANK: {hit.rank}",
                    f"RETRIEVAL_SCORE: {hit.score}",
                    f"PASSAGE_ID: {hit.passage_id}",
                    f"DOC_ID: {hit.doc_id}",
                    hit.text,
                    "\n".join([RAW_RESULT_APPENDIX] * 18),
                ]
            )
        return "\n\n".join(sections)


class ResearchAgent:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        search_tool: LocalSearchTool,
        carry_strategy: str,
        mock_llm: bool,
        timeout: float,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.search_tool = search_tool
        self.carry_strategy = carry_strategy
        self.mock_llm = mock_llm
        self.timeout = timeout
        self.records: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.tool_result_records: dict[str, ToolResultRecord] = {}

    def answer(self, question: Question, question_index: int) -> str:
        history: list[str] = []
        tool_result_ids: list[str] = []

        planner = self._llm_step(
            step_id=f"q{question_index:02d}-step-1",
            llm_call_id=f"{question.id}-planner",
            role="planner",
            components=[
                component("system", SYSTEM_INSTRUCTIONS),
                component("tool_schemas", TOOL_SCHEMA),
                component(
                    "user",
                    (
                        "Plan only. Do not answer the question. Return exactly two "
                        "search query lines for the local search tool.\n"
                        f"Question: {question.question}"
                    ),
                ),
            ],
            max_tokens=PLANNER_MAX_TOKENS,
        )
        history.append(f"Planner output:\n{planner}")

        first_tool_id = f"{question.id}-search-1"
        self._tool_step(
            step_id=f"q{question_index:02d}-step-2",
            tool_call_id=first_tool_id,
            query=question.queries[0],
        )
        tool_result_ids.append(first_tool_id)

        review_components = self._carried_tool_components([first_tool_id])
        review = self._llm_step(
            step_id=f"q{question_index:02d}-step-3",
            llm_call_id=f"{question.id}-review",
            role="evidence-review",
            components=[
                component("system", SYSTEM_INSTRUCTIONS),
                component("tool_schemas", TOOL_SCHEMA),
                component("history", "\n\n".join(history)),
                *[
                    component(
                        "tool_results",
                        carried.text,
                        source_tool_call_ids=[carried.tool_call_id],
                        metadata=carried.metadata,
                    )
                    for carried in review_components
                ],
                component(
                    "user",
                    (
                        "Copy only relevant DOC_ID, ANSWER_FACT, and CITATION lines "
                        "from the tool results. Do not add facts not present in those lines."
                    ),
                ),
            ],
            max_tokens=REVIEW_MAX_TOKENS,
        )
        history.append(f"Evidence review output:\n{review}")

        second_tool_id = f"{question.id}-search-2"
        self._tool_step(
            step_id=f"q{question_index:02d}-step-4",
            tool_call_id=second_tool_id,
            query=question.queries[1],
        )
        tool_result_ids.append(second_tool_id)

        final_components = [
            component("system", SYSTEM_INSTRUCTIONS),
            component("tool_schemas", TOOL_SCHEMA),
            component("history", "\n\n".join(history)),
        ]
        for carried in self._carried_tool_components(tool_result_ids):
            final_components.append(
                component(
                    "tool_results",
                    carried.text,
                    source_tool_call_ids=[carried.tool_call_id],
                    metadata=carried.metadata,
                )
            )
        final_components.append(
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
            )
        )
        return self._llm_step(
            step_id=f"q{question_index:02d}-step-5",
            llm_call_id=f"{question.id}-final",
            role="final",
            components=final_components,
            max_tokens=FINAL_MAX_TOKENS,
        )

    def _tool_step(
        self,
        *,
        step_id: str,
        tool_call_id: str,
        query: str,
    ) -> ToolResultRecord:
        started = time.perf_counter()
        result = self.search_tool.search(query, tool_call_id=tool_call_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.tool_result_records[tool_call_id] = result
        self.tool_calls.append(
            {
                "agent_step_id": step_id,
                "tool_call_id": tool_call_id,
                "name": "search",
                "input": {"query": query},
                "output": result.raw_text,
                "latency_ms": elapsed_ms,
                "metadata": {
                    "retrieved_doc_ids": [hit.doc_id for hit in result.hits],
                    "raw_output_tokens_approx": token_count(result.raw_text),
                    "evidence_items": [evidence_metadata(hit) for hit in result.hits],
                },
            }
        )
        return result

    def _carried_tool_components(self, tool_call_ids: list[str]) -> list[CarriedComponent]:
        records = [self.tool_result_records[tool_id] for tool_id in tool_call_ids]
        if self.carry_strategy == "raw_full":
            return [raw_carried_component(record, self.carry_strategy) for record in records]
        if self.carry_strategy == "aggressive_compact":
            return [
                compact_carried_component(record, self.carry_strategy)
                for record in records
            ]
        if self.carry_strategy == "dedup_only":
            return dedup_carried_components(records, self.carry_strategy)
        if self.carry_strategy.startswith("top_k_"):
            top_k = int(self.carry_strategy.rsplit("_", 1)[1])
            return ranked_carried_components(
                records,
                self.carry_strategy,
                top_k=top_k,
                token_budget=None,
            )
        if self.carry_strategy.startswith("budget_"):
            budget = int(self.carry_strategy.rsplit("_", 1)[1])
            return ranked_carried_components(
                records,
                self.carry_strategy,
                top_k=None,
                token_budget=budget,
            )
        raise ValueError(f"unknown carry strategy: {self.carry_strategy}")

    def _llm_step(
        self,
        *,
        step_id: str,
        llm_call_id: str,
        role: str,
        components: list[dict[str, Any]],
        max_tokens: int = 96,
    ) -> str:
        request_id = f"agentperf-m3-{llm_call_id}-{uuid4().hex[:8]}"
        trace_id = uuid4().hex
        started = time.perf_counter()
        response = (
            mock_response(request_id, components, max_tokens)
            if self.mock_llm
            else call_vllm(
                base_url=self.base_url,
                model=self.model,
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
                "prompt_components": components,
                "client_elapsed_ms": elapsed_ms,
                "response": response,
                "output_text": extract_output_text(response),
                "metadata": {"role": role},
            }
        )
        return extract_output_text(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real agent context-waste demo")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--corpus-dir", type=Path, default=Path("docs/corpus"))
    parser.add_argument(
        "--questions-path",
        type=Path,
        default=Path("docs/corpus/questions.json"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/real_agent_m3"))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--mock-llm", action="store_true")
    parser.add_argument(
        "--strategies",
        default=",".join(DEFAULT_STRATEGIES),
        help="Comma-separated context carry strategies to run.",
    )
    args = parser.parse_args(argv)

    questions = load_questions(args.questions_path)
    search_tool = LocalSearchTool(args.corpus_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    environment = collect_environment(args.model, args.base_url, args.mock_llm)
    strategies = [strategy.strip() for strategy in args.strategies.split(",") if strategy.strip()]

    recordings = {}
    for strategy in strategies:
        recording = run_config(
            config_name=strategy,
            questions=questions,
            search_tool=search_tool,
            base_url=args.base_url,
            model=args.model,
            carry_strategy=strategy,
            mock_llm=args.mock_llm,
            timeout=args.timeout,
            environment=environment,
        )
        recordings[strategy] = recording
        write_artifacts(args.output_dir, strategy, recording)

    strategies_summary = {
        strategy: summarize_recording(recording)
        for strategy, recording in recordings.items()
    }
    comparison: dict[str, Any] = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "strategies": strategies_summary,
    }
    if "raw_full" in recordings:
        comparison["baseline"] = strategies_summary["raw_full"]
    if "aggressive_compact" in recordings:
        comparison["optimized"] = strategies_summary["aggressive_compact"]
    comparison["pareto"] = pareto_summary(strategies_summary)
    comparison["quality_constraint"] = quality_constraint_summary(strategies_summary)
    (args.output_dir / "comparison.json").write_text(
        json.dumps(comparison, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote real-agent context-waste artifacts to {args.output_dir}")
    return 0


def run_config(
    *,
    config_name: str,
    questions: list[Question],
    search_tool: LocalSearchTool,
    base_url: str,
    model: str,
    carry_strategy: str,
    mock_llm: bool,
    timeout: float,
    environment: dict[str, Any],
) -> dict[str, Any]:
    agent = ResearchAgent(
        base_url=base_url,
        model=model,
        search_tool=search_tool,
        carry_strategy=carry_strategy,
        mock_llm=mock_llm,
        timeout=timeout,
    )
    answers = []
    for index, question in enumerate(questions):
        answer = agent.answer(question, index)
        answers.append(score_answer(question, answer))
    return {
        "agent_run_id": config_name,
        "name": config_name,
        "model": model,
        "environment": environment,
        "records": agent.records,
        "tool_calls": agent.tool_calls,
        "answers": answers,
    }


def write_artifacts(output_dir: Path, name: str, recording: dict[str, Any]) -> None:
    raw_dir = output_dir / name / "raw"
    normalized_dir = output_dir / name / "normalized"
    raw_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    recording_path = raw_dir / "recording.json"
    trace_path = normalized_dir / "trace.json"
    report_path = output_dir / name / "report.txt"
    recording_path.write_text(json.dumps(recording, indent=2), encoding="utf-8")
    run = VLLMTelemetryProvider().build_run(recording)
    trace_path.write_text(json.dumps(agent_run_to_json(run), indent=2), encoding="utf-8")
    report = analyze_run(run)
    report_path.write_text(render_report(report, show_provenance=True), encoding="utf-8")


def summarize_recording(recording: dict[str, Any]) -> dict[str, Any]:
    run = VLLMTelemetryProvider().build_run(recording)
    report = analyze_run(run)
    attribution = component_token_attribution(run)
    serving = run.serving_requests
    ttfts = [request.ttft_ms for request in serving if request.ttft_ms is not None]
    client_latencies = [
        float(record["client_elapsed_ms"])
        for record in recording.get("records", [])
        if isinstance(record, dict) and record.get("client_elapsed_ms") is not None
    ]
    answers = [
        answer for answer in recording.get("answers", []) if isinstance(answer, dict)
    ]
    return {
        "questions": len(answers),
        "correctness": correctness(answers),
        "llm_calls": len(run.llm_calls),
        "tool_calls": len(run.tool_calls),
        "input_tokens": sum(request.input_tokens or 0 for request in serving),
        "output_tokens": sum(request.output_tokens or 0 for request in serving),
        "component_processed_tokens": attribution.total_processed_tokens,
        "component_unique_tokens": attribution.total_unique_tokens,
        "processed_tokens_by_component": attribution.processed_tokens_by_component,
        "unique_tokens_by_component": attribution.unique_tokens_by_component,
        "prefix_cache_hit_ratio": prefix_cache_hit_ratio(serving),
        "ttft_p50_ms": percentile([float(value) for value in ttfts], 0.50),
        "ttft_p95_ms": percentile([float(value) for value in ttfts], 0.95),
        "prefill_or_path_latency_ms": sum(
            prefill_or_path_latency_ms(request) or 0 for request in serving
        ),
        "client_latency_p50_ms": percentile(client_latencies, 0.50),
        "client_latency_p95_ms": percentile(client_latencies, 0.95),
        "detectors_fired": [finding.id for finding in report.findings],
        "compaction": summarize_compaction(recording),
    }


def call_vllm(
    *,
    base_url: str,
    model: str,
    request_id: str,
    trace_id: str,
    components: list[dict[str, Any]],
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    prompt = chat_prompt_from_components(components)
    body = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
        "request_id": request_id,
        "return_token_ids": True,
        "return_prompt_text": True,
        "stop": ["<|im_end|>"],
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "traceparent": f"00-{trace_id}-{uuid4().hex[:16]}-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8")) from exc


def mock_response(
    request_id: str,
    components: list[dict[str, Any]],
    max_tokens: int,
) -> dict[str, Any]:
    prompt = "\n\n".join(str(component["text"]) for component in components)
    text = " ".join(_answer_fact_lines(prompt)[:6]) or "No evidence found."
    prompt_tokens = token_count(prompt)
    output_tokens = min(max(1, token_count(text)), max_tokens)
    return {
        "id": f"mock-{request_id}",
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
        "prompt_token_ids": list(range(prompt_tokens)),
        "choices": [{"text": text, "token_ids": list(range(output_tokens))}],
        "metrics": {
            "queue_time_ms": 0.0,
            "time_to_first_token_ms": prompt_tokens * 0.02,
            "generation_time_ms": output_tokens * 0.5,
            "mean_itl_ms": 0.5,
        },
    }


def chat_prompt_from_components(components: list[dict[str, Any]]) -> str:
    system_text = "\n\n".join(
        str(component["text"])
        for component in components
        if component.get("name") == "system"
    )
    user_blocks = [
        f"### {component['name']}\n{component['text']}"
        for component in components
        if component.get("name") != "system"
    ]
    user_text = "\n\n".join(user_blocks)
    return (
        "<|im_start|>system\n"
        f"{system_text}\n"
        "<|im_end|>\n"
        "<|im_start|>user\n"
        f"{user_text}\n"
        "<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def component(
    name: str,
    text: str,
    *,
    source_tool_call_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    component_metadata: dict[str, Any] = dict(metadata or {})
    if source_tool_call_ids is not None:
        component_metadata["source_tool_call_ids"] = source_tool_call_ids
    return {"name": name, "text": text, "metadata": component_metadata}


def raw_carried_component(record: ToolResultRecord, strategy: str) -> CarriedComponent:
    return CarriedComponent(
        tool_call_id=record.tool_call_id,
        text=record.raw_text,
        metadata=carry_metadata(
            strategy=strategy,
            record=record,
            carried_hits=record.hits,
            carried_text=record.raw_text,
            dropped_duplicate_tokens=0,
            dropped_low_rank_tokens=0,
        ),
    )


def compact_carried_component(record: ToolResultRecord, strategy: str) -> CarriedComponent:
    text = compact_tool_result(record.raw_text)
    return CarriedComponent(
        tool_call_id=record.tool_call_id,
        text=text,
        metadata=carry_metadata(
            strategy=strategy,
            record=record,
            carried_hits=record.hits,
            carried_text=text,
            dropped_duplicate_tokens=0,
            dropped_low_rank_tokens=max(
                0,
                token_count(record.raw_text) - token_count(text),
            ),
        ),
    )


def dedup_carried_components(
    records: list[ToolResultRecord],
    strategy: str,
) -> list[CarriedComponent]:
    seen_passages: set[str] = set()
    components: list[CarriedComponent] = []
    for record in records:
        carried_hits = []
        duplicate_tokens = 0
        for hit in record.hits:
            if hit.passage_id in seen_passages:
                duplicate_tokens += hit.original_tokens
                continue
            seen_passages.add(hit.passage_id)
            carried_hits.append(hit)
        if not carried_hits:
            continue
        text = format_evidence_result(
            record.query,
            strategy,
            carried_hits,
            include_appendix=True,
        )
        components.append(
            CarriedComponent(
                tool_call_id=record.tool_call_id,
                text=text,
                metadata=carry_metadata(
                    strategy=strategy,
                    record=record,
                    carried_hits=carried_hits,
                    carried_text=text,
                    dropped_duplicate_tokens=duplicate_tokens,
                    dropped_low_rank_tokens=0,
                ),
            )
        )
    return components


def ranked_carried_components(
    records: list[ToolResultRecord],
    strategy: str,
    *,
    top_k: int | None,
    token_budget: int | None,
) -> list[CarriedComponent]:
    ranked_hits = sorted(
        (hit for record in records for hit in record.hits),
        key=lambda hit: (hit.score, -hit.rank),
        reverse=True,
    )
    seen_passages: set[str] = set()
    selected: list[SearchHit] = []
    duplicate_tokens = 0
    low_rank_tokens = 0
    used_tokens = 0
    for hit in ranked_hits:
        if hit.passage_id in seen_passages:
            duplicate_tokens += hit.original_tokens
            continue
        seen_passages.add(hit.passage_id)
        if top_k is not None and len(selected) >= top_k:
            low_rank_tokens += hit.original_tokens
            continue
        if (
            token_budget is not None
            and selected
            and used_tokens + hit.original_tokens > token_budget
        ):
            low_rank_tokens += hit.original_tokens
            continue
        selected.append(hit)
        used_tokens += hit.original_tokens

    by_tool_call: dict[str, list[SearchHit]] = {}
    for hit in selected:
        by_tool_call.setdefault(hit.tool_call_id, []).append(hit)

    components = []
    for record in records:
        carried_hits = by_tool_call.get(record.tool_call_id, [])
        if not carried_hits:
            continue
        text = format_evidence_result(
            record.query,
            strategy,
            sorted(carried_hits, key=lambda hit: hit.rank),
            include_appendix=False,
        )
        components.append(
            CarriedComponent(
                tool_call_id=record.tool_call_id,
                text=text,
                metadata=carry_metadata(
                    strategy=strategy,
                    record=record,
                    carried_hits=carried_hits,
                    carried_text=text,
                    dropped_duplicate_tokens=duplicate_tokens,
                    dropped_low_rank_tokens=low_rank_tokens,
                ),
            )
        )
        duplicate_tokens = 0
        low_rank_tokens = 0
    return components


def format_evidence_result(
    query: str,
    mode: str,
    hits: list[SearchHit],
    *,
    include_appendix: bool,
) -> str:
    sections = [f"QUERY: {query}", f"MODE: {mode}"]
    for hit in hits:
        body = hit.text
        if include_appendix:
            body = "\n\n".join([body, "\n".join([RAW_RESULT_APPENDIX] * 18)])
        sections.extend(
            [
                f"RESULT_RANK: {hit.rank}",
                f"RETRIEVAL_SCORE: {hit.score}",
                f"PASSAGE_ID: {hit.passage_id}",
                f"DOC_ID: {hit.doc_id}",
                body,
            ]
        )
    return "\n\n".join(sections)


def carry_metadata(
    *,
    strategy: str,
    record: ToolResultRecord,
    carried_hits: list[SearchHit],
    carried_text: str,
    dropped_duplicate_tokens: int,
    dropped_low_rank_tokens: int,
) -> dict[str, Any]:
    original_tokens = token_count(record.raw_text)
    carried_tokens = token_count(carried_text)
    return {
        "carry_strategy": strategy,
        "tool_call_id": record.tool_call_id,
        "original_token_count": original_tokens,
        "carried_forward_token_count": carried_tokens,
        "dropped_duplicate_tokens": dropped_duplicate_tokens,
        "dropped_low_rank_tokens": dropped_low_rank_tokens,
        "evidence_items": [
            {
                **evidence_metadata(hit),
                "carried_forward_token_count": hit.original_tokens,
            }
            for hit in carried_hits
        ],
    }


def evidence_metadata(hit: SearchHit) -> dict[str, Any]:
    return {
        "source_document_id": hit.doc_id,
        "tool_call_id": hit.tool_call_id,
        "passage_id": hit.passage_id,
        "retrieval_rank": hit.rank,
        "retrieval_score": hit.score,
        "original_token_count": hit.original_tokens,
    }


def compact_tool_result(raw_result: str) -> str:
    keep_prefixes = ("QUERY:", "MODE:", "RESULT_RANK:", "DOC_ID:", "ANSWER_FACT:", "CITATION:")
    return "\n".join(
        line for line in raw_result.splitlines() if line.startswith(keep_prefixes)
    )


def summarize_compaction(recording: dict[str, Any]) -> dict[str, Any]:
    totals = {
        "carried_forward_tokens": 0,
        "original_tokens": 0,
        "dropped_duplicate_tokens": 0,
        "dropped_low_rank_tokens": 0,
    }
    for record in recording.get("records", []):
        if not isinstance(record, dict):
            continue
        for component_data in record.get("prompt_components", []):
            if not isinstance(component_data, dict):
                continue
            metadata = component_data.get("metadata", {})
            if not isinstance(metadata, dict) or "carry_strategy" not in metadata:
                continue
            totals["carried_forward_tokens"] += int(
                metadata.get("carried_forward_token_count", 0)
            )
            totals["original_tokens"] += int(metadata.get("original_token_count", 0))
            totals["dropped_duplicate_tokens"] += int(
                metadata.get("dropped_duplicate_tokens", 0)
            )
            totals["dropped_low_rank_tokens"] += int(
                metadata.get("dropped_low_rank_tokens", 0)
            )
    return totals


def pareto_summary(strategies: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, summary in strategies.items():
        correctness_summary = summary["correctness"]
        rows.append(
            {
                "strategy": name,
                "mean_score": correctness_summary["mean_score"],
                "pass_rate": correctness_summary["pass_rate"],
                "input_tokens": summary["input_tokens"],
                "tool_result_tokens": summary["processed_tokens_by_component"].get(
                    "tool_result",
                    0,
                ),
                "ttft_p95_ms": summary["ttft_p95_ms"],
                "client_latency_p95_ms": summary["client_latency_p95_ms"],
                "dominated": False,
            }
        )
    for row in rows:
        for other in rows:
            if other is row:
                continue
            other_ttft = other["ttft_p95_ms"] or float("inf")
            row_ttft = row["ttft_p95_ms"] or float("inf")
            if (
                other["mean_score"] >= row["mean_score"]
                and other["input_tokens"] <= row["input_tokens"]
                and other_ttft <= row_ttft
                and (
                    other["mean_score"] > row["mean_score"]
                    or other["input_tokens"] < row["input_tokens"]
                    or other_ttft < row_ttft
                )
            ):
                row["dominated"] = True
                break
    return rows


def quality_constraint_summary(strategies: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = strategies.get("raw_full")
    if baseline is None:
        return {
            "baseline_strategy": None,
            "mean_score_tolerance": QUALITY_MEAN_SCORE_TOLERANCE,
            "pass_rate_tolerance": QUALITY_PASS_RATE_TOLERANCE,
            "eligible_strategies": [],
            "selected_strategy": None,
        }
    baseline_correctness = baseline["correctness"]
    min_mean_score = baseline_correctness["mean_score"] - QUALITY_MEAN_SCORE_TOLERANCE
    min_pass_rate = baseline_correctness["pass_rate"] - QUALITY_PASS_RATE_TOLERANCE
    eligible = []
    for name, summary in strategies.items():
        correctness_summary = summary["correctness"]
        if (
            correctness_summary["mean_score"] + QUALITY_COMPARISON_EPSILON
            >= min_mean_score
            and correctness_summary["pass_rate"] + QUALITY_COMPARISON_EPSILON
            >= min_pass_rate
        ):
            eligible.append(
                {
                    "strategy": name,
                    "mean_score": correctness_summary["mean_score"],
                    "pass_rate": correctness_summary["pass_rate"],
                    "input_tokens": summary["input_tokens"],
                    "tool_result_tokens": summary["processed_tokens_by_component"].get(
                        "tool_result",
                        0,
                    ),
                    "ttft_p95_ms": summary["ttft_p95_ms"],
                    "client_latency_p95_ms": summary["client_latency_p95_ms"],
                }
            )
    selected = min(eligible, key=lambda row: row["input_tokens"])["strategy"] if eligible else None
    return {
        "baseline_strategy": "raw_full",
        "mean_score_tolerance": QUALITY_MEAN_SCORE_TOLERANCE,
        "pass_rate_tolerance": QUALITY_PASS_RATE_TOLERANCE,
        "minimum_mean_score": min_mean_score,
        "minimum_pass_rate": min_pass_rate,
        "eligible_strategies": eligible,
        "selected_strategy": selected,
        "objective": (
            "minimize processed input tokens subject to mean_score >= "
            "baseline - tolerance and pass_rate >= baseline - tolerance"
        ),
    }


def score_answer(question: Question, answer: str) -> dict[str, Any]:
    normalized = normalize_for_score(answer)
    fact_hits = [
        fact for fact in question.required_facts if fact_matches(fact, normalized)
    ]
    doc_hits = [
        doc_id
        for doc_id in question.required_doc_ids
        if normalize_for_score(doc_id) in normalized
    ]
    required = len(question.required_facts) + len(question.required_doc_ids)
    hits = len(fact_hits) + len(doc_hits)
    return {
        "question_id": question.id,
        "score": hits / required if required else 1.0,
        "passed": hits == required,
        "fact_hits": fact_hits,
        "doc_id_hits": doc_hits,
        "answer": answer,
    }


def normalize_for_score(text: str) -> str:
    return " ".join(
        text.lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace(":", " ")
        .replace(".", " ")
        .replace(",", " ")
        .replace(";", " ")
        .replace("(", " ")
        .replace(")", " ")
        .split()
    )


def fact_matches(required_fact: str, normalized_answer: str) -> bool:
    normalized_fact = normalize_for_score(required_fact)
    if normalized_fact in normalized_answer:
        return True
    fact_terms = [term for term in normalized_fact.split() if len(term) > 2]
    if not fact_terms:
        return False
    return all(term in normalized_answer for term in fact_terms)


def correctness(answers: list[dict[str, Any]]) -> dict[str, float]:
    if not answers:
        return {"pass_rate": 0.0, "mean_score": 0.0}
    return {
        "pass_rate": sum(1 for answer in answers if answer.get("passed")) / len(answers),
        "mean_score": sum(float(answer.get("score", 0.0)) for answer in answers)
        / len(answers),
    }


def load_questions(path: Path) -> list[Question]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Question(
            id=str(item["id"]),
            question=str(item["question"]),
            queries=[str(query) for query in item["queries"]],
            required_facts=[str(fact) for fact in item["required_facts"]],
            required_doc_ids=[str(doc_id) for doc_id in item["required_doc_ids"]],
        )
        for item in data
    ]


def load_documents(corpus_dir: Path) -> list[Document]:
    documents = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_id = path.stem.replace("_", "-")
        for line in text.splitlines():
            if line.startswith("DOC_ID:"):
                doc_id = line.split(":", 1)[1].strip()
                break
        documents.append(Document(doc_id=doc_id, path=path, text=text))
    return documents


def extract_output_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    if first.get("text") is not None:
        return str(first.get("text") or "")
    message = first.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return ""


def collect_environment(model: str, base_url: str, mock_llm: bool) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "mock" if mock_llm else "vllm",
        "base_url": base_url,
        "model": model,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "gpu": detect_gpu(),
        "agent_architecture": (
            "planner LLM -> local search -> evidence review LLM -> local search -> final LLM"
        ),
        "agent_framework": "none",
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


def _answer_fact_lines(prompt: str) -> list[str]:
    return [
        line
        for line in prompt.splitlines()
        if line.startswith(("DOC_ID:", "ANSWER_FACT:"))
    ]


def agent_run_to_json(run: AgentRun) -> dict[str, Any]:
    return {
        "schema_version": run.schema_version,
        "synthetic": run.synthetic,
        "agent_run": {
            "agent_run_id": run.agent_run_id,
            "name": run.name,
            "metadata": run.metadata,
            "steps": [
                {
                    "agent_step_id": step.agent_step_id,
                    "llm_calls": [
                        {
                            "llm_call_id": call.llm_call_id,
                            "llm_request_id": call.llm_request_id,
                            "serving_request_id": call.serving_request_id,
                            "model": call.model,
                            "provider": call.provider,
                            "backend": call.backend,
                            "prompt": [
                                {
                                    "name": component.name,
                                    "text": component.text,
                                    "metadata": component.metadata,
                                }
                                for component in call.prompt_components
                            ],
                            "input_tokens": call.input_tokens,
                            "output_tokens": call.output_tokens,
                            "prompt_token_ids": call.prompt_token_ids,
                            "output_token_ids": call.output_token_ids,
                            "tokenization_mode": call.tokenization_mode,
                        }
                        for call in step.llm_calls
                    ],
                    "tool_calls": [
                        {
                            "tool_call_id": tool.tool_call_id,
                            "name": tool.name,
                            "latency_ms": tool.latency_ms,
                            "input": tool.input,
                            "output": tool.output,
                            "metadata": tool.metadata,
                        }
                        for tool in step.tool_calls
                    ],
                }
                for step in run.steps
            ],
        },
        "serving_requests": [
            {
                "serving_request_id": request.serving_request_id,
                "llm_request_id": request.llm_request_id,
                "model": request.model,
                "backend": request.backend,
                "queue_latency_ms": request.queue_latency_ms,
                "prefill_latency_ms": request.prefill_latency_ms,
                "prefill_path_latency_ms": request.prefill_path_latency_ms,
                "decode_latency_ms": request.decode_latency_ms,
                "ttft_ms": request.ttft_ms,
                "tpot_ms": request.tpot_ms,
                "input_tokens": request.input_tokens,
                "output_tokens": request.output_tokens,
                "prefix_cache_hit_tokens": request.prefix_cache_hit_tokens,
                "prefix_cache_miss_tokens": request.prefix_cache_miss_tokens,
                "tokenization_mode": request.tokenization_mode,
                "metadata": request.metadata,
            }
            for request in run.serving_requests
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
