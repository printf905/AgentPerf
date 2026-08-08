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

    baseline_records = run_config(
        config_name="baseline_inefficient",
        base_url=args.base_url,
        model=args.model,
        api_key=args.api_key,
        repetitions=args.warmups + args.repetitions,
        warmups=args.warmups,
        timeout=args.timeout,
        improved=False,
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
    )

    baseline = build_recording("real-vllm-baseline", args.model, environment, baseline_records)
    improved = build_recording("real-vllm-improved", args.model, environment, improved_records)

    write_artifacts(args.output_dir, "baseline", baseline)
    write_artifacts(args.output_dir, "improved", improved)
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
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for rep in range(repetitions):
        for task_index, task in enumerate(TASKS):
            measured = rep >= warmups
            request_id = f"agentperf-{config_name}-{rep}-{task_index}-{uuid4().hex[:8]}"
            trace_id = uuid4().hex
            prompt_components = build_prompt_components(task, improved=improved)
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


def build_prompt_components(task: str, *, improved: bool) -> dict[str, str]:
    if improved:
        return {
            "system": f"{STABLE_POLICY}\n{RUNBOOK}",
            "user": task,
        }
    # Same logical content, but the stable material is split by per-request text.
    # This intentionally weakens exact prefix reuse while keeping the task equivalent.
    return {
        "system": STABLE_POLICY,
        "user": task,
        "other_context": RUNBOOK,
    }


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
    messages = [
        {"role": "system", "content": prompt_components["system"]},
        {"role": "user", "content": prompt_components["user"]},
    ]
    if prompt_components.get("other_context"):
        messages.append({"role": "user", "content": prompt_components["other_context"]})
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": 64,
        "temperature": 0,
        "stream": False,
        "request_id": request_id,
        "return_token_ids": True,
        "return_prompt_text": True,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
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
    recording_path = output_dir / f"{name}_recording.json"
    trace_path = output_dir / f"{name}_normalized_trace.json"
    report_path = output_dir / f"{name}_agentperf_report.txt"
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
        "prefix_cache_hit_tokens": sum(
            request.prefix_cache_hit_tokens or 0 for request in run.serving_requests
        ),
        "prefix_cache_miss_tokens": sum(
            request.prefix_cache_miss_tokens or 0 for request in run.serving_requests
        ),
        "queue_latency_ms": sum(request.queue_latency_ms or 0 for request in run.serving_requests),
        "prefill_latency_ms": sum(
            request.prefill_latency_ms or 0 for request in run.serving_requests
        ),
        "decode_latency_ms": sum(
            request.decode_latency_ms or 0 for request in run.serving_requests
        ),
        "detectors_fired": [finding.id for finding in report.findings],
    }


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
                            "prompt": {
                                component.name: component.text
                                for component in call.prompt_components
                            },
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
