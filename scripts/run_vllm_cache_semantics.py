#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import platform
import subprocess
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast
from uuid import uuid4


class RequestResult(TypedDict):
    case_id: str
    case_name: str
    target_stable_tokens: int
    actual_s_tokens: int
    actual_b_tokens: int | None
    request_index: int
    request_id: str
    response_id: str
    prompt_tokens: int
    cached_tokens: int
    created_cache_tokens: int | None
    cached_token_ratio: float
    queue_time_ms: float | None
    scheduled_to_first_token_ms: float | None
    generation_time_ms: float | None
    mean_itl_ms: float | None
    client_elapsed_ms: float
    output_text: str
    error: NotRequired[str]


STABLE_TARGETS = [1024, 4096, 8192]
B_TARGET_TOKENS = 512

CASES = {
    "A": "IDENTICAL_REQUESTS",
    "B": "DYNAMIC_PREFIX",
    "C": "STABLE_PREFIX",
    "D": "STABLE_PREFIX_DYNAMIC_SUFFIX",
}

DYNAMIC_SECTIONS = [
    (
        "ALPHA-17 incident update: checkout workers are retrying payment authorization "
        "after a regional routing change. Use this per-request fact pattern only for "
        "request one. The mitigation should mention rollback readiness and queue drain."
    ),
    (
        "BRAVO-29 field note: search indexing lag follows a schema migration and the "
        "customer impact is delayed discovery. Use this different request-specific "
        "context only for request two. The mitigation should mention read-only fallback."
    ),
    (
        "CHARLIE-43 operations brief: notification fanout is saturated after a partner "
        "webhook spike. Use this separate dynamic section only for request three. The "
        "mitigation should mention rate limiting and owner escalation."
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe vLLM prefix-cache token semantics")
    parser.add_argument("--base-url", default="http://localhost:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/vllm_cache_semantics"))
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--stable-targets",
        default=",".join(str(value) for value in STABLE_TARGETS),
        help="Comma-separated stable S token targets.",
    )
    args = parser.parse_args()

    targets = [int(value.strip()) for value in args.stable_targets.split(",") if value.strip()]
    args.output_dir.mkdir(parents=True, exist_ok=True)

    environment = collect_environment(args.model, args.base_url)
    results: list[RequestResult] = []
    stable_cache: dict[str, str] = {}

    for target in targets:
        for case_id, case_name in CASES.items():
            label = f"{case_id}-{target}"
            stable = stable_cache.setdefault(
                f"S-{label}",
                build_token_sized_text(
                    base_url=args.base_url,
                    model=args.model,
                    target_tokens=target,
                    label=f"stable-section-{label}",
                    api_key=args.api_key,
                    timeout=args.timeout,
                ),
            )
            bridge = (
                build_token_sized_text(
                    base_url=args.base_url,
                    model=args.model,
                    target_tokens=B_TARGET_TOKENS,
                    label=f"stable-bridge-{label}",
                    api_key=args.api_key,
                    timeout=args.timeout,
                )
                if case_id == "D"
                else None
            )
            actual_s_tokens = len(
                tokenize(args.base_url, args.model, stable, args.api_key, args.timeout)
            )
            actual_b_tokens = (
                len(tokenize(args.base_url, args.model, bridge, args.api_key, args.timeout))
                if bridge is not None
                else None
            )
            for request_index in range(3):
                dynamic = DYNAMIC_SECTIONS[0] if case_id == "A" else DYNAMIC_SECTIONS[request_index]
                prompt = build_prompt(case_id, stable, bridge, dynamic)
                results.append(
                    run_request(
                        base_url=args.base_url,
                        model=args.model,
                        api_key=args.api_key,
                        timeout=args.timeout,
                        case_id=case_id,
                        case_name=case_name,
                        target_stable_tokens=target,
                        actual_s_tokens=actual_s_tokens,
                        actual_b_tokens=actual_b_tokens,
                        request_index=request_index + 1,
                        prompt=prompt,
                    )
                )

    metrics_text = get_text(root_url(args.base_url) + "/metrics", args.api_key, args.timeout)
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "environment": environment,
        "protocol": {
            "cases": CASES,
            "stable_targets": targets,
            "b_target_tokens": B_TARGET_TOKENS,
            "max_tokens": 1,
            "temperature": 0,
            "notes": [
                "No warmups are used; first request behavior is preserved.",
                "Stable text is unique per case and size to avoid cross-case cache reuse.",
                "Prompts are sent through /v1/completions, not chat templates.",
            ],
        },
        "results": results,
        "prometheus_relevant_metrics": relevant_metric_lines(metrics_text),
        "analysis": analyze_results(results, metrics_text),
    }
    (args.output_dir / "cache_semantics_results.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    (args.output_dir / "cache_semantics_report.md").write_text(
        render_markdown(payload),
        encoding="utf-8",
    )
    (args.output_dir / "prometheus_metrics.txt").write_text(metrics_text, encoding="utf-8")
    print(f"Wrote cache semantics artifacts to {args.output_dir}")
    return 0


def build_prompt(case_id: str, stable: str, bridge: str | None, dynamic: str) -> str:
    if case_id == "A":
        return stable + "\n\n" + dynamic
    if case_id == "B":
        return dynamic + "\n\n" + stable
    if case_id == "C":
        return stable + "\n\n" + dynamic
    if case_id == "D":
        if bridge is None:
            raise ValueError("case D requires bridge text")
        return stable + "\n\n" + bridge + "\n\n" + dynamic
    raise ValueError(f"unknown case: {case_id}")


def build_token_sized_text(
    *,
    base_url: str,
    model: str,
    target_tokens: int,
    label: str,
    api_key: str,
    timeout: float,
) -> str:
    unit = (
        f"{label} cache-line evidence alpha beta gamma delta epsilon zeta eta theta "
        "iota kappa lambda mu nu xi omicron pi rho sigma tau.\n"
    )
    low = 1
    high = 1
    while token_count(base_url, model, unit * high, api_key, timeout) < target_tokens:
        high *= 2
    best = unit
    best_delta = target_tokens
    while low <= high:
        mid = (low + high) // 2
        candidate = unit * mid
        count = token_count(base_url, model, candidate, api_key, timeout)
        delta = abs(count - target_tokens)
        if delta < best_delta:
            best = candidate
            best_delta = delta
        if count < target_tokens:
            low = mid + 1
        else:
            high = mid - 1
    return best


def run_request(
    *,
    base_url: str,
    model: str,
    api_key: str,
    timeout: float,
    case_id: str,
    case_name: str,
    target_stable_tokens: int,
    actual_s_tokens: int,
    actual_b_tokens: int | None,
    request_index: int,
    prompt: str,
) -> RequestResult:
    request_id = (
        f"cache-semantics-{case_id}-{target_stable_tokens}-{request_index}-{uuid4().hex[:8]}"
    )
    body = {
        "model": model,
        "prompt": prompt,
        "max_tokens": 1,
        "temperature": 0,
        "stream": False,
        "request_id": request_id,
        "return_token_ids": True,
        "return_prompt_text": True,
    }
    started = time.perf_counter()
    response = post_json(
        f"{base_url.rstrip('/')}/completions",
        body,
        api_key=api_key,
        timeout=timeout,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    usage = as_dict(response.get("usage"))
    details = as_dict(usage.get("prompt_tokens_details"))
    metrics = as_dict(response.get("metrics"))
    prompt_tokens = int_or_zero(usage.get("prompt_tokens"))
    cached_tokens = int_or_zero(details.get("cached_tokens"))
    return {
        "case_id": case_id,
        "case_name": case_name,
        "target_stable_tokens": target_stable_tokens,
        "actual_s_tokens": actual_s_tokens,
        "actual_b_tokens": actual_b_tokens,
        "request_index": request_index,
        "request_id": request_id,
        "response_id": str(response.get("id") or ""),
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "created_cache_tokens": optional_int(details.get("created_cache_tokens")),
        "cached_token_ratio": cached_tokens / prompt_tokens if prompt_tokens else 0.0,
        "queue_time_ms": optional_float(metrics.get("queue_time_ms")),
        "scheduled_to_first_token_ms": optional_float(metrics.get("time_to_first_token_ms")),
        "generation_time_ms": optional_float(metrics.get("generation_time_ms")),
        "mean_itl_ms": optional_float(metrics.get("mean_itl_ms")),
        "client_elapsed_ms": elapsed_ms,
        "output_text": extract_output_text(response),
    }


def tokenize(base_url: str, model: str, text: str, api_key: str, timeout: float) -> list[int]:
    response = post_json(
        root_url(base_url) + "/tokenize",
        {"model": model, "prompt": text},
        api_key=api_key,
        timeout=timeout,
    )
    for key in ("tokens", "token_ids", "input_ids"):
        value = response.get(key)
        if isinstance(value, list):
            return [int(item) for item in value]
    raise RuntimeError(f"Could not parse tokenize response keys: {sorted(response.keys())}")


def token_count(base_url: str, model: str, text: str, api_key: str, timeout: float) -> int:
    return len(tokenize(base_url, model, text, api_key, timeout))


def post_json(
    url: str,
    body: dict[str, Any],
    *,
    api_key: str,
    timeout: float,
) -> dict[str, Any]:
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
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(exc.read().decode("utf-8")) from exc


def get_text(url: str, api_key: str, timeout: float) -> str:
    request = urllib.request.Request(url, method="GET")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return str(text)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return ""


def root_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        return stripped[:-3]
    return stripped


def as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def int_or_zero(value: object) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return 0


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int_or_zero(value)


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return None


def extract_output_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    return str(first.get("text") or "")


def analyze_results(results: list[RequestResult], metrics_text: str) -> dict[str, Any]:
    by_case_size: dict[tuple[str, int], list[RequestResult]] = defaultdict(list)
    for result in results:
        by_case_size[(result["case_id"], result["target_stable_tokens"])].append(result)

    summaries: list[dict[str, Any]] = []
    nonzero_cached = [result["cached_tokens"] for result in results if result["cached_tokens"] > 0]
    for (case_id, target), group in sorted(by_case_size.items()):
        ordered = sorted(group, key=lambda item: item["request_index"])
        summaries.append(
            {
                "case_id": case_id,
                "case_name": CASES[case_id],
                "target_stable_tokens": target,
                "cached_tokens_by_request": [item["cached_tokens"] for item in ordered],
                "cached_ratios_by_request": [
                    round(item["cached_token_ratio"], 4) for item in ordered
                ],
                "scheduled_to_first_token_ms_by_request": [
                    item["scheduled_to_first_token_ms"] for item in ordered
                ],
                "prompt_tokens_by_request": [item["prompt_tokens"] for item in ordered],
            }
        )

    block_size_lines = [line for line in metrics_text.splitlines() if "block_size" in line]
    return {
        "case_summaries": summaries,
        "nonzero_cached_tokens_gcd": math.gcd(*nonzero_cached) if nonzero_cached else None,
        "all_nonzero_cached_tokens_multiple_of_16": all(
            value % 16 == 0 for value in nonzero_cached
        ),
        "prometheus_block_size_lines": block_size_lines[:20],
    }


def relevant_metric_lines(metrics_text: str) -> list[str]:
    patterns = ("prefix_cache", "kv_cache", "cache_config", "request_", "time_to_first_token")
    return [
        line
        for line in metrics_text.splitlines()
        if line and not line.startswith("#") and any(pattern in line for pattern in patterns)
    ][:400]


def render_markdown(payload: dict[str, Any]) -> str:
    results = cast(list[RequestResult], payload["results"])
    analysis = cast(dict[str, Any], payload["analysis"])
    environment = cast(dict[str, Any], payload["environment"])
    lines = [
        "# vLLM Prefix Cache Semantics Report",
        "",
        "This report records request-by-request `cached_tokens` behavior from a live vLLM "
        "server. It is not an AgentPerf detector run.",
        "",
        "## Environment",
        "",
    ]
    for key, value in environment.items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Request Results", ""])
    for target in sorted({result["target_stable_tokens"] for result in results}):
        lines.extend([f"### Stable Target {target} Tokens", ""])
        lines.append(
            "| Case | Request | Prompt Tokens | Cached Tokens | Cached Ratio | "
            "Queue ms | Scheduled->First ms | Generation ms |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for result in [
            item for item in results if item["target_stable_tokens"] == target
        ]:
            lines.append(
                "| "
                f"{result['case_id']} {result['case_name']} | "
                f"{result['request_index']} | "
                f"{result['prompt_tokens']} | "
                f"{result['cached_tokens']} | "
                f"{result['cached_token_ratio']:.2%} | "
                f"{format_optional(result['queue_time_ms'])} | "
                f"{format_optional(result['scheduled_to_first_token_ms'])} | "
                f"{format_optional(result['generation_time_ms'])} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Block Granularity Clues",
            "",
            f"- Nonzero cached-token GCD: `{analysis['nonzero_cached_tokens_gcd']}`",
            "- All nonzero cached-token counts are multiples of 16: "
            f"`{analysis['all_nonzero_cached_tokens_multiple_of_16']}`",
            "",
            "Prometheus lines mentioning block size:",
            "",
            "```text",
        ]
    )
    block_lines = cast(list[str], analysis["prometheus_block_size_lines"])
    lines.extend(block_lines or ["<none>"])
    lines.extend(["```", ""])
    return "\n".join(lines)


def format_optional(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def collect_environment(model: str, base_url: str) -> dict[str, Any]:
    return {
        "date": datetime.now(UTC).isoformat(),
        "backend": "vllm",
        "base_url": base_url,
        "model": model,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "gpu": detect_gpu(),
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


if __name__ == "__main__":
    raise SystemExit(main())
