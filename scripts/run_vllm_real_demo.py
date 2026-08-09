#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from agentperf.analyzer import analyze_run
from agentperf.backends.vllm import VLLMTelemetryProvider
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import percentile, prefill_or_path_latency_ms
from agentperf.reporters.terminal import render_report
from agentperf.schema.trace import AgentRun

STABLE_POLICY = " ".join(
    [
        "You are an internal incident analyst.",
        "Use the runbook exactly.",
        "Preserve customer safety.",
        "Return a compact JSON object.",
        "Check service impact, blast radius, mitigation, owner, and next action.",
    ]
    * 24
)

RUNBOOK = " ".join(
    [
        "Runbook section:",
        "If error rate rises, inspect deploy history, recent config changes, queue depth,",
        "database saturation, cache evictions, and upstream dependency health.",
        "Prefer reversible mitigation before root-cause certainty.",
    ]
    * 16
)

TASKS = [
    "Incident A has rising HTTP 503s after a cache rollout. Choose the first mitigation.",
    "Incident B has delayed jobs and elevated database CPU. Choose the first mitigation.",
    "Incident C has one-region latency and clean deploy history. Choose the first mitigation.",
]

STABLE_TARGET_TOKENS = 8192


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AgentPerf's vLLM real telemetry demo")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/real_vllm_demo"))
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    environment = collect_environment(args.model, args.base_url, args.warmups, args.repetitions)
    stable_context, stable_tokens = build_stable_context(
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        target_tokens=STABLE_TARGET_TOKENS,
        timeout=args.timeout,
    )
    environment["stable_context_target_tokens"] = STABLE_TARGET_TOKENS
    environment["stable_context_observed_tokens"] = stable_tokens

    baseline_records = run_config(
        config_name="baseline_inefficient",
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        repetitions=args.warmups + args.repetitions,
        warmups=args.warmups,
        timeout=args.timeout,
        improved=False,
        stable_context=stable_context,
    )
    improved_records = run_config(
        config_name="improved_stable_prefix",
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        repetitions=args.warmups + args.repetitions,
        warmups=args.warmups,
        timeout=args.timeout,
        improved=True,
        stable_context=stable_context,
    )

    baseline = build_recording("real-vllm-baseline", args.model, environment, baseline_records)
    improved = build_recording("real-vllm-improved", args.model, environment, improved_records)

    (args.output_dir / "environment.json").write_text(
        json.dumps(environment, indent=2),
        encoding="utf-8",
    )

    write_artifacts(args.output_dir, "baseline", baseline)
    write_artifacts(args.output_dir, "optimized", improved)
    compare_path = args.output_dir / "comparison.json"
    compare_path.write_text(
        json.dumps(
            {
                "created_at": datetime.now(UTC).isoformat(),
                "environment": environment,
                "baseline": summarize_recording(baseline),
                "improved": summarize_recording(improved),
                "quality_observation": (
                    "Manual review required. Runner records outputs but does not grade quality."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote real vLLM demo artifacts to {args.output_dir}")
    return 0


def run_config(
    *,
    config_name: str,
    base_url: str,
    model: str,
    api_key: str,
    repetitions: int,
    warmups: int,
    timeout: float,
    improved: bool,
    stable_context: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rep in range(repetitions):
        for task_index, task in enumerate(TASKS):
            measured = rep >= warmups
            request_id = f"agentperf-{config_name}-{rep}-{task_index}-{uuid4().hex[:8]}"
            trace_id = uuid4().hex
            prompt_components = build_prompt_components(
                build_dynamic_task(task, request_id),
                stable_context=stable_context,
                improved=improved,
            )
            started = time.perf_counter()
            response = call_vllm(
                base_url=base_url,
                api_key=api_key,
                model=model,
                request_id=request_id,
                trace_id=trace_id,
                prompt_components=prompt_components,
                timeout=timeout,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            records.append(
                {
                    "measured": measured,
                    "config": config_name,
                    "repetition": rep,
                    "task_index": task_index,
                    "llm_call_id": f"{config_name}-llm-{rep}-{task_index}",
                    "agent_step_id": f"{config_name}-step-{rep}",
                    "trace_id": trace_id,
                    "client_request_id": request_id,
                    "request_id": response.get("id", request_id),
                    "prompt_components": prompt_components,
                    "client_elapsed_ms": elapsed_ms,
                    "response": response,
                    "output_text": extract_output_text(response),
                }
            )
    return [record for record in records if record["measured"]]


def build_prompt_components(
    task: str,
    *,
    stable_context: str,
    improved: bool,
) -> dict[str, str]:
    if improved:
        return {
            "stable_context": stable_context,
            "dynamic_request": task,
        }
    return {
        "dynamic_request": task,
        "stable_context": stable_context,
    }


def build_dynamic_task(task: str, request_id: str) -> str:
    return "\n".join(
        [
            "Analyze the incident and return compact JSON with keys:",
            "impact, mitigation, owner, next_action.",
            f"Request nonce: {request_id}",
            f"Task: {task}",
        ]
    )


def build_stable_context(
    *,
    base_url: str,
    model: str,
    api_key: str,
    target_tokens: int,
    timeout: float,
) -> tuple[str, int]:
    section = "\n".join([STABLE_POLICY, RUNBOOK])
    repeats = 1
    stable_context = section
    token_count = count_prompt_tokens(
        base_url=base_url,
        model=model,
        api_key=api_key,
        prompt=stable_context,
        timeout=timeout,
    )
    while token_count < target_tokens:
        repeats *= 2
        stable_context = "\n\n".join([section] * repeats)
        token_count = count_prompt_tokens(
            base_url=base_url,
            model=model,
            api_key=api_key,
            prompt=stable_context,
            timeout=timeout,
        )
    print(
        f"Built stable context with {token_count} prompt tokens "
        f"(target {target_tokens}, repeats {repeats})"
    )
    return stable_context, token_count


def count_prompt_tokens(
    *,
    base_url: str,
    model: str,
    api_key: str,
    prompt: str,
    timeout: float,
) -> int:
    body = {"model": model, "prompt": prompt}
    errors: list[str] = []
    for url in tokenize_urls(base_url):
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                break
        except urllib.error.HTTPError as exc:
            errors.append(f"{url}: {exc.code} {exc.read().decode('utf-8')}")
    else:
        raise RuntimeError("No vLLM tokenize endpoint succeeded: " + "; ".join(errors))

    tokens = payload.get("tokens")
    if isinstance(tokens, list):
        return len(tokens)
    count = payload.get("count")
    if isinstance(count, int):
        return count
    raise RuntimeError(f"Unexpected tokenize response shape: {payload}")


def tokenize_urls(base_url: str) -> list[str]:
    normalized = base_url.rstrip("/")
    urls = [f"{normalized}/tokenize"]
    if normalized.endswith("/v1"):
        urls.append(f"{normalized[:-3]}/tokenize")
    return urls


def call_vllm(
    *,
    base_url: str,
    api_key: str,
    model: str,
    request_id: str,
    trace_id: str,
    prompt_components: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    prompt = "\n\n".join(prompt_components.values())
    body = {
        "model": model,
        "prompt": prompt,
        "max_tokens": 8,
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
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8")) from exc


def build_recording(
    run_id: str,
    model: str,
    environment: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "agent_run_id": run_id,
        "name": run_id,
        "model": model,
        "environment": environment,
        "records": records,
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
    trace_path.write_text(json.dumps(_agent_run_to_json(run), indent=2), encoding="utf-8")
    report = analyze_run(run)
    report_path.write_text(render_report(report, show_provenance=True), encoding="utf-8")


def summarize_recording(recording: dict[str, Any]) -> dict[str, Any]:
    run = VLLMTelemetryProvider().build_run(recording)
    report = analyze_run(run)
    return {
        "requests": len(recording.get("records", [])),
        "input_tokens": sum(request.input_tokens or 0 for request in run.serving_requests),
        "output_tokens": sum(request.output_tokens or 0 for request in run.serving_requests),
        "prefix_cache_hit_ratio": prefix_cache_hit_ratio(run.serving_requests),
        "prefix_cache_hit_tokens": sum(
            request.prefix_cache_hit_tokens or 0 for request in run.serving_requests
        ),
        "prefix_cache_miss_tokens": sum(
            request.prefix_cache_miss_tokens or 0 for request in run.serving_requests
        ),
        "queue_latency_ms": sum(request.queue_latency_ms or 0 for request in run.serving_requests),
        "queue_latency_p50_ms": _p(run, "queue_latency_ms", 0.50),
        "queue_latency_p95_ms": _p(run, "queue_latency_ms", 0.95),
        "prefill_or_path_latency_ms": sum(
            prefill_or_path_latency_ms(request) or 0 for request in run.serving_requests
        ),
        "prefill_or_path_latency_p50_ms": percentile(
            [
                value
                for request in run.serving_requests
                if (value := prefill_or_path_latency_ms(request)) is not None
            ],
            0.50,
        ),
        "prefill_or_path_latency_p95_ms": percentile(
            [
                value
                for request in run.serving_requests
                if (value := prefill_or_path_latency_ms(request)) is not None
            ],
            0.95,
        ),
        "decode_latency_ms": sum(
            request.decode_latency_ms or 0 for request in run.serving_requests
        ),
        "decode_latency_p50_ms": _p(run, "decode_latency_ms", 0.50),
        "decode_latency_p95_ms": _p(run, "decode_latency_ms", 0.95),
        "tpot_p50_ms": _p(run, "tpot_ms", 0.50),
        "tpot_p95_ms": _p(run, "tpot_ms", 0.95),
        "client_latency_p50_ms": percentile(
            [
                float(record["client_elapsed_ms"])
                for record in recording.get("records", [])
                if isinstance(record, dict) and record.get("client_elapsed_ms") is not None
            ],
            0.50,
        ),
        "client_latency_p95_ms": percentile(
            [
                float(record["client_elapsed_ms"])
                for record in recording.get("records", [])
                if isinstance(record, dict) and record.get("client_elapsed_ms") is not None
            ],
            0.95,
        ),
        "detectors_fired": [finding.id for finding in report.findings],
    }


def _p(run: AgentRun, field: str, quantile: float) -> float | None:
    values: list[float] = []
    for request in run.serving_requests:
        value = getattr(request, field)
        if value is not None:
            values.append(float(value))
    return percentile(values, quantile)


def collect_environment(
    model: str,
    base_url: str,
    warmups: int,
    repetitions: int,
) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "vllm",
        "base_url": base_url,
        "model": model,
        "warmups": warmups,
        "measured_repetitions": repetitions,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "gpu": detect_gpu(),
        "agentperf_version": "0.1.0",
    }


def detect_gpu() -> str | None:
    for command in (["nvidia-smi", "-L"], ["system_profiler", "SPDisplaysDataType"]):
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


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
    if not isinstance(message, dict):
        return ""
    return str(message.get("content") or "")


def _agent_run_to_json(run: AgentRun) -> dict[str, Any]:
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
                                {"name": component.name, "text": component.text}
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
