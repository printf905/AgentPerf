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


@dataclass
class AgentExecution:
    records: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    answers: list[dict[str, Any]]


class LocalSearchTool:
    def __init__(self, corpus_dir: Path) -> None:
        self.documents = load_documents(corpus_dir)

    def search(self, query: str, *, compact: bool) -> tuple[str, list[str]]:
        terms = {term.lower() for term in query.replace("-", " ").split() if len(term) > 2}
        ranked = sorted(
            self.documents,
            key=lambda doc: sum(term in doc.text.lower() for term in terms),
            reverse=True,
        )
        selected = ranked[:3]
        if compact:
            return self._compact_result(query, selected), [doc.doc_id for doc in selected]
        return self._raw_result(query, selected), [doc.doc_id for doc in selected]

    def _raw_result(self, query: str, documents: list[Document]) -> str:
        sections = [f"QUERY: {query}", "MODE: full raw result"]
        for rank, document in enumerate(documents, start=1):
            sections.extend(
                [
                    f"RESULT_RANK: {rank}",
                    f"DOC_ID: {document.doc_id}",
                    document.text,
                    "\n".join([RAW_RESULT_APPENDIX] * 18),
                ]
            )
        return "\n\n".join(sections)

    def _compact_result(self, query: str, documents: list[Document]) -> str:
        sections = [f"QUERY: {query}", "MODE: compact result"]
        for rank, document in enumerate(documents, start=1):
            fact_lines = [
                line
                for line in document.text.splitlines()
                if line.startswith(("DOC_ID:", "ANSWER_FACT:", "CITATION:"))
            ]
            sections.extend([f"RESULT_RANK: {rank}", "\n".join(fact_lines)])
        return "\n\n".join(sections)


class ResearchAgent:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        search_tool: LocalSearchTool,
        optimized: bool,
        mock_llm: bool,
        timeout: float,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.search_tool = search_tool
        self.optimized = optimized
        self.mock_llm = mock_llm
        self.timeout = timeout
        self.records: list[dict[str, Any]] = []
        self.tool_calls: list[dict[str, Any]] = []

    def answer(self, question: Question, question_index: int) -> str:
        history: list[str] = []
        raw_tool_results: list[tuple[str, str]] = []
        compact_tool_results: list[tuple[str, str]] = []

        planner = self._llm_step(
            step_id=f"q{question_index:02d}-step-1",
            llm_call_id=f"{question.id}-planner",
            role="planner",
            components=[
                component("system", SYSTEM_INSTRUCTIONS),
                component("tool_schemas", TOOL_SCHEMA),
                component("user", question.question),
            ],
        )
        history.append(f"Planner output:\n{planner}")

        first_tool_id = f"{question.id}-search-1"
        first_result, _ = self._tool_step(
            step_id=f"q{question_index:02d}-step-2",
            tool_call_id=first_tool_id,
            query=question.queries[0],
        )
        raw_tool_results.append((first_tool_id, first_result))
        compact_tool_results.append((first_tool_id, compact_tool_result(first_result)))

        review_result_text = self._carried_tool_text(raw_tool_results, compact_tool_results)
        review = self._llm_step(
            step_id=f"q{question_index:02d}-step-3",
            llm_call_id=f"{question.id}-review",
            role="evidence-review",
            components=[
                component("system", SYSTEM_INSTRUCTIONS),
                component("tool_schemas", TOOL_SCHEMA),
                component("history", "\n\n".join(history)),
                component(
                    "tool_results",
                    review_result_text,
                    source_tool_call_ids=[first_tool_id],
                ),
                component("user", "Extract the most relevant answer facts."),
            ],
        )
        history.append(f"Evidence review output:\n{review}")

        second_tool_id = f"{question.id}-search-2"
        second_result, _ = self._tool_step(
            step_id=f"q{question_index:02d}-step-4",
            tool_call_id=second_tool_id,
            query=question.queries[1],
        )
        raw_tool_results.append((second_tool_id, second_result))
        compact_tool_results.append((second_tool_id, compact_tool_result(second_result)))

        final_pairs = compact_tool_results if self.optimized else raw_tool_results
        final_components = [
            component("system", SYSTEM_INSTRUCTIONS),
            component("tool_schemas", TOOL_SCHEMA),
            component("history", "\n\n".join(history)),
        ]
        for tool_call_id, text in final_pairs:
            final_components.append(
                component(
                    "tool_results",
                    text,
                    source_tool_call_ids=[tool_call_id],
                )
            )
        final_components.append(
            component(
                "user",
                (
                    "Answer the original question. Include required facts and cite DOC_IDs. "
                    f"Original question: {question.question}"
                ),
            )
        )
        return self._llm_step(
            step_id=f"q{question_index:02d}-step-5",
            llm_call_id=f"{question.id}-final",
            role="final",
            components=final_components,
            max_tokens=192,
        )

    def _carried_tool_text(
        self,
        raw_results: list[tuple[str, str]],
        compact_results: list[tuple[str, str]],
    ) -> str:
        pairs = compact_results if self.optimized else raw_results
        return "\n\n".join(text for _, text in pairs)

    def _tool_step(
        self,
        *,
        step_id: str,
        tool_call_id: str,
        query: str,
    ) -> tuple[str, list[str]]:
        started = time.perf_counter()
        result, doc_ids = self.search_tool.search(query, compact=False)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.tool_calls.append(
            {
                "agent_step_id": step_id,
                "tool_call_id": tool_call_id,
                "name": "search",
                "input": {"query": query},
                "output": result,
                "latency_ms": elapsed_ms,
                "metadata": {
                    "retrieved_doc_ids": doc_ids,
                    "raw_output_tokens_approx": token_count(result),
                },
            }
        )
        return result, doc_ids

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
    args = parser.parse_args(argv)

    questions = load_questions(args.questions_path)
    search_tool = LocalSearchTool(args.corpus_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    environment = collect_environment(args.model, args.base_url, args.mock_llm)

    baseline = run_config(
        config_name="baseline_raw_tool_results",
        questions=questions,
        search_tool=search_tool,
        base_url=args.base_url,
        model=args.model,
        optimized=False,
        mock_llm=args.mock_llm,
        timeout=args.timeout,
        environment=environment,
    )
    optimized = run_config(
        config_name="optimized_compact_tool_results",
        questions=questions,
        search_tool=search_tool,
        base_url=args.base_url,
        model=args.model,
        optimized=True,
        mock_llm=args.mock_llm,
        timeout=args.timeout,
        environment=environment,
    )

    write_artifacts(args.output_dir, "baseline", baseline)
    write_artifacts(args.output_dir, "optimized", optimized)
    comparison = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "baseline": summarize_recording(baseline),
        "optimized": summarize_recording(optimized),
    }
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
    optimized: bool,
    mock_llm: bool,
    timeout: float,
    environment: dict[str, Any],
) -> dict[str, Any]:
    agent = ResearchAgent(
        base_url=base_url,
        model=model,
        search_tool=search_tool,
        optimized=optimized,
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
    prompt = "\n\n".join(
        f"## {component['name']}\n{component['text']}" for component in components
    )
    body = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
        "request_id": request_id,
        "return_token_ids": True,
        "return_prompt_text": True,
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


def component(
    name: str,
    text: str,
    *,
    source_tool_call_ids: list[str] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if source_tool_call_ids is not None:
        metadata["source_tool_call_ids"] = source_tool_call_ids
    return {"name": name, "text": text, "metadata": metadata}


def compact_tool_result(raw_result: str) -> str:
    keep_prefixes = ("QUERY:", "MODE:", "RESULT_RANK:", "DOC_ID:", "ANSWER_FACT:", "CITATION:")
    return "\n".join(
        line for line in raw_result.splitlines() if line.startswith(keep_prefixes)
    )


def score_answer(question: Question, answer: str) -> dict[str, Any]:
    lower = answer.lower()
    fact_hits = [
        fact for fact in question.required_facts if fact.lower() in lower
    ]
    doc_hits = [
        doc_id for doc_id in question.required_doc_ids if doc_id.lower() in lower
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
