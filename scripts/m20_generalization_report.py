from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

TAXONOMY = {
    "ACTIONABLE",
    "VALID_NON_ACTIONABLE",
    "EXPECTED_STRUCTURAL",
    "INSUFFICIENT_EVIDENCE",
    "FALSE_POSITIVE",
}

CAPABILITY_ROWS = [
    ("Tasks captured", "tasks_captured"),
    ("Run structure", "run_structure"),
    ("LLM timing", "llm_timing"),
    ("Tool timing", "tool_timing"),
    ("Provider usage", "provider_usage"),
    ("Component attribution", "component_attribution"),
    ("Task quality", "task_quality"),
    ("Serving correlation", "serving_correlation"),
    ("Context findings", "context_findings"),
    ("Replay validation", "replay_validation"),
]


class ReviewDataError(ValueError):
    """Raised when the M20 finding-review dataset is malformed."""


def load_review_data(path: Path) -> dict[str, Any]:
    try:
        data = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        raise ReviewDataError(f"invalid JSON in {path}: {exc}") from exc
    validate_review_data(data)
    return data


def validate_review_data(data: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise ReviewDataError("schema_version must be 1")
    declared = set(_list(data, "taxonomy"))
    if declared != TAXONOMY:
        raise ReviewDataError(f"taxonomy must be {sorted(TAXONOMY)}")
    workloads = _list(data, "workloads")
    if not workloads:
        raise ReviewDataError("at least one workload is required")
    for workload in workloads:
        _validate_workload(_dict(workload, "workload"))


def aggregate_reviews(data: dict[str, Any]) -> dict[str, Any]:
    workloads = [_dict(item, "workload") for item in _list(data, "workloads")]
    counts: Counter[str] = Counter()
    workload_counts: dict[str, Counter[str]] = {}
    for workload in workloads:
        workload_id = _str(workload, "workload_id")
        reviews = [_dict(item, "review") for item in _list(workload, "reviews")]
        local: Counter[str] = Counter()
        for review in reviews:
            classification = _str(review, "classification")
            counts[classification] += 1
            local[classification] += 1
        workload_counts[workload_id] = local
    return {
        "workloads": len(workloads),
        "tasks": sum(int(workload.get("tasks", 0)) for workload in workloads),
        "runs": sum(int(workload.get("runs", 0)) for workload in workloads),
        "llm_calls": sum(int(workload.get("llm_calls", 0)) for workload in workloads),
        "tool_calls": sum(int(workload.get("tool_calls", 0)) for workload in workloads),
        "findings_reviewed": sum(counts.values()),
        "counts": {name: counts.get(name, 0) for name in sorted(TAXONOMY)},
        "workload_counts": {
            key: {name: value.get(name, 0) for name in sorted(TAXONOMY)}
            for key, value in workload_counts.items()
        },
    }


def render_summary(data: dict[str, Any]) -> str:
    aggregate = aggregate_reviews(data)
    workloads = [_dict(item, "workload") for item in _list(data, "workloads")]
    lines = [
        "AgentPerf M20 Generalization Summary",
        "=" * 50,
        "",
        f"Workloads                         {aggregate['workloads']}",
        f"Tasks                             {aggregate['tasks']}",
        f"Runs                              {aggregate['runs']}",
        f"LLM calls                         {aggregate['llm_calls']}",
        f"Tool calls                        {aggregate['tool_calls']}",
        f"Findings reviewed                 {aggregate['findings_reviewed']}",
        "",
        "Generalization Matrix",
        "-" * 50,
        _matrix_header(workloads),
    ]
    for label, key in CAPABILITY_ROWS:
        values = [
            str(_dict(workload, "workload").get("capabilities", {}).get(key, "UNKNOWN"))
            for workload in workloads
        ]
        lines.append(_matrix_row(label, values))
    lines.extend(["", "Readiness", "-" * 50])
    for workload in workloads:
        readiness = _dict(workload.get("readiness", {}), "readiness")
        lines.append(
            f"{_str(workload, 'workload_id'):<32} "
            f"agent={readiness.get('agent', 'UNKNOWN')} "
            f"cross_layer={readiness.get('cross_layer', 'UNKNOWN')}"
        )
    lines.extend(["", "Finding Review", "-" * 50])
    counts = _dict(aggregate["counts"], "counts")
    for name in sorted(TAXONOMY):
        lines.append(f"{name:<32} {counts[name]}")
    lines.extend(["", "Per Workload", "-" * 50])
    workload_counts = _dict(aggregate["workload_counts"], "workload_counts")
    for workload_id, counts_obj in workload_counts.items():
        counts_dict = _dict(counts_obj, "workload_counts")
        summary = ", ".join(
            f"{name}={counts_dict[name]}"
            for name in sorted(TAXONOMY)
            if counts_dict[name]
        )
        lines.append(f"{workload_id:<32} {summary or 'no findings reviewed'}")
    return "\n".join(lines)


def _validate_workload(workload: dict[str, Any]) -> None:
    workload_id = _str(workload, "workload_id")
    if not _str(workload, "workload_class"):
        raise ReviewDataError(f"{workload_id}: workload_class is required")
    task_ids = set(str(item) for item in _list(workload, "task_ids"))
    finding_ids = set(str(item) for item in _list(workload, "finding_ids"))
    if not task_ids:
        raise ReviewDataError(f"{workload_id}: task_ids must not be empty")
    reviews = [_dict(item, "review") for item in _list(workload, "reviews")]
    for review in reviews:
        finding_id = _str(review, "finding_id")
        if finding_id not in finding_ids:
            raise ReviewDataError(
                f"{workload_id}: review references unknown finding_id {finding_id}"
            )
        task_id = review.get("task_id")
        if task_id is not None and str(task_id) not in task_ids:
            raise ReviewDataError(
                f"{workload_id}: review references unknown task_id {task_id}"
            )
        classification = _str(review, "classification")
        if classification not in TAXONOMY:
            raise ReviewDataError(
                f"{workload_id}: unsupported classification {classification}"
            )
        if not _str(review, "rationale"):
            raise ReviewDataError(f"{workload_id}: review rationale is required")
    capabilities = _dict(workload.get("capabilities", {}), "capabilities")
    missing = [key for _, key in CAPABILITY_ROWS if key not in capabilities]
    if missing:
        raise ReviewDataError(f"{workload_id}: missing capability keys {missing}")


def _matrix_header(workloads: list[dict[str, Any]]) -> str:
    names = [_str(workload, "workload_id") for workload in workloads]
    return _matrix_row("Capability", names)


def _matrix_row(label: str, values: list[str]) -> str:
    return f"{label:<28} " + "  ".join(f"{value:<28}" for value in values)


def _dict(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewDataError(f"{name} must be an object")
    return value


def _list(value: dict[str, Any], key: str) -> list[Any]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise ReviewDataError(f"{key} must be a list")
    return raw


def _str(value: dict[str, Any], key: str) -> str:
    raw = value.get(key)
    if not isinstance(raw, str):
        raise ReviewDataError(f"{key} must be a string")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the M20 generalization summary.")
    parser.add_argument(
        "review_data",
        type=Path,
        nargs="?",
        default=Path("docs/m20_finding_reviews.json"),
    )
    args = parser.parse_args(argv)
    print(render_summary(load_review_data(args.review_data)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
